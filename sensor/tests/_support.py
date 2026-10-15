"""Shared helpers for the sensor test suite.

Events are built by running real firmware-format lines through the shipping
:class:`~spectre.parser.Parser`, so a parser change reaches every detector test
instead of drifting away from a hand-written fixture. Only ``received_at`` is
overridden, because detection is time-windowed and the tests need a clock they
control.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spectre.models import Event  # noqa: E402
from spectre.parser import Parser  # noqa: E402
from spectre.sim.generate import TAG, Simulator  # noqa: E402

BROADCAST = "FF:FF:FF:FF:FF:FF"


def make_cfg(**overrides):
    """A ``cfg(key, default)`` accessor with per-test overrides.

    Mirrors :class:`spectre.config.Config`'s contract: the override wins,
    otherwise the caller's default is used.
    """
    values = dict(overrides)

    def cfg(key, default=None):
        return values.get(key, default)

    cfg.values = values  # tests retune live through this
    return cfg


def frame(ts: float, *, sensor: str = "sensor-test", band: str = "2.4GHz",
          **fields) -> Event:
    """Parse one firmware line built from *fields* and stamp it at *ts*."""
    parser = Parser(sensor, default_band=band)
    ev = parser.parse_line(TAG + json.dumps(fields))
    if ev is None:
        raise AssertionError(f"parser rejected test frame {fields!r}")
    return dataclasses.replace(ev, received_at=ts)


def sim_events(name: str, *, band: str = "2.4GHz", t0: float = 1000.0,
               step: float = 0.01, seed: int = 7) -> list[Event]:
    """Events for a built-in attack scenario, through the real parser."""
    sim = Simulator(band=band, seed=seed)
    parser = Parser("sim-" + band)
    for line in sim.boot_lines():
        parser.parse_line(line)
    out = []
    for i, line in enumerate(sim.scenario(name)):
        ev = parser.parse_line(line)
        if ev is not None:
            out.append(dataclasses.replace(ev, received_at=t0 + i * step))
    if not out:
        raise AssertionError(f"scenario {name!r} produced no events")
    return out


class TempDir:
    """A throwaway directory that removes itself (use in setUp/tearDown)."""

    def __init__(self) -> None:
        self.path = tempfile.mkdtemp(prefix="spectre-test-")

    def file(self, name: str) -> str:
        return os.path.join(self.path, name)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class UdpSink:
    """A bound loopback UDP socket that records what a sender delivered."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(2.0)
        self.port = self.sock.getsockname()[1]

    def recv(self) -> str:
        data, _ = self.sock.recvfrom(65535)
        return data.decode("utf-8")

    def empty(self) -> bool:
        self.sock.settimeout(0.2)
        try:
            self.sock.recvfrom(65535)
        except socket.timeout:
            return True
        finally:
            self.sock.settimeout(2.0)
        return False

    def close(self) -> None:
        self.sock.close()
