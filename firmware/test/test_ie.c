/*
 * Information element parsing.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"
#include "frames.h"
#include "../spectre-sniffer/main/core/ie.h"

static void test_ssid_and_ds_channel(void)
{
    uint8_t b[64];
    size_t n = fr_ie(b, 0, 0, "LabNet", 6);
    uint8_t ch = 11;
    n = fr_ie(b, n, 3, &ch, 1);
    n = fr_ie(b, n, 0, "Second", 6);                 /* first SSID wins */
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK(ie.has_ssid);
    CHECK_EQ(ie.ssid_len, 6);
    CHECK(memcmp(ie.ssid, "LabNet", 6) == 0);
    CHECK_EQ(ie.ds_channel, 11);
    ie_parse(NULL, 10, &ie);
    CHECK(!ie.has_ssid);
}

static void test_oversized_ssid_is_ignored(void)
{
    uint8_t b[64] = {0};
    b[0] = 0; b[1] = 33;                             /* 33 > 32 */
    ie_info_t ie;
    ie_parse(b, 35, &ie);
    CHECK(!ie.has_ssid);
}

static void test_truncated_element_stops_the_walk(void)
{
    uint8_t b[64];
    size_t n = fr_ie(b, 0, 0, "Net", 3);
    b[n] = 45; b[n + 1] = 26;                        /* HT cap claims 26 bytes */
    ie_info_t ie;
    ie_parse(b, n + 2 + 10, &ie);
    CHECK(ie.has_ssid);
    CHECK(!ie.ht);
    ie_parse(b, n + 2 + 26, &ie);
    CHECK(ie.ht);
    ie_parse(b, n + 1, &ie);                         /* lone id byte */
    CHECK(ie.has_ssid);
}

static void test_rsn_wpa2_psk_with_pmf_capable(void)
{
    uint8_t b[64], r[32];
    uint8_t akm[] = {2};
    uint8_t rn = rsn_body(r, akm, 1, 0x0080);
    size_t n = fr_ie(b, 0, 48, r, rn);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK(ie.rsn);
    CHECK_EQ(ie.akm, AKM_PSK);
    CHECK_EQ(ie.group_cipher, CIPHER_CCMP);
    CHECK_EQ(ie.pairwise, CIPHER_CCMP);
    CHECK_EQ(ie.pmf, PMF_CAPABLE);
    CHECK_STR(ie_security(&ie, 0x0011), "WPA2");
}

static void test_rsn_transition_mode_with_pmf_required(void)
{
    uint8_t b[64], r[40];
    uint8_t akm[] = {2, 8};
    uint8_t rn = rsn_body(r, akm, 2, 0x00C0);
    size_t n = fr_ie(b, 0, 48, r, rn);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK_EQ(ie.akm, AKM_PSK | AKM_SAE);
    CHECK_EQ(ie.pmf, PMF_REQUIRED);
    CHECK_STR(ie_security(&ie, 0x0011), "WPA2/WPA3");
    uint8_t sae[] = {8};
    rn = rsn_body(r, sae, 1, 0x00C0);
    n = fr_ie(b, 0, 48, r, rn);
    ie_parse(b, n, &ie);
    CHECK_STR(ie_security(&ie, 0x0011), "WPA3");
}

static void test_rsn_truncated_parts_are_safe(void)
{
    uint8_t b[64], r[40];
    uint8_t akm[] = {2};
    uint8_t rn = rsn_body(r, akm, 1, 0x00C0);
    ie_info_t ie;
    for (uint8_t cut = 0; cut <= rn; cut++) {
        size_t n = fr_ie(b, 0, 48, r, cut);
        ie_parse(b, n, &ie);
        CHECK(ie.rsn);
        if (cut < 6)
            CHECK_EQ(ie.group_cipher, 0);
        if (cut < 12)
            CHECK_EQ(ie.pairwise, 0);
        if (cut < 18)
            CHECK_EQ(ie.akm, 0);
        if (cut < rn)
            CHECK_EQ(ie.pmf, PMF_NONE);
    }
    CHECK_EQ(ie.pmf, PMF_REQUIRED);                  /* full element */
    /* AKM count larger than the element: keep what fits */
    r[12] = 9;
    size_t n = fr_ie(b, 0, 48, r, 18);
    ie_parse(b, n, &ie);
    CHECK_EQ(ie.akm, AKM_PSK);
}

static void test_unknown_suites_map_to_other(void)
{
    uint8_t b[64], r[40];
    uint8_t akm[] = {99};
    uint8_t rn = rsn_body(r, akm, 1, 0);
    r[11] = 77;                                      /* pairwise type */
    r[2] = 0x11;                                     /* group from a vendor OUI */
    size_t n = fr_ie(b, 0, 48, r, rn);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK_EQ(ie.akm, AKM_OTHER);
    CHECK_EQ(ie.pairwise, CIPHER_OTHER);
    CHECK_EQ(ie.group_cipher, CIPHER_OTHER);
}

static void test_wpa1_and_wps_vendor_elements(void)
{
    uint8_t b[96];
    uint8_t wpa[] = {0x00, 0x50, 0xF2, 1, 1, 0, 0x00, 0x50, 0xF2, 2,
                     1, 0, 0x00, 0x50, 0xF2, 2, 1, 0, 0x00, 0x50, 0xF2, 2};
    uint8_t wps[] = {0x00, 0x50, 0xF2, 4, 0x10, 0x4A};
    size_t n = fr_ie(b, 0, 221, wpa, sizeof wpa);
    n = fr_ie(b, n, 221, wps, sizeof wps);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK(ie.wpa1);
    CHECK(!ie.rsn);
    CHECK(ie.wps);
    CHECK_EQ(ie.akm, AKM_PSK);
    CHECK_EQ(ie.pairwise, CIPHER_TKIP);
    CHECK_EQ(ie.group_cipher, CIPHER_TKIP);
    CHECK_STR(ie_security(&ie, 0x0011), "WPA");
    CHECK_EQ(ie.n_ouis, 1);                          /* same OUI twice */
}

static void test_rsn_overrides_earlier_wpa1(void)
{
    uint8_t b[96], r[40];
    uint8_t wpa[] = {0x00, 0x50, 0xF2, 1, 1, 0, 0x00, 0x50, 0xF2, 2,
                     1, 0, 0x00, 0x50, 0xF2, 2, 1, 0, 0x00, 0x50, 0xF2, 2};
    uint8_t akm[] = {8};
    size_t n = fr_ie(b, 0, 221, wpa, sizeof wpa);
    n = fr_ie(b, n, 48, r, rsn_body(r, akm, 1, 0));
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK(ie.wpa1);
    CHECK_EQ(ie.akm, AKM_SAE);
    CHECK_EQ(ie.pairwise, CIPHER_CCMP);              /* TKIP gone */
    CHECK_EQ(ie.group_cipher, CIPHER_CCMP);
    /* and a WPA1 element after RSN does not overwrite it */
    n = fr_ie(b, 0, 48, r, rsn_body(r, akm, 1, 0));
    n = fr_ie(b, n, 221, wpa, sizeof wpa);
    ie_parse(b, n, &ie);
    CHECK_EQ(ie.akm, AKM_SAE);
    CHECK_EQ(ie.pairwise, CIPHER_CCMP);
}

static void test_capability_elements(void)
{
    uint8_t b[96], z[26] = {0};
    size_t n = fr_ie(b, 0, 45, z, 26);
    uint8_t htop[22] = {6, 0x07};                    /* secondary below + any width */
    n = fr_ie(b, n, 61, htop, 22);
    n = fr_ie(b, n, 191, z, 12);
    uint8_t he[] = {35, 0, 0};
    n = fr_ie(b, n, 255, he, 3);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK(ie.ht);
    CHECK(ie.vht);
    CHECK(ie.he);
    CHECK(!ie.eht);
    CHECK_EQ(ie.ht_sec_offset, 3);
    uint8_t eht[] = {108, 0};
    n = fr_ie(b, 0, 255, eht, 2);
    ie_parse(b, n, &ie);
    CHECK(ie.eht);
    CHECK(!ie.he);
}

static void test_channel_switch_announcement(void)
{
    uint8_t b[16];
    uint8_t csa[] = {1, 149, 5};
    size_t n = fr_ie(b, 0, 37, csa, 3);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK(ie.csa);
    CHECK_EQ(ie.csa_mode, 1);
    CHECK_EQ(ie.csa_channel, 149);
    CHECK_EQ(ie.csa_count, 5);
    n = fr_ie(b, 0, 37, csa, 2);                     /* malformed */
    ie_parse(b, n, &ie);
    CHECK(!ie.csa);
}

static void test_vendor_ouis_deduped_and_capped(void)
{
    uint8_t b[128];
    size_t n = 0;
    for (uint8_t i = 0; i < 10; i++) {
        uint8_t v[4] = {0x00, 0x10, i, 1};
        n = fr_ie(b, n, 221, v, 4);
    }
    uint8_t dup[4] = {0x00, 0x10, 0, 2};
    n = fr_ie(b, n, 221, dup, 4);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    CHECK_EQ(ie.n_ouis, IE_MAX_OUIS);
    CHECK_EQ(ie.ouis[0][2], 0);
    CHECK_EQ(ie.ouis[7][2], 7);
}

static void test_security_labels(void)
{
    ie_info_t ie;
    memset(&ie, 0, sizeof ie);
    CHECK_STR(ie_security(&ie, 0x0001), "OPEN");
    CHECK_STR(ie_security(&ie, 0x0011), "WEP");
    ie.rsn = true;
    ie.akm = AKM_8021X;
    CHECK_STR(ie_security(&ie, 0x0011), "ENT");
    ie.akm = AKM_OWE;
    CHECK_STR(ie_security(&ie, 0x0011), "OWE");
    ie.akm = AKM_FT_SAE | AKM_FT_PSK;
    CHECK_STR(ie_security(&ie, 0x0011), "WPA2/WPA3");
    ie.akm = AKM_SAE_EXT;
    CHECK_STR(ie_security(&ie, 0x0011), "WPA3");
    ie.akm = AKM_PSK_SHA256;
    CHECK_STR(ie_security(&ie, 0x0011), "WPA2");
}

static size_t beacon_ies(uint8_t *b, const char *ssid, uint8_t tim_count, bool csa)
{
    size_t n = fr_ie(b, 0, 0, ssid, (uint8_t)strlen(ssid));
    uint8_t tim[4] = {tim_count, 3, 0, 0};
    n = fr_ie(b, n, 5, tim, 4);
    uint8_t load[5] = {tim_count, 0, 0, 0, 0};
    n = fr_ie(b, n, 11, load, 5);
    if (csa) {
        uint8_t c[3] = {1, 36, tim_count};
        n = fr_ie(b, n, 37, c, 3);
    }
    return n;
}

static void test_ap_hash_tracks_config_not_volatile_fields(void)
{
    uint8_t b[96];
    ie_info_t ie;
    ie_parse(b, beacon_ies(b, "LabNet", 0, false), &ie);
    uint32_t base = ie_ap_hash(&ie, 0x0011);
    ie_parse(b, beacon_ies(b, "LabNet", 2, false), &ie);
    CHECK_EQ(ie_ap_hash(&ie, 0x0011), base);         /* DTIM count / load moved */
    CHECK(ie_ap_hash(&ie, 0x0001) != base);          /* privacy bit cleared */
    ie_parse(b, beacon_ies(b, "LabNet2", 0, false), &ie);
    CHECK(ie_ap_hash(&ie, 0x0011) != base);
    ie_parse(b, beacon_ies(b, "LabNeu", 0, false), &ie);   /* same length */
    CHECK(ie_ap_hash(&ie, 0x0011) != base);
    ie_parse(b, beacon_ies(b, "LabNet", 0, true), &ie);
    uint32_t with_csa = ie_ap_hash(&ie, 0x0011);
    CHECK(with_csa != base);
    ie_parse(b, beacon_ies(b, "LabNet", 4, true), &ie);
    CHECK_EQ(ie_ap_hash(&ie, 0x0011), with_csa);     /* countdown only */
}

static void test_probe_fingerprint_ignores_ssid_text(void)
{
    uint8_t b[64];
    uint8_t rates[4] = {2, 4, 11, 22}, v[4] = {0x00, 0x50, 0xF2, 8};
    size_t n = fr_ie(b, 0, 0, "Alpha", 5);
    n = fr_ie(b, n, 1, rates, 4);
    n = fr_ie(b, n, 221, v, 4);
    ie_info_t a, c;
    ie_parse(b, n, &a);
    n = fr_ie(b, 0, 0, "Bravo-longer", 12);
    n = fr_ie(b, n, 1, rates, 4);
    n = fr_ie(b, n, 221, v, 4);
    ie_parse(b, n, &c);
    CHECK_EQ(a.fingerprint, c.fingerprint);
    n = fr_ie(b, 0, 1, rates, 4);                    /* different element order */
    n = fr_ie(b, n, 0, "Alpha", 5);
    n = fr_ie(b, n, 221, v, 4);
    ie_parse(b, n, &c);
    CHECK(a.fingerprint != c.fingerprint);
    v[3] = 9;                                        /* different vendor type */
    n = fr_ie(b, 0, 0, "Alpha", 5);
    n = fr_ie(b, n, 1, rates, 4);
    n = fr_ie(b, n, 221, v, 4);
    ie_parse(b, n, &c);
    CHECK(a.fingerprint != c.fingerprint);
}

void suite_ie(void)
{
    RUN(test_ssid_and_ds_channel);
    RUN(test_oversized_ssid_is_ignored);
    RUN(test_truncated_element_stops_the_walk);
    RUN(test_rsn_wpa2_psk_with_pmf_capable);
    RUN(test_rsn_transition_mode_with_pmf_required);
    RUN(test_rsn_truncated_parts_are_safe);
    RUN(test_unknown_suites_map_to_other);
    RUN(test_wpa1_and_wps_vendor_elements);
    RUN(test_rsn_overrides_earlier_wpa1);
    RUN(test_capability_elements);
    RUN(test_channel_switch_announcement);
    RUN(test_vendor_ouis_deduped_and_capped);
    RUN(test_security_labels);
    RUN(test_ap_hash_tracks_config_not_volatile_fields);
    RUN(test_probe_fingerprint_ignores_ssid_text);
}
