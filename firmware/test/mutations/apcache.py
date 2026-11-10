"""Per-BSSID ap_info scheduling and beacon dedup."""
TARGET = "spectre-sniffer/main/core/apcache.c"

MUTATIONS = [
    ("never-new", "    if (!e->info_sent)\n        why = APC_NEW;\n    else if", "    if (0)\n        why = APC_NEW;\n    else if",
     "test_info_new_changed_periodic"),
    ("change-ignored", "    else if (e->hash != hash)\n        why = APC_CHANGED;", "    else if (0)\n        why = APC_CHANGED;",
     "test_info_new_changed_periodic"),
    ("periodic-early", "else if (interval_ms && now_ms - e->last_info_ms >= interval_ms)",
     "else if (interval_ms && now_ms - e->last_info_ms + 1 >= interval_ms)", "test_info_new_changed_periodic"),
    ("periodic-when-off", "else if (interval_ms && now_ms - e->last_info_ms >= interval_ms)",
     "else if (now_ms - e->last_info_ms >= interval_ms)", "test_info_new_changed_periodic"),
    ("periodic-clock-not-reset", "        e->last_info_ms = now_ms;\n", "",
     "test_info_new_changed_periodic"),
    ("hash-not-stored", "        e->hash = hash;\n", "", "test_info_new_changed_periodic"),
    ("wrap-unsafe", "else if (interval_ms && now_ms - e->last_info_ms >= interval_ms)",
     "else if (interval_ms && (uint64_t)now_ms >= (uint64_t)e->last_info_ms + interval_ms)", "test_periodic_survives_uptime_wrap"),
    ("dedup-never", "    if (e->dedup_epoch == epoch)\n        return true;", "    if (0)\n        return true;",
     "test_dedup_once_per_epoch"),
    ("dedup-epoch-not-stored", "    e->dedup_epoch = epoch;\n", "", "test_dedup_once_per_epoch"),
    ("lookup-no-touch", "            e->last_seen_ms = now_ms;\n            return e;", "            return e;",
     "test_eviction_drops_least_recently_seen"),
    ("evict-newest", "if (victim == NULL || (victim->used && age > oldest_age)) {",
     "if (victim == NULL || (victim->used && age < oldest_age)) {", "test_eviction_drops_least_recently_seen"),
    ("new-entry-keeps-old-state", "    memset(victim, 0, sizeof *victim);\n", "",
     "test_eviction_drops_least_recently_seen"),
    ("reason-names-swapped", "    case APC_CHANGED:  return \"changed\";", "    case APC_CHANGED:  return \"periodic\";",
     "test_info_new_changed_periodic"),
]
