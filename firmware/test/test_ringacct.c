/*
 * Ring buffer byte accounting.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"
#include "ringacct.h"

static void test_item_bytes_match_the_idf_layout(void)
{
    CHECK_EQ(ra_item_bytes(0), 8);
    CHECK_EQ(ra_item_bytes(1), 12);
    CHECK_EQ(ra_item_bytes(4), 12);
    CHECK_EQ(ra_item_bytes(5), 16);
    CHECK_EQ(ra_item_bytes(310), 320);      /* a full management copy + item header */
}

static void test_used_follows_adds_and_returns(void)
{
    ring_acct_t r;
    ra_init(&r);
    CHECK_EQ(ra_used(&r), 0);
    ra_add(&r, 100);                         /* 100 + 8 */
    ra_add(&r, 30);                          /* 32 + 8 */
    CHECK_EQ(ra_used(&r), 148);
    ra_sub(&r, 100);
    CHECK_EQ(ra_used(&r), 40);
    ra_sub(&r, 30);
    CHECK_EQ(ra_used(&r), 0);
}

static void test_hwm_keeps_the_peak(void)
{
    ring_acct_t r;
    ra_init(&r);
    ra_add(&r, 100);
    ra_add(&r, 100);
    CHECK_EQ(ra_hwm(&r), 216);
    ra_sub(&r, 100);
    ra_sub(&r, 100);
    CHECK_EQ(ra_hwm(&r), 216);               /* draining does not lower the mark */
    ra_add(&r, 4);
    CHECK_EQ(ra_hwm(&r), 216);               /* a smaller fill does not either */
    CHECK_EQ(ra_used(&r), 12);
}

static void test_steady_flow_stays_small(void)
{
    /* One item in flight at a time, many times over: the bug this replaces
     * reported about half the ring here once the write pointer wrapped. */
    ring_acct_t r;
    ra_init(&r);
    for (int i = 0; i < 1000; i++) {
        ra_add(&r, 250);
        ra_sub(&r, 250);
    }
    CHECK_EQ(ra_hwm(&r), 260);              /* 250 -> 252 aligned + 8 */
    CHECK_EQ(ra_used(&r), 0);
}

static void test_mismatched_return_clamps_at_zero(void)
{
    ring_acct_t r;
    ra_init(&r);
    ra_add(&r, 10);
    ra_sub(&r, 100);
    CHECK_EQ(ra_used(&r), 0);
    ra_add(&r, 10);
    CHECK_EQ(ra_used(&r), 20);
    CHECK_EQ(ra_hwm(&r), 20);
}

void suite_ringacct(void)
{
    RUN(test_item_bytes_match_the_idf_layout);
    RUN(test_used_follows_adds_and_returns);
    RUN(test_hwm_keeps_the_peak);
    RUN(test_steady_flow_stays_small);
    RUN(test_mismatched_return_clamps_at_zero);
}
