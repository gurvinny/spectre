/*
 * SPECTRE sniffer firmware for the ESP32-C5.
 *
 * Data path:
 *   radio -> promiscuous callback -> ring buffer -> emit task -> UART0
 * The callback only copies bytes and bumps counters; all decoding happens in
 * the emit task, so a slow UART shows up as counted ring-buffer drops rather
 * than as silent loss inside the Wi-Fi driver.
 *
 * The radio never transmits: Wi-Fi runs in NULL mode with promiscuous
 * receive only, so the full channel list can be monitored without assuming
 * a regulatory domain.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "driver/temperature_sensor.h"
#include "driver/uart.h"
#include "esp_app_desc.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/ringbuf.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "apcache.h"
#include "cfg.h"
#include "dot11.h"
#include "ie.h"
#include "line.h"

#define UART_PORT UART_NUM_0
#define UART_BAUD 460800
#define UART_TX_BUF 8192
#define UART_RX_BUF 1024
#define RING_SIZE (32 * 1024)
#define MGMT_COPY_MAX 768    /* enough for the IEs we parse */
#define DATA_COPY_MAX 64     /* header + LLC + EAPOL key info */
#define TELEMETRY_MS 10000
#define CLOCK_SYNC_MS 10000

typedef struct {
    radio_meta_t rm;
    uint16_t len;            /* bytes that follow */
} rx_item_t;

static RingbufHandle_t s_ring;
static SemaphoreHandle_t s_uart_lock;
static SemaphoreHandle_t s_cfg_lock;
static cfg_t s_cfg;
static atomic_uint s_cfg_gen;     /* bumped on every applied change */
static atomic_uint s_epoch = 1;   /* hop epoch, for dedup */
static atomic_uint s_rx_total, s_drop_queue, s_drop_short;
static uint32_t s_emitted, s_drop_dedup, s_drop_overflow, s_q_hwm; /* emit task only */
static atomic_uint s_uart_bytes;
static atomic_uint s_filter_mask = FILT_MGMT | FILT_DATA;
static apc_t s_apc;
static temperature_sensor_handle_t s_tsens;
static char s_ver[32], s_sha[17];

static uint32_t uptime_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

static void uart_line(const char *buf, size_t len)
{
    if (len == 0)
        return;
    xSemaphoreTake(s_uart_lock, portMAX_DELAY);
    uart_write_bytes(UART_PORT, buf, len);
    xSemaphoreGive(s_uart_lock);
    atomic_fetch_add(&s_uart_bytes, (unsigned)len);
}

static void snapshot(counters_t *k)
{
    k->rx_total = atomic_load(&s_rx_total);
    k->emitted = s_emitted;
    k->drop_queue = atomic_load(&s_drop_queue);
    k->drop_short = atomic_load(&s_drop_short);
    k->drop_dedup = s_drop_dedup;
    k->drop_overflow = s_drop_overflow;
    k->q_hwm = s_q_hwm;
    k->q_size = RING_SIZE;
}

static cfg_t cfg_get(void)
{
    xSemaphoreTake(s_cfg_lock, portMAX_DELAY);
    cfg_t c = s_cfg;
    xSemaphoreGive(s_cfg_lock);
    return c;
}

/* ---- NVS ----------------------------------------------------------------- */

static bool cfg_load(cfg_t *c)
{
    nvs_handle_t h;
    if (nvs_open("spectre", NVS_READONLY, &h) != ESP_OK)
        return false;
    size_t sz = sizeof *c;
    esp_err_t err = nvs_get_blob(h, "cfg", c, &sz);
    nvs_close(h);
    return err == ESP_OK && sz == sizeof *c && cfg_valid(c);
}

static void cfg_save(const cfg_t *c)
{
    nvs_handle_t h;
    if (nvs_open("spectre", NVS_READWRITE, &h) != ESP_OK)
        return;
    nvs_set_blob(h, "cfg", c, sizeof *c);
    nvs_commit(h);
    nvs_close(h);
}

/* ---- radio --------------------------------------------------------------- */

static void rx_cb(void *buf, wifi_promiscuous_pkt_type_t type)
{
    const wifi_promiscuous_pkt_t *pkt = buf;
    const wifi_pkt_rx_ctrl_t *rc = &pkt->rx_ctrl;
    atomic_fetch_add(&s_rx_total, 1);

    unsigned len = rc->sig_len > 4 ? rc->sig_len - 4 : 0;  /* drop the FCS */
    if (len < 10 || type == WIFI_PKT_MISC) {
        atomic_fetch_add(&s_drop_short, 1);
        return;
    }
    unsigned cap = type == WIFI_PKT_DATA ? DATA_COPY_MAX : MGMT_COPY_MAX;
    if (len > cap)
        len = cap;

    /* Copy straight into the ring: no large buffer on the Wi-Fi task stack. */
    void *slot = NULL;
    if (xRingbufferSendAcquire(s_ring, &slot, sizeof(rx_item_t) + len, 0) != pdTRUE) {
        atomic_fetch_add(&s_drop_queue, 1);
        return;
    }
    rx_item_t *it = slot;
    it->rm.rssi = rc->rssi;
    it->rm.noise = rc->noise_floor;
    it->rm.rate = rc->rate;
    it->rm.fmt = rc->cur_bb_format;
    it->rm.siga1 = rc->he_siga1;
    it->rm.siga2 = rc->he_siga2;
    it->rm.ts_us = rc->timestamp;
    it->rm.channel = rc->channel;
    it->len = (uint16_t)len;
    memcpy(it + 1, pkt->payload, len);
    xRingbufferSendComplete(s_ring, slot);
}

static void radio_apply(const cfg_t *c)
{
    esp_wifi_set_band_mode(c->band == BAND_5 ? WIFI_BAND_MODE_5G_ONLY : WIFI_BAND_MODE_2G_ONLY);
    wifi_promiscuous_filter_t f = {.filter_mask = 0};
    if (c->filter & FILT_MGMT) f.filter_mask |= WIFI_PROMIS_FILTER_MASK_MGMT;
    if (c->filter & FILT_CTRL) f.filter_mask |= WIFI_PROMIS_FILTER_MASK_CTRL;
    if (c->filter & FILT_DATA) f.filter_mask |= WIFI_PROMIS_FILTER_MASK_DATA;
    esp_wifi_set_promiscuous_filter(&f);
    if (c->filter & FILT_CTRL) {
        wifi_promiscuous_filter_t cf = {.filter_mask = WIFI_PROMIS_CTRL_FILTER_MASK_ALL};
        esp_wifi_set_promiscuous_ctrl_filter(&cf);
    }
    atomic_store(&s_filter_mask, c->filter);
}

static void radio_init(const cfg_t *c)
{
    wifi_init_config_t wc = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wc));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    /* Receive-only: allow every channel the radio can tune. */
    wifi_country_t country = {
        .cc = "01", .schan = 1, .nchan = 14,
        .policy = WIFI_COUNTRY_POLICY_MANUAL,
        .wifi_5g_channel_mask = 0x1FFFFFFEu,     /* channels 36-177 */
    };
    ESP_ERROR_CHECK(esp_wifi_set_country(&country));
    ESP_ERROR_CHECK(esp_wifi_start());
    radio_apply(c);
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(rx_cb));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    esp_wifi_set_channel(c->pin ? c->pin : c->ch[0], WIFI_SECOND_CHAN_NONE);
}

/* ---- tasks --------------------------------------------------------------- */

static void emit_task(void *arg)
{
    (void)arg;
    static char line[LINE_BUF];
    for (;;) {
        size_t sz;
        rx_item_t *it = xRingbufferReceive(s_ring, &sz, portMAX_DELAY);
        if (it == NULL)
            continue;
        size_t used = RING_SIZE - xRingbufferGetCurFreeSize(s_ring);
        if (used > s_q_hwm)
            s_q_hwm = (uint32_t)used;

        const uint8_t *p = (const uint8_t *)(it + 1);
        d11_frame_t f;
        if (!d11_parse(p, it->len, &f)) {
            atomic_fetch_add(&s_drop_short, 1);
            vRingbufferReturnItem(s_ring, it);
            continue;
        }
        ie_info_t ie;
        const ie_info_t *iep = NULL;
        uint32_t now = uptime_ms();
        if (f.ies) {
            ie_parse(f.ies, f.ies_len, &ie);
            iep = &ie;
        }
        bool beacon_like = f.type == D11_MGMT &&
            (f.subtype == D11_ST_BEACON || f.subtype == D11_ST_PROBE_RESP);
        if (beacon_like && f.bssid && f.body_len >= 12) {
            cfg_t c = cfg_get();
            uint16_t bi = (uint16_t)(f.body[8] | (f.body[9] << 8));
            uint16_t capa = (uint16_t)(f.body[10] | (f.body[11] << 8));
            int why = apc_info_due(&s_apc, f.bssid, ie_ap_hash(&ie, capa), now,
                                   (uint32_t)c.ap_info_s * 1000u);
            if (why != APC_NO) {
                size_t n = line_ap_info(line, sizeof line, now, it->rm.channel, f.bssid,
                                        bi, capa, &ie, apc_reason_name(why));
                if (n)
                    uart_line(line, n);
                else
                    s_drop_overflow++;
            }
            if (c.dedup && f.subtype == D11_ST_BEACON
                    && apc_dedup(&s_apc, f.bssid, atomic_load(&s_epoch), now)) {
                s_drop_dedup++;
                vRingbufferReturnItem(s_ring, it);
                continue;
            }
        }
        size_t n = line_frame(line, sizeof line, s_emitted + 1, now, &it->rm, &f, iep);
        vRingbufferReturnItem(s_ring, it);
        if (n == 0) {
            s_drop_overflow++;
            continue;
        }
        s_emitted++;
        uart_line(line, n);
    }
}

static void hop_task(void *arg)
{
    (void)arg;
    static char line[LINE_BUF];
    unsigned gen = atomic_load(&s_cfg_gen);
    cfg_t c = cfg_get();
    uint8_t idx = 0;
    uint32_t sweep_start = uptime_ms();
    uint32_t last_tel = sweep_start, last_clock = sweep_start;
    counters_t k;

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(c.dwell_ms));
        uint32_t now = uptime_ms();

        if (atomic_load(&s_cfg_gen) != gen) {
            gen = atomic_load(&s_cfg_gen);
            c = cfg_get();
            idx = 0;
            sweep_start = now;
            esp_wifi_set_channel(c.pin ? c.pin : c.ch[0], WIFI_SECOND_CHAN_NONE);
            continue;
        }
        bool wrapped;
        if (c.pin) {
            /* pinned: still report a "sweep" every list-length worth of dwells */
            wrapped = ++idx >= c.n_ch;
            if (wrapped)
                idx = 0;
        } else {
            idx = (uint8_t)((idx + 1) % c.n_ch);
            wrapped = idx == 0;
            esp_wifi_set_channel(c.ch[idx], WIFI_SECOND_CHAN_NONE);
        }
        atomic_fetch_add(&s_epoch, 1);

        if (wrapped) {
            snapshot(&k);
            uart_line(line, line_sweep(line, sizeof line, now, now - sweep_start, &k));
            sweep_start = now;
        }
        if (now - last_tel >= TELEMETRY_MS) {
            float t = 0;
            int temp_dc = TEMP_UNKNOWN;
            if (s_tsens && temperature_sensor_get_celsius(s_tsens, &t) == ESP_OK)
                temp_dc = (int)(t * 10.0f);
            uint32_t bytes = atomic_exchange(&s_uart_bytes, 0);
            uint32_t bps = (uint32_t)((uint64_t)bytes * 1000u / (now - last_tel));
            snapshot(&k);
            uart_line(line, line_telemetry(line, sizeof line, now, &k,
                      (uint32_t)esp_get_free_heap_size(),
                      (uint32_t)esp_get_minimum_free_heap_size(), temp_dc, bps));
            last_tel = now;
        }
        if (now - last_clock >= CLOCK_SYNC_MS) {
            uart_line(line, line_clock(line, sizeof line, now, (uint64_t)esp_timer_get_time()));
            last_clock = now;
        }
    }
}

static void cmd_task(void *arg)
{
    (void)arg;
    static char out[LINE_BUF];
    char buf[256];
    size_t n = 0;
    bool overlong = false;
    for (;;) {
        uint8_t ch;
        if (uart_read_bytes(UART_PORT, &ch, 1, portMAX_DELAY) != 1)
            continue;
        if (ch != '\n' && ch != '\r') {
            if (n + 1 < sizeof buf)
                buf[n++] = (char)ch;
            else
                overlong = true;
            continue;
        }
        if (n == 0)
            continue;
        buf[n] = '\0';
        n = 0;

        cfg_t cur = cfg_get(), next;
        cmd_t cmd;
        bool ok = !overlong && cmd_parse(buf, &cur, &next, &cmd);
        if (overlong) {
            memset(&cmd, 0, sizeof cmd);
            cmd.err = "line too long";
        }
        overlong = false;
        if (ok && (cmd.kind == CMD_SET || cmd.kind == CMD_RESET)) {
            xSemaphoreTake(s_cfg_lock, portMAX_DELAY);
            s_cfg = next;
            xSemaphoreGive(s_cfg_lock);
            cfg_save(&next);
            radio_apply(&next);
            atomic_fetch_add(&s_cfg_gen, 1);
            cur = next;
        }
        uart_line(out, line_ack(out, sizeof out, &cmd, &cur));
        if (ok && cmd.kind == CMD_REBOOT) {
            uart_wait_tx_done(UART_PORT, pdMS_TO_TICKS(500));
            esp_restart();
        }
    }
}

/* ---- boot ---------------------------------------------------------------- */

static const char *reset_name(esp_reset_reason_t r)
{
    switch (r) {
    case ESP_RST_POWERON:  return "poweron";
    case ESP_RST_EXT:      return "external";
    case ESP_RST_SW:       return "software";
    case ESP_RST_PANIC:    return "panic";
    case ESP_RST_INT_WDT:  return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT:      return "wdt";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_USB:      return "usb";
    case ESP_RST_JTAG:     return "jtag";
    default:               return "other";
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    uart_config_t uc = {
        .baud_rate = UART_BAUD, .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, UART_RX_BUF, UART_TX_BUF, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &uc));

    s_uart_lock = xSemaphoreCreateMutex();
    s_cfg_lock = xSemaphoreCreateMutex();
    s_ring = xRingbufferCreate(RING_SIZE, RINGBUF_TYPE_NOSPLIT);
    configASSERT(s_uart_lock && s_cfg_lock && s_ring);
    apc_init(&s_apc);

    temperature_sensor_config_t tc = TEMPERATURE_SENSOR_CONFIG_DEFAULT(-10, 80);
    if (temperature_sensor_install(&tc, &s_tsens) == ESP_OK)
        temperature_sensor_enable(s_tsens);
    else
        s_tsens = NULL;

    if (!cfg_load(&s_cfg))
        cfg_defaults(&s_cfg, BAND_24);   /* a fresh board: set the band by command */

    const esp_app_desc_t *app = esp_app_get_description();
    snprintf(s_ver, sizeof s_ver, "%s", app->version);
    esp_app_get_elf_sha256(s_sha, sizeof s_sha);
    fw_info_t fw = {.ver = s_ver, .elf_sha = s_sha,
                    .reset = reset_name(esp_reset_reason()), .baud = UART_BAUD};

    static char line[LINE_BUF];
    uart_line(line, line_boot(line, sizeof line, &fw, &s_cfg));
    radio_init(&s_cfg);
    esp_log_level_set("*", ESP_LOG_ERROR);   /* keep the UART for data lines */
    uart_line(line, line_started(line, sizeof line, s_cfg.pin ? s_cfg.pin : s_cfg.ch[0]));

    xTaskCreate(emit_task, "emit", 6144, NULL, 5, NULL);
    xTaskCreate(hop_task, "hop", 4096, NULL, 6, NULL);
    xTaskCreate(cmd_task, "cmd", 4096, NULL, 4, NULL);
}
