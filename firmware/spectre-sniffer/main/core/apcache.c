/*
 * Per-BSSID ap_info / dedup table. See apcache.h.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "apcache.h"

#include <string.h>

void apc_init(apc_t *c) { memset(c, 0, sizeof *c); }

static apc_entry_t *lookup(apc_t *c, const uint8_t *mac, uint32_t now_ms)
{
    apc_entry_t *victim = NULL;
    uint32_t oldest_age = 0;
    for (int i = 0; i < APC_SIZE; i++) {
        apc_entry_t *e = &c->e[i];
        if (e->used && memcmp(e->mac, mac, 6) == 0) {
            e->last_seen_ms = now_ms;
            return e;
        }
        if (!e->used) {
            if (victim == NULL || victim->used)
                victim = e;          /* prefer a free slot */
            continue;
        }
        uint32_t age = now_ms - e->last_seen_ms;   /* wrap-safe */
        if (victim == NULL || (victim->used && age > oldest_age)) {
            victim = e;
            oldest_age = age;
        }
    }
    memset(victim, 0, sizeof *victim);
    memcpy(victim->mac, mac, 6);
    victim->used = true;
    victim->last_seen_ms = now_ms;
    return victim;
}

int apc_info_due(apc_t *c, const uint8_t *mac, uint32_t hash,
                 uint32_t now_ms, uint32_t interval_ms)
{
    apc_entry_t *e = lookup(c, mac, now_ms);
    int why = APC_NO;
    if (!e->info_sent)
        why = APC_NEW;
    else if (e->hash != hash)
        why = APC_CHANGED;
    else if (interval_ms && now_ms - e->last_info_ms >= interval_ms)
        why = APC_PERIODIC;
    if (why != APC_NO) {
        e->info_sent = true;
        e->hash = hash;
        e->last_info_ms = now_ms;
    }
    return why;
}

bool apc_dedup(apc_t *c, const uint8_t *mac, uint32_t epoch, uint32_t now_ms)
{
    apc_entry_t *e = lookup(c, mac, now_ms);
    if (e->dedup_epoch == epoch)
        return true;
    e->dedup_epoch = epoch;
    return false;
}

const char *apc_reason_name(int why)
{
    switch (why) {
    case APC_NEW:      return "new";
    case APC_CHANGED:  return "changed";
    case APC_PERIODIC: return "periodic";
    default:           return "none";
    }
}
