#!/usr/bin/env python3
"""Flash a SPECTRE sniffer board and prove it came up as intended.

A board that accepted an image is not yet a board running it with the right
plan. So after flashing, this tool talks to the firmware itself:

1. reads the version and ELF sha256 out of the image's app descriptor and
   checks every image file against ``SHA256SUMS`` when the build has one,
2. writes the image with esptool (``uvx``, pinned, 460800 baud), without the
   flasher stub when the build's ``flasher_args.json`` says so,
3. sets the band by command, restores that band's default plan (unless
   ``--keep-config``), and reboots the board by command,
4. waits for the fresh ``boot`` line and checks firmware name, version, ELF
   sha, band, baud and plan against what was flashed and acknowledged,
5. waits for ``sniffer_started``, then soaks for a few seconds: every line
   must parse and frame ``seq`` must not skip (a console log spliced into a
   data line shows up exactly like that),
6. prints a JSON report with the image sha256s on stdout (esptool's own
   output goes to stderr).

Any mismatch exits non-zero. Stop the sensor first: two readers on one port
each see half the lines.

Usage:
  python3 firmware/flash.py --port /dev/ttyUSB0 --band 2.4GHz
  python3 firmware/flash.py --port /dev/ttyUSB1 --band 5GHz
  python3 firmware/flash.py --port /dev/ttyUSB0 --band 2.4GHz --verify-only

Standard library only; esptool is fetched by ``uvx``.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import select
import struct
import subprocess
import sys
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BUILD = HERE / "spectre-sniffer" / "build"
APP_BIN = "spectre-sniffer.bin"
FW_NAME = "spectre-sniffer"
BAUD = 460800
ESPTOOL = "esptool==5.6.0"
BANDS = ("2.4GHz", "5GHz")
# The board prints CONFIG_APP_RETRIEVE_LEN_ELF_SHA hex chars of the ELF sha;
# fewer than this proves too little to count as a match.
MIN_SHA_CHARS = 8
SETTLE_S = 1.5
ACK_TIMEOUT_S = 5.0
BOOT_TIMEOUT_S = 15.0
SOAK_S = 10.0

_IMAGE_MAGIC = 0xE9
_DESC_MAGIC = 0xABCD5432
# esp_image_header_t (24 B) + the first segment header (8 B)
_DESC_OFFSET = 32
_TAG = "wifi_sniffer: "

_TIOCMBIC = 0x5417
_TIOCM_DTR = 0x002
_TIOCM_RTS = 0x004
_SPEEDS = {115200: termios.B115200, 460800: termios.B460800, 921600: termios.B921600}


class FlashError(Exception):
    """The board did not end up running the image with the intended plan."""


@dataclass
class AppDesc:
    version: str
    project: str
    idf: str
    elf_sha256: str


@dataclass
class Image:
    build: Path
    desc: AppDesc
    options: list[str]
    parts: list[tuple[str, str]]
    sha256: dict[str, str] = field(default_factory=dict)
    stub: bool = True


# ---- image ------------------------------------------------------------------

def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def read_app_desc(data: bytes) -> AppDesc:
    """Decode esp_app_desc_t from the start of an app image."""
    if len(data) < _DESC_OFFSET + 176 or data[0] != _IMAGE_MAGIC:
        raise FlashError("not an ESP app image")
    d = data[_DESC_OFFSET:_DESC_OFFSET + 176]
    if struct.unpack_from("<I", d, 0)[0] != _DESC_MAGIC:
        raise FlashError("app descriptor not found")
    return AppDesc(version=_cstr(d[16:48]), project=_cstr(d[48:80]),
                   idf=_cstr(d[112:144]), elf_sha256=d[144:176].hex())


def parse_flash_args(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Split ESP-IDF's ``flash_args`` into esptool options and (offset, file)."""
    options: list[str] = []
    parts: list[tuple[str, str]] = []
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        if words[0].startswith("--"):
            # esptool 5 spells these with dashes; IDF still writes underscores.
            options += [w.replace("_", "-") if w.startswith("--") else w for w in words]
        elif len(words) == 2 and words[0].startswith("0x"):
            parts.append((words[0], words[1]))
        else:
            raise FlashError(f"unexpected flash_args line: {line!r}")
    if not parts:
        raise FlashError("flash_args lists no images")
    return options, parts


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_image(build: Path) -> Image:
    """Load a build dir (local ``idf.py build`` or the CI artifact)."""
    args = build / "flash_args"
    if not args.is_file():
        raise FlashError(f"{args} not found: build the firmware first")
    options, parts = parse_flash_args(args.read_text())
    sums: dict[str, str] = {}
    for _, rel in parts:
        path = build / rel
        if not path.is_file():
            raise FlashError(f"{path} not found")
        sums[rel] = _sha256(path)
    recorded = build / "SHA256SUMS"
    if recorded.is_file():
        for line in recorded.read_text().splitlines():
            if not line.strip():
                continue
            digest, rel = line.split(maxsplit=1)
            rel = rel.lstrip("*")
            if rel in sums and sums[rel] != digest:
                raise FlashError(f"{rel} does not match SHA256SUMS")
    app = [rel for _, rel in parts if Path(rel).name == APP_BIN]
    if len(app) != 1:
        raise FlashError(f"flash_args does not list {APP_BIN}")
    desc = read_app_desc((build / app[0]).read_bytes())
    if desc.project != FW_NAME:
        raise FlashError(f"image is {desc.project!r}, not {FW_NAME}")
    # IDF records whether this target may use esptool's flasher stub (it
    # disables it for chips still in bring-up); follow the build, not a guess.
    stub = True
    extra = build / "flasher_args.json"
    if extra.is_file():
        stub = json.loads(extra.read_text()).get("extra_esptool_args", {}).get("stub") is not False
    return Image(build=build, desc=desc, options=options, parts=parts, sha256=sums,
                 stub=stub)


def esptool_argv(port: str, image: Image, baud: int = BAUD,
                 esptool: str = ESPTOOL) -> list[str]:
    argv = ["uvx", "--from", esptool, "esptool", "--chip", "esp32c5",
            "--port", port, "--baud", str(baud),
            "--before", "default-reset", "--after", "hard-reset",
            *([] if image.stub else ["--no-stub"]),
            "write-flash", *image.options]
    for offset, rel in image.parts:
        argv += [offset, str(image.build / rel)]
    return argv


# ---- lines ------------------------------------------------------------------

def parse_line(text: str) -> dict | None:
    """The JSON object of one firmware line, or None for anything else."""
    at = text.find(_TAG)
    if at < 0:
        return None
    try:
        obj = json.loads(text[at + len(_TAG):])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def check_boot(boot: dict, desc: AppDesc, band: str, plan: dict | None,
               baud: int = BAUD) -> list[str]:
    """Every way *boot* differs from what was flashed and configured."""
    problems = []
    if boot.get("fw") != FW_NAME:
        problems.append(f"fw is {boot.get('fw')!r}, expected {FW_NAME!r}")
    if boot.get("ver") != desc.version:
        problems.append(f"version is {boot.get('ver')!r}, image has {desc.version!r}")
    sha = boot.get("elf_sha")
    if not isinstance(sha, str) or len(sha) < MIN_SHA_CHARS:
        problems.append(f"elf_sha {sha!r} is too short to identify the image")
    elif not desc.elf_sha256.startswith(sha.lower()):
        problems.append(f"elf_sha {sha} is not the flashed image ({desc.elf_sha256[:16]}...)")
    if boot.get("band") != band:
        problems.append(f"band is {boot.get('band')!r}, expected {band!r}")
    if boot.get("baud") != baud:
        problems.append(f"baud is {boot.get('baud')!r}, expected {baud}")
    for key, want in (plan or {}).items():
        if key != "band" and boot.get(key) != want:
            problems.append(f"{key} is {boot.get(key)!r}, acknowledged {want!r}")
    return problems


# ---- serial -----------------------------------------------------------------

def open_port(path: str, baud: int = BAUD) -> int:
    """Open *path* raw N-8-1 with DTR/RTS held low, so opening does not reset."""
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, _TIOCMBIC, struct.pack("I", _TIOCM_DTR | _TIOCM_RTS))
        attrs = termios.tcgetattr(fd)
        cc = list(attrs[6])
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, [
            0, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0,
            _SPEEDS[baud], _SPEEDS[baud], cc])
        fcntl.ioctl(fd, _TIOCMBIC, struct.pack("I", _TIOCM_DTR | _TIOCM_RTS))
    except BaseException:
        os.close(fd)
        raise
    return fd


class SerialLink:
    """Line-oriented access to an open port."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self._buf = b""
        self.clock = time.monotonic

    def readline(self, timeout: float) -> str | None:
        deadline = self.clock() + timeout
        while b"\n" not in self._buf:
            left = deadline - self.clock()
            if left <= 0:
                return None
            ready, _, _ = select.select([self.fd], [], [], left)
            if ready:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    return None
                self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", "replace").rstrip("\r")

    def send(self, obj: dict) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode() + b"\n"
        while data:
            select.select([], [self.fd], [], 1.0)
            data = data[os.write(self.fd, data):]


# ---- session ----------------------------------------------------------------

def wait_for(link, match, timeout: float) -> dict | None:
    """The first parsed line for which ``match(obj)`` holds, or None."""
    deadline = link.clock() + timeout
    while True:
        left = deadline - link.clock()
        if left <= 0:
            return None
        text = link.readline(left)
        if text is None:
            return None
        obj = parse_line(text)
        if obj is not None and match(obj):
            return obj


def command(link, cmd: dict, cid: str, timeout: float = ACK_TIMEOUT_S) -> dict:
    """Send *cmd* and return its successful ack; raise on silence or ok:false."""
    link.send({**cmd, "id": cid})
    ack = wait_for(link, lambda o: o.get("event") == "cmd_ack" and o.get("id") == cid,
                   timeout)
    if ack is None:
        raise FlashError(f"no ack for {cmd['cmd']} within {timeout:.0f} s")
    if ack.get("ok") is not True:
        raise FlashError(f"{cmd['cmd']} rejected: {ack.get('err')!r}")
    return ack


def soak(link, seconds: float) -> dict:
    """Read for *seconds*: count lines that do not parse and frame seq skips."""
    lines = frames = bad = gaps = 0
    last = None
    deadline = link.clock() + seconds
    while True:
        left = deadline - link.clock()
        if left <= 0:
            break
        text = link.readline(left)
        if text is None:
            break
        if not text.strip():
            continue
        lines += 1
        obj = parse_line(text)
        if obj is None:
            bad += 1
            continue
        seq = obj.get("seq")
        if isinstance(seq, int) and "type" in obj:
            frames += 1
            if last is not None and seq != last + 1:
                gaps += 1
            last = seq
    return {"seconds": seconds, "lines": lines, "frames": frames,
            "bad_lines": bad, "seq_gaps": gaps}


def configure_and_verify(link, desc: AppDesc, band: str, keep_config: bool = False,
                         settle: float = SETTLE_S,
                         boot_timeout: float = BOOT_TIMEOUT_S,
                         soak_s: float = SOAK_S) -> dict:
    """Set the band (and default plan), reboot, and check the new boot line."""
    if band not in BANDS:
        raise FlashError(f"band must be one of {', '.join(BANDS)}")
    # Opening the port can still reset some boards; let that boot finish.
    wait_for(link, lambda o: False, settle)
    ack = command(link, {"cmd": "set", "band": band}, "fl-band")
    if ack.get("config", {}).get("band") != band:
        raise FlashError(f"board acknowledged band {ack.get('config', {}).get('band')!r}")
    if not keep_config:
        ack = command(link, {"cmd": "reset_config"}, "fl-reset")
    plan = ack.get("config")
    if not isinstance(plan, dict) or plan.get("band") != band:
        raise FlashError("board did not report its plan")
    command(link, {"cmd": "reboot"}, "fl-reboot")
    boot = wait_for(link, lambda o: o.get("event") == "boot", boot_timeout)
    if boot is None:
        raise FlashError(f"no boot line within {boot_timeout:.0f} s of the reboot")
    problems = check_boot(boot, desc, band, plan)
    if problems:
        raise FlashError("; ".join(problems))
    if wait_for(link, lambda o: o.get("event") == "sniffer_started", boot_timeout) is None:
        raise FlashError("booted, but the sniffer never started")
    result = {"band": band, "plan": plan, "reset": boot.get("reset")}
    if soak_s > 0:
        result["soak"] = s = soak(link, soak_s)
        if s["bad_lines"] or s["seq_gaps"]:
            raise FlashError(f"soak: {s['bad_lines']} unparseable lines, "
                             f"{s['seq_gaps']} seq gaps in {soak_s:.0f} s")
    return result


def report(port: str, image: Image, result: dict, flashed: bool) -> dict:
    return {"port": port, "flashed": flashed, "version": image.desc.version,
            "idf": image.desc.idf, "elf_sha256": image.desc.elf_sha256,
            "image_sha256": image.sha256, **result}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--band", required=True, choices=BANDS)
    ap.add_argument("--build", type=Path, default=DEFAULT_BUILD,
                    help="dir with flash_args (local build or the CI artifact)")
    ap.add_argument("--verify-only", action="store_true",
                    help="do not flash; configure and check the running image")
    ap.add_argument("--keep-config", action="store_true",
                    help="keep the board's channel plan instead of the band defaults")
    ap.add_argument("--soak", type=float, default=SOAK_S,
                    help="seconds of clean output required after start (0 = skip)")
    args = ap.parse_args(argv)
    try:
        image = load_image(args.build)
        if not args.verify_only:
            subprocess.run(esptool_argv(args.port, image), check=True, stdout=sys.stderr)
        fd = open_port(args.port)
        try:
            result = configure_and_verify(SerialLink(fd), image.desc, args.band,
                                          keep_config=args.keep_config,
                                          soak_s=args.soak)
        finally:
            os.close(fd)
    except (FlashError, OSError, subprocess.CalledProcessError) as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(json.dumps(report(args.port, image, result, not args.verify_only), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
