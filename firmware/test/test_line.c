/*
 * UART line contract. Also writes every line kind to $SAMPLES_OUT when set,
 * so check_samples.py can prove each one is valid JSON the sensor parses.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"
#include "frames.h"
#include "../spectre-sniffer/main/core/line.h"

#include <stdlib.h>

static FILE *g_samples;

static void sample(const char *buf)
{
    if (g_samples && buf[0])
        fputs(buf, g_samples);
}

static radio_meta_t rm_legacy(uint8_t ch)
{
    radio_meta_t rm = {.rssi = -52, .noise = -95, .rate = 11, .fmt = PHY_11AG,
                       .ts_us = 123456789u, .channel = ch};
    return rm;
}

static void test_phy_decode(void)
{
    radio_meta_t rm = rm_legacy(6);
    phy_info_t p;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "g");
    CHECK_EQ(p.mcs, -1);
    CHECK_EQ(p.bw, 20);
    rm.channel = 36;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "a");
    rm.channel = 14;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "g");
    rm.fmt = PHY_11B;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "b");
    rm.fmt = PHY_HT;
    rm.siga1 = 0x87;                                 /* MCS 7, 40 MHz */
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "n");
    CHECK_EQ(p.mcs, 7);
    CHECK_EQ(p.bw, 40);
    rm.siga1 = 0x0F;
    phy_decode(&rm, &p);
    CHECK_EQ(p.mcs, 15);
    CHECK_EQ(p.bw, 20);
    rm.fmt = PHY_HE_SU;
    rm.siga1 = (9u << 3) | (1u << 19);               /* MCS 9, 40 MHz */
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "ax");
    CHECK_EQ(p.mcs, 9);
    CHECK_EQ(p.bw, 40);
    rm.siga1 = (11u << 3) | (2u << 19) | 0x7;        /* low bits are not MCS */
    phy_decode(&rm, &p);
    CHECK_EQ(p.mcs, 11);
    CHECK_EQ(p.bw, 80);
    rm.fmt = PHY_VHT;
    rm.siga1 = 2;                                    /* 80 MHz */
    rm.siga2 = 8 << 4;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "ac");
    CHECK_EQ(p.mcs, 8);
    CHECK_EQ(p.bw, 80);
    rm.fmt = PHY_VHT_MU;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "ac-mu");
    CHECK_EQ(p.mcs, -1);
    rm.fmt = PHY_HE_ERSU;
    rm.siga1 = (2u << 3) | (1u << 19);
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "ax-er");
    CHECK_EQ(p.mcs, 2);
    CHECK_EQ(p.bw, 20);
    rm.fmt = PHY_HE_MU;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "ax-mu");
    rm.fmt = PHY_HE_TB;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "ax-tb");
    rm.fmt = 9;
    phy_decode(&rm, &p);
    CHECK_STR(p.phy, "?");
}

static void test_beacon_line_keeps_original_keys(void)
{
    uint8_t b[128];
    size_t n = fr_beacon(b, 0x0011);
    n = fr_ie(b, n, 0, "LabNet", 6);
    d11_frame_t f;
    ie_info_t ie;
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    radio_meta_t rm = rm_legacy(6);
    char out[LINE_BUF];
    size_t len = line_frame(out, sizeof out, 47, 2728, &rm, &f, &ie);
    CHECK(len > 0);
    CHECK_EQ(len, strlen(out));
    CHECK_PREFIX(out, "<190>ESP32C5 wifi_sniffer: {\"seq\":47,\"uptime_ms\":2728,"
                       "\"ch\":6,\"rssi\":-52,\"type\":\"BEACON\",\"sub\":8,"
                       "\"src\":\"00:00:5E:00:53:01\",\"dst\":\"FF:FF:FF:FF:FF:FF\","
                       "\"bssid\":\"00:00:5E:00:53:01\",\"ssid\":\"LabNet\",");
    CHECK_HAS(out, "\"nf\":-95,\"phy\":\"g\",\"bw\":20,\"rate\":11,\"ts\":123456789,"
                   "\"sn\":100,\"fl\":0,\"dur\":314}\n");
    CHECK_LACKS(out, "\"mcs\"");
    CHECK_LACKS(out, "\"reason\"");
    CHECK_LACKS(out, "\"eapol\"");
    CHECK_LACKS(out, "\"fp\"");
    CHECK_EQ(out[len - 1], '\n');
    sample(out);
}

static void test_frame_channel_is_the_radio_channel(void)
{
    /* A beacon from an AP on channel 11 leaks onto channel 9. The line must
     * say where it was heard; the advertised channel goes in ap_info only. */
    uint8_t b[128];
    size_t n = fr_beacon(b, 0x0011);
    uint8_t ds = 11;
    n = fr_ie(b, n, 3, &ds, 1);
    d11_frame_t f;
    ie_info_t ie;
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    radio_meta_t rm = rm_legacy(9);
    char out[LINE_BUF];
    CHECK(line_frame(out, sizeof out, 1, 1, &rm, &f, &ie) > 0);
    CHECK_HAS(out, "\"ch\":9,");
    CHECK_LACKS(out, "\"ch\":11");
    CHECK(line_ap_info(out, sizeof out, 1, 9, MAC_AP, 100, 0x0011, &ie, "new") > 0);
    CHECK_HAS(out, "\"ch\":9,\"ds_ch\":11,");
}

static void test_hidden_ssid_is_question_mark(void)
{
    uint8_t b[128];
    d11_frame_t f;
    ie_info_t ie;
    char out[LINE_BUF];
    radio_meta_t rm = rm_legacy(1);
    size_t n = fr_beacon(b, 0x0011);
    n = fr_ie(b, n, 0, "", 0);
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    CHECK(line_frame(out, sizeof out, 1, 1, &rm, &f, &ie) > 0);
    CHECK_HAS(out, "\"ssid\":\"?\"");
    n = fr_beacon(b, 0x0011);
    n = fr_ie(b, n, 0, "\0\0\0\0", 4);
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    CHECK(line_frame(out, sizeof out, 1, 1, &rm, &f, &ie) > 0);
    CHECK_HAS(out, "\"ssid\":\"?\"");
    n = fr_beacon(b, 0x0011);
    n = fr_ie(b, n, 0, "\0A", 2);                    /* not all zero: real */
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    CHECK(line_frame(out, sizeof out, 1, 1, &rm, &f, &ie) > 0);
    CHECK_HAS(out, "\"ssid\":\"\\u0000A\"");
    n = fr_beacon(b, 0x0011);                        /* no SSID element at all */
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    CHECK(line_frame(out, sizeof out, 1, 1, &rm, &f, &ie) > 0);
    CHECK_LACKS(out, "\"ssid\"");
}

static void test_deauth_auth_and_eapol_fields(void)
{
    uint8_t b[96];
    d11_frame_t f;
    char out[LINE_BUF];
    radio_meta_t rm = rm_legacy(36);
    rm.fmt = PHY_HT;
    rm.siga1 = 0x05;
    size_t n = fr_hdr(b, 0, D11_ST_DEAUTH, D11_FL_RETRY, MAC_STA, MAC_AP, MAC_AP, 9);
    b[n++] = 7; b[n++] = 0;
    CHECK(d11_parse(b, n, &f));
    CHECK(line_frame(out, sizeof out, 2, 3, &rm, &f, NULL) > 0);
    CHECK_HAS(out, "\"type\":\"DEAUTH\",\"sub\":12,");
    CHECK_HAS(out, "\"phy\":\"n\",\"mcs\":5,\"bw\":20,\"ts\":");
    CHECK_HAS(out, "\"fl\":8,");
    CHECK_HAS(out, "\"reason\":7}");
    CHECK_LACKS(out, "\"rate\"");
    CHECK_LACKS(out, "\"ssid\"");
    sample(out);

    n = fr_hdr(b, 0, D11_ST_AUTH, 0, MAC_AP, MAC_STA, MAC_AP, 2);
    uint8_t body[6] = {3, 0, 1, 0, 0, 0};
    n = fr_put(b, n, body, 6);
    CHECK(d11_parse(b, n, &f));
    CHECK(line_frame(out, sizeof out, 3, 4, &rm, &f, NULL) > 0);
    CHECK_HAS(out, "\"aalg\":3,\"aseq\":1,\"st\":0");
    sample(out);

    n = fr_hdr(b, 2, 8, D11_FL_FROMDS, MAC_STA, MAC_AP, MAC_AP, 5);
    b[n++] = 0; b[n++] = 0;
    static const uint8_t llc[8] = {0xAA, 0xAA, 0x03, 0, 0, 0, 0x88, 0x8E};
    n = fr_put(b, n, llc, 8);
    uint8_t key[7] = {2, 3, 0, 95, 2, 0x00, 0x8A};
    n = fr_put(b, n, key, 7);
    CHECK(d11_parse(b, n, &f));
    CHECK(line_frame(out, sizeof out, 4, 5, &rm, &f, NULL) > 0);
    CHECK_HAS(out, "\"type\":\"DATA\",\"sub\":8,");
    CHECK_HAS(out, "\"fl\":2,");
    CHECK_HAS(out, "\"eapol\":1}");
    sample(out);
}

static void test_probe_request_carries_fingerprint(void)
{
    uint8_t b[96];
    d11_frame_t f;
    ie_info_t ie;
    char out[LINE_BUF];
    radio_meta_t rm = rm_legacy(11);
    size_t n = fr_hdr(b, 0, D11_ST_PROBE_REQ, 0, MAC_BC, MAC_STA, MAC_BC, 77);
    n = fr_ie(b, n, 0, "", 0);
    uint8_t v[4] = {0x00, 0x50, 0xF2, 8};
    n = fr_ie(b, n, 221, v, 4);
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    CHECK(line_frame(out, sizeof out, 5, 6, &rm, &f, &ie) > 0);
    char fp[32];
    snprintf(fp, sizeof fp, "\"fp\":\"%08x\"", (unsigned)ie.fingerprint);
    CHECK_HAS(out, fp);
    CHECK_HAS(out, "\"ouis\":[\"0050F2\"]");
    CHECK_HAS(out, "\"ssid\":\"?\"");
    sample(out);
    /* a beacon with vendor elements does not carry the client fingerprint */
    n = fr_beacon(b, 0x0011);
    n = fr_ie(b, n, 221, v, 4);
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    CHECK(line_frame(out, sizeof out, 6, 7, &rm, &f, &ie) > 0);
    CHECK_LACKS(out, "\"fp\"");
    CHECK_LACKS(out, "\"ouis\"");
}

static void test_cts_line_has_no_src_or_bssid(void)
{
    uint8_t b[16] = {0};
    b[0] = (uint8_t)((1 << 2) | (12 << 4));
    memcpy(b + 4, MAC_STA, 6);
    d11_frame_t f;
    char out[LINE_BUF];
    radio_meta_t rm = rm_legacy(1);
    CHECK(d11_parse(b, 10, &f));
    CHECK(line_frame(out, sizeof out, 8, 9, &rm, &f, NULL) > 0);
    CHECK_HAS(out, "\"type\":\"CTRL\"");
    CHECK_LACKS(out, "\"src\"");
    CHECK_LACKS(out, "\"bssid\"");
    CHECK_LACKS(out, "\"sn\"");
    sample(out);
}

static void test_ap_info_line(void)
{
    uint8_t b[160], r[40];
    uint8_t akm[] = {2, 8};
    size_t n = fr_ie(b, 0, 0, "LabNet", 6);
    uint8_t ch = 36;
    n = fr_ie(b, n, 3, &ch, 1);
    n = fr_ie(b, n, 48, r, rsn_body(r, akm, 2, 0x0080));
    uint8_t z[26] = {0};
    n = fr_ie(b, n, 45, z, 26);
    uint8_t csa[] = {1, 149, 5};
    n = fr_ie(b, n, 37, csa, 3);
    uint8_t wps[] = {0x00, 0x50, 0xF2, 4, 0x10};
    n = fr_ie(b, n, 221, wps, 5);
    ie_info_t ie;
    ie_parse(b, n, &ie);
    char out[LINE_BUF];
    CHECK(line_ap_info(out, sizeof out, 5000, 36, MAC_AP, 100, 0x0011, &ie, "new") > 0);
    CHECK_PREFIX(out, LINE_PREFIX "{\"event\":\"ap_info\",\"uptime_ms\":5000,\"why\":\"new\","
                       "\"bssid\":\"00:00:5E:00:53:01\",\"ch\":36,\"ds_ch\":36,\"ssid\":\"LabNet\","
                       "\"bi\":100,\"cap\":17,\"sec\":\"WPA2/WPA3\",\"akm\":[\"PSK\",\"SAE\"],"
                       "\"pairwise\":[\"CCMP\"],\"group\":[\"CCMP\"],\"pmf\":\"capable\","
                       "\"wpa1\":false,\"ht\":true,\"vht\":false,\"he\":false,\"eht\":false,"
                       "\"wps\":true,\"csa\":{\"mode\":1,\"ch\":149,\"count\":5},"
                       "\"ouis\":[\"0050F2\"],\"hash\":\"");
    char h[24];
    snprintf(h, sizeof h, "\"hash\":\"%08x\"}\n", (unsigned)ie_ap_hash(&ie, 0x0011));
    CHECK_HAS(out, h);
    sample(out);
    memset(&ie, 0, sizeof ie);                       /* bare open network */
    ie.ht_sec_offset = 1;
    CHECK(line_ap_info(out, sizeof out, 1, 6, MAC_AP, 100, 0x0001, &ie, "periodic") > 0);
    CHECK_HAS(out, "\"sec\":\"OPEN\",\"akm\":[],\"pairwise\":[],\"group\":[],\"pmf\":\"none\"");
    CHECK_HAS(out, "\"ht_sec\":1,");
    CHECK_LACKS(out, "\"ds_ch\"");
    CHECK_LACKS(out, "\"csa\"");
    CHECK_LACKS(out, "\"ouis\"");
    CHECK(line_ap_info(out, sizeof out, 1, 6, MAC_AP, 100, 0x0011, &ie, "new") > 0);
    CHECK_HAS(out, "\"cap\":17,\"sec\":\"WEP\"");   /* privacy bit, no RSN */
}

static void test_lifecycle_lines(void)
{
    cfg_t c;
    char out[LINE_BUF];
    fw_info_t fw = {.ver = "v2.0.0-3-gabc1234", .elf_sha = "0123456789abcdef",
                    .reset = "poweron", .baud = 460800};
    cfg_defaults(&c, BAND_5);
    CHECK(line_boot(out, sizeof out, &fw, &c) > 0);
    CHECK_PREFIX(out, LINE_PREFIX "{\"event\":\"boot\",\"chip\":\"ESP32-C5\",\"mode\":\"promiscuous\","
                       "\"band\":\"5GHz\",\"channels\":\"36-165\",\"dwell_ms\":200,\"pin\":0,"
                       "\"filter\":[\"mgmt\",\"data\"],\"dedup\":0,\"ap_info_s\":300,"
                       "\"fw\":\"spectre-sniffer\",\"ver\":\"v2.0.0-3-gabc1234\","
                       "\"elf_sha\":\"0123456789abcdef\",\"reset\":\"poweron\",\"baud\":460800,"
                       "\"caps\":[\"counters\",\"cmd\",\"ap_info\",\"phy\",\"telemetry\"]}\n");
    sample(out);

    CHECK(line_started(out, sizeof out, 36) > 0);
    CHECK_STR(out, LINE_PREFIX "{\"event\":\"sniffer_started\",\"ch\":36}\n");
    sample(out);

    counters_t k = {.rx_total = 1000, .emitted = 990, .drop_queue = 4, .drop_short = 3,
                    .drop_dedup = 2, .drop_overflow = 1, .q_hwm = 2048, .q_size = 32768};
    CHECK(line_sweep(out, sizeof out, 16570, 5012, &k) > 0);
    CHECK_STR(out, LINE_PREFIX "{\"event\":\"channel_sweep_complete\",\"total_pkts\":990,"
                   "\"uptime_ms\":16570,\"sweep_ms\":5012,\"rx_total\":1000,\"emitted\":990,"
                   "\"drop_queue\":4,\"drop_short\":3,\"drop_dedup\":2,\"drop_overflow\":1}\n");
    sample(out);

    CHECK(line_telemetry(out, sizeof out, 20000, &k, 150000, 120000, 412, 23040) > 0);
    CHECK_HAS(out, "\"event\":\"telemetry\",\"uptime_ms\":20000,\"rx_total\":1000,");
    CHECK_HAS(out, "\"q_hwm\":2048,\"q_size\":32768,\"heap\":150000,\"heap_min\":120000,"
                   "\"temp_dc\":412,\"uart_bps\":23040}\n");
    sample(out);
    CHECK(line_telemetry(out, sizeof out, 20000, &k, 1, 1, TEMP_UNKNOWN, 0) > 0);
    CHECK_LACKS(out, "temp_dc");

    CHECK(line_clock(out, sizeof out, 30000, 30000123456ULL) > 0);
    CHECK_STR(out, LINE_PREFIX "{\"event\":\"clock_sync\",\"uptime_ms\":30000,\"mono_us\":30000123456}\n");
    sample(out);
}

static void test_ack_lines(void)
{
    cfg_t c, next;
    cmd_t cmd;
    char out[LINE_BUF];
    cfg_defaults(&c, BAND_24);
    CHECK(cmd_parse("{\"cmd\":\"set\",\"id\":\"a1\",\"channels\":[1,6,11]}", &c, &next, &cmd));
    CHECK(line_ack(out, sizeof out, &cmd, &next) > 0);
    CHECK_STR(out, LINE_PREFIX "{\"event\":\"cmd_ack\",\"cmd\":\"set\",\"id\":\"a1\",\"ok\":true,"
                   "\"config\":{\"band\":\"2.4GHz\",\"channels\":\"1,6,11\",\"dwell_ms\":300,"
                   "\"pin\":0,\"filter\":[\"mgmt\",\"data\"],\"dedup\":0,\"ap_info_s\":300}}\n");
    sample(out);
    CHECK(!cmd_parse("{\"cmd\":\"set\",\"dwell_ms\":1}", &c, &next, &cmd));
    CHECK(line_ack(out, sizeof out, &cmd, &c) > 0);
    CHECK_HAS(out, "\"cmd\":\"set\",\"ok\":false,\"err\":\"bad dwell\",\"config\":{");
    CHECK_LACKS(out, "\"id\"");
    sample(out);
    c.filter = FILT_ALL;
    CHECK(cmd_parse("{\"cmd\":\"get_config\"}", &c, &next, &cmd));
    CHECK(line_ack(out, sizeof out, &cmd, &c) > 0);
    CHECK_HAS(out, "\"filter\":[\"mgmt\",\"ctrl\",\"data\"]");
}

static void test_worst_case_lines_fit(void)
{
    uint8_t b[256], ssid[32];
    memset(ssid, 0xFF, sizeof ssid);                 /* every byte escapes to 6 */
    char out[LINE_BUF];
    radio_meta_t rm = rm_legacy(165);
    rm.rssi = -128;
    rm.noise = -128;
    rm.ts_us = 0xFFFFFFFFu;
    size_t n = fr_hdr(b, 0, D11_ST_PROBE_REQ, 0xFF, MAC_BC, MAC_STA, MAC_BC, 4095);
    b[2] = b[3] = 0xFF;
    n = fr_ie(b, n, 0, ssid, 32);
    for (uint8_t i = 0; i < IE_MAX_OUIS; i++) {
        uint8_t v[3] = {0xAB, 0xCD, i};
        n = fr_ie(b, n, 221, v, 3);
    }
    d11_frame_t f;
    ie_info_t ie;
    CHECK(d11_parse(b, n, &f));
    ie_parse(f.ies, f.ies_len, &ie);
    size_t len = line_frame(out, sizeof out, 0xFFFFFFFFu, 0xFFFFFFFFu, &rm, &f, &ie);
    CHECK(len > 0);
    CHECK(len < LINE_BUF);
    sample(out);
    ie.csa = true;
    ie.akm = 0xFFF;
    ie.pairwise = ie.group_cipher = 0xFF;
    ie.ds_channel = ie.csa_channel = ie.csa_count = ie.csa_mode = 255;
    ie.ht_sec_offset = 3;
    len = line_ap_info(out, sizeof out, 0xFFFFFFFFu, 255, MAC_AP, 0xFFFF, 0xFFFF, &ie, "periodic");
    CHECK(len > 0);
    CHECK(len < LINE_BUF);
    sample(out);
    CHECK_EQ(line_ap_info(out, 200, 1, 1, MAC_AP, 1, 1, &ie, "new"), 0);  /* small buffer */
}

void suite_line(void)
{
    const char *path = getenv("SAMPLES_OUT");
    g_samples = path ? fopen(path, "w") : NULL;
    RUN(test_phy_decode);
    RUN(test_beacon_line_keeps_original_keys);
    RUN(test_frame_channel_is_the_radio_channel);
    RUN(test_hidden_ssid_is_question_mark);
    RUN(test_deauth_auth_and_eapol_fields);
    RUN(test_probe_request_carries_fingerprint);
    RUN(test_cts_line_has_no_src_or_bssid);
    RUN(test_ap_info_line);
    RUN(test_lifecycle_lines);
    RUN(test_ack_lines);
    RUN(test_worst_case_lines_fit);
    if (g_samples)
        fclose(g_samples);
}
