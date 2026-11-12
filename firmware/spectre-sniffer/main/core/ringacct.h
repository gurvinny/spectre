/*
 * Byte accounting for the receive ring buffer.
 *
 * The IDF call for free space on a no-split ring returns the largest item
 * that fits contiguously, which drops to about half the buffer as soon as the
 * write pointer wraps, so "size minus free" overstates use. This tracks what
 * is actually held instead: the rx callback adds each item it commits, the
 * emit task subtracts it on return, and the high-water mark follows that.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdatomic.h>
#include <stdint.h>

/* Ring overhead per item (IDF esp_ringbuf): payload rounded up to 4 bytes,
 * plus an 8-byte item header (length + flags on a 32-bit target). */
#define RA_ALIGN 4u
#define RA_HEADER 8u

typedef struct {
    atomic_uint used;
    atomic_uint hwm;
} ring_acct_t;

uint32_t ra_item_bytes(uint32_t len);
void ra_init(ring_acct_t *r);
void ra_add(ring_acct_t *r, uint32_t len);
void ra_sub(ring_acct_t *r, uint32_t len);
/* Return one item: subtract it, then call give_back (vRingbufferReturnItem).
 * Subtracting first means the rx callback can never commit into the freed
 * space while the returned item is still counted, so used and the
 * high-water mark never exceed what the ring can hold. */
void ra_return(ring_acct_t *r, uint32_t len, void (*give_back)(void *ctx), void *ctx);
uint32_t ra_used(ring_acct_t *r);
uint32_t ra_hwm(ring_acct_t *r);
