/*
 * Tagged-parameter (information element) parsing for management frames.
 *
 * Pure C, host-testable. The element walk stops at the first element whose
 * declared length runs past the capture, and every element body is checked
 * against its own minimum size before a field is read.
 *
 * Author: gurvinny
 * Project: SPECTRE
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* AKM suites (00-0F-AC:n), as a bitmask. */
enum {
    AKM_8021X = 1 << 0, AKM_PSK = 1 << 1, AKM_FT_8021X = 1 << 2,
    AKM_FT_PSK = 1 << 3, AKM_8021X_SHA256 = 1 << 4, AKM_PSK_SHA256 = 1 << 5,
    AKM_SAE = 1 << 6, AKM_FT_SAE = 1 << 7, AKM_SUITE_B = 1 << 8,
    AKM_OWE = 1 << 9, AKM_SAE_EXT = 1 << 10, AKM_OTHER = 1 << 11,
};

/* Cipher suites, as a bitmask. */
enum {
    CIPHER_WEP = 1 << 0, CIPHER_TKIP = 1 << 1, CIPHER_CCMP = 1 << 2,
    CIPHER_GCMP = 1 << 3, CIPHER_GCMP256 = 1 << 4, CIPHER_CCMP256 = 1 << 5,
    CIPHER_BIP = 1 << 6, CIPHER_OTHER = 1 << 7,
};

enum { PMF_NONE = 0, PMF_CAPABLE = 1, PMF_REQUIRED = 2 };

#define IE_MAX_OUIS 8

typedef struct {
    bool has_ssid;
    uint8_t ssid_len;
    uint8_t ssid[32];
    uint8_t ds_channel;       /* DS Parameter Set, 0 if absent */

    bool rsn;                 /* RSN element present */
    bool wpa1;                /* legacy WPA vendor element present */
    uint16_t akm;             /* AKM_* from RSN, or from WPA1 if no RSN */
    uint8_t group_cipher;     /* CIPHER_* */
    uint8_t pairwise;         /* CIPHER_* */
    uint8_t pmf;              /* PMF_* */

    bool ht, vht, he, eht;
    uint8_t ht_sec_offset;    /* HT Operation: 0 none, 1 above, 3 below */
    bool wps;

    bool csa;                 /* Channel Switch Announcement present */
    uint8_t csa_mode, csa_channel, csa_count;

    uint8_t n_ouis;
    uint8_t ouis[IE_MAX_OUIS][3];

    uint32_t fingerprint;     /* FNV-1a over element ids + vendor types */
} ie_info_t;

void ie_parse(const uint8_t *ies, size_t len, ie_info_t *out);

/* Hash of the AP-describing fields only. Volatile elements (TIM, BSS load,
 * CSA countdown) are excluded, so it changes only when the advertised
 * configuration changes. */
uint32_t ie_ap_hash(const ie_info_t *ie, uint16_t capability);

/* Short security label: OPEN, WEP, WPA, WPA2, WPA2/WPA3, WPA3, OWE, ENT. */
const char *ie_security(const ie_info_t *ie, uint16_t capability);

uint32_t fnv1a(uint32_t h, const void *data, size_t len);
#define FNV_SEED 2166136261u
