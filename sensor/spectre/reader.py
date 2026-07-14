"""Asynchronous UART reader for the ESP32-C5 sniffer boards.

Critical detail proven against the real hardware: the boards auto-reset when the
serial adapter's DTR/RTS lines are asserted on open. Holding **DTR and RTS low**
keeps the board running so it streams continuously. We do this with stdlib
``termios``/``fcntl`` (clearing the modem-control bits via ``TIOCMBIC``) — no
third-party serial dependency required.

Each port is opened non-blocking and registered with the asyncio event loop via
``add_reader``, so reads are fully async and cheap even at ~30 frames/sec/board.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import struct
import termios

from .parser import Parser
from .pipeline import Pipeline

log = logging.getLogger("spectre.reader")

# Linux ioctl constants for clearing modem-control lines.
_TIOCMBIC = 0x5417
_TIOCM_DTR = 0x002
_TIOCM_RTS = 0x004

_BAUD_MAP = {
    9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
    57600: termios.B57600, 115200: termios.B115200, 230400: termios.B230400,
}


def _open_serial(path: str, baud: int) -> int:
    """Open *path*, hold DTR/RTS low, configure raw N-8-1 at *baud*."""
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    speed = _BAUD_MAP.get(baud, termios.B115200)

    # Clear DTR + RTS immediately so the board does not reset.
    fcntl.ioctl(fd, _TIOCMBIC, struct.pack("I", _TIOCM_DTR | _TIOCM_RTS))

    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(fd)
    iflag = 0
    oflag = 0
    lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
    ispeed = ospeed = speed
    cc = list(cc)
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag,
                                            ispeed, ospeed, cc])

    # tcsetattr can re-assert the lines; clear them again.
    fcntl.ioctl(fd, _TIOCMBIC, struct.pack("I", _TIOCM_DTR | _TIOCM_RTS))
    return fd


class SerialReader:
    """Reads one serial port, parses lines, and feeds the pipeline."""

    def __init__(self, path: str, baud: int, pipeline: Pipeline) -> None:
        self.path = path
        self.baud = baud
        self.pipeline = pipeline
        self.sensor_id = os.path.basename(path)  # e.g. "ttyUSB0"
        self.parser = Parser(self.sensor_id)
        self._fd: int | None = None
        self._buf = b""

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._fd = _open_serial(self.path, self.baud)
        loop.add_reader(self._fd, self._on_readable)
        log.info("reader attached to %s (%s baud)", self.path, self.baud)

    def _on_readable(self) -> None:
        assert self._fd is not None
        try:
            chunk = os.read(self._fd, 4096)
        except BlockingIOError:
            return
        except OSError as exc:
            log.error("read error on %s: %s", self.path, exc)
            return
        if not chunk:
            return
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            text = line.decode("utf-8", "replace").rstrip("\r")
            if not text:
                continue
            event = self.parser.parse_line(text)
            if event is not None:
                self.pipeline.ingest(event)

    def stop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._fd is not None:
            with __import__("contextlib").suppress(Exception):
                loop.remove_reader(self._fd)
                os.close(self._fd)
            self._fd = None


def build_readers(ports: list[str], baud: int, pipeline: Pipeline) -> list[SerialReader]:
    return [SerialReader(p.strip(), baud, pipeline) for p in ports if p.strip()]
