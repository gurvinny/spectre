/*
 * 802.11 header decoding.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"

#include <stdlib.h>
#include "frames.h"
#include "../spectre-sniffer/main/core/dot11.h"

/* Parse from a heap copy of exactly `n` bytes, so ASan flags any read past
 * the captured length (a stack buffer larger than the frame would hide it). */
static bool parse_exact(const uint8_t *b, size_t n)
{
    uint8_t *copy = malloc(n ? n : 1);
    memcpy(copy, b, n);
    d11_frame_t f;
    bool ok = d11_parse(copy, n, &f);
    free(copy);
    return ok;
}

static void test_beacon_header_fields(void)
{
    uint8_t b[64];
    size_t n = fr_beacon(b, 0x0011);
    d11_frame_t f;
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.type, D11_MGMT);
    CHECK_EQ(f.subtype, D11_ST_BEACON);
    CHECK_EQ(f.duration, 314);
    CHECK(f.has_seq);
    CHECK_EQ(f.seq, 100);
    CHECK(memcmp(f.ra, MAC_BC, 6) == 0);
    CHECK(memcmp(f.ta, MAC_AP, 6) == 0);
    CHECK(memcmp(f.bssid, MAC_AP, 6) == 0);
    CHECK_EQ(f.hdr_len, 24);
    CHECK_EQ(f.body_len, 12);
    CHECK(f.ies == b + 36);
    CHECK_EQ(f.ies_len, 0);
    CHECK_EQ(f.reason, -1);
    CHECK_EQ(f.eapol, D11_EAPOL_NONE);
}

static void test_seq_number_uses_upper_12_bits(void)
{
    uint8_t b[32];
    size_t n = fr_hdr(b, 0, 4, 0, MAC_BC, MAC_STA, MAC_BC, 1234);
    b[22] |= 0x05;                                 /* fragment number 5 */
    d11_frame_t f;
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.seq, 1234);
    n = fr_hdr(b, 0, 4, 0, MAC_BC, MAC_STA, MAC_BC, 4095);
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.seq, 4095);
}

static void test_too_short_is_rejected(void)
{
    uint8_t b[40] = {0};
    d11_frame_t f;
    CHECK(!d11_parse(NULL, 30, &f));
    CHECK(!d11_parse(b, 9, &f));
    b[0] = (uint8_t)((1 << 2) | (12 << 4));         /* CTS needs 10 */
    CHECK(!d11_parse(b, 9, &f));
    CHECK(d11_parse(b, 10, &f));
    b[0] = 0;
    size_t n = fr_hdr(b, 0, 8, 0, MAC_BC, MAC_AP, MAC_AP, 1);
    CHECK(!d11_parse(b, n - 1, &f));               /* mgmt needs 24 */
    for (size_t cut = 10; cut < 24; cut++)
        CHECK(!parse_exact(b, cut));                 /* and reads nothing past it */
    CHECK(d11_parse(b, n, &f));
    b[0] = (uint8_t)((1 << 2) | (11 << 4));         /* RTS needs 16 */
    CHECK(!d11_parse(b, 15, &f));
    CHECK(d11_parse(b, 16, &f));
    b[0] = (uint8_t)(3 << 2);                       /* extension frames */
    CHECK(!d11_parse(b, 30, &f));
}

static void test_ctrl_cts_has_only_receiver(void)
{
    uint8_t b[16] = {0};
    b[0] = (uint8_t)((1 << 2) | (12 << 4));
    memcpy(b + 4, MAC_STA, 6);
    d11_frame_t f;
    CHECK(d11_parse(b, 10, &f));
    CHECK_EQ(f.type, D11_CTRL);
    CHECK(f.ta == NULL);
    CHECK(f.bssid == NULL);
    CHECK(!f.has_seq);
    CHECK_EQ(f.hdr_len, 10);
    CHECK_STR(d11_type_name(&f), "CTRL");
}

static void test_data_bssid_follows_ds_bits(void)
{
    uint8_t b[64];
    d11_frame_t f;
    size_t n = fr_hdr(b, 2, 0, 0, MAC_STA, MAC_DS, MAC_AP, 1);
    CHECK(d11_parse(b, n, &f));
    CHECK(f.bssid == b + 16);                       /* neither: addr3 */
    n = fr_hdr(b, 2, 0, D11_FL_TODS, MAC_AP, MAC_STA, MAC_DS, 1);
    CHECK(d11_parse(b, n, &f));
    CHECK(f.bssid == b + 4);                        /* to DS: addr1 */
    CHECK(memcmp(f.ta, MAC_STA, 6) == 0);
    n = fr_hdr(b, 2, 0, D11_FL_FROMDS, MAC_STA, MAC_AP, MAC_DS, 1);
    CHECK(d11_parse(b, n, &f));
    CHECK(f.bssid == b + 10);                       /* from DS: addr2 */
    n = fr_hdr(b, 2, 0, D11_FL_TODS | D11_FL_FROMDS, MAC_STA, MAC_AP, MAC_DS, 1);
    CHECK(!d11_parse(b, n, &f));                    /* addr4 missing */
    CHECK(d11_parse(b, n + 6, &f));
    CHECK(f.bssid == NULL);
    CHECK_EQ(f.hdr_len, 30);
}

static void test_qos_and_ht_control_lengths(void)
{
    uint8_t b[64] = {0};
    d11_frame_t f;
    fr_hdr(b, 2, 8, 0, MAC_STA, MAC_AP, MAC_AP, 1);          /* QoS data */
    CHECK(!d11_parse(b, 25, &f));
    CHECK(d11_parse(b, 26, &f));
    CHECK_EQ(f.hdr_len, 26);
    fr_hdr(b, 2, 8, D11_FL_ORDER, MAC_STA, MAC_AP, MAC_AP, 1);
    CHECK(d11_parse(b, 40, &f));
    CHECK_EQ(f.hdr_len, 30);
    fr_hdr(b, 2, 0, D11_FL_ORDER, MAC_STA, MAC_AP, MAC_AP, 1); /* non-QoS: no HTC */
    CHECK(d11_parse(b, 40, &f));
    CHECK_EQ(f.hdr_len, 24);
    fr_hdr(b, 2, 8, D11_FL_TODS | D11_FL_FROMDS | D11_FL_ORDER, MAC_STA, MAC_AP, MAC_AP, 1);
    CHECK(d11_parse(b, 40, &f));
    CHECK_EQ(f.hdr_len, 36);
    fr_hdr(b, 0, 8, D11_FL_ORDER, MAC_BC, MAC_AP, MAC_AP, 1);  /* mgmt + HTC */
    CHECK(d11_parse(b, 40, &f));
    CHECK_EQ(f.hdr_len, 28);
}

static void test_deauth_reason_is_read_when_unprotected(void)
{
    uint8_t b[32];
    d11_frame_t f;
    size_t n = fr_hdr(b, 0, D11_ST_DEAUTH, 0, MAC_STA, MAC_AP, MAC_AP, 9);
    b[n++] = 7; b[n++] = 0;
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.reason, 7);
    CHECK_STR(d11_type_name(&f), "DEAUTH");
    b[24] = 0x03; b[25] = 0x01;                      /* reason 259, little endian */
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.reason, 259);
    b[1] = D11_FL_PROTECTED;                         /* PMF-protected: opaque */
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.reason, -1);
    b[1] = 0;
    b[0] = (uint8_t)(D11_ST_DISASSOC << 4);
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.reason, 259);
    CHECK(d11_parse(b, n - 1, &f));                  /* body too short */
    CHECK_EQ(f.reason, -1);
}

static void test_auth_fields(void)
{
    uint8_t b[40];
    d11_frame_t f;
    size_t n = fr_hdr(b, 0, D11_ST_AUTH, 0, MAC_AP, MAC_STA, MAC_AP, 2);
    uint8_t body[6] = {3, 0, 1, 0, 0x4C, 0};         /* SAE, seq 1, status 76 */
    n = fr_put(b, n, body, 6);
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.auth_alg, 3);
    CHECK_EQ(f.auth_seq, 1);
    CHECK_EQ(f.status, 76);
    CHECK(d11_parse(b, n - 1, &f));
    CHECK_EQ(f.auth_alg, -1);
    CHECK_EQ(f.status, -1);
}

static void test_ie_offset_per_subtype(void)
{
    struct { uint8_t sub; int off; } cases[] = {
        {D11_ST_ASSOC_REQ, 4}, {D11_ST_ASSOC_RESP, 6}, {D11_ST_REASSOC_REQ, 10},
        {D11_ST_REASSOC_RESP, 6}, {D11_ST_PROBE_REQ, 0}, {D11_ST_PROBE_RESP, 12},
        {D11_ST_BEACON, 12},
    };
    uint8_t b[64] = {0};
    d11_frame_t f;
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        size_t n = fr_hdr(b, 0, cases[i].sub, 0, MAC_BC, MAC_STA, MAC_AP, 1);
        CHECK(d11_parse(b, n + 20, &f));
        CHECK(f.ies == b + 24 + cases[i].off);
        CHECK_EQ(f.ies_len, 20 - cases[i].off);
    }
    size_t n = fr_hdr(b, 0, D11_ST_ACTION, 0, MAC_BC, MAC_STA, MAC_AP, 1);
    CHECK(d11_parse(b, n + 20, &f));
    CHECK(f.ies == NULL);
    n = fr_hdr(b, 0, D11_ST_BEACON, 0, MAC_BC, MAC_AP, MAC_AP, 1);
    CHECK(d11_parse(b, n + 11, &f));                 /* fixed fields cut short */
    CHECK(f.ies == NULL);
}

static size_t eapol_frame(uint8_t *b, uint16_t key_info, uint8_t flags, uint8_t pkt_type)
{
    size_t n = fr_hdr(b, 2, 8, flags, MAC_STA, MAC_AP, MAC_AP, 5);
    b[n++] = 0x07; b[n++] = 0x00;                    /* QoS control */
    static const uint8_t llc[8] = {0xAA, 0xAA, 0x03, 0, 0, 0, 0x88, 0x8E};
    n = fr_put(b, n, llc, 8);
    b[n++] = 2; b[n++] = pkt_type; b[n++] = 0; b[n++] = 95;
    b[n++] = 2;                                      /* descriptor: RSN */
    b[n++] = (uint8_t)(key_info >> 8);
    b[n++] = (uint8_t)(key_info & 0xFF);
    return n;
}

static void test_eapol_handshake_messages(void)
{
    uint8_t b[80];
    d11_frame_t f;
    struct { uint16_t info; int want; } cases[] = {
        {0x008A, 1},   /* pairwise + ack */
        {0x010A, 2},   /* pairwise + mic */
        {0x13CA, 3},   /* pairwise + install + ack + mic + secure */
        {0x030A, 4},   /* pairwise + mic + secure */
        {0x0382, D11_EAPOL_GROUP},
        {0x0008, D11_EAPOL_OTHER},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        size_t n = eapol_frame(b, cases[i].info, 0, 3);
        CHECK(d11_parse(b, n, &f));
        CHECK_EQ(f.eapol, cases[i].want);
    }
    size_t n = eapol_frame(b, 0x008A, 0, 1);         /* EAPOL-Start */
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.eapol, D11_EAPOL_OTHER);
    n = eapol_frame(b, 0x008A, D11_FL_PROTECTED, 3); /* encrypted payload */
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.eapol, D11_EAPOL_NONE);
    n = eapol_frame(b, 0x008A, 0, 3);
    b[26 + 7] = 0x00;                                /* not 888E */
    CHECK(d11_parse(b, n, &f));
    CHECK_EQ(f.eapol, D11_EAPOL_NONE);
    n = eapol_frame(b, 0x008A, 0, 3);
    CHECK(d11_parse(b, n - 2, &f));                  /* key info cut off */
    CHECK_EQ(f.eapol, D11_EAPOL_OTHER);
}

static void test_type_names_match_original_firmware(void)
{
    d11_frame_t f;
    memset(&f, 0, sizeof f);
    struct { uint8_t t, s; const char *name; } cases[] = {
        {0, 0, "ASSOC_REQ"}, {0, 1, "ASSOC_RESP"}, {0, 2, "MGMT"}, {0, 3, "MGMT"},
        {0, 4, "PROBE_REQ"}, {0, 5, "PROBE_RESP"}, {0, 8, "BEACON"},
        {0, 10, "DISASSOC"}, {0, 11, "AUTH"}, {0, 12, "DEAUTH"}, {0, 13, "MGMT"},
        {1, 11, "CTRL"}, {2, 0, "DATA"}, {2, 12, "DATA"}, {3, 0, "UNKNOWN"},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        f.type = cases[i].t;
        f.subtype = cases[i].s;
        CHECK_STR(d11_type_name(&f), cases[i].name);
    }
}

void suite_dot11(void)
{
    RUN(test_beacon_header_fields);
    RUN(test_seq_number_uses_upper_12_bits);
    RUN(test_too_short_is_rejected);
    RUN(test_ctrl_cts_has_only_receiver);
    RUN(test_data_bssid_follows_ds_bits);
    RUN(test_qos_and_ht_control_lengths);
    RUN(test_deauth_reason_is_read_when_unprotected);
    RUN(test_auth_fields);
    RUN(test_ie_offset_per_subtype);
    RUN(test_eapol_handshake_messages);
    RUN(test_type_names_match_original_firmware);
}
