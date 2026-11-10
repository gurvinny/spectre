/*
 * UART line formatting. See line.h for the contract.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "line.h"

#include <string.h>

#include "jsonw.h"

void phy_decode(const radio_meta_t *rm, phy_info_t *out)
{
    out->mcs = -1;
    out->bw = 20;
    switch (rm->fmt) {
    case PHY_11B:
        out->phy = "b";
        break;
    case PHY_11AG:
        out->phy = rm->channel > 14 ? "a" : "g";
        break;
    case PHY_HT:
        /* HT-SIG1: B0-B6 MCS, B7 CBW 20/40 */
        out->phy = "n";
        out->mcs = (int)(rm->siga1 & 0x7F);
        out->bw = (rm->siga1 & 0x80) ? 40 : 20;
        break;
    case PHY_VHT:
    case PHY_VHT_MU:
        /* VHT-SIG-A1: B0-B1 BW; VHT-SIG-A2: B4-B7 SU MCS */
        out->phy = rm->fmt == PHY_VHT ? "ac" : "ac-mu";
        out->bw = 20 << (rm->siga1 & 0x3);
        if (rm->fmt == PHY_VHT)
            out->mcs = (rm->siga2 >> 4) & 0xF;
        break;
    case PHY_HE_SU:
        /* HE-SU-SIG-A1: B3-B6 MCS, B19-B20 BW */
        out->phy = "ax";
        out->mcs = (int)((rm->siga1 >> 3) & 0xF);
        out->bw = 20 << ((rm->siga1 >> 19) & 0x3);
        break;
    case PHY_HE_ERSU:
        out->phy = "ax-er";
        out->mcs = (int)((rm->siga1 >> 3) & 0xF);
        break;
    case PHY_HE_MU:
        out->phy = "ax-mu";
        break;
    case PHY_HE_TB:
        out->phy = "ax-tb";
        break;
    default:
        out->phy = "?";
        break;
    }
}

static void begin(jw_t *w, char *buf, size_t cap)
{
    jw_init(w, buf, cap);
    jw_raw(w, LINE_PREFIX);
    jw_open(w, NULL);
}

static size_t end(jw_t *w)
{
    jw_close(w);
    jw_raw(w, "\n");
    return jw_finish(w);
}

static void ssid(jw_t *w, const ie_info_t *ie)
{
    /* Empty, or zero bytes of the real length: both mean a hidden network,
     * reported as "?" exactly as the original firmware did. */
    bool hidden = true;
    for (uint8_t i = 0; i < ie->ssid_len; i++)
        if (ie->ssid[i] != 0)
            hidden = false;
    if (hidden)
        jw_str(w, "ssid", "?");
    else
        jw_bytes(w, "ssid", ie->ssid, ie->ssid_len);
}

static void ouis(jw_t *w, const ie_info_t *ie)
{
    if (ie->n_ouis == 0)
        return;
    jw_arr(w, "ouis");
    for (uint8_t i = 0; i < ie->n_ouis; i++) {
        char s[7];
        static const char hex[] = "0123456789ABCDEF";
        for (int j = 0; j < 3; j++) {
            s[2 * j] = hex[ie->ouis[i][j] >> 4];
            s[2 * j + 1] = hex[ie->ouis[i][j] & 0xF];
        }
        s[6] = '\0';
        jw_str(w, NULL, s);
    }
    jw_arr_end(w);
}

size_t line_frame(char *buf, size_t cap, uint32_t seq, uint32_t uptime_ms,
                  const radio_meta_t *rm, const d11_frame_t *f, const ie_info_t *ie)
{
    jw_t w;
    phy_info_t phy;
    phy_decode(rm, &phy);

    begin(&w, buf, cap);
    jw_int(&w, "seq", seq);
    jw_int(&w, "uptime_ms", uptime_ms);
    jw_int(&w, "ch", rm->channel);
    jw_int(&w, "rssi", rm->rssi);
    jw_str(&w, "type", d11_type_name(f));
    jw_int(&w, "sub", f->subtype);
    if (f->ta)
        jw_mac(&w, "src", f->ta);
    jw_mac(&w, "dst", f->ra);
    if (f->bssid)
        jw_mac(&w, "bssid", f->bssid);
    if (ie && ie->has_ssid)
        ssid(&w, ie);
    jw_int(&w, "nf", rm->noise);
    jw_str(&w, "phy", phy.phy);
    if (phy.mcs >= 0)
        jw_int(&w, "mcs", phy.mcs);
    jw_int(&w, "bw", phy.bw);
    if (rm->fmt == PHY_11B || rm->fmt == PHY_11AG)
        jw_int(&w, "rate", rm->rate);
    jw_int(&w, "ts", rm->ts_us);
    if (f->has_seq)
        jw_int(&w, "sn", f->seq);
    jw_int(&w, "fl", f->flags);
    jw_int(&w, "dur", f->duration);
    if (f->reason >= 0)
        jw_int(&w, "reason", f->reason);
    if (f->auth_alg >= 0) {
        jw_int(&w, "aalg", f->auth_alg);
        jw_int(&w, "aseq", f->auth_seq);
        jw_int(&w, "st", f->status);
    }
    if (f->eapol)
        jw_int(&w, "eapol", f->eapol);
    if (ie && f->type == D11_MGMT && f->subtype == D11_ST_PROBE_REQ) {
        jw_hex32(&w, "fp", ie->fingerprint);
        ouis(&w, ie);
    }
    return end(&w);
}

static void names(jw_t *w, const char *key, unsigned mask,
                  const char *const *tbl, int n)
{
    jw_arr(w, key);
    for (int i = 0; i < n; i++)
        if (mask & (1u << i))
            jw_str(w, NULL, tbl[i]);
    jw_arr_end(w);
}

static const char *const AKM_NAMES[] = {
    "802.1X", "PSK", "FT-802.1X", "FT-PSK", "802.1X-SHA256", "PSK-SHA256",
    "SAE", "FT-SAE", "SUITE-B", "OWE", "SAE-EXT", "OTHER",
};
static const char *const CIPHER_NAMES[] = {
    "WEP", "TKIP", "CCMP", "GCMP", "GCMP-256", "CCMP-256", "BIP", "OTHER",
};
static const char *const PMF_NAMES[] = {"none", "capable", "required"};

size_t line_ap_info(char *buf, size_t cap, uint32_t uptime_ms, uint8_t ch,
                    const uint8_t *bssid, uint16_t beacon_int, uint16_t capability,
                    const ie_info_t *ie, const char *why)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "ap_info");
    jw_int(&w, "uptime_ms", uptime_ms);
    jw_str(&w, "why", why);
    jw_mac(&w, "bssid", bssid);
    jw_int(&w, "ch", ch);
    if (ie->ds_channel)
        jw_int(&w, "ds_ch", ie->ds_channel);
    ssid(&w, ie);
    jw_int(&w, "bi", beacon_int);
    jw_int(&w, "cap", capability);
    jw_str(&w, "sec", ie_security(ie, capability));
    names(&w, "akm", ie->akm, AKM_NAMES, 12);
    names(&w, "pairwise", ie->pairwise, CIPHER_NAMES, 8);
    names(&w, "group", ie->group_cipher, CIPHER_NAMES, 8);
    jw_str(&w, "pmf", PMF_NAMES[ie->pmf <= PMF_REQUIRED ? ie->pmf : 0]);
    jw_bool(&w, "wpa1", ie->wpa1);
    jw_bool(&w, "ht", ie->ht);
    jw_bool(&w, "vht", ie->vht);
    jw_bool(&w, "he", ie->he);
    jw_bool(&w, "eht", ie->eht);
    if (ie->ht_sec_offset)
        jw_int(&w, "ht_sec", ie->ht_sec_offset);
    jw_bool(&w, "wps", ie->wps);
    if (ie->csa) {
        jw_open(&w, "csa");
        jw_int(&w, "mode", ie->csa_mode);
        jw_int(&w, "ch", ie->csa_channel);
        jw_int(&w, "count", ie->csa_count);
        jw_close(&w);
    }
    ouis(&w, ie);
    jw_hex32(&w, "hash", ie_ap_hash(ie, capability));
    return end(&w);
}

static void config(jw_t *w, const cfg_t *c)
{
    char chs[CFG_MAX_CH * 4 + 1];
    cfg_channels_str(c, chs, sizeof chs);
    jw_str(w, "band", cfg_band_name(c->band));
    jw_str(w, "channels", chs);
    jw_int(w, "dwell_ms", c->dwell_ms);
    jw_int(w, "pin", c->pin);
    jw_arr(w, "filter");
    if (c->filter & FILT_MGMT) jw_str(w, NULL, "mgmt");
    if (c->filter & FILT_CTRL) jw_str(w, NULL, "ctrl");
    if (c->filter & FILT_DATA) jw_str(w, NULL, "data");
    jw_arr_end(w);
    jw_int(w, "dedup", c->dedup);
    jw_int(w, "ap_info_s", c->ap_info_s);
}

size_t line_boot(char *buf, size_t cap, const fw_info_t *fw, const cfg_t *c)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "boot");
    jw_str(&w, "chip", "ESP32-C5");
    jw_str(&w, "mode", "promiscuous");
    config(&w, c);
    jw_str(&w, "fw", "spectre-sniffer");
    jw_str(&w, "ver", fw->ver);
    jw_str(&w, "elf_sha", fw->elf_sha);
    jw_str(&w, "reset", fw->reset);
    jw_int(&w, "baud", fw->baud);
    jw_arr(&w, "caps");
    jw_str(&w, NULL, "counters");
    jw_str(&w, NULL, "cmd");
    jw_str(&w, NULL, "ap_info");
    jw_str(&w, NULL, "phy");
    jw_str(&w, NULL, "telemetry");
    jw_arr_end(&w);
    return end(&w);
}

size_t line_started(char *buf, size_t cap, uint8_t ch)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "sniffer_started");
    jw_int(&w, "ch", ch);
    return end(&w);
}

static void counters(jw_t *w, const counters_t *k)
{
    jw_int(w, "rx_total", k->rx_total);
    jw_int(w, "emitted", k->emitted);
    jw_int(w, "drop_queue", k->drop_queue);
    jw_int(w, "drop_short", k->drop_short);
    jw_int(w, "drop_dedup", k->drop_dedup);
    jw_int(w, "drop_overflow", k->drop_overflow);
}

size_t line_sweep(char *buf, size_t cap, uint32_t uptime_ms, uint32_t sweep_ms,
                  const counters_t *k)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "channel_sweep_complete");
    /* total_pkts keeps its original meaning: frame lines emitted so far */
    jw_int(&w, "total_pkts", k->emitted);
    jw_int(&w, "uptime_ms", uptime_ms);
    jw_int(&w, "sweep_ms", sweep_ms);
    counters(&w, k);
    return end(&w);
}

size_t line_telemetry(char *buf, size_t cap, uint32_t uptime_ms, const counters_t *k,
                      uint32_t heap_free, uint32_t heap_min, int temp_dc,
                      uint32_t uart_bps)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "telemetry");
    jw_int(&w, "uptime_ms", uptime_ms);
    counters(&w, k);
    jw_int(&w, "q_hwm", k->q_hwm);
    jw_int(&w, "q_size", k->q_size);
    jw_int(&w, "heap", heap_free);
    jw_int(&w, "heap_min", heap_min);
    if (temp_dc != TEMP_UNKNOWN)
        jw_int(&w, "temp_dc", temp_dc);
    jw_int(&w, "uart_bps", uart_bps);
    return end(&w);
}

size_t line_clock(char *buf, size_t cap, uint32_t uptime_ms, uint64_t mono_us)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "clock_sync");
    jw_int(&w, "uptime_ms", uptime_ms);
    jw_int(&w, "mono_us", (long long)mono_us);
    return end(&w);
}

size_t line_ack(char *buf, size_t cap, const cmd_t *cmd, const cfg_t *c)
{
    jw_t w;
    begin(&w, buf, cap);
    jw_str(&w, "event", "cmd_ack");
    jw_str(&w, "cmd", cmd->name);
    if (cmd->id[0])
        jw_str(&w, "id", cmd->id);
    jw_bool(&w, "ok", cmd->err == NULL);
    if (cmd->err)
        jw_str(&w, "err", cmd->err);
    jw_open(&w, "config");
    config(&w, c);
    jw_close(&w);
    return end(&w);
}
