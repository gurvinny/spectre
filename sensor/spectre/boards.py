"""Board health and board control for the console.

The boards report themselves through lifecycle lines (``boot``, ``telemetry``,
``channel_sweep_complete``, ``cmd_ack``), all stored in ``board_events``. This
module reduces the newest row of each kind to what an operator checks first:
which firmware and radio plan a board runs, how much it loses, how close its
UART is to the line rate, and the last command sent to it.

Control is off unless ``SPECTRE_BOARD_CONTROL=true``: a command can retune or
reboot a board, which interrupts capture.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from typing import Any, Optional

CONTROL_ENV = "SPECTRE_BOARD_CONTROL"
COMMANDS = ("get_config", "set", "reset_config", "reboot")
CMD_ID_MAX = 16             # the firmware truncates a longer id
UART_BITS_PER_BYTE = 10     # 8N1: start + 8 data + stop

_FIRMWARE_KEYS = ("chip", "fw", "ver", "elf_sha", "reset", "baud", "caps")
_PLAN_KEYS = ("channels", "dwell_ms", "pin", "filter", "dedup", "ap_info_s")
# A boot row older than the boot that telemetry implies (received_at minus
# uptime) by more than this was missed: the board restarted while nothing read
# the port. Covers serial latency and the host clock's jitter.
BOOT_SLACK_S = 5.0
_COUNTER_KEYS = ("rx_total", "emitted", "drop_queue", "drop_short", "drop_dedup",
                 "drop_overflow")


def control_enabled(env: Mapping[str, str] = os.environ) -> bool:
    return env.get(CONTROL_ENV, "").strip().lower() == "true"


def _num(v: Any) -> Optional[float]:
    """A board-supplied number, or None. bool is an int subclass; refuse it."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _ratio(a: Any, b: Any) -> Optional[float]:
    a, b = _num(a), _num(b)
    if a is None or not b:
        return None
    return a / b


def health(boot: Optional[dict], telemetry: Optional[dict], sweep: Optional[dict],
           sweep_newer: bool = False) -> dict:
    """Derived figures from the newest boot, telemetry and sweep payloads.

    Both telemetry and (v2) sweep lines carry the since-boot counters; the
    newer one wins. The original firmware's sweep only has ``total_pkts``,
    its emitted-line count, so loss stays unknown for it.
    """
    boot, tel = boot or {}, telemetry or {}
    sweep = sweep or {}
    counters = tel
    if "rx_total" in sweep and (sweep_newer or "rx_total" not in tel):
        counters = sweep
    rx = _num(counters.get("rx_total"))
    emitted = _num(counters.get("emitted"))
    if emitted is None and rx is None:
        emitted = _num(sweep.get("total_pkts"))
    lost = None
    if rx is not None:
        lost = (_num(counters.get("drop_queue")) or 0) + (_num(counters.get("drop_overflow")) or 0)
    loss_pct = round(100 * lost / rx, 3) if rx else None
    bps = _num(tel.get("uart_bps"))
    uart_load = _ratio(bps * UART_BITS_PER_BYTE if bps is not None else None, boot.get("baud"))
    temp = _num(tel.get("temp_dc"))
    return {
        "rx_total": rx, "emitted": emitted, "lost": lost, "loss_pct": loss_pct,
        "drops": {k: _num(counters.get(k)) for k in _COUNTER_KEYS[2:]},
        "uart_bps": bps, "uart_load": uart_load,
        "queue_fill": _ratio(tel.get("q_hwm"), tel.get("q_size")),
        "heap": _num(tel.get("heap")), "heap_min": _num(tel.get("heap_min")),
        "temp_c": temp / 10 if temp is not None else None,
        "uptime_ms": _num(tel.get("uptime_ms") if tel else sweep.get("uptime_ms")),
    }


def _with_ts(r: Optional[dict]) -> Optional[dict]:
    return dict(r["payload"], received_at=r["received_at"]) if r else None


def summarize(sensor_id: str, latest: Mapping[str, dict], controllable: bool) -> dict:
    """One board's card: *latest* maps each kind to its newest stored row."""
    rows = list(latest.values())
    newest = max(rows, key=lambda r: r["received_at"]) if rows else None
    boot, ack = latest.get("boot"), latest.get("cmd_ack")
    tel, sweep = latest.get("telemetry"), latest.get("channel_sweep_complete")
    boot_p = boot["payload"] if boot else {}

    plan = {k: boot_p.get(k) for k in _PLAN_KEYS}
    if ack and ack["payload"].get("ok") is True and isinstance(ack["payload"].get("config"), dict) \
            and (boot is None or ack["received_at"] >= boot["received_at"]):
        plan.update({k: v for k, v in ack["payload"]["config"].items() if k in _PLAN_KEYS})

    firmware = None
    if boot:
        firmware = {k: boot_p.get(k) for k in _FIRMWARE_KEYS}
        firmware["booted_at"] = boot["received_at"]
    # Telemetry names the running image every 10 s (firmware >= 2.0.3), and its
    # uptime dates the current boot, so a boot line the host never saw cannot
    # leave a stale version on the card.
    tel_p = tel["payload"] if tel else {}
    uptime = _num(tel_p.get("uptime_ms"))
    booted = tel["received_at"] - uptime / 1000 if uptime is not None else None
    boot_missed = bool(boot and booted is not None
                       and booted > boot["received_at"] + BOOT_SLACK_S)
    if isinstance(tel_p.get("ver"), str):
        firmware = dict(firmware or dict.fromkeys(_FIRMWARE_KEYS))
        firmware["ver"] = tel_p["ver"]
        firmware["elf_sha"] = tel_p.get("elf_sha")
        if boot is None or boot_missed:
            firmware["booted_at"] = booted
    if firmware is not None:
        firmware["boot_missed"] = boot_missed

    sweep_newer = bool(sweep and (tel is None or sweep["received_at"] > tel["received_at"]))
    return {
        "sensor_id": sensor_id,
        "band": newest["band"] if newest else None,
        "last_seen": newest["received_at"] if newest else None,
        "controllable": controllable,
        "firmware": firmware,
        "plan": plan,
        "health": health(boot_p, tel["payload"] if tel else None,
                         sweep["payload"] if sweep else None, sweep_newer),
        "last_cmd": _with_ts(latest.get("cmd")),
        "last_ack": _with_ts(ack),
    }


def list_boards(latest_rows: list[dict], controllable: set[str] | Mapping[str, Any]) -> list[dict]:
    """Every board with stored rows or a live command path, sorted by id."""
    by_board: dict[str, dict[str, dict]] = {}
    for r in latest_rows:
        by_board.setdefault(r["sensor_id"], {})[r["kind"]] = r
    ids = sorted(set(by_board) | set(controllable))
    return [summarize(sid, by_board.get(sid, {}), sid in controllable) for sid in ids]


def validate_command(body: Any) -> dict:
    """A command the console may send: a known ``cmd`` and an ``id`` to match
    the ack. The firmware validates every other key itself and acks errors."""
    if not isinstance(body, dict) or body.get("cmd") not in COMMANDS:
        raise ValueError(f"cmd must be one of {', '.join(COMMANDS)}")
    cid = body.get("id")
    if cid is None:
        cid = "c" + secrets.token_hex(4)
    elif not isinstance(cid, str) or not 0 < len(cid) <= CMD_ID_MAX:
        raise ValueError(f"id must be a string of 1-{CMD_ID_MAX} characters")
    out = {"cmd": body["cmd"], "id": cid}
    out.update({k: v for k, v in body.items() if k not in ("cmd", "id")})
    return out
