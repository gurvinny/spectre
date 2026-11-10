/*
 * Bounded JSON writer for UART lines.
 *
 * Writes into a caller buffer and never past it. If a line would not fit,
 * `overflow` is set and the caller drops the line rather than emitting a
 * truncated object the host would count as malformed.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define JW_MAX_DEPTH 4

typedef struct {
    char *buf;
    size_t cap, len;
    bool overflow;
    int depth;
    bool first[JW_MAX_DEPTH];
} jw_t;

void jw_init(jw_t *w, char *buf, size_t cap);
void jw_raw(jw_t *w, const char *s);
void jw_open(jw_t *w, const char *key);    /* "key":{  (key NULL at top level) */
void jw_close(jw_t *w);                     /* } */
void jw_arr(jw_t *w, const char *key);      /* "key":[ */
void jw_arr_end(jw_t *w);                   /* ] */
void jw_int(jw_t *w, const char *key, long long v);  /* key NULL inside arrays */
void jw_bool(jw_t *w, const char *key, bool v);
void jw_str(jw_t *w, const char *key, const char *s);
void jw_bytes(jw_t *w, const char *key, const uint8_t *s, size_t n);
void jw_mac(jw_t *w, const char *key, const uint8_t *mac);
void jw_hex32(jw_t *w, const char *key, uint32_t v);
/* Terminates the string. Returns the length, or 0 on overflow. */
size_t jw_finish(jw_t *w);
