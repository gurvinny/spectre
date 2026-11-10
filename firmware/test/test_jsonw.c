/*
 * Bounded JSON writer.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"
#include "../spectre-sniffer/main/core/jsonw.h"

static void test_object_with_commas_and_nesting(void)
{
    char buf[128];
    jw_t w;
    jw_init(&w, buf, sizeof buf);
    jw_open(&w, NULL);
    jw_int(&w, "a", -5);
    jw_bool(&w, "b", true);
    jw_arr(&w, "c");
    jw_int(&w, NULL, 1);
    jw_str(&w, NULL, "x");
    jw_arr_end(&w);
    jw_open(&w, "d");
    jw_bool(&w, "e", false);
    jw_close(&w);
    jw_arr(&w, "f");
    jw_arr_end(&w);
    jw_close(&w);
    size_t n = jw_finish(&w);
    CHECK_STR(buf, "{\"a\":-5,\"b\":true,\"c\":[1,\"x\"],\"d\":{\"e\":false},\"f\":[]}");
    CHECK_EQ(n, strlen(buf));
}

static void test_escapes_quotes_backslash_and_controls(void)
{
    char buf[128];
    jw_t w;
    jw_init(&w, buf, sizeof buf);
    jw_open(&w, NULL);
    const uint8_t s[] = {'a', '"', '\\', '\n', 0x00, 0x7F, 'z'};
    jw_bytes(&w, "s", s, sizeof s);
    jw_close(&w);
    CHECK(jw_finish(&w) > 0);
    CHECK_STR(buf, "{\"s\":\"a\\\"\\\\\\u000a\\u0000\\u007fz\"}");
}

static void test_utf8_passes_and_invalid_bytes_are_escaped(void)
{
    char buf[200];
    jw_t w;
    jw_init(&w, buf, sizeof buf);
    jw_open(&w, NULL);
    const uint8_t ok[] = {'c', 0xC3, 0xA9, 0xE2, 0x82, 0xAC, 0xF0, 0x9F, 0x93, 0xB6};
    jw_bytes(&w, "ok", ok, sizeof ok);
    const uint8_t bad[] = {0xFF, 0xC0, 0xAF, 0xED, 0xA0, 0x80, 0xC3};
    jw_bytes(&w, "bad", bad, sizeof bad);
    const uint8_t over[] = {0xE0, 0x80, 0x80, 0xF0, 0x80, 0x80, 0x80, 0xF4, 0x90, 0x80, 0x80};
    jw_bytes(&w, "over", over, sizeof over);
    const uint8_t lead[] = {0xC3, 'A'};              /* lead byte, no continuation */
    jw_bytes(&w, "lead", lead, sizeof lead);
    jw_close(&w);
    CHECK(jw_finish(&w) > 0);
    CHECK_HAS(buf, "\"ok\":\"c\xC3\xA9\xE2\x82\xAC\xF0\x9F\x93\xB6\"");
    CHECK_HAS(buf, "\"bad\":\"\\u00ff\\u00c0\\u00af\\u00ed\\u00a0\\u0080\\u00c3\"");
    CHECK_HAS(buf, "\"over\":\"\\u00e0\\u0080\\u0080\\u00f0\\u0080\\u0080\\u0080\\u00f4\\u0090\\u0080\\u0080\"");
    CHECK_HAS(buf, "\"lead\":\"\\u00c3A\"");
}

static void test_mac_and_hex(void)
{
    char buf[64];
    jw_t w;
    const uint8_t m[6] = {0x00, 0x00, 0x5E, 0x00, 0x53, 0xab};
    jw_init(&w, buf, sizeof buf);
    jw_open(&w, NULL);
    jw_mac(&w, "m", m);
    jw_hex32(&w, "h", 0x00ABCDEFu);
    jw_close(&w);
    CHECK(jw_finish(&w) > 0);
    CHECK_STR(buf, "{\"m\":\"00:00:5E:00:53:AB\",\"h\":\"00abcdef\"}");
}

static void test_overflow_returns_zero_and_never_writes_past_cap(void)
{
    char buf[32];
    memset(buf, 'Q', sizeof buf);
    jw_t w;
    jw_init(&w, buf, 20);
    jw_open(&w, NULL);
    jw_str(&w, "k", "0123456789abcdef");
    jw_close(&w);
    CHECK_EQ(jw_finish(&w), 0);
    CHECK_EQ(buf[0], '\0');
    for (int i = 20; i < 32; i++)
        CHECK_EQ(buf[i], 'Q');
    /* exactly fits: 19 chars + terminator */
    jw_init(&w, buf, 20);
    jw_open(&w, NULL);
    jw_str(&w, "k", "0123456789a");
    jw_close(&w);
    CHECK_EQ(jw_finish(&w), 19);
    jw_init(&w, buf, 19);
    jw_open(&w, NULL);
    jw_str(&w, "k", "0123456789a");
    jw_close(&w);
    CHECK_EQ(jw_finish(&w), 0);
    jw_init(&w, buf, 0);
    CHECK(w.overflow);
}

static void test_unclosed_object_is_not_emitted(void)
{
    char buf[32];
    jw_t w;
    jw_init(&w, buf, sizeof buf);
    jw_open(&w, NULL);
    jw_int(&w, "a", 1);
    CHECK_EQ(jw_finish(&w), 0);
    jw_init(&w, buf, sizeof buf);
    jw_open(&w, NULL);
    jw_open(&w, "a");
    jw_open(&w, "b");
    jw_open(&w, "c");                                /* past JW_MAX_DEPTH */
    jw_close(&w); jw_close(&w); jw_close(&w); jw_close(&w);
    CHECK_EQ(jw_finish(&w), 0);
}

void suite_jsonw(void)
{
    RUN(test_object_with_commas_and_nesting);
    RUN(test_escapes_quotes_backslash_and_controls);
    RUN(test_utf8_passes_and_invalid_bytes_are_escaped);
    RUN(test_mac_and_hex);
    RUN(test_overflow_returns_zero_and_never_writes_past_cap);
    RUN(test_unclosed_object_is_not_emitted);
}
