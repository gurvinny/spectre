/*
 * Configuration and command parsing. See cfg.h.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "cfg.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* 20 MHz primaries the radio can tune to. No regulatory domain is assumed:
 * the sniffer only listens, and the operator chooses the list. */
static const uint8_t CH_5G[] = {
    36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128,
    132, 136, 140, 144, 149, 153, 157, 161, 165, 169, 173, 177,
};
#define N_5G_DEFAULT 25    /* 36-165 */

void cfg_defaults(cfg_t *c, uint8_t band)
{
    memset(c, 0, sizeof *c);
    c->version = CFG_VERSION;
    c->band = band == BAND_5 ? BAND_5 : BAND_24;
    if (c->band == BAND_24) {
        c->n_ch = 13;
        for (uint8_t i = 0; i < 13; i++)
            c->ch[i] = (uint8_t)(i + 1);
        c->dwell_ms = 300;   /* 13 x 300 ms ~ 3.9 s sweep */
    } else {
        c->n_ch = N_5G_DEFAULT;
        memcpy(c->ch, CH_5G, N_5G_DEFAULT);
        c->dwell_ms = 200;   /* 25 x 200 ms = 5.0 s sweep */
    }
    c->filter = FILT_MGMT | FILT_DATA;
    c->ap_info_s = 300;
}

bool cfg_channel_ok(uint8_t band, uint8_t ch)
{
    if (band == BAND_24)
        return ch >= 1 && ch <= 14;
    if (band != BAND_5)
        return false;
    for (size_t i = 0; i < sizeof CH_5G; i++)
        if (CH_5G[i] == ch)
            return true;
    return false;
}

bool cfg_valid(const cfg_t *c)
{
    if (c->version != CFG_VERSION || c->band > BAND_5)
        return false;
    if (c->n_ch == 0 || c->n_ch > CFG_MAX_CH)
        return false;
    for (uint8_t i = 0; i < c->n_ch; i++) {
        if (!cfg_channel_ok(c->band, c->ch[i]))
            return false;
        for (uint8_t j = 0; j < i; j++)
            if (c->ch[j] == c->ch[i])
                return false;
    }
    if (c->dwell_ms < DWELL_MIN_MS || c->dwell_ms > DWELL_MAX_MS)
        return false;
    if (c->pin != 0 && !cfg_channel_ok(c->band, c->pin))
        return false;
    if (c->filter == 0 || (c->filter & ~FILT_ALL))
        return false;
    if (c->dedup > 1 || c->ap_info_s > AP_INFO_MAX_S)
        return false;
    return true;
}

const char *cfg_band_name(uint8_t band)
{
    return band == BAND_5 ? "5GHz" : "2.4GHz";
}

void cfg_channels_str(const cfg_t *c, char *out, size_t cap)
{
    cfg_t d;
    cfg_defaults(&d, c->band);
    if (cap == 0)
        return;
    if (c->n_ch == d.n_ch && memcmp(c->ch, d.ch, d.n_ch) == 0) {
        snprintf(out, cap, "%s", c->band == BAND_5 ? "36-165" : "1-13");
        return;
    }
    size_t len = 0;
    out[0] = '\0';
    for (uint8_t i = 0; i < c->n_ch && len < cap; i++) {
        int n = snprintf(out + len, cap - len, i ? ",%u" : "%u", c->ch[i]);
        if (n < 0 || (size_t)n >= cap - len) {
            out[len] = '\0';       /* drop a partial number */
            return;
        }
        len += (size_t)n;
    }
}

/* ---- minimal flat-JSON reader ------------------------------------------ */

#define MAX_ITEMS CFG_MAX_CH

typedef enum { V_NONE, V_STR, V_INT, V_BOOL, V_ARR } vtype_t;

typedef struct {
    vtype_t type;
    char s[24];
    long n;
    int n_items;
    vtype_t item_type;
    long items[MAX_ITEMS];
    char item_s[4][8];          /* string arrays: filter names only */
} val_t;

typedef struct {
    const char *p;
} rd_t;

static void ws(rd_t *r)
{
    while (*r->p && isspace((unsigned char)*r->p))
        r->p++;
}

static bool rd_str(rd_t *r, char *out, size_t cap)
{
    if (*r->p != '"')
        return false;
    r->p++;
    size_t n = 0;
    while (*r->p && *r->p != '"') {
        unsigned char c = (unsigned char)*r->p;
        if (c == '\\' || c < 0x20)
            return false;        /* no escapes in this protocol */
        if (n + 1 >= cap)
            return false;
        out[n++] = (char)c;
        r->p++;
    }
    if (*r->p != '"')
        return false;
    r->p++;
    out[n] = '\0';
    return true;
}

static bool rd_int(rd_t *r, long *out)
{
    const char *s = r->p;
    if (*s == '-')
        s++;
    if (!isdigit((unsigned char)*s))
        return false;
    int digits = 0;
    while (isdigit((unsigned char)s[digits]))
        digits++;
    if (digits > 9)
        return false;            /* far beyond any valid setting */
    char *end;
    /* integers only: a trailing '.' or 'e' fails at the next-token check */
    *out = strtol(r->p, &end, 10);
    r->p = end;
    return true;
}

static bool rd_scalar(rd_t *r, val_t *v, char *sbuf, size_t scap, long *num, vtype_t *t)
{
    if (*r->p == '"') {
        *t = V_STR;
        return rd_str(r, sbuf, scap);
    }
    if (strncmp(r->p, "true", 4) == 0) {
        r->p += 4; *t = V_BOOL; *num = 1;
        return true;
    }
    if (strncmp(r->p, "false", 5) == 0) {
        r->p += 5; *t = V_BOOL; *num = 0;
        return true;
    }
    (void)v;
    *t = V_INT;
    return rd_int(r, num);
}

static bool rd_value(rd_t *r, val_t *v)
{
    memset(v, 0, sizeof *v);
    if (*r->p != '[') {
        vtype_t t;
        if (!rd_scalar(r, v, v->s, sizeof v->s, &v->n, &t))
            return false;
        v->type = t;
        return true;
    }
    r->p++;
    v->type = V_ARR;
    ws(r);
    if (*r->p == ']') {
        r->p++;
        return true;
    }
    for (;;) {
        ws(r);
        if (v->n_items >= MAX_ITEMS)
            return false;
        vtype_t t;
        long num = 0;
        char sb[8] = {0};
        if (!rd_scalar(r, v, sb, sizeof sb, &num, &t))
            return false;
        if (v->n_items == 0)
            v->item_type = t;
        else if (t != v->item_type)
            return false;        /* mixed arrays are not part of the protocol */
        if (t == V_STR) {
            if (v->n_items >= 4)
                return false;
            memcpy(v->item_s[v->n_items], sb, sizeof sb);
        }
        v->items[v->n_items++] = num;
        ws(r);
        if (*r->p == ',') {
            r->p++;
            continue;
        }
        if (*r->p == ']') {
            r->p++;
            return true;
        }
        return false;
    }
}

/* ---- command application ------------------------------------------------ */

typedef struct {
    bool band, channels, dwell, pin, filter, dedup, ap_info;
    uint8_t band_v;
    val_t channels_v, filter_v;
    long dwell_v, pin_v, dedup_v, ap_info_v;
} staged_t;

static bool apply_key(const char *k, const val_t *v, staged_t *st, cmd_t *out)
{
    if (strcmp(k, "cmd") == 0) {
        if (v->type != V_STR)
            return false;
        size_t n = strlen(v->s);
        if (n >= sizeof out->name)
            n = sizeof out->name - 1;
        memcpy(out->name, v->s, n);
        out->name[n] = '\0';
        if (strcmp(v->s, "get_config") == 0)
            out->kind = CMD_GET;
        else if (strcmp(v->s, "set") == 0)
            out->kind = CMD_SET;
        else if (strcmp(v->s, "reset_config") == 0)
            out->kind = CMD_RESET;
        else if (strcmp(v->s, "reboot") == 0)
            out->kind = CMD_REBOOT;
        else
            out->err = "unknown cmd";
        return true;
    }
    if (strcmp(k, "id") == 0) {
        size_t n = v->type == V_STR ? strlen(v->s) : sizeof out->id;
        if (n >= sizeof out->id)
            return false;
        memcpy(out->id, v->s, n + 1);
        return true;
    }
    if (strcmp(k, "band") == 0) {
        if (v->type != V_STR)
            return false;
        if (strcmp(v->s, "2.4GHz") == 0)
            st->band_v = BAND_24;
        else if (strcmp(v->s, "5GHz") == 0)
            st->band_v = BAND_5;
        else {
            out->err = "bad band";
            return true;
        }
        st->band = true;
        return true;
    }
    if (strcmp(k, "channels") == 0) {
        if (v->type != V_ARR || (v->n_items > 0 && v->item_type != V_INT))
            return false;
        st->channels = true;
        st->channels_v = *v;
        return true;
    }
    if (strcmp(k, "filter") == 0) {
        if (v->type != V_ARR || (v->n_items > 0 && v->item_type != V_STR))
            return false;
        st->filter = true;
        st->filter_v = *v;
        return true;
    }
    long *slot = NULL;
    bool *flag = NULL;
    if (strcmp(k, "dwell_ms") == 0) { slot = &st->dwell_v; flag = &st->dwell; }
    else if (strcmp(k, "pin") == 0) { slot = &st->pin_v; flag = &st->pin; }
    else if (strcmp(k, "dedup") == 0) { slot = &st->dedup_v; flag = &st->dedup; }
    else if (strcmp(k, "ap_info_s") == 0) { slot = &st->ap_info_v; flag = &st->ap_info; }
    if (slot == NULL) {
        out->err = "unknown key";
        return true;
    }
    if (v->type != V_INT && v->type != V_BOOL)
        return false;
    *slot = v->n;
    *flag = true;
    return true;
}

static const char *apply_staged(const staged_t *st, const cfg_t *cur, cfg_t *next)
{
    *next = *cur;
    if (st->band && st->band_v != cur->band)
        cfg_defaults(next, st->band_v);   /* a new band starts from its plan */
    if (st->channels) {
        const val_t *v = &st->channels_v;
        if (v->n_items == 0)
            return "bad channel";
        for (int i = 0; i < v->n_items; i++) {
            if (v->items[i] < 0 || v->items[i] > 255
                    || !cfg_channel_ok(next->band, (uint8_t)v->items[i]))
                return "bad channel";
            for (int j = 0; j < i; j++)
                if (v->items[j] == v->items[i])
                    return "bad channel";
            next->ch[i] = (uint8_t)v->items[i];
        }
        next->n_ch = (uint8_t)v->n_items;
        if (next->pin) {            /* an explicit "pin" is applied below */
            bool listed = false;
            for (uint8_t i = 0; i < next->n_ch; i++)
                listed |= next->ch[i] == next->pin;
            if (!listed)
                next->pin = 0;            /* a pin outside the new list lapses */
        }
    }
    if (st->dwell) {
        if (st->dwell_v < DWELL_MIN_MS || st->dwell_v > DWELL_MAX_MS)
            return "bad dwell";
        next->dwell_ms = (uint16_t)st->dwell_v;
    }
    if (st->pin) {
        if (st->pin_v != 0 && (st->pin_v < 0 || st->pin_v > 255
                || !cfg_channel_ok(next->band, (uint8_t)st->pin_v)))
            return "bad pin";
        next->pin = (uint8_t)st->pin_v;
    }
    if (st->filter) {
        uint8_t f = 0;
        const val_t *v = &st->filter_v;
        for (int i = 0; i < v->n_items; i++) {
            if (strcmp(v->item_s[i], "mgmt") == 0) f |= FILT_MGMT;
            else if (strcmp(v->item_s[i], "ctrl") == 0) f |= FILT_CTRL;
            else if (strcmp(v->item_s[i], "data") == 0) f |= FILT_DATA;
            else return "bad filter";
        }
        if (f == 0)
            return "bad filter";
        next->filter = f;
    }
    if (st->dedup) {
        if (st->dedup_v < 0 || st->dedup_v > 1)
            return "bad value";
        next->dedup = (uint8_t)st->dedup_v;
    }
    if (st->ap_info) {
        if (st->ap_info_v < 0 || st->ap_info_v > AP_INFO_MAX_S)
            return "bad value";
        next->ap_info_s = (uint16_t)st->ap_info_v;
    }
    return cfg_valid(next) ? NULL : "bad value";
}

bool cmd_parse(const char *line, const cfg_t *cur, cfg_t *next, cmd_t *out)
{
    memset(out, 0, sizeof *out);
    out->kind = CMD_NONE;
    staged_t st;
    memset(&st, 0, sizeof st);
    rd_t r = {line};

    ws(&r);
    if (*r.p != '{')
        goto bad;
    r.p++;
    ws(&r);
    if (*r.p != '}') {
        for (;;) {
            char key[16];
            val_t v;
            ws(&r);
            if (!rd_str(&r, key, sizeof key))
                goto bad;
            ws(&r);
            if (*r.p != ':')
                goto bad;
            r.p++;
            ws(&r);
            if (!rd_value(&r, &v))
                goto bad;
            if (!apply_key(key, &v, &st, out))
                goto bad;
            ws(&r);
            if (*r.p == ',') {
                r.p++;
                continue;
            }
            if (*r.p == '}')
                break;
            goto bad;
        }
    }
    r.p++;
    ws(&r);
    if (*r.p != '\0')
        goto bad;

    if (out->err)
        return false;
    switch (out->kind) {
    case CMD_NONE:
        out->err = "missing cmd";
        return false;
    case CMD_SET:
        out->err = apply_staged(&st, cur, next);
        return out->err == NULL;
    case CMD_RESET:
        cfg_defaults(next, cur->band);
        return true;
    default:
        *next = *cur;
        return true;
    }
bad:
    out->kind = CMD_NONE;
    out->err = "bad json";
    return false;
}
