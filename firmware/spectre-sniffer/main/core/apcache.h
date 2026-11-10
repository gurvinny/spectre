/*
 * Small per-BSSID table that decides when an ap_info line is due and, in
 * dedup mode, whether a beacon was already emitted during this dwell.
 *
 * Fixed size, least-recently-seen eviction. An evicted BSSID simply counts
 * as new the next time it is heard.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define APC_SIZE 128

enum { APC_NO = 0, APC_NEW = 1, APC_CHANGED = 2, APC_PERIODIC = 3 };

typedef struct {
    uint8_t mac[6];
    bool used;
    bool info_sent;
    uint32_t hash;
    uint32_t last_info_ms;
    uint32_t last_seen_ms;
    uint32_t dedup_epoch;   /* hop epoch of the last emitted beacon, 0 = none */
} apc_entry_t;

typedef struct {
    apc_entry_t e[APC_SIZE];
} apc_t;

void apc_init(apc_t *c);

/* Whether an ap_info line is due for `mac` given the current IE hash.
 * `interval_ms` 0 disables periodic resends. Marks the line as sent. */
int apc_info_due(apc_t *c, const uint8_t *mac, uint32_t hash,
                 uint32_t now_ms, uint32_t interval_ms);

/* Dedup check for a beacon in hop epoch `epoch` (starts at 1). Returns true
 * when one was already emitted this epoch (suppress it); otherwise records
 * this one as emitted and returns false. */
bool apc_dedup(apc_t *c, const uint8_t *mac, uint32_t epoch, uint32_t now_ms);

const char *apc_reason_name(int why);
