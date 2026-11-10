/*
 * 802.11 MAC header decoding. See dot11.h.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "dot11.h"

#include <string.h>

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint16_t be16(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }

/* Offset of the tagged parameters inside a management frame body. */
static int mgmt_ie_offset(uint8_t subtype)
{
    switch (subtype) {
    case D11_ST_ASSOC_REQ:    return 4;  /* capability, listen interval */
    case D11_ST_ASSOC_RESP:
    case D11_ST_REASSOC_RESP: return 6;  /* capability, status, AID */
    case D11_ST_REASSOC_REQ:  return 10; /* + current AP address */
    case D11_ST_PROBE_REQ:    return 0;
    case D11_ST_PROBE_RESP:
    case D11_ST_BEACON:       return 12; /* timestamp, interval, capability */
    default:                  return -1; /* no IEs we parse */
    }
}

static const uint8_t LLC_EAPOL[8] = {0xAA, 0xAA, 0x03, 0x00, 0x00, 0x00, 0x88, 0x8E};

/* Classify an unprotected data frame body that starts with an LLC header. */
static int classify_eapol(const uint8_t *b, size_t n)
{
    if (n < sizeof LLC_EAPOL || memcmp(b, LLC_EAPOL, sizeof LLC_EAPOL) != 0)
        return D11_EAPOL_NONE;
    b += sizeof LLC_EAPOL;
    n -= sizeof LLC_EAPOL;
    /* EAPOL header: version, packet type, body length */
    if (n < 4 || b[1] != 3)          /* 3 = EAPOL-Key */
        return D11_EAPOL_OTHER;
    b += 4;
    n -= 4;
    if (n < 3)                       /* descriptor type + key information */
        return D11_EAPOL_OTHER;
    uint16_t info = be16(b + 1);
    bool pairwise = info & 0x0008, ack = info & 0x0080;
    bool mic = info & 0x0100, secure = info & 0x0200;
    if (!pairwise)
        return D11_EAPOL_GROUP;
    if (ack)
        return mic ? 3 : 1;
    if (mic)
        return secure ? 4 : 2;
    return D11_EAPOL_OTHER;
}

bool d11_parse(const uint8_t *p, size_t len, d11_frame_t *f)
{
    memset(f, 0, sizeof *f);
    f->reason = f->auth_alg = f->auth_seq = f->status = -1;
    if (p == NULL || len < 10)
        return false;

    uint16_t fc = le16(p);
    f->type = (fc >> 2) & 0x3;
    f->subtype = (fc >> 4) & 0xF;
    f->flags = (uint8_t)(fc >> 8);
    f->duration = le16(p + 2);
    f->ra = p + 4;

    size_t hdr;
    if (f->type == D11_CTRL) {
        /* CTS (12) and ACK (13) carry only the receiver address. */
        if (f->subtype == 12 || f->subtype == 13) {
            hdr = 10;
        } else {
            if (len < 16)
                return false;
            hdr = 16;
            f->ta = p + 10;
        }
        f->hdr_len = hdr;
        f->body = p + hdr;
        f->body_len = len - hdr;
        return true;
    }
    if (f->type == D11_EXT)
        return false;

    if (len < 24)
        return false;
    hdr = 24;
    f->ta = p + 10;
    f->has_seq = true;
    f->seq = le16(p + 22) >> 4;

    bool tods = f->flags & D11_FL_TODS, fromds = f->flags & D11_FL_FROMDS;
    if (f->type == D11_DATA) {
        if (tods && fromds)
            hdr += 6;                         /* addr4 */
        bool qos = f->subtype & 0x8;
        if (qos)
            hdr += 2;
        if (qos && (f->flags & D11_FL_ORDER))
            hdr += 4;                         /* HT control */
        if (len < hdr)
            return false;
        if (tods && fromds)
            f->bssid = NULL;                  /* mesh / WDS: no single BSS */
        else if (tods)
            f->bssid = p + 4;
        else if (fromds)
            f->bssid = p + 10;
        else
            f->bssid = p + 16;
    } else {
        if (f->flags & D11_FL_ORDER)
            hdr += 4;                         /* HT control */
        if (len < hdr)
            return false;
        f->bssid = p + 16;
    }

    f->hdr_len = hdr;
    f->body = p + hdr;
    f->body_len = len - hdr;

    if (f->type == D11_MGMT) {
        if ((f->subtype == D11_ST_DEAUTH || f->subtype == D11_ST_DISASSOC)
                && f->body_len >= 2 && !(f->flags & D11_FL_PROTECTED))
            f->reason = le16(f->body);
        if (f->subtype == D11_ST_AUTH && f->body_len >= 6) {
            f->auth_alg = le16(f->body);
            f->auth_seq = le16(f->body + 2);
            f->status = le16(f->body + 4);
        }
        int off = mgmt_ie_offset(f->subtype);
        if (off >= 0 && (size_t)off <= f->body_len) {
            f->ies = f->body + off;
            f->ies_len = f->body_len - (size_t)off;
        }
    } else if (!(f->flags & D11_FL_PROTECTED) && f->body_len > 0) {
        f->eapol = classify_eapol(f->body, f->body_len);
    }
    return true;
}

const char *d11_type_name(const d11_frame_t *f)
{
    switch (f->type) {
    case D11_MGMT:
        switch (f->subtype) {
        case D11_ST_ASSOC_REQ:  return "ASSOC_REQ";
        case D11_ST_ASSOC_RESP: return "ASSOC_RESP";
        case D11_ST_PROBE_REQ:  return "PROBE_REQ";
        case D11_ST_PROBE_RESP: return "PROBE_RESP";
        case D11_ST_BEACON:     return "BEACON";
        case D11_ST_DISASSOC:   return "DISASSOC";
        case D11_ST_AUTH:       return "AUTH";
        case D11_ST_DEAUTH:     return "DEAUTH";
        default:                return "MGMT";  /* exact subtype is in "sub" */
        }
    case D11_CTRL: return "CTRL";
    case D11_DATA: return "DATA";
    default:       return "UNKNOWN";
    }
}
