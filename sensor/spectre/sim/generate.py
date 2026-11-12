"""Synthetic UART traffic generator with injectable attack scenarios.

Every line is emitted in the real firmware format::

    <190>ESP32C5 wifi_sniffer: {"seq":..,"uptime_ms":..,"type":"BEACON",...}

so it flows through the same :class:`~spectre.parser.Parser` the serial reader
uses. Run standalone to print to stdout::

    python -m spectre.sim.generate --scenario deauth_flood --duration 20

or drive the live pipeline via :func:`SimSource` (used when SPECTRE_SOURCE=sim).

By default the simulator speaks the v2 firmware's contract
(``docs/data-contract.md``): rich frame keys, ``ap_info`` on first sighting,
on change and every ``ap_info_s``, a ``channel_sweep_complete`` with counters
every sweep, ``telemetry`` and ``clock_sync`` every 10 s, and a command
interface that acks ``get_config`` / ``set`` / ``reset_config`` / ``reboot``
with the firmware's validation and error strings. ``fw="v1"`` reproduces the
original firmware's lines. The v2 extras draw from their own RNG, so a seeded
v1 stream (and every detector fixture built from it) is identical in both
modes.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import threading
import time
import zlib
from typing import Callable, Optional

from ..parser import Parser
from ..pipeline import Pipeline
from ..reader import MAX_COMMAND_BYTES

TAG = "<190>ESP32C5 wifi_sniffer: "
BROADCAST = "FF:FF:FF:FF:FF:FF"

FW_VERSION = "v2.0.0-sim"
ELF_SHA = "0000000000000000"
CAPS = ["counters", "cmd", "ap_info", "phy", "telemetry"]
BAUD = 460800
TELEMETRY_MS = 10000
CLOCK_SYNC_MS = 10000
Q_SIZE = 65536                # the firmware ring (RING_SIZE, 2.0.4+)
HEAP = 150000
CMD_LINE_MAX = 255           # the firmware's command buffer, less its terminator
DWELL_MIN_MS, DWELL_MAX_MS = 50, 5000
AP_INFO_MAX_S = 3600
MAX_CHANNELS = 32
DEFAULT_DROP_RATE = 0.002

# 20 MHz primaries the radio can tune to, as in the firmware's cfg.c.
CH_5G = (36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128,
         132, 136, 140, 144, 149, 153, 157, 161, 165, 169, 173, 177)
_PLANS = {"2.4GHz": (list(range(1, 14)), 300, "1-13"),
          "5GHz": (list(CH_5G[:25]), 200, "36-165")}
_FILTERS = ("mgmt", "ctrl", "data")
_SUBTYPES = {"BEACON": 8, "PROBE_REQ": 4, "PROBE_RESP": 5, "DEAUTH": 12,
             "DISASSOC": 10, "AUTH": 11, "DATA": 8, "CTRL": 13}

# A small fake but plausible RF environment.
_APS = [
    {"bssid": "00:00:5E:00:53:01", "ssid": "ExampleNet", "band": "2.4GHz", "ch": 6,
     "sec": "WPA2/WPA3", "akm": ["PSK", "SAE"], "pairwise": ["CCMP"], "group": ["CCMP"],
     "pmf": "capable", "wpa1": False, "ht": True, "vht": False, "he": True, "eht": False,
     "wps": False},
    {"bssid": "00:00:5E:00:53:02", "ssid": "ExampleNet", "band": "2.4GHz", "ch": 1,
     "sec": "WPA2/WPA3", "akm": ["PSK", "SAE"], "pairwise": ["CCMP"], "group": ["CCMP"],
     "pmf": "capable", "wpa1": False, "ht": True, "vht": False, "he": True, "eht": False,
     "wps": False},
    {"bssid": "00:00:5E:00:53:03", "ssid": "Neighbor-24", "band": "2.4GHz", "ch": 11,
     "sec": "WPA2", "akm": ["PSK"], "pairwise": ["TKIP", "CCMP"], "group": ["TKIP"],
     "pmf": "none", "wpa1": True, "ht": True, "vht": False, "he": False, "eht": False,
     "wps": True, "ouis": ["0050F2"]},
    {"bssid": "00:00:5E:00:53:04", "ssid": "GuestWiFi", "band": "2.4GHz", "ch": 3,
     "sec": "OPEN", "akm": [], "pairwise": [], "group": [], "pmf": "none", "wpa1": False,
     "ht": True, "vht": False, "he": False, "eht": False, "wps": False},
    {"bssid": "00:00:5E:00:53:05", "ssid": "IoT-5G", "band": "5GHz", "ch": 36,
     "sec": "WPA2", "akm": ["PSK"], "pairwise": ["CCMP"], "group": ["CCMP"], "pmf": "none",
     "wpa1": False, "ht": True, "vht": True, "he": False, "eht": False, "wps": False},
    {"bssid": "00:00:5E:00:53:06", "ssid": "ExampleNet", "band": "5GHz", "ch": 149,
     "sec": "WPA2/WPA3", "akm": ["PSK", "SAE"], "pairwise": ["CCMP"], "group": ["CCMP"],
     "pmf": "capable", "wpa1": False, "ht": True, "vht": True, "he": True, "eht": False,
     "wps": False, "ouis": ["00904C"]},
]
_CLIENTS = ["00:00:5E:00:53:10", "00:00:5E:00:53:11", "00:00:5E:00:53:12",
            "36:00:5E:00:53:13"]  # last one is a randomized MAC
_CLIENT_OUIS = {"00:00:5E:00:53:10": ["0050F2"], "00:00:5E:00:53:11": ["0017F2", "0050F2"],
                "00:00:5E:00:53:12": ["00904C"], "36:00:5E:00:53:13": ["0017F2"]}
# Elements that feed the ap_info hash, so a change to any of them is "changed".
_IE_KEYS = ("ssid", "sec", "akm", "pairwise", "group", "pmf", "wpa1", "ht", "vht", "he",
            "eht", "wps", "csa", "ouis")


def _open_ap(bssid: str, ssid: str, ch: int) -> dict:
    """What a rogue or fake AP typically advertises: nothing but an SSID."""
    return {"bssid": bssid, "ssid": ssid, "ch": ch, "sec": "OPEN", "akm": [],
            "pairwise": [], "group": [], "pmf": "none", "wpa1": False, "ht": True,
            "vht": False, "he": False, "eht": False, "wps": False}


def _plan(band: str) -> dict:
    channels, dwell, _ = _PLANS[band]
    return {"band": band, "channels": list(channels), "dwell_ms": dwell, "pin": 0,
            "filter": ["mgmt", "data"], "dedup": 0, "ap_info_s": 300}


def _channel_ok(band: str, ch) -> bool:
    if band == "2.4GHz":
        return 1 <= ch <= 14
    return ch in CH_5G


def _frame_class(frame_type: str) -> str:
    return {"DATA": "data", "CTRL": "ctrl"}.get(frame_type, "mgmt")


class Simulator:
    """Produces firmware-format lines; scenarios can be injected on demand."""

    def __init__(self, band: str = "2.4GHz", seed: Optional[int] = None, fw: str = "v2",
                 clock: Callable[[], float] = time.time,
                 drop_rate: float = DEFAULT_DROP_RATE) -> None:
        if fw not in ("v1", "v2"):
            raise ValueError(f"unknown firmware {fw!r}")
        self.fw = fw
        self.rng = random.Random(seed)
        # v2 extras never touch self.rng: v1 output stays identical per seed.
        self._prng = random.Random(None if seed is None else f"v2-{seed}")
        self.clock = clock
        self.drop_rate = drop_rate
        self.config = _plan(band)
        self._ap_table = [dict(a) for a in _APS]
        self._sn: dict[str, int] = {}
        self._boot("poweron")

    @property
    def band(self) -> str:
        return self.config["band"]

    @property
    def _aps(self) -> list[dict]:
        return [a for a in self._ap_table if a.get("band") == self.band] or self._ap_table

    def _boot(self, reset: str) -> None:
        self.t0 = self.clock()
        self.seq = 0
        self.reset_reason = reset
        self.counters = dict.fromkeys(("rx_total", "emitted", "drop_queue", "drop_short",
                                       "drop_dedup", "drop_overflow"), 0)
        self._q_hwm = 0
        self._heap_min = HEAP
        self._apc: dict[str, tuple[str, int]] = {}
        self._dedup: dict[str, int] = {}
        self._last_sweep = self._last_tel = self._last_clock = 0
        self._bytes = self._bytes_at_tel = 0

    # ── clock ──────────────────────────────────────────────────────────
    def _elapsed_us(self) -> int:
        return round((self.clock() - self.t0) * 1_000_000)

    def _uptime(self) -> int:
        return self._elapsed_us() // 1000

    # ── line construction ──────────────────────────────────────────────
    def _emit(self, obj: dict) -> str:
        line = TAG + json.dumps(obj, separators=(",", ":") if self.fw == "v2" else None)
        self._bytes += len(line) + 1
        return line

    def _line(self, **fields) -> str:
        self.seq += 1
        obj = {"seq": self.seq, "uptime_ms": self._uptime()}
        obj.update(fields)
        return self._emit(obj)

    def _channels_str(self) -> str:
        channels, _, label = _PLANS[self.band]
        if self.config["channels"] == channels:
            return label
        return ",".join(str(c) for c in self.config["channels"])

    def wire_config(self) -> dict:
        c = self.config
        return {"band": c["band"], "channels": self._channels_str(), "dwell_ms": c["dwell_ms"],
                "pin": c["pin"], "filter": list(c["filter"]), "dedup": c["dedup"],
                "ap_info_s": c["ap_info_s"]}

    def boot_lines(self) -> list[str]:
        if self.fw == "v1":
            chans = "1-13" if self.band == "2.4GHz" else "36-165"
            return [
                self._emit({"event": "boot", "chip": "ESP32-C5", "mode": "promiscuous",
                            "band": self.band, "channels": chans}),
                self._emit({"event": "sniffer_started", "ch": 1, "usb_cdc": True}),
            ]
        boot = {"event": "boot", "chip": "ESP32-C5", "mode": "promiscuous"}
        boot.update(self.wire_config())
        boot.update({"fw": "spectre-sniffer", "ver": FW_VERSION, "elf_sha": ELF_SHA,
                     "reset": self.reset_reason, "baud": BAUD, "caps": list(CAPS)})
        c = self.config
        return [self._emit(boot),
                self._emit({"event": "sniffer_started", "ch": c["pin"] or c["channels"][0]})]

    # ── v2 frame building ──────────────────────────────────────────────
    def _frame(self, fields: dict, droppable: bool = False) -> list[str]:
        """One captured frame: [] if filtered or dropped, else its lines
        (an ``ap_info`` first when one is due, then the frame)."""
        if self.fw == "v1":
            return [self._line(**{k: v for k, v in fields.items()
                                  if k != "eapol" and not k.startswith("_")})]
        c = self.config
        kind = fields["type"]
        if _frame_class(kind) not in c["filter"]:
            return []           # the promiscuous filter: never reaches the callback
        active = [c["pin"]] if c["pin"] else c["channels"]
        if fields.get("ch") not in active:
            fields = dict(fields, ch=active[self._prng.randrange(len(active))])
        k = self.counters
        k["rx_total"] += 1
        if droppable and self._prng.random() < self.drop_rate:
            k["drop_queue" if self._prng.random() < 0.8 else "drop_short"] += 1
            return []
        now = self._uptime()
        out = []
        bssid = fields.get("bssid")
        if kind in ("BEACON", "PROBE_RESP") and bssid:
            info = self._ap_info_due(bssid, fields, now)
            if info:
                out.append(info)
            if c["dedup"] and kind == "BEACON":
                epoch = now // c["dwell_ms"]
                if self._dedup.get(bssid) == epoch:
                    k["drop_dedup"] += 1
                    return out
                self._dedup[bssid] = epoch
        self._q_hwm = max(self._q_hwm, self._prng.randrange(256, 4096))
        self.seq += 1
        k["emitted"] += 1
        obj = {"seq": self.seq, "uptime_ms": now}
        for key, value in fields.items():
            obj[key] = value
            if key == "type":
                obj["sub"] = 0 if kind == "DATA" and self._prng.random() < 0.1 \
                    else _SUBTYPES[kind]
        obj.update(self._radio(obj))
        return out + [self._emit(obj)]

    def _radio(self, f: dict) -> dict:
        """The v2 keys after ``ssid``, in the firmware's order."""
        kind = f["type"]
        five = self.band == "5GHz"
        r = {"nf": self._prng.randint(-96, -90)}
        if kind == "DATA":
            phy = self._prng.choice(("n", "ac", "ax") if five else ("n", "ax"))
            r.update(phy=phy, mcs=self._prng.randint(0, {"n": 7, "ac": 9, "ax": 11}[phy]),
                     bw=20)
        else:
            r.update(phy="a" if five else "g", bw=20, rate=11)
        r["ts"] = self._elapsed_us() % 2 ** 32
        src = f.get("src")
        if src is not None:
            sn = self._sn.get(src)
            self._sn[src] = sn = self._prng.randrange(4096) if sn is None else (sn + 1) % 4096
            r["sn"] = sn
        unicast = f.get("dst") != BROADCAST
        fl = 0x08 if unicast and kind != "CTRL" and self._prng.random() < 0.05 else 0
        if kind == "DATA":
            fl |= 0x01 if f.get("dst") == f.get("bssid") else 0x02
            if "eapol" not in f:
                fl |= 0x40
        r["fl"] = fl
        r["dur"] = 0 if not unicast or kind == "CTRL" else (44 if kind != "DATA" else 314)
        if kind in ("DEAUTH", "DISASSOC"):
            r["reason"] = 7     # class 3 frame from a non-associated station
        if kind == "AUTH":
            r.update(aalg=0, aseq=f.pop("_aseq"), st=0)
        if "eapol" in f:
            r["eapol"] = f.pop("eapol")
        if kind == "PROBE_REQ":
            r["fp"] = f"{zlib.crc32(('fp|' + src).encode()):08x}"
            r["ouis"] = list(_CLIENT_OUIS.get(src, ["0050F2"]))
        return r

    # ── ap_info ────────────────────────────────────────────────────────
    def _ap(self, bssid: str, fields: dict) -> dict:
        for ap in self._ap_table:
            if ap["bssid"] == bssid:
                return ap
        return _open_ap(bssid, fields.get("ssid") or "?", fields.get("ch") or 0)

    @staticmethod
    def _ie_hash(ap: dict) -> str:
        ie = {k: ap.get(k) for k in _IE_KEYS}
        return f"{zlib.crc32(json.dumps(ie, sort_keys=True).encode()):08x}"

    def _ap_info_due(self, bssid: str, fields: dict, now: int) -> Optional[str]:
        ap = self._ap(bssid, fields)
        h = self._ie_hash(ap)
        seen = self._apc.get(bssid)
        if seen is None:
            why = "new"
        elif seen[0] != h:
            why = "changed"
        elif self.config["ap_info_s"] and now - seen[1] >= self.config["ap_info_s"] * 1000:
            why = "periodic"
        else:
            return None
        self._apc[bssid] = (h, now)
        return self.ap_info_line(ap, why, ch=fields.get("ch"))

    def ap_info_line(self, ap: dict, why: str, ch: Optional[int] = None) -> str:
        """One AP's advertised security and capabilities, as the firmware sends it."""
        info = {"event": "ap_info", "uptime_ms": self._uptime(), "why": why,
                "bssid": ap["bssid"], "ch": ch if ch is not None else ap["ch"],
                "ds_ch": ap["ch"], "ssid": ap["ssid"] or "?", "bi": 100,
                "cap": 0x0001 if ap["sec"] == "OPEN" else 0x0011}
        for key in ("sec", "akm", "pairwise", "group", "pmf", "wpa1", "ht", "vht", "he",
                    "eht", "wps"):
            info[key] = ap[key]
        for key in ("csa", "ouis"):
            if ap.get(key):
                info[key] = ap[key]
        info["hash"] = self._ie_hash(ap)
        return self._emit(info)

    def set_ap(self, bssid: str, **changes) -> None:
        """Change what a known AP advertises (its next beacon reports "changed")."""
        for ap in self._ap_table:
            if ap["bssid"] == bssid:
                ap.update(changes)
                return
        raise KeyError(bssid)

    # ── normal background traffic ──────────────────────────────────────
    def background(self) -> list[str]:
        c = self.config
        active = [c["pin"]] if c["pin"] else c["channels"]
        aps = self._aps
        if self.fw == "v2" and any(a["ch"] not in active for a in aps):
            aps = [a for a in aps if a["ch"] in active] or aps
        roll = self.rng.random()
        ap = self.rng.choice(aps)
        client = self.rng.choice(_CLIENTS)
        if roll < 0.55:  # beacon
            f = dict(ch=ap["ch"], rssi=self._rssi(), type="BEACON", src=ap["bssid"],
                     dst=BROADCAST, bssid=ap["bssid"], ssid=ap["ssid"])
        elif roll < 0.75:  # data
            f = dict(ch=ap["ch"], rssi=self._rssi(), type="DATA", src=client,
                     dst=ap["bssid"], bssid=ap["bssid"])
        elif roll < 0.9:   # probe req
            ssid = ap["ssid"] if self.rng.random() < 0.5 else "?"
            f = dict(ch=ap["ch"], rssi=self._rssi(), type="PROBE_REQ", src=client,
                     dst=BROADCAST, bssid=BROADCAST, ssid=ssid)
        else:
            f = dict(ch=ap["ch"], rssi=self._rssi(), type="PROBE_RESP", src=ap["bssid"],
                     dst=client, bssid=ap["bssid"], ssid=ap["ssid"])
        out = self._frame(f, droppable=True)
        if (self.fw == "v2" and "ctrl" in c["filter"] and f["dst"] != BROADCAST
                and self._prng.random() < 0.3):
            out += self._frame(dict(ch=f["ch"], rssi=self._prng.randint(-92, -20),
                                    type="CTRL", dst=f["src"]), droppable=True)
        return out

    def _rssi(self) -> int:
        return self.rng.randint(-92, -20)

    # ── attack scenarios ───────────────────────────────────────────────
    def scenario(self, name: str) -> list[str]:
        ap = self._aps[0]
        out: list[str] = []
        if name == "deauth_flood":
            victim = _CLIENTS[0]
            for _ in range(40):
                out += self._frame(dict(ch=ap["ch"], rssi=self._rssi(),
                                        type=self.rng.choice(["DEAUTH", "DISASSOC"]),
                                        src=ap["bssid"], dst=victim, bssid=ap["bssid"]))
        elif name == "evil_twin":
            rogue = "00:00:5E:00:53:66"
            for _ in range(3):
                out += self._frame(dict(ch=ap["ch"], rssi=-38, type="BEACON", src=rogue,
                                        dst=BROADCAST, bssid=rogue, ssid=ap["ssid"]))
        elif name == "beacon_flood":
            for i in range(60):
                fake = f"AA:BB:CC:{i:02X}:{self.rng.randint(0,255):02X}:{self.rng.randint(0,255):02X}"
                out += self._frame(dict(ch=ap["ch"], rssi=self._rssi(), type="BEACON",
                                        src=fake, dst=BROADCAST, bssid=fake,
                                        ssid=f"FreeWiFi_{i}"))
        elif name == "probe_flood":
            for i in range(200):
                out += self._frame(dict(ch=ap["ch"], rssi=self._rssi(), type="PROBE_REQ",
                                        src=f"3A:{self.rng.randint(0,255):02X}:9F:00:2B:{i:02X}",
                                        dst=BROADCAST, bssid=BROADCAST, ssid="?"))
        elif name == "reconnect":
            # A client re-joining after a deauth: open-system auth, then the
            # four-way handshake. Not an attack; it gives EAPOL rows to look at.
            client, bssid = _CLIENTS[1], ap["bssid"]
            for src, dst, aseq in ((client, bssid, 1), (bssid, client, 2)):
                out += self._frame(dict(ch=ap["ch"], rssi=self._rssi(), type="AUTH", src=src,
                                        dst=dst, bssid=bssid, _aseq=aseq))
            for msg in (1, 2, 3, 4):
                src, dst = (bssid, client) if msg % 2 else (client, bssid)
                out += self._frame(dict(ch=ap["ch"], rssi=self._rssi(), type="DATA", src=src,
                                        dst=dst, bssid=bssid, eapol=msg))
        return out

    # ── periodic lines ─────────────────────────────────────────────────
    def ticks(self) -> list[str]:
        """Lifecycle lines due now: sweep counters, telemetry, clock sync."""
        if self.fw == "v1":
            return []
        now = self._uptime()
        wire_bytes = self._bytes
        k = self.counters
        out = []
        c = self.config
        if now - self._last_sweep >= len(c["channels"]) * c["dwell_ms"]:
            sweep = {"event": "channel_sweep_complete", "total_pkts": k["emitted"],
                     "uptime_ms": now, "sweep_ms": now - self._last_sweep}
            sweep.update(k)
            out.append(self._emit(sweep))
            self._last_sweep = now
        if now - self._last_tel >= TELEMETRY_MS:
            heap = HEAP - self._prng.randrange(0, 4000)
            self._heap_min = min(self._heap_min, heap)
            tel = {"event": "telemetry", "uptime_ms": now}
            tel.update(k)
            tel.update({"q_hwm": self._q_hwm, "q_size": Q_SIZE, "heap": heap,
                        "heap_min": self._heap_min, "temp_dc": 400 + self._prng.randrange(40),
                        "uart_bps": int((wire_bytes - self._bytes_at_tel)
                                        / ((now - self._last_tel) / 1000))})
            out.append(self._emit(tel))
            self._last_tel = now
            self._bytes_at_tel = wire_bytes
        if now - self._last_clock >= CLOCK_SYNC_MS:
            out.append(self._emit({"event": "clock_sync", "uptime_ms": now,
                                   "mono_us": self._elapsed_us()}))
            self._last_clock = now
        return out

    # ── command interface ──────────────────────────────────────────────
    def command(self, cmd) -> list[str]:
        """Apply one UART command; returns the lines the board answers with.

        Mirrors the firmware's ``cmd_parse``: keys are taken in order, a
        later error overwrites an earlier one, and a failed command changes
        nothing. ``reboot`` acks, then boots again with the saved plan.
        """
        if self.fw == "v1":
            return []           # the original firmware has no command interface
        name, cid, err, kind, staged = self._parse(cmd)
        if err is None:
            if kind is None:
                err = "missing cmd"
            elif kind == "set":
                new, err = self._apply(staged)
                if err is None:
                    self.config = new
            elif kind == "reset_config":
                self.config = _plan(self.band)
        ack = {"event": "cmd_ack", "cmd": name}
        if cid:
            ack["id"] = cid
        ack["ok"] = err is None
        if err:
            ack["err"] = err
        ack["config"] = self.wire_config()
        out = [self._emit(ack)]
        if err is None and kind == "reboot":
            self._boot("software")
            out += self.boot_lines()
        return out

    @staticmethod
    def _value_ok(v) -> bool:
        if isinstance(v, (bool, int, str)):
            return True
        if isinstance(v, list):
            if len(v) > MAX_CHANNELS:
                return False
            kinds = {type(x) for x in v}
            return len(kinds) <= 1 and kinds <= {bool, int, str}
        return False

    def _parse(self, cmd):
        name, cid, err, kind, staged = "", "", None, None, {}
        bad = (name, cid, "bad json", None, {})
        if isinstance(cmd, str):
            if len(cmd) > CMD_LINE_MAX:
                return "", "", "line too long", None, {}
            try:
                cmd = json.loads(cmd)
            except ValueError:
                return bad
        if not isinstance(cmd, dict):
            return bad
        for key, v in cmd.items():
            if not self._value_ok(v):
                return name, cid, "bad json", None, {}
            if key == "cmd":
                if not isinstance(v, str):
                    return name, cid, "bad json", None, {}
                name = v[:15]
                if v in ("get_config", "set", "reset_config", "reboot"):
                    kind = v
                else:
                    err = "unknown cmd"
            elif key == "id":
                if not isinstance(v, str) or len(v) > 16:
                    return name, cid, "bad json", None, {}
                cid = v
            elif key == "band":
                if not isinstance(v, str):
                    return name, cid, "bad json", None, {}
                if v in _PLANS:
                    staged["band"] = v
                else:
                    err = "bad band"
            elif key == "channels":
                if not isinstance(v, list) or any(type(x) is not int for x in v):
                    return name, cid, "bad json", None, {}
                staged["channels"] = v
            elif key == "filter":
                if (not isinstance(v, list) or len(v) > 4
                        or any(not isinstance(x, str) or len(x) > 7 for x in v)):
                    return name, cid, "bad json", None, {}
                staged["filter"] = v
            elif key in ("dwell_ms", "pin", "dedup", "ap_info_s"):
                if not isinstance(v, int):
                    return name, cid, "bad json", None, {}
                staged[key] = int(v)
            else:
                err = "unknown key"
        return name, cid, err, kind, staged

    def _apply(self, st: dict):
        cur = self.config
        new = dict(cur, channels=list(cur["channels"]), filter=list(cur["filter"]))
        if "band" in st and st["band"] != cur["band"]:
            new = _plan(st["band"])     # a new band starts from its plan
        band = new["band"]
        if "channels" in st:
            chans = st["channels"]
            if not chans or len(set(chans)) != len(chans) \
                    or not all(_channel_ok(band, ch) for ch in chans):
                return None, "bad channel"
            new["channels"] = list(chans)
            if new["pin"] and new["pin"] not in chans:
                new["pin"] = 0          # a pin outside the new list lapses
        if "dwell_ms" in st:
            if not DWELL_MIN_MS <= st["dwell_ms"] <= DWELL_MAX_MS:
                return None, "bad dwell"
            new["dwell_ms"] = st["dwell_ms"]
        if "pin" in st:
            if st["pin"] != 0 and not _channel_ok(band, st["pin"]):
                return None, "bad pin"
            new["pin"] = st["pin"]
        if "filter" in st:
            if not st["filter"] or any(f not in _FILTERS for f in st["filter"]):
                return None, "bad filter"
            new["filter"] = [f for f in _FILTERS if f in st["filter"]]
        if "dedup" in st:
            if st["dedup"] not in (0, 1):
                return None, "bad value"
            new["dedup"] = st["dedup"]
        if "ap_info_s" in st:
            if not 0 <= st["ap_info_s"] <= AP_INFO_MAX_S:
                return None, "bad value"
            new["ap_info_s"] = st["ap_info_s"]
        return new, None


# ── async source that drives the live pipeline ─────────────────────────
class SimBoard:
    """One simulated board as the pipeline sees it: a parser plus ``send()``."""

    def __init__(self, sensor_id: str, sim: Simulator, pipeline: Pipeline,
                 lock: Optional[threading.Lock] = None) -> None:
        self.sensor_id = sensor_id
        self.sim = sim
        self.pipeline = pipeline
        # Shared with the source's step(): the API sends from a worker thread
        # while the event loop is generating traffic on the same Simulator.
        self.lock = lock if lock is not None else threading.Lock()
        self.parser = Parser(sensor_id, default_band=sim.band,
                             on_lifecycle=pipeline.record_board_event,
                             on_ap_info=pipeline.record_ap_info)

    def feed(self, lines) -> None:
        for line in lines:
            ev = self.parser.parse_line(line)
            if ev is not None:
                self.pipeline.ingest(ev)

    def send(self, command: dict | str) -> int:
        """Same contract as :meth:`SerialReader.send`; the ack is fed back in."""
        text = command if isinstance(command, str) else json.dumps(
            command, separators=(",", ":"))
        if "\n" in text or "\r" in text:
            raise ValueError("a command must be a single line")
        data = text.encode("utf-8")
        if len(data) > MAX_COMMAND_BYTES:
            raise ValueError(f"command is {len(data)} bytes, limit {MAX_COMMAND_BYTES}")
        with self.lock:
            self.feed(self.sim.command(text))
        return len(data) + 1


class SimSource:
    """Feeds synthetic lines into the pipeline (SPECTRE_SOURCE=sim).

    Runs continuous background traffic on both bands and periodically injects a
    rotating set of attack scenarios so the dashboard has something to show.
    """

    ROTATION = ("deauth_flood", "reconnect", "evil_twin", "beacon_flood", "probe_flood")

    def __init__(self, pipeline: Pipeline, fps: float = 45.0,
                 auto_scenarios: bool = True,
                 clock: Callable[[], float] = time.time) -> None:
        self.pipeline = pipeline
        self.fps = fps
        self.auto_scenarios = auto_scenarios
        self.clock = clock
        self.lock = threading.Lock()
        self.boards = {f"sim-{b}": SimBoard(f"sim-{b}", Simulator(b, seed=s, clock=clock),
                                            pipeline, self.lock)
                       for b, s in (("2.4GHz", 24), ("5GHz", 5))}
        self._parsers = {b.sim.band: b.parser for b in self.boards.values()}
        self.scenario_idx = 0
        self.next_scenario = clock() + 20
        self._task: Optional[asyncio.Task] = None

    def prime(self) -> None:
        """Boot lines first, so each board's band is latched before traffic."""
        with self.lock:
            for board in self.boards.values():
                board.feed(board.sim.boot_lines())

    def step(self) -> None:
        with self.lock:
            self._step()

    def _step(self) -> None:
        band = "2.4GHz" if random.random() < 0.65 else "5GHz"
        board = self.boards[f"sim-{band}"]
        board.feed(board.sim.background())
        for b in self.boards.values():
            b.feed(b.sim.ticks())
        if self.auto_scenarios and self.clock() >= self.next_scenario:
            name = self.ROTATION[self.scenario_idx % len(self.ROTATION)]
            self.scenario_idx += 1
            target = self.boards["sim-2.4GHz"]
            target.feed(target.sim.scenario(name))
            self.next_scenario = self.clock() + 45

    async def run(self) -> None:
        self.prime()
        interval = 1.0 / self.fps
        while True:
            self.step()
            await asyncio.sleep(interval)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# ── standalone CLI (prints to stdout) ──────────────────────────────────
def _main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SPECTRE synthetic UART generator")
    ap.add_argument("--band", default="2.4GHz", choices=["2.4GHz", "5GHz"])
    ap.add_argument("--fw", default="v2", choices=["v1", "v2"], help="line contract")
    ap.add_argument("--fps", type=float, default=30.0, help="background frames/sec")
    ap.add_argument("--duration", type=float, default=20.0, help="seconds (0=forever)")
    ap.add_argument("--scenario", default=None,
                    help="inject once after 3s: deauth_flood|evil_twin|beacon_flood|"
                         "probe_flood|reconnect")
    args = ap.parse_args(argv)

    sim = Simulator(args.band, fw=args.fw)
    for line in sim.boot_lines():
        print(line, flush=True)

    start = time.time()
    injected = False
    interval = 1.0 / args.fps
    try:
        while args.duration == 0 or time.time() - start < args.duration:
            for line in sim.background() + sim.ticks():
                print(line, flush=True)
            if args.scenario and not injected and time.time() - start > 3:
                for line in sim.scenario(args.scenario):
                    print(line, flush=True)
                injected = True
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(_main())
