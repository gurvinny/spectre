/*
 * Bounded JSON writer. See jsonw.h.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#include "jsonw.h"

#include <stdio.h>
#include <string.h>

static void put(jw_t *w, const char *s, size_t n)
{
    /* keep one byte for the terminator; once overflowed, jw_finish drops
     * the whole line, so later writes only need to stay in bounds */
    if (w->len + n + 1 > w->cap) {
        w->overflow = true;
        return;
    }
    memcpy(w->buf + w->len, s, n);
    w->len += n;
}

static void putc_(jw_t *w, char c) { put(w, &c, 1); }

void jw_init(jw_t *w, char *buf, size_t cap)
{
    memset(w, 0, sizeof *w);
    w->buf = buf;
    w->cap = cap;
    w->first[0] = true;
    if (cap == 0)
        w->overflow = true;
}

void jw_raw(jw_t *w, const char *s) { put(w, s, strlen(s)); }

static void key(jw_t *w, const char *k)
{
    if (!w->first[w->depth])
        putc_(w, ',');
    w->first[w->depth] = false;
    if (k) {
        putc_(w, '"');
        jw_raw(w, k);
        put(w, "\":", 2);
    }
}

static void push(jw_t *w, char c)
{
    putc_(w, c);
    if (w->depth + 1 >= JW_MAX_DEPTH) {
        w->overflow = true;
        return;
    }
    w->first[++w->depth] = true;
}

void jw_open(jw_t *w, const char *k)
{
    if (k || w->depth > 0 || !w->first[0])
        key(w, k);
    push(w, '{');
}

void jw_close(jw_t *w)
{
    putc_(w, '}');
    if (w->depth > 0)
        w->depth--;
}

void jw_arr(jw_t *w, const char *k) { key(w, k); push(w, '['); }

void jw_arr_end(jw_t *w)
{
    putc_(w, ']');
    if (w->depth > 0)
        w->depth--;
}

void jw_int(jw_t *w, const char *k, long long v)
{
    char tmp[24];
    key(w, k);
    int n = snprintf(tmp, sizeof tmp, "%lld", v);
    put(w, tmp, (size_t)n);
}

void jw_bool(jw_t *w, const char *k, bool v)
{
    key(w, k);
    jw_raw(w, v ? "true" : "false");
}

/* Length of a valid UTF-8 sequence starting at s[0], or 0 if invalid. */
static size_t utf8_len(const uint8_t *s, size_t n)
{
    uint8_t c = s[0];
    size_t need;
    if (c >= 0xC2 && c <= 0xDF)
        need = 2;
    else if (c >= 0xE0 && c <= 0xEF)
        need = 3;
    else if (c >= 0xF0 && c <= 0xF4)
        need = 4;
    else
        return 0;
    if (n < need)
        return 0;
    for (size_t i = 1; i < need; i++)
        if ((s[i] & 0xC0) != 0x80)
            return 0;
    /* reject overlongs and surrogates */
    if (c == 0xE0 && s[1] < 0xA0) return 0;
    if (c == 0xED && s[1] > 0x9F) return 0;
    if (c == 0xF0 && s[1] < 0x90) return 0;
    if (c == 0xF4 && s[1] > 0x8F) return 0;
    return need;
}

void jw_bytes(jw_t *w, const char *k, const uint8_t *s, size_t n)
{
    key(w, k);
    putc_(w, '"');
    for (size_t i = 0; i < n;) {
        uint8_t c = s[i];
        if (c == '"' || c == '\\') {
            char e[2] = {'\\', (char)c};
            put(w, e, 2);
            i++;
        } else if (c >= 0x20 && c < 0x7F) {
            putc_(w, (char)c);
            i++;
        } else {
            size_t u = c >= 0x80 ? utf8_len(s + i, n - i) : 0;
            if (u) {
                put(w, (const char *)s + i, u);
                i += u;
            } else {
                /* control byte or invalid UTF-8: escape it as U+00XX */
                char e[7];
                snprintf(e, sizeof e, "\\u%04x", c);
                put(w, e, 6);
                i++;
            }
        }
    }
    putc_(w, '"');
}

void jw_str(jw_t *w, const char *k, const char *s)
{
    jw_bytes(w, k, (const uint8_t *)s, strlen(s));
}

void jw_mac(jw_t *w, const char *k, const uint8_t *m)
{
    char tmp[20];
    key(w, k);
    snprintf(tmp, sizeof tmp, "\"%02X:%02X:%02X:%02X:%02X:%02X\"",
             m[0], m[1], m[2], m[3], m[4], m[5]);
    put(w, tmp, 19);
}

void jw_hex32(jw_t *w, const char *k, uint32_t v)
{
    char tmp[12];
    key(w, k);
    snprintf(tmp, sizeof tmp, "\"%08x\"", (unsigned)v);
    put(w, tmp, 10);
}

size_t jw_finish(jw_t *w)
{
    if (w->overflow || w->depth != 0) {
        if (w->cap)
            w->buf[0] = '\0';
        return 0;
    }
    w->buf[w->len] = '\0';
    return w->len;
}
