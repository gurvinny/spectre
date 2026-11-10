/*
 * Builders for synthetic 802.11 frames. Addresses come from the IANA
 * documentation range 00:00:5E:00:53:xx; SSIDs are made up.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

static const uint8_t MAC_AP[6]  = {0x00, 0x00, 0x5E, 0x00, 0x53, 0x01};
static const uint8_t MAC_STA[6] = {0x00, 0x00, 0x5E, 0x00, 0x53, 0x02};
static const uint8_t MAC_BC[6]  = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static const uint8_t MAC_DS[6]  = {0x00, 0x00, 0x5E, 0x00, 0x53, 0x03};

/* Generic 24-byte header. */
static inline size_t fr_hdr(uint8_t *b, uint8_t type, uint8_t sub, uint8_t flags,
                            const uint8_t *a1, const uint8_t *a2, const uint8_t *a3,
                            uint16_t seq)
{
    b[0] = (uint8_t)((type << 2) | (sub << 4));
    b[1] = flags;
    b[2] = 0x3A; b[3] = 0x01;                  /* duration 314 */
    memcpy(b + 4, a1, 6);
    memcpy(b + 10, a2, 6);
    memcpy(b + 16, a3, 6);
    uint16_t sc = (uint16_t)(seq << 4);
    b[22] = (uint8_t)(sc & 0xFF);
    b[23] = (uint8_t)(sc >> 8);
    return 24;
}

static inline size_t fr_put(uint8_t *b, size_t at, const void *d, size_t n)
{
    memcpy(b + at, d, n);
    return at + n;
}

static inline size_t fr_ie(uint8_t *b, size_t at, uint8_t id, const void *d, uint8_t n)
{
    b[at] = id;
    b[at + 1] = n;
    memcpy(b + at + 2, d, n);
    return at + 2 + n;
}

/* Beacon header + fixed fields (timestamp, interval 100, capability). */
static inline size_t fr_beacon(uint8_t *b, uint16_t capability)
{
    size_t n = fr_hdr(b, 0, 8, 0, MAC_BC, MAC_AP, MAC_AP, 100);
    memset(b + n, 0, 8);
    n += 8;
    b[n++] = 100; b[n++] = 0;
    b[n++] = (uint8_t)(capability & 0xFF);
    b[n++] = (uint8_t)(capability >> 8);
    return n;
}

/* RSN body: version 1, group CCMP, the given pairwise + AKM suite types,
 * capabilities. */
static inline uint8_t rsn_body(uint8_t *r, const uint8_t *akms, uint8_t n_akm, uint16_t caps)
{
    uint8_t n = 0;
    r[n++] = 1; r[n++] = 0;
    r[n++] = 0x00; r[n++] = 0x0F; r[n++] = 0xAC; r[n++] = 4;     /* group CCMP */
    r[n++] = 1; r[n++] = 0;
    r[n++] = 0x00; r[n++] = 0x0F; r[n++] = 0xAC; r[n++] = 4;     /* pairwise CCMP */
    r[n++] = n_akm; r[n++] = 0;
    for (uint8_t i = 0; i < n_akm; i++) {
        r[n++] = 0x00; r[n++] = 0x0F; r[n++] = 0xAC; r[n++] = akms[i];
    }
    r[n++] = (uint8_t)(caps & 0xFF);
    r[n++] = (uint8_t)(caps >> 8);
    return n;
}
