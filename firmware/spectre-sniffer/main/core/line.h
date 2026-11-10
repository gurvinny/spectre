/*
 * UART line formatting. Every line is
 *     <190>ESP32C5 wifi_sniffer: {json}\n
 * Frame lines carry "type"; every other line carries "event". The keys the
 * original firmware emitted keep their names and meaning; everything else is
 * additive, so an older sensor still ingests these lines.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "cfg.h"
#include "dot11.h"
#include "ie.h"

#define LINE_PREFIX "<190>ESP32C5 wifi_sniffer: "
#define LINE_BUF 640

/* PHY formats as reported by the radio. */
enum {
    PHY_11B = 0, PHY_11AG = 1, PHY_HT = 2, PHY_VHT = 3, PHY_HE_SU = 4,
    PHY_HE_MU = 5, PHY_HE_ERSU = 6, PHY_HE_TB = 7, PHY_VHT_MU = 11,
};

typedef struct {
    int8_t rssi;
    int8_t noise;
    uint8_t rate;        /* legacy rate code (11b/11ag only) */
    uint8_t fmt;         /* PHY_* */
    uint32_t siga1;      /* HT-SIG / VHT-SIG-A1 / HE-SIG-A1 */
    uint16_t siga2;
    uint32_t ts_us;      /* radio receive timestamp */
    uint8_t channel;
} radio_meta_t;

typedef struct {
    const char *phy;     /* "b","g","a","n","ac","ax",... */
    int mcs;             /* -1 when not applicable */
    int bw;              /* MHz */
} phy_info_t;

void phy_decode(const radio_meta_t *rm, phy_info_t *out);

typedef struct {
    uint32_t rx_total;      /* frames delivered by the radio */
    uint32_t emitted;       /* frame lines written (== last seq) */
    uint32_t drop_queue;    /* ring buffer full in the rx callback */
    uint32_t drop_short;    /* too short / undecodable */
    uint32_t drop_dedup;    /* beacons suppressed by dedup mode */
    uint32_t drop_overflow; /* line longer than LINE_BUF */
    uint32_t q_hwm;         /* ring buffer high-water mark, bytes */
    uint32_t q_size;        /* ring buffer size, bytes */
} counters_t;

typedef struct {
    const char *ver;        /* app version (git describe) */
    const char *elf_sha;    /* first 16 hex chars of the app ELF sha256 */
    const char *reset;      /* reset reason */
    uint32_t baud;
} fw_info_t;

size_t line_frame(char *buf, size_t cap, uint32_t seq, uint32_t uptime_ms,
                  const radio_meta_t *rm, const d11_frame_t *f, const ie_info_t *ie);
size_t line_ap_info(char *buf, size_t cap, uint32_t uptime_ms, uint8_t ch,
                    const uint8_t *bssid, uint16_t beacon_int, uint16_t capability,
                    const ie_info_t *ie, const char *why);
size_t line_boot(char *buf, size_t cap, const fw_info_t *fw, const cfg_t *c);
size_t line_started(char *buf, size_t cap, uint8_t ch);
size_t line_sweep(char *buf, size_t cap, uint32_t uptime_ms, uint32_t sweep_ms,
                  const counters_t *k);
size_t line_telemetry(char *buf, size_t cap, uint32_t uptime_ms, const counters_t *k,
                      uint32_t heap_free, uint32_t heap_min, int temp_dc,
                      uint32_t uart_bps);
size_t line_clock(char *buf, size_t cap, uint32_t uptime_ms, uint64_t mono_us);
size_t line_ack(char *buf, size_t cap, const cmd_t *cmd, const cfg_t *c);

#define TEMP_UNKNOWN (-32768)
