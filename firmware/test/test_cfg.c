/*
 * Configuration defaults, validation and the UART command protocol.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"
#include "../spectre-sniffer/main/core/cfg.h"

static void test_defaults_are_valid_per_band(void)
{
    cfg_t c;
    char s[160];
    cfg_defaults(&c, BAND_24);
    CHECK(cfg_valid(&c));
    CHECK_EQ(c.n_ch, 13);
    CHECK_EQ(c.ch[0], 1);
    CHECK_EQ(c.ch[12], 13);
    CHECK_EQ(c.dwell_ms, 300);
    CHECK_EQ(c.filter, FILT_MGMT | FILT_DATA);
    CHECK_EQ(c.dedup, 0);
    CHECK_EQ(c.pin, 0);
    CHECK_EQ(c.ap_info_s, 300);
    cfg_channels_str(&c, s, sizeof s);
    CHECK_STR(s, "1-13");
    CHECK_STR(cfg_band_name(c.band), "2.4GHz");
    cfg_defaults(&c, BAND_5);
    CHECK(cfg_valid(&c));
    CHECK_EQ(c.n_ch, 25);
    CHECK_EQ(c.ch[0], 36);
    CHECK_EQ(c.ch[8], 100);
    CHECK_EQ(c.ch[24], 165);
    CHECK_EQ(c.dwell_ms, 200);
    cfg_channels_str(&c, s, sizeof s);
    CHECK_STR(s, "36-165");
    CHECK_STR(cfg_band_name(c.band), "5GHz");
    cfg_defaults(&c, 9);                             /* garbage band */
    CHECK_EQ(c.band, BAND_24);
}

static void test_channel_membership(void)
{
    CHECK(cfg_channel_ok(BAND_24, 1));
    CHECK(cfg_channel_ok(BAND_24, 14));
    CHECK(!cfg_channel_ok(BAND_24, 0));
    CHECK(!cfg_channel_ok(BAND_24, 15));
    CHECK(!cfg_channel_ok(BAND_24, 36));
    CHECK(cfg_channel_ok(BAND_5, 36));
    CHECK(cfg_channel_ok(BAND_5, 144));
    CHECK(cfg_channel_ok(BAND_5, 177));
    CHECK(!cfg_channel_ok(BAND_5, 38));
    CHECK(!cfg_channel_ok(BAND_5, 6));
    CHECK(!cfg_channel_ok(2, 36));
}

static void test_valid_rejects_each_bad_field(void)
{
    cfg_t c, d;
    cfg_defaults(&d, BAND_24);
    c = d; c.version = 0;           CHECK(!cfg_valid(&c));
    c = d; c.band = 2;              CHECK(!cfg_valid(&c));
    c = d; c.n_ch = 0;              CHECK(!cfg_valid(&c));
    c = d; c.n_ch = CFG_MAX_CH + 1; CHECK(!cfg_valid(&c));
    c = d; c.ch[3] = 40;            CHECK(!cfg_valid(&c));
    c = d; c.ch[12] = 1;            CHECK(!cfg_valid(&c));   /* duplicate */
    c = d; c.dwell_ms = DWELL_MIN_MS - 1; CHECK(!cfg_valid(&c));
    c = d; c.dwell_ms = DWELL_MIN_MS;     CHECK(cfg_valid(&c));
    c = d; c.dwell_ms = DWELL_MAX_MS;     CHECK(cfg_valid(&c));
    c = d; c.dwell_ms = DWELL_MAX_MS + 1; CHECK(!cfg_valid(&c));
    c = d; c.pin = 36;              CHECK(!cfg_valid(&c));
    c = d; c.pin = 6;               CHECK(cfg_valid(&c));
    c = d; c.filter = 0;            CHECK(!cfg_valid(&c));
    c = d; c.filter = 8;            CHECK(!cfg_valid(&c));
    c = d; c.dedup = 2;             CHECK(!cfg_valid(&c));
    c = d; c.ap_info_s = AP_INFO_MAX_S + 1; CHECK(!cfg_valid(&c));
    c = d; c.ap_info_s = AP_INFO_MAX_S;     CHECK(cfg_valid(&c));
}

static void test_simple_commands(void)
{
    cfg_t cur, next;
    cmd_t cmd;
    cfg_defaults(&cur, BAND_5);
    CHECK(cmd_parse("{\"cmd\":\"get_config\"}", &cur, &next, &cmd));
    CHECK_EQ(cmd.kind, CMD_GET);
    CHECK_STR(cmd.name, "get_config");
    CHECK(cmd.err == NULL);
    CHECK(cmd_parse(" { \"cmd\" : \"reboot\" , \"id\":\"r1\" } \r\n", &cur, &next, &cmd));
    CHECK_EQ(cmd.kind, CMD_REBOOT);
    CHECK_STR(cmd.id, "r1");
    cur.dwell_ms = 999;
    CHECK(cmd_parse("{\"cmd\":\"reset_config\"}", &cur, &next, &cmd));
    CHECK_EQ(cmd.kind, CMD_RESET);
    CHECK_EQ(next.band, BAND_5);                     /* keeps the band */
    CHECK_EQ(next.dwell_ms, 200);
}

static void test_set_channels_dwell_filter(void)
{
    cfg_t cur, next;
    cmd_t cmd;
    char s[160];
    cfg_defaults(&cur, BAND_24);
    CHECK(cmd_parse("{\"cmd\":\"set\",\"id\":\"7\",\"channels\":[1,6,11],\"dwell_ms\":250,"
                    "\"filter\":[\"mgmt\",\"ctrl\"],\"dedup\":true,\"ap_info_s\":0}",
                    &cur, &next, &cmd));
    CHECK_EQ(cmd.kind, CMD_SET);
    CHECK_EQ(next.n_ch, 3);
    CHECK_EQ(next.ch[1], 6);
    CHECK_EQ(next.dwell_ms, 250);
    CHECK_EQ(next.filter, FILT_MGMT | FILT_CTRL);
    CHECK_EQ(next.dedup, 1);
    CHECK_EQ(next.ap_info_s, 0);
    cfg_channels_str(&next, s, sizeof s);
    CHECK_STR(s, "1,6,11");
    CHECK_EQ(cur.dwell_ms, 300);                     /* current untouched */
    /* same length as the default list, different channels: never "1-13" */
    cfg_t same_len;
    CHECK(cmd_parse("{\"cmd\":\"set\",\"channels\":[1,2,3,4,5,6,7,8,9,10,11,12,14]}",
                    &cur, &same_len, &cmd));
    cfg_channels_str(&same_len, s, sizeof s);
    CHECK_STR(s, "1,2,3,4,5,6,7,8,9,10,11,12,14");
    CHECK(cmd_parse("{\"cmd\":\"set\",\"pin\":6}", &next, &cur, &cmd));
    CHECK_EQ(cur.pin, 6);
    CHECK_EQ(cur.n_ch, 3);                           /* rest carried over */
}

static void test_band_switch_starts_from_band_plan(void)
{
    cfg_t cur, next;
    cmd_t cmd;
    cfg_defaults(&cur, BAND_24);
    cur.pin = 6;
    cur.dwell_ms = 999;
    cur.dedup = 1;
    CHECK(cmd_parse("{\"cmd\":\"set\",\"band\":\"5GHz\"}", &cur, &next, &cmd));
    CHECK_EQ(next.band, BAND_5);
    CHECK_EQ(next.n_ch, 25);
    CHECK_EQ(next.pin, 0);
    CHECK_EQ(next.dwell_ms, 200);
    CHECK_EQ(next.dedup, 0);
    /* band + channels together: channels are checked against the NEW band */
    CHECK(cmd_parse("{\"cmd\":\"set\",\"channels\":[36,149],\"band\":\"5GHz\"}", &cur, &next, &cmd));
    CHECK_EQ(next.n_ch, 2);
    CHECK_EQ(next.ch[1], 149);
    /* same band again is not a reset */
    cfg_defaults(&cur, BAND_5);
    cur.dwell_ms = 400;
    CHECK(cmd_parse("{\"cmd\":\"set\",\"band\":\"5GHz\"}", &cur, &next, &cmd));
    CHECK_EQ(next.dwell_ms, 400);
}

static void test_pin_lapses_outside_new_list(void)
{
    cfg_t cur, next;
    cmd_t cmd;
    cfg_defaults(&cur, BAND_24);
    cur.pin = 6;
    CHECK(cmd_parse("{\"cmd\":\"set\",\"channels\":[1,11]}", &cur, &next, &cmd));
    CHECK_EQ(next.pin, 0);
    CHECK(cmd_parse("{\"cmd\":\"set\",\"channels\":[6,11]}", &cur, &next, &cmd));
    CHECK_EQ(next.pin, 6);
    CHECK(cmd_parse("{\"cmd\":\"set\",\"channels\":[1,11],\"pin\":13}", &cur, &next, &cmd));
    CHECK_EQ(next.pin, 13);                          /* explicit pin wins */
    CHECK(cmd_parse("{\"cmd\":\"set\",\"pin\":0}", &cur, &next, &cmd));
    CHECK_EQ(next.pin, 0);
}

static void expect_err(const char *line, const char *err)
{
    cfg_t cur, next;
    cmd_t cmd;
    cfg_defaults(&cur, BAND_24);
    CHECK(!cmd_parse(line, &cur, &next, &cmd));
    CHECK_STR(cmd.err, err);
}

static void test_set_rejects_bad_values(void)
{
    expect_err("{\"cmd\":\"set\",\"channels\":[36]}", "bad channel");
    expect_err("{\"cmd\":\"set\",\"channels\":[]}", "bad channel");
    expect_err("{\"cmd\":\"set\",\"channels\":[1,1]}", "bad channel");
    expect_err("{\"cmd\":\"set\",\"channels\":[-1]}", "bad channel");
    expect_err("{\"cmd\":\"set\",\"channels\":[-255]}", "bad channel");   /* would wrap to 1 */
    expect_err("{\"cmd\":\"set\",\"channels\":[257]}", "bad channel");
    expect_err("{\"cmd\":\"set\",\"dwell_ms\":49}", "bad dwell");
    expect_err("{\"cmd\":\"set\",\"dwell_ms\":5001}", "bad dwell");
    expect_err("{\"cmd\":\"set\",\"pin\":36}", "bad pin");
    expect_err("{\"cmd\":\"set\",\"pin\":-6}", "bad pin");
    expect_err("{\"cmd\":\"set\",\"filter\":[]}", "bad filter");
    expect_err("{\"cmd\":\"set\",\"filter\":[\"mgmt\",\"nope\"]}", "bad filter");
    expect_err("{\"cmd\":\"set\",\"dedup\":2}", "bad value");
    expect_err("{\"cmd\":\"set\",\"dedup\":257}", "bad value");          /* would wrap to 1 */
    expect_err("{\"cmd\":\"set\",\"ap_info_s\":3601}", "bad value");
    expect_err("{\"cmd\":\"set\",\"ap_info_s\":-1}", "bad value");
    expect_err("{\"cmd\":\"set\",\"ap_info_s\":-62000}", "bad value");   /* would wrap to 3536 */
    expect_err("{\"cmd\":\"set\",\"band\":\"6GHz\"}", "bad band");
    expect_err("{\"cmd\":\"set\",\"color\":1}", "unknown key");
    expect_err("{\"cmd\":\"fly\"}", "unknown cmd");
    expect_err("{\"id\":\"1\"}", "missing cmd");
    expect_err("{}", "missing cmd");
}

static void test_malformed_lines_are_rejected(void)
{
    const char *bad[] = {
        "", "   ", "cmd", "[1]", "{", "{\"cmd\"}", "{\"cmd\":}", "{\"cmd\":\"set\"",
        "{\"cmd\":\"set\",}", "{\"cmd\":\"set\"} x", "{\"cmd\":\"se\\\"t\"}",
        "{\"cmd\":\"set\",\"dwell_ms\":2.5}", "{\"cmd\":\"get_config\",\"id\":\"a\\\\b\"}", "{\"cmd\":\"set\",\"dwell_ms\":1e3}",
        "{\"cmd\":\"set\",\"dwell_ms\":\"300\"}", "{\"cmd\":\"set\",\"channels\":[1,\"6\"]}",
        "{\"cmd\":\"set\",\"channels\":{\"a\":1}}", "{\"cmd\":\"set\",\"channels\":[1,,6]}",
        "{\"cmd\":\"set\",\"channels\":[1 6]}", "{\"cmd\":\"set\",\"dwell_ms\":9999999999}",
        "{\"cmd\":\"set\",\"channels\":\"1\"}", "{\"cmd\":1}", "{\"id\":7,\"cmd\":\"get_config\"}",
        "{\"id\":\"12345678901234567\",\"cmd\":\"get_config\"}",
        "{\"cmd\":\"set\",\"filter\":[\"management\"]}", "{\"averyveryverylongkey\":1}",
        "{\"cmd\":\"get_config\"\x01}", "{\"cmd\":\"get\x01\"}",
    };
    cfg_t cur, next;
    cmd_t cmd;
    cfg_defaults(&cur, BAND_24);
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        bool ok = cmd_parse(bad[i], &cur, &next, &cmd);
        CHECK(!ok);
        CHECK_STR(cmd.err, "bad json");
        CHECK_EQ(cmd.kind, CMD_NONE);
    }
    char many[512] = "{\"cmd\":\"set\",\"channels\":[1";
    for (int i = 0; i < CFG_MAX_CH; i++)
        strcat(many, ",1");
    strcat(many, "]}");
    CHECK(!cmd_parse(many, &cur, &next, &cmd));       /* 33 items */
    CHECK_STR(cmd.err, "bad json");
}

static void test_max_channel_list_is_accepted(void)
{
    cfg_t cur, next;
    cmd_t cmd;
    char line[512] = "{\"cmd\":\"set\",\"band\":\"5GHz\",\"channels\":[";
    static const int all[] = {36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120,
                              124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165, 169,
                              173, 177};
    for (size_t i = 0; i < sizeof all / sizeof all[0]; i++) {
        char t[8];
        snprintf(t, sizeof t, i ? ",%d" : "%d", all[i]);
        strcat(line, t);
    }
    strcat(line, "]}");
    cfg_defaults(&cur, BAND_24);
    CHECK(cmd_parse(line, &cur, &next, &cmd));
    CHECK_EQ(next.n_ch, 28);
    CHECK_EQ(next.ch[27], 177);
    char s[CFG_MAX_CH * 4 + 1];
    cfg_channels_str(&next, s, sizeof s);
    CHECK_HAS(s, "36,40,");
    CHECK_HAS(s, ",173,177");
    char tiny[8];
    cfg_channels_str(&next, tiny, sizeof tiny);
    CHECK_STR(tiny, "36,40");                         /* never half a number */
}

void suite_cfg(void)
{
    RUN(test_defaults_are_valid_per_band);
    RUN(test_channel_membership);
    RUN(test_valid_rejects_each_bad_field);
    RUN(test_simple_commands);
    RUN(test_set_channels_dwell_filter);
    RUN(test_band_switch_starts_from_band_plan);
    RUN(test_pin_lapses_outside_new_list);
    RUN(test_set_rejects_bad_values);
    RUN(test_malformed_lines_are_rejected);
    RUN(test_max_channel_list_is_accepted);
}
