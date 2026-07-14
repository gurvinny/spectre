"""Synthetic UART traffic generator with injectable attack scenarios.

Every line is emitted in the real firmware format::

    <190>ESP32C5 wifi_sniffer: {"seq":..,"uptime_ms":..,"type":"BEACON",...}

so it flows through the same :class:`~spectre.parser.Parser` the serial reader
uses. Run standalone to print to stdout::

    python -m spectre.sim.generate --scenario deauth_flood --duration 20

or drive the live pipeline via :func:`SimSource` (used when SPECTRE_SOURCE=sim).

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from typing import Iterable, Optional

from ..parser import Parser
from ..pipeline import Pipeline

TAG = "<190>ESP32C5 wifi_sniffer: "

# A small fake but plausible RF environment.
_APS = [
    {"bssid": "00:00:5E:00:53:01", "ssid": "ExampleNet", "band": "2.4GHz", "ch": 6},
    {"bssid": "00:00:5E:00:53:02", "ssid": "ExampleNet", "band": "2.4GHz", "ch": 1},
    {"bssid": "00:00:5E:00:53:03", "ssid": "Neighbor-24", "band": "2.4GHz", "ch": 11},
    {"bssid": "00:00:5E:00:53:04", "ssid": "GuestWiFi", "band": "2.4GHz", "ch": 3},
    {"bssid": "00:00:5E:00:53:05", "ssid": "IoT-5G", "band": "5GHz", "ch": 36},
    {"bssid": "00:00:5E:00:53:06", "ssid": "ExampleNet", "band": "5GHz", "ch": 149},
]
_CLIENTS = ["00:00:5E:00:53:10", "00:00:5E:00:53:11", "00:00:5E:00:53:12",
            "36:00:5E:00:53:13"]  # last one is a randomized MAC


class Simulator:
    """Produces firmware-format lines; scenarios can be injected on demand."""

    def __init__(self, band: str = "2.4GHz", seed: Optional[int] = None) -> None:
        self.band = band
        self.rng = random.Random(seed)
        self.seq = 0
        self.t0 = time.time()
        self._aps = [a for a in _APS if a["band"] == band] or _APS
        self._pending: list[str] = []

    # ── line construction ──────────────────────────────────────────────
    def _line(self, **fields) -> str:
        self.seq += 1
        obj = {"seq": self.seq,
               "uptime_ms": int((time.time() - self.t0) * 1000)}
        obj.update(fields)
        return TAG + json.dumps(obj)

    def boot_lines(self) -> list[str]:
        chans = "1-13" if self.band == "2.4GHz" else "36-165"
        return [
            TAG + json.dumps({"event": "boot", "chip": "ESP32-C5",
                              "mode": "promiscuous", "band": self.band,
                              "channels": chans}),
            TAG + json.dumps({"event": "sniffer_started", "ch": 1, "usb_cdc": True}),
        ]

    # ── normal background traffic ──────────────────────────────────────
    def background(self) -> str:
        roll = self.rng.random()
        ap = self.rng.choice(self._aps)
        client = self.rng.choice(_CLIENTS)
        if roll < 0.55:  # beacon
            return self._line(ch=ap["ch"], rssi=self._rssi(), type="BEACON",
                              src=ap["bssid"], dst="FF:FF:FF:FF:FF:FF",
                              bssid=ap["bssid"], ssid=ap["ssid"])
        if roll < 0.75:  # data
            return self._line(ch=ap["ch"], rssi=self._rssi(), type="DATA",
                              src=client, dst=ap["bssid"], bssid=ap["bssid"])
        if roll < 0.9:   # probe req
            ssid = ap["ssid"] if self.rng.random() < 0.5 else "?"
            return self._line(ch=ap["ch"], rssi=self._rssi(), type="PROBE_REQ",
                              src=client, dst="FF:FF:FF:FF:FF:FF",
                              bssid="FF:FF:FF:FF:FF:FF", ssid=ssid)
        return self._line(ch=ap["ch"], rssi=self._rssi(), type="PROBE_RESP",
                          src=ap["bssid"], dst=client, bssid=ap["bssid"],
                          ssid=ap["ssid"])

    def _rssi(self) -> int:
        return self.rng.randint(-92, -20)

    # ── attack scenarios ───────────────────────────────────────────────
    def scenario(self, name: str) -> list[str]:
        ap = self._aps[0]
        if name == "deauth_flood":
            victim = _CLIENTS[0]
            return [self._line(ch=ap["ch"], rssi=self._rssi(),
                               type=self.rng.choice(["DEAUTH", "DISASSOC"]),
                               src=ap["bssid"], dst=victim, bssid=ap["bssid"])
                    for _ in range(40)]
        if name == "evil_twin":
            rogue = "00:00:5E:00:53:66"
            return [self._line(ch=ap["ch"], rssi=-38, type="BEACON",
                               src=rogue, dst="FF:FF:FF:FF:FF:FF",
                               bssid=rogue, ssid=ap["ssid"]) for _ in range(3)]
        if name == "beacon_flood":
            out = []
            for i in range(60):
                fake = f"AA:BB:CC:{i:02X}:{self.rng.randint(0,255):02X}:{self.rng.randint(0,255):02X}"
                out.append(self._line(ch=ap["ch"], rssi=self._rssi(),
                                      type="BEACON", src=fake,
                                      dst="FF:FF:FF:FF:FF:FF", bssid=fake,
                                      ssid=f"FreeWiFi_{i}"))
            return out
        if name == "probe_flood":
            return [self._line(ch=ap["ch"], rssi=self._rssi(), type="PROBE_REQ",
                               src=f"3A:{self.rng.randint(0,255):02X}:9F:00:2B:{i:02X}",
                               dst="FF:FF:FF:FF:FF:FF",
                               bssid="FF:FF:FF:FF:FF:FF", ssid="?")
                    for i in range(200)]
        return []


# ── async source that drives the live pipeline ─────────────────────────
class SimSource:
    """Feeds synthetic lines into the pipeline (SPECTRE_SOURCE=sim).

    Runs continuous background traffic on both bands and periodically injects a
    rotating set of attack scenarios so the dashboard has something to show.
    """

    def __init__(self, pipeline: Pipeline, fps: float = 45.0,
                 auto_scenarios: bool = True) -> None:
        self.pipeline = pipeline
        self.fps = fps
        self.auto_scenarios = auto_scenarios
        self._sims = {"2.4GHz": Simulator("2.4GHz", seed=24),
                      "5GHz": Simulator("5GHz", seed=5)}
        self._parsers = {b: Parser(f"sim-{b}", default_band=b) for b in self._sims}
        self._task: Optional[asyncio.Task] = None

    def _feed(self, band: str, line: str) -> None:
        ev = self._parsers[band].parse_line(line)
        if ev is not None:
            self.pipeline.ingest(ev)

    async def run(self) -> None:
        # Prime band identity via boot events.
        for band, sim in self._sims.items():
            for line in sim.boot_lines():
                self._parsers[band].parse_line(line)
        rotation = ["deauth_flood", "evil_twin", "beacon_flood", "probe_flood"]
        idx = 0
        next_scenario = time.time() + 20
        interval = 1.0 / self.fps
        while True:
            band = "2.4GHz" if random.random() < 0.65 else "5GHz"
            self._feed(band, self._sims[band].background())
            if self.auto_scenarios and time.time() >= next_scenario:
                name = rotation[idx % len(rotation)]
                idx += 1
                for line in self._sims["2.4GHz"].scenario(name):
                    self._feed("2.4GHz", line)
                next_scenario = time.time() + 45
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
    ap.add_argument("--fps", type=float, default=30.0, help="background frames/sec")
    ap.add_argument("--duration", type=float, default=20.0, help="seconds (0=forever)")
    ap.add_argument("--scenario", default=None,
                    help="inject once after 3s: deauth_flood|evil_twin|beacon_flood|probe_flood")
    args = ap.parse_args(argv)

    sim = Simulator(args.band)
    for line in sim.boot_lines():
        print(line, flush=True)

    start = time.time()
    injected = False
    interval = 1.0 / args.fps
    try:
        while args.duration == 0 or time.time() - start < args.duration:
            print(sim.background(), flush=True)
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
