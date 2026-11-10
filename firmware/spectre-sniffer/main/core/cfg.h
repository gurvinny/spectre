/*
 * Runtime configuration (band, hop plan, filters) and the UART command
 * protocol that changes it.
 *
 * Commands are one JSON object per line, e.g.
 *   {"cmd":"get_config"}
 *   {"cmd":"set","id":"7","channels":[1,6,11],"dwell_ms":250}
 *   {"cmd":"reset_config"}  {"cmd":"reboot"}
 * The parser accepts a flat object only: string, integer, boolean and
 * arrays of those. Anything else is rejected with an error, never guessed.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CFG_VERSION 1
#define CFG_MAX_CH 32

enum { BAND_24 = 0, BAND_5 = 1 };
enum { FILT_MGMT = 1, FILT_CTRL = 2, FILT_DATA = 4, FILT_ALL = 7 };

#define DWELL_MIN_MS 50
#define DWELL_MAX_MS 5000
#define AP_INFO_MAX_S 3600

typedef struct {
    uint8_t version;
    uint8_t band;
    uint8_t n_ch;
    uint8_t ch[CFG_MAX_CH];
    uint16_t dwell_ms;
    uint8_t pin;          /* 0 = hop, else stay on this channel */
    uint8_t filter;       /* FILT_* */
    uint8_t dedup;        /* 1 = one beacon per BSSID per dwell */
    uint16_t ap_info_s;   /* periodic ap_info resend, 0 = only on change */
} cfg_t;

void cfg_defaults(cfg_t *c, uint8_t band);
bool cfg_channel_ok(uint8_t band, uint8_t ch);
bool cfg_valid(const cfg_t *c);
const char *cfg_band_name(uint8_t band);
/* "1-13" / "36-165" when the list is the band default, else "1,6,11". */
void cfg_channels_str(const cfg_t *c, char *out, size_t cap);

typedef enum { CMD_NONE, CMD_GET, CMD_SET, CMD_RESET, CMD_REBOOT } cmd_kind_t;

typedef struct {
    cmd_kind_t kind;
    char name[16];        /* the "cmd" value as sent, for the ack */
    char id[17];          /* optional caller id, echoed in the ack */
    const char *err;      /* NULL on success */
} cmd_t;

/* Parse one command line. For "set", `next` receives `cur` with the
 * changes applied; it is only meaningful when the function returns true.
 * For "reset_config", `next` receives the defaults for the current band. */
bool cmd_parse(const char *line, const cfg_t *cur, cfg_t *next, cmd_t *out);
