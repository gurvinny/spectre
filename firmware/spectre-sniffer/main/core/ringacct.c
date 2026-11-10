/*
 * Byte accounting for the receive ring buffer. See ringacct.h.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "ringacct.h"

uint32_t ra_item_bytes(uint32_t len)
{
    return ((len + RA_ALIGN - 1) & ~(RA_ALIGN - 1)) + RA_HEADER;
}

void ra_init(ring_acct_t *r)
{
    atomic_init(&r->used, 0);
    atomic_init(&r->hwm, 0);
}

void ra_add(ring_acct_t *r, uint32_t len)
{
    unsigned now = atomic_fetch_add(&r->used, ra_item_bytes(len)) + ra_item_bytes(len);
    unsigned hwm = atomic_load(&r->hwm);
    /* Another context may raise the mark between the load and the swap. */
    while (now > hwm && !atomic_compare_exchange_weak(&r->hwm, &hwm, now))
        ;
}

void ra_sub(ring_acct_t *r, uint32_t len)
{
    unsigned n = ra_item_bytes(len);
    unsigned cur = atomic_load(&r->used);
    /* Never wrap below zero: a mismatched return must not read as a full ring. */
    while (!atomic_compare_exchange_weak(&r->used, &cur, cur > n ? cur - n : 0))
        ;
}

uint32_t ra_used(ring_acct_t *r)
{
    return atomic_load(&r->used);
}

uint32_t ra_hwm(ring_acct_t *r)
{
    return atomic_load(&r->hwm);
}
