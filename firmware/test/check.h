/*
 * Minimal host test harness: counted assertions, one failure header per
 * failing test ("FAIL: test_name (file:line: expr)"), and floors on the
 * number of tests and assertions so a suite that silently stops running
 * cannot pass.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

extern int g_asserts;
void check_fail(const char *file, int line, const char *expr);
void run_test(const char *name, void (*fn)(void));

#define CHECK(c) do { g_asserts++; if (!(c)) check_fail(__FILE__, __LINE__, #c); } while (0)
#define CHECK_EQ(a, b) do { g_asserts++; long long _a = (long long)(a), _b = (long long)(b); \
    if (_a != _b) { char _m[160]; snprintf(_m, sizeof _m, "%s == %s (%lld != %lld)", #a, #b, _a, _b); \
    check_fail(__FILE__, __LINE__, _m); } } while (0)
#define CHECK_STR(a, b) do { g_asserts++; const char *_a = (a), *_b = (b); \
    if (!_a || !_b || strcmp(_a, _b) != 0) { char _m[2048]; snprintf(_m, sizeof _m, "%.100s == \"%.900s\" (got \"%.900s\")", #a, _b ? _b : "(null)", _a ? _a : "(null)"); \
    check_fail(__FILE__, __LINE__, _m); } } while (0)
#define CHECK_HAS(hay, needle) do { g_asserts++; const char *_h = (hay), *_n = (needle); \
    if (!_h || !strstr(_h, _n)) { char _m[2048]; snprintf(_m, sizeof _m, "contains %.400s in: %.900s", _n, _h ? _h : "(null)"); \
    check_fail(__FILE__, __LINE__, _m); } } while (0)
#define CHECK_LACKS(hay, needle) do { g_asserts++; const char *_h = (hay), *_n = (needle); \
    if (!_h || strstr(_h, _n)) { char _m[2048]; snprintf(_m, sizeof _m, "lacks %.400s in: %.900s", _n, _h ? _h : "(null)"); \
    check_fail(__FILE__, __LINE__, _m); } } while (0)

#define CHECK_PREFIX(s, prefix) do { g_asserts++; const char *_s = (s), *_p = (prefix); \
    if (!_s || strncmp(_s, _p, strlen(_p)) != 0) { char _m[2048]; snprintf(_m, sizeof _m, "starts with %.900s got: %.900s", _p, _s ? _s : "(null)"); \
    check_fail(__FILE__, __LINE__, _m); } } while (0)

#define RUN(fn) run_test(#fn, fn)

void suite_dot11(void);
void suite_ringacct(void);
void suite_ie(void);
void suite_jsonw(void);
void suite_cfg(void);
void suite_apcache(void);
void suite_line(void);
