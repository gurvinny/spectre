/*
 * 802.11 MAC header decoding for captured frames.
 *
 * Everything here is pure C with no ESP-IDF dependency so it can be unit
 * tested on the host. Input comes straight off the air: every read is
 * bounds-checked against the captured length and nothing is trusted.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { D11_MGMT = 0, D11_CTRL = 1, D11_DATA = 2, D11_EXT = 3 };

enum {
    D11_ST_ASSOC_REQ = 0, D11_ST_ASSOC_RESP = 1,
    D11_ST_REASSOC_REQ = 2, D11_ST_REASSOC_RESP = 3,
    D11_ST_PROBE_REQ = 4, D11_ST_PROBE_RESP = 5,
    D11_ST_BEACON = 8, D11_ST_DISASSOC = 10, D11_ST_AUTH = 11,
    D11_ST_DEAUTH = 12, D11_ST_ACTION = 13,
};

/* Frame-control flag byte, emitted as-is in the "fl" key. */
enum {
    D11_FL_TODS = 0x01, D11_FL_FROMDS = 0x02, D11_FL_MOREFRAG = 0x04,
    D11_FL_RETRY = 0x08, D11_FL_PM = 0x10, D11_FL_MOREDATA = 0x20,
    D11_FL_PROTECTED = 0x40, D11_FL_ORDER = 0x80,
};

/* EAPOL classification of a data frame. */
enum {
    D11_EAPOL_NONE = 0,
    /* 1-4: pairwise 4-way handshake message number */
    D11_EAPOL_GROUP = 5,  /* group key handshake message */
    D11_EAPOL_OTHER = 6,  /* EAP packet, EAPOL-Start, Logoff, ... */
};

typedef struct {
    uint8_t type;            /* D11_MGMT / CTRL / DATA / EXT */
    uint8_t subtype;
    uint8_t flags;           /* D11_FL_* */
    uint16_t duration;
    bool has_seq;
    uint16_t seq;            /* 802.11 sequence number, 0-4095 */
    const uint8_t *ra;       /* addr1, receiver */
    const uint8_t *ta;       /* addr2, transmitter (NULL for CTS/ACK) */
    const uint8_t *bssid;    /* resolved from the DS bits, NULL if none */
    size_t hdr_len;
    const uint8_t *body;     /* frame body after the MAC header */
    size_t body_len;
    const uint8_t *ies;      /* tagged parameters, mgmt frames only */
    size_t ies_len;
    int reason;              /* deauth/disassoc reason code, -1 if n/a */
    int auth_alg, auth_seq, status; /* auth frames, -1 if n/a */
    int eapol;               /* D11_EAPOL_* */
} d11_frame_t;

/* Decode the header of a captured frame. Returns false when the capture is
 * too short to hold the header its frame-control field announces. */
bool d11_parse(const uint8_t *p, size_t len, d11_frame_t *f);

/* Frame type name on the wire. Names match the original firmware so the
 * sensor's detectors and stored history stay comparable. */
const char *d11_type_name(const d11_frame_t *f);
