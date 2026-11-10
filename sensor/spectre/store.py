"""SQLite persistence for SPECTRE.

Design goals given ~50-60 frames/sec:

* **Batched frame writes** — the pipeline buffers frames and calls
  :meth:`insert_frames` on a timer (``executemany``), never one INSERT/frame.
* **Rolling retention** — raw ``frames`` are pruned to a time window; the
  device / AP inventory, threats and summaries are kept long-term.
* **Disk guard** — if the data partition crosses a usage threshold, the raw
  window is trimmed aggressively so the box never fills.

Only the standard library is used (``sqlite3``) so the storage + detection core
runs without any pip install (handy for the local smoke test).

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from typing import Any, Iterable, Optional

from .models import FRAME_COLUMNS, Event, Threat, SEVERITY

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL    NOT NULL,
    sensor_id  TEXT,
    band       TEXT,
    frame_type TEXT,
    ch         INTEGER,
    rssi       INTEGER,
    seq        INTEGER,
    uptime_ms  INTEGER,
    src        TEXT,
    dst        TEXT,
    bssid      TEXT,
    ssid       TEXT
);
CREATE INDEX IF NOT EXISTS idx_frames_ts    ON frames(received_at);
CREATE INDEX IF NOT EXISTS idx_frames_bssid ON frames(bssid);
CREATE INDEX IF NOT EXISTS idx_frames_type  ON frames(frame_type);

CREATE TABLE IF NOT EXISTS devices (
    mac         TEXT PRIMARY KEY,
    first_seen  REAL,
    last_seen   REAL,
    bands       TEXT,          -- comma list
    last_rssi   INTEGER,
    min_rssi    INTEGER,
    max_rssi    INTEGER,
    frames      INTEGER DEFAULT 0,
    is_random   INTEGER DEFAULT 0,
    last_ssid   TEXT
);

CREATE TABLE IF NOT EXISTS access_points (
    bssid       TEXT PRIMARY KEY,
    ssid        TEXT,
    band        TEXT,
    channels    TEXT,          -- comma list
    first_seen  REAL,
    last_seen   REAL,
    last_rssi   INTEGER,
    beacons     INTEGER DEFAULT 0,
    is_known    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS known_networks (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ssid   TEXT,
    bssid  TEXT,
    band   TEXT,
    note   TEXT,
    added_at REAL
);

CREATE TABLE IF NOT EXISTS threats (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    rule      TEXT,
    severity  TEXT,
    rank      INTEGER,
    title     TEXT,
    band      TEXT,
    bssid     TEXT,
    ssid      TEXT,
    src       TEXT,
    detail    TEXT,           -- JSON
    wazuh_sent INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_threats_ts ON threats(ts);

CREATE TABLE IF NOT EXISTS summaries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    payload   TEXT             -- JSON
);
CREATE INDEX IF NOT EXISTS idx_summaries_ts ON summaries(ts);

-- Board lifecycle lines (boot, sniffer_started, channel_sweep_complete).
-- Same retention as raw frames.
CREATE TABLE IF NOT EXISTS board_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL NOT NULL,
    sensor_id   TEXT,
    band        TEXT,
    kind        TEXT,
    payload     TEXT             -- JSON
);
CREATE INDEX IF NOT EXISTS idx_board_events_ts ON board_events(received_at);
-- The console reads the newest row of each kind per board.
CREATE INDEX IF NOT EXISTS idx_board_events_sensor_kind ON board_events(sensor_id, kind);

-- One row per ap_info line from the v2 firmware: an AP's advertised security
-- and capabilities, on first sighting, on change and periodically. Typed
-- columns for the common questions, the whole line in payload. Same retention
-- as raw frames.
CREATE TABLE IF NOT EXISTS ap_info (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL NOT NULL,
    sensor_id   TEXT,
    band        TEXT,
    bssid       TEXT,
    why         TEXT,            -- new | changed | periodic
    ch          INTEGER,         -- channel the radio was on
    ds_ch       INTEGER,         -- channel the AP advertises
    ssid        TEXT,
    sec         TEXT,
    pmf         TEXT,            -- none | capable | required
    wpa1        INTEGER,
    ht          INTEGER,
    vht         INTEGER,
    he          INTEGER,
    eht         INTEGER,
    wps         INTEGER,
    hash        TEXT,
    payload     TEXT             -- JSON
);
CREATE INDEX IF NOT EXISTS idx_ap_info_ts    ON ap_info(received_at);
CREATE INDEX IF NOT EXISTS idx_ap_info_bssid ON ap_info(bssid);

CREATE TABLE IF NOT EXISTS config (
    key       TEXT PRIMARY KEY,
    value     TEXT,            -- JSON-encoded
    encrypted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    username  TEXT PRIMARY KEY,
    pwd_hash  TEXT,
    salt      TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    username   TEXT,
    created_at REAL,
    expires_at REAL
);
"""


# ── Search index builders ──────────────────────────────────────────────
# Each returns (text, label, sub, band): `text` is tokenized/indexed; the rest
# are stored UNINDEXED for rendering results without a join. MACs/BSSIDs are also
# indexed colon-stripped so a partial like "2a2fd0" prefix-matches.
# Columns added to `frames` for the v2 firmware, in FRAME_COLUMNS order.
# `_migrate` adds whichever are missing, so a fresh database and an upgraded one
# end up with the same columns in the same order. Never reorder or remove.
_FRAME_V2_COLUMNS = (
    ("sub", "INTEGER"), ("nf", "INTEGER"), ("phy", "TEXT"), ("mcs", "INTEGER"),
    ("bw", "INTEGER"), ("rate", "INTEGER"), ("ts_us", "INTEGER"), ("sn", "INTEGER"),
    ("fc_flags", "INTEGER"), ("dur", "INTEGER"), ("reason", "INTEGER"),
    ("auth_alg", "INTEGER"), ("auth_seq", "INTEGER"), ("status", "INTEGER"),
    ("eapol", "INTEGER"), ("probe_fp", "TEXT"), ("ouis", "TEXT"),
)
_INSERT_FRAME = (f"INSERT INTO frames({','.join(FRAME_COLUMNS)}) "
                 f"VALUES({','.join('?' * len(FRAME_COLUMNS))})")

_AP_INFO_BOOLS = ("wpa1", "ht", "vht", "he", "eht", "wps")


def _flag(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, bool) else None


def _int_or_none(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _str_or_none(v: Any) -> Optional[str]:
    return v if isinstance(v, str) and v else None


def _norm(mac: Optional[str]) -> str:
    return (mac or "").replace(":", "")


def _device_index(d: dict) -> tuple[str, str, str, str]:
    mac = d.get("mac") or ""
    ssid = d.get("last_ssid") or ""
    rnd = "random randomized" if d.get("is_random") else ""
    return (f"{mac} {_norm(mac)} {ssid} {rnd}".strip(), ssid or mac, mac,
            d.get("bands") or "")


def _ap_index(a: dict) -> tuple[str, str, str, str]:
    bssid = a.get("bssid") or ""
    ssid = a.get("ssid") or ""
    ch = a.get("channels") or ""
    return (f"{bssid} {_norm(bssid)} {ssid} ch{ch}".strip(), ssid or bssid,
            bssid, a.get("band") or "")


def _threat_index(title: Optional[str], rule: Optional[str], severity: Optional[str],
                  band: Optional[str], bssid: Optional[str], ssid: Optional[str],
                  src: Optional[str]) -> tuple[str, str, str, str]:
    text = " ".join(x for x in (title, rule, severity, bssid, _norm(bssid),
                                ssid, src) if x).strip()
    return (text, title or rule or "threat", rule or "", band or "")


def _known_index(ssid: Optional[str], bssid: Optional[str],
                 band: Optional[str]) -> tuple[str, str, str, str]:
    return (f"{ssid or ''} {bssid or ''} {_norm(bssid)}".strip(),
            ssid or bssid or "known", bssid or "any BSSID", band or "")


def _fts_match(query: str) -> str:
    """Turn free text into a safe FTS5 prefix query (guards against injection)."""
    tokens = re.findall(r"[A-Za-z0-9]+", query)
    return " ".join(f"{t}*" for t in tokens if t)


class Store:
    """Thread-safe SQLite wrapper. A single connection guarded by a lock."""

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # check_same_thread=False: the asyncio loop and the uvicorn worker may
        # touch the connection from different threads; the lock serializes them.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(_SCHEMA)
            self._migrate()
            self._db.commit()
        # Full-text search index (FTS5). Created separately so a SQLite build
        # without FTS5 degrades to a LIKE fallback rather than failing startup.
        self._fts = self._init_fts()
        if self._fts:
            self._reindex_all()

    def _migrate(self) -> None:
        """Bring an older database up to the current schema. Idempotent.

        ``CREATE TABLE IF NOT EXISTS`` never changes an existing table, so new
        ``frames`` columns are added here. ``ADD COLUMN`` with no default only
        rewrites the schema, not the rows, so it is instant on a large table;
        existing rows read the new columns as NULL. Caller holds the lock.
        """
        have = {r[1] for r in self._db.execute("PRAGMA table_info(frames)")}
        for name, sql_type in _FRAME_V2_COLUMNS:
            if name not in have:
                self._db.execute(f"ALTER TABLE frames ADD COLUMN {name} {sql_type}")
                log.info("migrated frames: added column %s", name)

    # ── Frames (high volume, batched) ──────────────────────────────────
    def insert_frames(self, events: Iterable[Event]) -> int:
        rows = [e.to_row() for e in events]
        if not rows:
            return 0
        with self._lock:
            self._db.executemany(_INSERT_FRAME, rows)
            self._db.commit()
        return len(rows)

    def recent_frames(self, limit: int = 200, band: Optional[str] = None,
                      frame_type: Optional[str] = None) -> list[dict]:
        q = "SELECT received_at,sensor_id,band,frame_type,ch,rssi,src,dst,bssid,ssid FROM frames"
        clauses, args = [], []
        if band:
            clauses.append("band=?"); args.append(band)
        if frame_type:
            clauses.append("frame_type=?"); args.append(frame_type.upper())
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    # ── Inventory upserts (batched from the pipeline's dirty maps) ─────
    def upsert_devices(self, devices: list[dict]) -> None:
        if not devices:
            return
        with self._lock:
            for d in devices:
                self._db.execute(
                    "INSERT INTO devices(mac,first_seen,last_seen,bands,last_rssi,"
                    "min_rssi,max_rssi,frames,is_random,last_ssid) "
                    "VALUES(:mac,:first_seen,:last_seen,:bands,:last_rssi,"
                    ":min_rssi,:max_rssi,:frames,:is_random,:last_ssid) "
                    "ON CONFLICT(mac) DO UPDATE SET "
                    "last_seen=excluded.last_seen, bands=excluded.bands, "
                    "last_rssi=excluded.last_rssi, "
                    "min_rssi=MIN(devices.min_rssi,excluded.min_rssi), "
                    "max_rssi=MAX(devices.max_rssi,excluded.max_rssi), "
                    "frames=excluded.frames, last_ssid=excluded.last_ssid", d)
                if self._fts:
                    self._fts_put("device", d["mac"], _device_index(d))
            self._db.commit()

    def upsert_aps(self, aps: list[dict]) -> None:
        if not aps:
            return
        with self._lock:
            for a in aps:
                self._db.execute(
                    "INSERT INTO access_points(bssid,ssid,band,channels,first_seen,"
                    "last_seen,last_rssi,beacons,is_known) "
                    "VALUES(:bssid,:ssid,:band,:channels,:first_seen,:last_seen,"
                    ":last_rssi,:beacons,:is_known) "
                    "ON CONFLICT(bssid) DO UPDATE SET "
                    "ssid=excluded.ssid, band=excluded.band, "
                    "channels=excluded.channels, last_seen=excluded.last_seen, "
                    "last_rssi=excluded.last_rssi, beacons=excluded.beacons, "
                    "is_known=excluded.is_known", a)
                if self._fts:
                    self._fts_put("ap", a["bssid"], _ap_index(a))
            self._db.commit()

    def list_devices(self, limit: int = 500, since: Optional[float] = None,
                     until: Optional[float] = None) -> list[dict]:
        return self._list_inventory("devices", "mac", limit, since, until)

    def list_aps(self, limit: int = 500, since: Optional[float] = None,
                 until: Optional[float] = None) -> list[dict]:
        return self._list_inventory("access_points", "bssid", limit, since, until)

    def _list_inventory(self, table: str, _key: str, limit: int,
                        since: Optional[float], until: Optional[float]) -> list[dict]:
        """Scoped inventory read: `since` = last_seen ≥ (active), `until` =
        last_seen < (archived). Both None returns everything (all)."""
        clauses, args = [], []
        if since is not None:
            clauses.append("last_seen>=?"); args.append(since)
        if until is not None:
            clauses.append("last_seen<?"); args.append(until)
        q = f"SELECT * FROM {table}"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY last_seen DESC LIMIT ?"; args.append(limit)
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    # ── Threats ────────────────────────────────────────────────────────
    def insert_threat(self, t: Threat, wazuh_sent: bool = False) -> int:
        rank = SEVERITY.get(t.severity, (9, 7))[0]
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO threats(ts,rule,severity,rank,title,band,bssid,ssid,"
                "src,detail,wazuh_sent) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (t.ts, t.rule, t.severity, rank, t.title, t.band, t.bssid,
                 t.ssid, t.src, json.dumps(t.detail), int(wazuh_sent)))
            if self._fts:
                self._fts_put("threat", str(cur.lastrowid), _threat_index(
                    t.title, t.rule, t.severity, t.band, t.bssid, t.ssid, t.src))
            self._db.commit()
            return cur.lastrowid

    def list_threats(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM threats ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"]) if d.get("detail") else {}
            out.append(d)
        return out

    def count_threats_since(self, since: float) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) c FROM threats WHERE ts>=?", (since,)).fetchone()
        return int(row["c"])

    # ── Summaries ──────────────────────────────────────────────────────
    def insert_summary(self, payload: dict) -> None:
        with self._lock:
            self._db.execute("INSERT INTO summaries(ts,payload) VALUES(?,?)",
                             (payload.get("ts", time.time()), json.dumps(payload)))
            self._db.commit()

    def recent_summaries(self, limit: int = 120) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM summaries ORDER BY ts DESC LIMIT ?",
                (limit,)).fetchall()
        return [json.loads(r["payload"]) for r in rows][::-1]

    # ── Board lifecycle events ─────────────────────────────────────────
    def insert_board_event(self, rec: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO board_events(received_at,sensor_id,band,kind,payload)"
                " VALUES(?,?,?,?,?)",
                (rec.get("received_at", time.time()), rec.get("sensor_id"),
                 rec.get("band"), rec.get("kind"), json.dumps(rec.get("payload") or {})))
            self._db.commit()

    def board_events(self, since: float = 0.0, limit: int = 10000) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT received_at,sensor_id,band,kind,payload FROM board_events"
                " WHERE received_at>=? ORDER BY received_at LIMIT ?",
                (since, limit)).fetchall()
        return [{"received_at": r["received_at"], "sensor_id": r["sensor_id"],
                 "band": r["band"], "kind": r["kind"],
                 "payload": json.loads(r["payload"] or "{}")} for r in rows]

    def latest_board_events(self) -> list[dict]:
        """The newest row of each kind for each board."""
        with self._lock:
            rows = self._db.execute(
                "SELECT b.received_at,b.sensor_id,b.band,b.kind,b.payload FROM board_events b"
                " JOIN (SELECT MAX(id) AS id FROM board_events GROUP BY sensor_id, kind) m"
                " ON b.id = m.id ORDER BY b.sensor_id, b.kind").fetchall()
        return [{"received_at": r["received_at"], "sensor_id": r["sensor_id"],
                 "band": r["band"], "kind": r["kind"],
                 "payload": json.loads(r["payload"] or "{}")} for r in rows]

    def find_cmd_ack(self, sensor_id: str, cmd_id: str, since: float) -> Optional[dict]:
        """The newest ``cmd_ack`` from *sensor_id* echoing *cmd_id*, at or after *since*."""
        with self._lock:
            r = self._db.execute(
                "SELECT received_at,payload FROM board_events WHERE sensor_id=?"
                " AND kind='cmd_ack' AND received_at>=? AND json_extract(payload,'$.id')=?"
                " ORDER BY id DESC LIMIT 1", (sensor_id, since, cmd_id)).fetchone()
        if r is None:
            return None
        return dict(json.loads(r["payload"] or "{}"), received_at=r["received_at"])

    # ── AP security / capability lines (v2 firmware) ───────────────────
    def insert_ap_info(self, rec: dict) -> None:
        p = rec.get("payload") or {}
        bssid = _str_or_none(p.get("bssid"))
        ssid = _str_or_none(p.get("ssid"))
        with self._lock:
            self._db.execute(
                "INSERT INTO ap_info(received_at,sensor_id,band,bssid,why,ch,ds_ch,"
                "ssid,sec,pmf,wpa1,ht,vht,he,eht,wps,hash,payload)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec.get("received_at", time.time()), rec.get("sensor_id"),
                 rec.get("band"), bssid.upper() if bssid else None,
                 _str_or_none(p.get("why")), _int_or_none(p.get("ch")),
                 _int_or_none(p.get("ds_ch")), None if ssid == "?" else ssid,
                 _str_or_none(p.get("sec")), _str_or_none(p.get("pmf")),
                 *(_flag(p.get(k)) for k in _AP_INFO_BOOLS),
                 _str_or_none(p.get("hash")), json.dumps(p)))
            self._db.commit()

    def ap_info(self, since: float = 0.0, limit: int = 10000) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM ap_info WHERE received_at>=?"
                " ORDER BY received_at LIMIT ?", (since, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("id", None)
            d["payload"] = json.loads(d["payload"] or "{}")
            out.append(d)
        return out

    # ── Known networks (evil-twin allowlist) ──────────────────────────
    def list_known_networks(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM known_networks ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def add_known_network(self, ssid: str, bssid: Optional[str],
                          band: Optional[str], note: str = "") -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO known_networks(ssid,bssid,band,note,added_at) "
                "VALUES(?,?,?,?,?)",
                (ssid, (bssid or "").upper() or None, band, note, time.time()))
            if self._fts:
                self._fts_put("known", str(cur.lastrowid),
                              _known_index(ssid, (bssid or "").upper() or None, band))
            self._db.commit()
            return cur.lastrowid

    def delete_known_network(self, row_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM known_networks WHERE id=?", (row_id,))
            if self._fts:
                self._fts_del("known", str(row_id))
            self._db.commit()

    def delete_known_by_bssid(self, bssid: str) -> int:
        """Remove every allowlist entry for a BSSID (used to 'untrust' an AP)."""
        with self._lock:
            ids = [r["id"] for r in self._db.execute(
                "SELECT id FROM known_networks WHERE bssid=?", (bssid.upper(),))]
            cur = self._db.execute("DELETE FROM known_networks WHERE bssid=?",
                                   (bssid.upper(),))
            if self._fts:
                for rid in ids:
                    self._fts_del("known", str(rid))
            self._db.commit()
            return cur.rowcount

    # ── Config (key/value, JSON-encoded) ───────────────────────────────
    def get_config(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM config WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set_config(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO config(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))
            self._db.commit()

    def all_config(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT key,value FROM config").fetchall()
        out = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except (ValueError, TypeError):
                out[r["key"]] = None
        return out

    # ── Users / sessions ───────────────────────────────────────────────
    def get_user(self, username: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

    def upsert_user(self, username: str, pwd_hash: str, salt: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO users(username,pwd_hash,salt,created_at) "
                "VALUES(?,?,?,?) ON CONFLICT(username) DO UPDATE SET "
                "pwd_hash=excluded.pwd_hash, salt=excluded.salt",
                (username, pwd_hash, salt, time.time()))
            self._db.commit()

    def has_users(self) -> bool:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) c FROM users").fetchone()
        return int(row["c"]) > 0

    def create_session(self, token: str, username: str, ttl_seconds: int) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions(token,username,created_at,expires_at) "
                "VALUES(?,?,?,?)", (token, username, now, now + ttl_seconds))
            self._db.commit()

    def get_session(self, token: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            self.delete_session(token)
            return None
        return dict(row)

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._db.commit()

    # ── Full-text search (FTS5, with a LIKE fallback) ──────────────────
    def _init_fts(self) -> bool:
        try:
            with self._lock:
                self._db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
                    "text, kind UNINDEXED, ref UNINDEXED, label UNINDEXED, "
                    "sub UNINDEXED, band UNINDEXED, tokenize='unicode61')")
                self._db.commit()
            return True
        except sqlite3.OperationalError as e:
            log.warning("FTS5 unavailable — search uses LIKE fallback: %s", e)
            return False

    def _fts_del(self, kind: str, ref: str) -> None:
        """Remove an index row. The caller holds the lock and commits."""
        self._db.execute("DELETE FROM search_fts WHERE kind=? AND ref=?", (kind, ref))

    def _fts_put(self, kind: str, ref: str, idx: tuple[str, str, str, str]) -> None:
        """Upsert an index row (delete + insert). Caller holds the lock/commits."""
        text, label, sub, band = idx
        self._db.execute("DELETE FROM search_fts WHERE kind=? AND ref=?", (kind, ref))
        self._db.execute(
            "INSERT INTO search_fts(text,kind,ref,label,sub,band) VALUES(?,?,?,?,?,?)",
            (text, kind, ref, label, sub, band))

    def _reindex_all(self) -> None:
        """Rebuild the index from the durable tables — covers rows that went
        archived (they stop re-upserting) so history stays searchable."""
        try:
            with self._lock:
                self._db.execute("DELETE FROM search_fts")
                for r in self._db.execute(
                        "SELECT mac,last_ssid,is_random,bands FROM devices"):
                    self._fts_put("device", r["mac"], _device_index(dict(r)))
                for r in self._db.execute(
                        "SELECT bssid,ssid,channels,band FROM access_points"):
                    self._fts_put("ap", r["bssid"], _ap_index(dict(r)))
                for r in self._db.execute(
                        "SELECT id,title,rule,severity,band,bssid,ssid,src "
                        "FROM threats ORDER BY ts DESC LIMIT 1000"):
                    self._fts_put("threat", str(r["id"]), _threat_index(
                        r["title"], r["rule"], r["severity"], r["band"],
                        r["bssid"], r["ssid"], r["src"]))
                for r in self._db.execute(
                        "SELECT id,ssid,bssid,band FROM known_networks"):
                    self._fts_put("known", str(r["id"]),
                                  _known_index(r["ssid"], r["bssid"], r["band"]))
                self._db.commit()
        except sqlite3.Error:
            log.exception("search reindex failed")

    def search(self, query: str, limit: int = 20) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        if self._fts:
            match = _fts_match(query)
            if match:
                try:
                    with self._lock:
                        rows = self._db.execute(
                            "SELECT kind,ref,label,sub,band FROM search_fts "
                            "WHERE search_fts MATCH ? ORDER BY rank LIMIT ?",
                            (match, limit)).fetchall()
                    return [dict(r) for r in rows]
                except sqlite3.Error:
                    log.exception("FTS search failed — using LIKE fallback")
        return self._search_like(query, limit)

    def _search_like(self, query: str, limit: int) -> list[dict]:
        like = "%" + query.replace("%", "").replace("_", "") + "%"
        out: list[dict] = []
        with self._lock:
            for r in self._db.execute(
                    "SELECT mac,last_ssid,bands FROM devices "
                    "WHERE mac LIKE ? OR last_ssid LIKE ? "
                    "ORDER BY last_seen DESC LIMIT ?", (like, like, limit)):
                out.append({"kind": "device", "ref": r["mac"],
                            "label": r["last_ssid"] or r["mac"], "sub": r["mac"],
                            "band": r["bands"]})
            for r in self._db.execute(
                    "SELECT bssid,ssid,band FROM access_points "
                    "WHERE bssid LIKE ? OR ssid LIKE ? "
                    "ORDER BY last_seen DESC LIMIT ?", (like, like, limit)):
                out.append({"kind": "ap", "ref": r["bssid"],
                            "label": r["ssid"] or r["bssid"], "sub": r["bssid"],
                            "band": r["band"]})
        return out[:limit]

    def prune_inventory(self, device_purge_seconds: float, ap_purge_seconds: float,
                        muted_macs: Iterable[str]) -> dict:
        """Delete inventory not seen within its purge window. Muted devices and
        trusted (is_known) APs are exempt — they never expire."""
        now = time.time()
        muted = {str(m).upper() for m in (muted_macs or []) if m}
        dev_cut = now - device_purge_seconds
        ap_cut = now - ap_purge_seconds
        with self._lock:
            stale_devs = [r["mac"] for r in self._db.execute(
                "SELECT mac FROM devices WHERE last_seen < ?", (dev_cut,))]
            drop_devs = [m for m in stale_devs if m.upper() not in muted]
            for m in drop_devs:
                self._db.execute("DELETE FROM devices WHERE mac=?", (m,))
                if self._fts:
                    self._fts_del("device", m)
            stale_aps = [r["bssid"] for r in self._db.execute(
                "SELECT bssid FROM access_points WHERE last_seen < ? AND is_known=0",
                (ap_cut,))]
            for b in stale_aps:
                self._db.execute("DELETE FROM access_points WHERE bssid=?", (b,))
                if self._fts:
                    self._fts_del("ap", b)
            self._db.commit()
        return {"devices_purged": len(drop_devs), "aps_purged": len(stale_aps)}

    # ── Retention / disk guard ─────────────────────────────────────────
    def prune(self, raw_retention_hours: float, disk_guard_percent: float) -> dict:
        """Delete raw frames older than the window; trim harder if disk is tight.

        Returns a small report dict for logging/telemetry.
        """
        cutoff = time.time() - raw_retention_hours * 3600
        deleted = self._delete_frames_before(cutoff)

        # Disk guard: if the partition is over the threshold, keep halving the
        # retained window (down to 1h) until we're back under it.
        used_pct = self._disk_used_percent()
        window_h = raw_retention_hours
        guard_deleted = 0
        while used_pct >= disk_guard_percent and window_h > 1:
            window_h = max(1.0, window_h / 2)
            guard_deleted += self._delete_frames_before(time.time() - window_h * 3600)
            used_pct = self._disk_used_percent()

        # Expire stale sessions opportunistically.
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
            self._db.commit()

        if deleted or guard_deleted:
            with self._lock:
                # Reclaim pages incrementally; full VACUUM would block too long.
                self._db.execute("PRAGMA incremental_vacuum")
                self._db.commit()

        return {"deleted": deleted, "guard_deleted": guard_deleted,
                "disk_used_pct": round(used_pct, 1), "window_hours": window_h}

    def _delete_frames_before(self, cutoff: float) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM frames WHERE received_at < ?", (cutoff,))
            self._db.execute("DELETE FROM board_events WHERE received_at < ?", (cutoff,))
            self._db.execute("DELETE FROM ap_info WHERE received_at < ?", (cutoff,))
            self._db.commit()
            return cur.rowcount

    def _disk_used_percent(self) -> float:
        try:
            usage = shutil.disk_usage(os.path.dirname(self.path) or ".")
            return usage.used / usage.total * 100.0
        except OSError:
            return 0.0

    def close(self) -> None:
        with self._lock:
            self._db.close()
