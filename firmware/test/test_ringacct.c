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

/* Stand-in for vRingbufferReturnItem: at the moment the space is given back,
 * the rx callback may immediately commit a new item into it. */
typedef struct {
    ring_acct_t *r;
    uint32_t used_at_return;
    uint32_t refill_len;
    int calls;
} give_back_t;

static void give_back(void *ctx)
{
    give_back_t *g = ctx;
    g->calls++;
    g->used_at_return = ra_used(g->r);
    if (g->refill_len)
        ra_add(g->r, g->refill_len);
}

static void test_return_subtracts_before_giving_the_space_back(void)
{
    ring_acct_t r;
    ra_init(&r);
    ra_add(&r, 100);
    ra_add(&r, 100);
    give_back_t g = {.r = &r};
    ra_return(&r, 100, give_back, &g);
    CHECK_EQ(g.calls, 1);
    CHECK_EQ(g.used_at_return, 108);         /* already subtracted */
    CHECK_EQ(ra_used(&r), 108);
}

static void test_refill_into_returned_space_does_not_raise_the_peak(void)
{
    /* A full ring, one item returned, and a new item of the same size
     * committed into the freed space: the peak is still one ring's worth. */
    ring_acct_t r;
    ra_init(&r);
    for (int i = 0; i < 4; i++)
        ra_add(&r, 248);                     /* 4 x 256 */
    CHECK_EQ(ra_hwm(&r), 1024);
    give_back_t g = {.r = &r, .refill_len = 248};
    ra_return(&r, 248, give_back, &g);
    CHECK_EQ(ra_used(&r), 1024);
    CHECK_EQ(ra_hwm(&r), 1024);
}

void suite_ringacct(void)
{
    RUN(test_item_bytes_match_the_idf_layout);
    RUN(test_used_follows_adds_and_returns);
    RUN(test_hwm_keeps_the_peak);
    RUN(test_steady_flow_stays_small);
    RUN(test_mismatched_return_clamps_at_zero);
    RUN(test_return_subtracts_before_giving_the_space_back);
    RUN(test_refill_into_returned_space_does_not_raise_the_peak);
}
