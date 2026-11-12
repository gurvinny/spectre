/*
 * Host test runner for the firmware's portable core.
 *
 * Raise the floors when the suite grows. Never lower them to make a run pass.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"

#include <stdlib.h>

#define MIN_TESTS 64
#define MIN_ASSERTS 861

int g_asserts;
static int g_tests, g_failed, g_extra, g_fail_total;
static const char *g_current;
static bool g_current_failed;

void check_fail(const char *file, int line, const char *expr)
{
    /* A defect inside a loop can fail the same assertion forever: keep the
     * output bounded and give up rather than flood the log. */
    if (++g_fail_total > 10000) {
        printf("ABORT: more than 10000 failed assertions\n");
        fflush(stdout);
        exit(1);
    }
    if (!g_current_failed) {
        printf("FAIL: %s (%s:%d: %s)\n", g_current, file, line, expr);
        g_failed++;
        g_extra = 0;
    } else if (++g_extra <= 20) {
        printf("      also %s:%d: %s\n", file, line, expr);
    }
    g_current_failed = true;
}

void run_test(const char *name, void (*fn)(void))
{
    g_current = name;
    g_current_failed = false;
    g_tests++;
    /* announce first, so a crash (ASan abort) is attributed to this test */
    printf("RUN: %s\n", name);
    fflush(stdout);
    fn();
    if (!g_current_failed)
        printf("ok    %s\n", name);
}

int main(void)
{
    suite_dot11();
    suite_ie();
    suite_jsonw();
    suite_cfg();
    suite_apcache();
    suite_line();
    suite_ringacct();

    printf("\n%d tests, %d assertions, %d failed\n", g_tests, g_asserts, g_failed);
    if (g_failed)
        return 1;
    if (g_tests < MIN_TESTS) {
        printf("FAIL: ran %d tests, floor is %d\n", g_tests, MIN_TESTS);
        return 1;
    }
    if (g_asserts < MIN_ASSERTS) {
        printf("FAIL: %d assertions, floor is %d\n", g_asserts, MIN_ASSERTS);
        return 1;
    }
    return 0;
}
