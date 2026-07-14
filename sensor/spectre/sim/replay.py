"""Replay a captured UART text file through the pipeline.

Useful for regression testing against real-world captures: point it at a file of
raw firmware lines (one per line) and it re-feeds them, pacing by each frame's
``uptime_ms`` delta when available, otherwise at a fixed rate.

    python -m spectre.sim.replay capture.txt --speed 2.0

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Optional

from ..parser import Parser
from ..pipeline import Pipeline


def _uptime(line: str) -> Optional[int]:
    start = line.find("{")
    if start == -1:
        return None
    try:
        obj = json.loads(line[start:line.rfind("}") + 1])
        return int(obj.get("uptime_ms")) if "uptime_ms" in obj else None
    except (ValueError, TypeError):
        return None


class ReplaySource:
    """Async source that replays a capture file, optionally looping."""

    def __init__(self, pipeline: Pipeline, path: str, speed: float = 1.0,
                 loop: bool = True) -> None:
        self.pipeline = pipeline
        self.path = path
        self.speed = max(0.01, speed)
        self.loop = loop
        self.parser = Parser("replay")
        self._task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        while True:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
            prev_uptime: Optional[int] = None
            for line in lines:
                up = _uptime(line)
                if prev_uptime is not None and up is not None and up >= prev_uptime:
                    await asyncio.sleep(min(2.0, (up - prev_uptime) / 1000.0 / self.speed))
                else:
                    await asyncio.sleep(0.02 / self.speed)
                if up is not None:
                    prev_uptime = up
                ev = self.parser.parse_line(line)
                if ev is not None:
                    self.pipeline.ingest(ev)
            if not self.loop:
                break

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def _main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay a SPECTRE UART capture")
    ap.add_argument("path")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args(argv)
    # Standalone: just parse and print normalized events (no live pipeline).
    parser = Parser("replay")
    with open(args.path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            ev = parser.parse_line(line.rstrip("\n"))
            if ev is not None:
                print(json.dumps(ev.to_public()))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
