/*
 * Information element parsing. See ie.h.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "ie.h"

#include <string.h>

enum {
    EID_SSID = 0, EID_DS = 3, EID_CSA = 37, EID_HT_CAP = 45, EID_RSN = 48,
    EID_HT_OP = 61, EID_VHT_CAP = 191, EID_VENDOR = 221, EID_EXT = 255,
};
enum { EXT_HE_CAP = 35, EXT_EHT_CAP = 108 };

static const uint8_t OUI_IEEE[3] = {0x00, 0x0F, 0xAC};
static const uint8_t OUI_MSFT[3] = {0x00, 0x50, 0xF2};

uint32_t fnv1a(uint32_t h, const void *data, size_t len)
{
    const uint8_t *p = data;
    while (len--) {
        h ^= *p++;
        h *= 16777619u;
    }
    return h;
}

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

static uint16_t akm_bit(uint8_t t)
{
    switch (t) {
    case 1:  return AKM_8021X;
    case 2:  return AKM_PSK;
    case 3:  return AKM_FT_8021X;
    case 4:  return AKM_FT_PSK;
    case 5:  return AKM_8021X_SHA256;
    case 6:  return AKM_PSK_SHA256;
    case 8:  return AKM_SAE;
    case 9:  return AKM_FT_SAE;
    case 11: case 12: return AKM_SUITE_B;
    case 18: return AKM_OWE;
    case 24: case 25: return AKM_SAE_EXT;
    default: return AKM_OTHER;
    }
}

static uint8_t cipher_bit(uint8_t t)
{
    switch (t) {
    case 1: case 5: return CIPHER_WEP;
    case 2:  return CIPHER_TKIP;
    case 4:  return CIPHER_CCMP;
    case 6: case 11: case 12: case 13: return CIPHER_BIP;
    case 8:  return CIPHER_GCMP;
    case 9:  return CIPHER_GCMP256;
    case 10: return CIPHER_CCMP256;
    default: return CIPHER_OTHER;
    }
}

/* Parse the shared RSN/WPA1 layout: version, group, pairwise list, AKM list,
 * then (RSN only) capabilities. Each part is optional; stop where the
 * element ends. `oui` is the suite OUI expected for this element. */
static void parse_suites(const uint8_t *b, size_t n, const uint8_t oui[3],
                         bool rsn, ie_info_t *out)
{
    if (n < 2)
        return;
    b += 2; n -= 2;                                   /* version */
    if (n < 4)
        return;
    out->group_cipher = memcmp(b, oui, 3) == 0 ? cipher_bit(b[3]) : CIPHER_OTHER;
    b += 4; n -= 4;
    if (n < 2)
        return;
    size_t cnt = le16(b);
    b += 2; n -= 2;
    for (size_t i = 0; i < cnt; i++) {
        if (n < 4)
            return;
        out->pairwise |= memcmp(b, oui, 3) == 0 ? cipher_bit(b[3]) : CIPHER_OTHER;
        b += 4; n -= 4;
    }
    if (n < 2)
        return;
    cnt = le16(b);
    b += 2; n -= 2;
    uint16_t akm = 0;
    for (size_t i = 0; i < cnt; i++) {
        if (n < 4)
            break;
        akm |= memcmp(b, oui, 3) == 0 ? akm_bit(b[3]) : AKM_OTHER;
        b += 4; n -= 4;
    }
    out->akm = akm;
    if (!rsn || n < 2)
        return;
    uint16_t caps = le16(b);
    if (caps & 0x0040)
        out->pmf = PMF_REQUIRED;      /* MFPR */
    else if (caps & 0x0080)
        out->pmf = PMF_CAPABLE;       /* MFPC */
}

static void add_oui(ie_info_t *out, const uint8_t *oui)
{
    for (uint8_t i = 0; i < out->n_ouis; i++)
        if (memcmp(out->ouis[i], oui, 3) == 0)
            return;
    if (out->n_ouis < IE_MAX_OUIS)
        memcpy(out->ouis[out->n_ouis++], oui, 3);
}

void ie_parse(const uint8_t *ies, size_t len, ie_info_t *out)
{
    memset(out, 0, sizeof *out);
    uint32_t fp = FNV_SEED;
    if (ies == NULL)
        return;

    size_t i = 0;
    while (i + 2 <= len) {
        uint8_t id = ies[i], n = ies[i + 1];
        if (i + 2 + n > len)
            break;                                    /* truncated element */
        const uint8_t *b = ies + i + 2;
        fp = fnv1a(fp, &id, 1);

        switch (id) {
        case EID_SSID:
            if (!out->has_ssid && n <= 32) {
                out->has_ssid = true;
                out->ssid_len = n;
                memcpy(out->ssid, b, n);
            }
            break;
        case EID_DS:
            if (n >= 1)
                out->ds_channel = b[0];
            break;
        case EID_CSA:
            if (n >= 3) {
                out->csa = true;
                out->csa_mode = b[0];
                out->csa_channel = b[1];
                out->csa_count = b[2];
            }
            break;
        case EID_HT_CAP:
            out->ht = true;
            break;
        case EID_HT_OP:
            if (n >= 2)
                out->ht_sec_offset = b[1] & 0x3;
            break;
        case EID_VHT_CAP:
            out->vht = true;
            break;
        case EID_RSN:
            /* RSN wins over a legacy WPA element seen earlier. */
            out->rsn = true;
            out->akm = 0;
            out->group_cipher = 0;
            out->pairwise = 0;
            parse_suites(b, n, OUI_IEEE, true, out);
            break;
        case EID_EXT:
            if (n >= 1) {
                fp = fnv1a(fp, b, 1);
                if (b[0] == EXT_HE_CAP)
                    out->he = true;
                else if (b[0] == EXT_EHT_CAP)
                    out->eht = true;
            }
            break;
        case EID_VENDOR:
            if (n >= 3) {
                add_oui(out, b);
                fp = fnv1a(fp, b, n >= 4 ? 4 : 3);
                if (n >= 4 && memcmp(b, OUI_MSFT, 3) == 0) {
                    if (b[3] == 1 && !out->rsn) {
                        out->wpa1 = true;
                        parse_suites(b + 4, n - 4, OUI_MSFT, false, out);
                    } else if (b[3] == 1) {
                        out->wpa1 = true;
                    } else if (b[3] == 4) {
                        out->wps = true;
                    }
                }
            }
            break;
        default:
            break;
        }
        i += 2 + (size_t)n;
    }
    out->fingerprint = fp;
}

uint32_t ie_ap_hash(const ie_info_t *ie, uint16_t capability)
{
    uint32_t h = FNV_SEED;
    h = fnv1a(h, &ie->ssid_len, 1);
    h = fnv1a(h, ie->ssid, ie->ssid_len);
    h = fnv1a(h, &capability, sizeof capability);
    uint8_t flags[] = {
        ie->rsn, ie->wpa1, ie->group_cipher, ie->pairwise, ie->pmf,
        ie->ht, ie->vht, ie->he, ie->eht, ie->ht_sec_offset, ie->wps,
        ie->csa, ie->csa_mode, ie->csa_channel, ie->ds_channel, ie->n_ouis,
    };
    h = fnv1a(h, flags, sizeof flags);
    h = fnv1a(h, &ie->akm, sizeof ie->akm);
    h = fnv1a(h, ie->ouis, (size_t)ie->n_ouis * 3);
    return h;
}

const char *ie_security(const ie_info_t *ie, uint16_t capability)
{
    uint16_t a = ie->akm;
    if (a & AKM_OWE)
        return "OWE";
    if (a & (AKM_8021X | AKM_FT_8021X | AKM_8021X_SHA256 | AKM_SUITE_B))
        return "ENT";
    bool sae = a & (AKM_SAE | AKM_FT_SAE | AKM_SAE_EXT);
    bool psk = a & (AKM_PSK | AKM_FT_PSK | AKM_PSK_SHA256);
    if (ie->rsn && sae && psk)
        return "WPA2/WPA3";
    if (ie->rsn && sae)
        return "WPA3";
    if (ie->rsn)
        return "WPA2";
    if (ie->wpa1)
        return "WPA";
    return (capability & 0x0010) ? "WEP" : "OPEN";
}
