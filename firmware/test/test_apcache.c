/*
 * Per-BSSID ap_info scheduling and beacon dedup.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "check.h"
#include "../spectre-sniffer/main/core/apcache.h"

static apc_t g_cache;

static void mac_n(uint8_t *m, int n)
{
    m[0] = 0x00; m[1] = 0x00; m[2] = 0x5E; m[3] = 0x00;
    m[4] = (uint8_t)(n >> 8); m[5] = (uint8_t)n;
}

static void test_info_new_changed_periodic(void)
{
    uint8_t m[6];
    mac_n(m, 1);
    apc_init(&g_cache);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xAA, 1000, 300000), APC_NEW);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xAA, 2000, 300000), APC_NO);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xBB, 3000, 300000), APC_CHANGED);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xBB, 3000 + 299999, 300000), APC_NO);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xBB, 3000 + 300000, 300000), APC_PERIODIC);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xBB, 3000 + 300001, 300000), APC_NO);
    CHECK_EQ(apc_info_due(&g_cache, m, 0xBB, 0xF0000000u, 0), APC_NO);  /* periodic off */
    CHECK_STR(apc_reason_name(APC_NEW), "new");
    CHECK_STR(apc_reason_name(APC_CHANGED), "changed");
    CHECK_STR(apc_reason_name(APC_PERIODIC), "periodic");
    CHECK_STR(apc_reason_name(APC_NO), "none");
}

static void test_periodic_survives_uptime_wrap(void)
{
    uint8_t m[6];
    mac_n(m, 2);
    apc_init(&g_cache);
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 0xFFFFFF00u, 1000), APC_NEW);
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 0x000002E7u, 1000), APC_NO);    /* 999 ms later */
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 0x000002E8u, 1000), APC_PERIODIC);
}

static void test_dedup_once_per_epoch(void)
{
    uint8_t a[6], b[6];
    mac_n(a, 3);
    mac_n(b, 4);
    apc_init(&g_cache);
    CHECK(!apc_dedup(&g_cache, a, 1, 10));
    CHECK(apc_dedup(&g_cache, a, 1, 20));
    CHECK(!apc_dedup(&g_cache, b, 1, 20));
    CHECK(!apc_dedup(&g_cache, a, 2, 30));
    CHECK(apc_dedup(&g_cache, a, 2, 40));
    /* dedup and ap_info share an entry without clobbering each other */
    CHECK_EQ(apc_info_due(&g_cache, a, 5, 50, 0), APC_NEW);
    CHECK(apc_dedup(&g_cache, a, 2, 60));
    CHECK_EQ(apc_info_due(&g_cache, a, 5, 70, 0), APC_NO);
}

static void test_eviction_drops_least_recently_seen(void)
{
    uint8_t m[6];
    apc_init(&g_cache);
    for (int i = 0; i < APC_SIZE; i++) {
        mac_n(m, 100 + i);
        CHECK_EQ(apc_info_due(&g_cache, m, 1, (uint32_t)i, 0), APC_NEW);
    }
    mac_n(m, 100);                                   /* touch the oldest */
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 1000, 0), APC_NO);
    mac_n(m, 999);                                   /* table full: evicts #101 */
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 1001, 0), APC_NEW);
    mac_n(m, 100);
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 1002, 0), APC_NO);
    mac_n(m, 102);
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 1003, 0), APC_NO);
    mac_n(m, 101);
    CHECK_EQ(apc_info_due(&g_cache, m, 1, 1004, 0), APC_NEW);
}

void suite_apcache(void)
{
    RUN(test_info_new_changed_periodic);
    RUN(test_periodic_survives_uptime_wrap);
    RUN(test_dedup_once_per_epoch);
    RUN(test_eviction_drops_least_recently_seen);
}
