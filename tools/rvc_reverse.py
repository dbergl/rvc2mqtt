#!/usr/bin/env python3
"""
rvc_reverse.py - RV-C unknown message reverse engineering tool

Modes:
  analyze  Parse UNHANDLED_RVC log files and produce byte-level analysis
           with change timelines. Use --search to scan all log files
           (including full bus trace) for known strings via J1939 TP reassembly.
  monitor  Live curses TUI that tails the unhandled log file in real time.

Usage:
  python3 tools/rvc_reverse.py analyze [LOG_DIR] [--source 9C 9D] [--unknown-only]
  python3 tools/rvc_reverse.py analyze --search "3.0d" "1.6r" "13.6"
  python3 tools/rvc_reverse.py monitor [--log FILE] [--source 9C 9D] [--unknown-only]
"""

import argparse
import ast
import curses
import glob
import os
import string
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

DEFAULT_LOG_DIR = "/opt/coach2mqtt/rvc-logs"
DEFAULT_LOG_FILE = "/opt/coach2mqtt/rvc-logs/UNHANDLED_RVC.log"
ENUM_THRESHOLD = 8      # <= this many unique values → ENUM, else VARIES
NA_VALUE = 0xFF         # RV-C "not available" sentinel


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DgnRecord:
    dgn: str
    source_id: str
    name: str
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    count: int = 0
    payloads: Counter = field(default_factory=Counter)
    # per-byte value history: byte_values[i] = Counter of observed int values
    byte_values: list = field(default_factory=lambda: [Counter() for _ in range(8)])
    # chronological change log: (timestamp, byte_idx, old_val, new_val)
    changes: list = field(default_factory=list)
    # last known byte values (None = not yet seen)
    last_bytes: list = field(default_factory=lambda: [None] * 8)
    # recent timestamps for rate calculation (deque of datetime)
    recent_ts: deque = field(default_factory=lambda: deque(maxlen=500))
    # which bytes recently changed (for TUI highlight), maps byte_idx → float(time.time())
    flash: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def data_to_bytes(data) -> bytes:
    """Convert data field (hex string or integer) to an 8-byte bytes object.

    The rvc decoder stores the raw CAN payload as a little-endian integer when
    the DGN has a single catch-all parameter (e.g. DATA_PACKET, TERMINAL).
    """
    if isinstance(data, str):
        try:
            raw = bytes.fromhex(data)
            return raw.ljust(8, b'\xff')[:8]
        except ValueError:
            return b'\xff' * 8
    if isinstance(data, int):
        try:
            return data.to_bytes(8, 'little')
        except OverflowError:
            return (data & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little')
    return b'\xff' * 8


def data_to_hex(data) -> str:
    """Return uppercase 16-char hex string for data field."""
    return data_to_bytes(data).hex().upper()


def parse_log_line(line: str) -> Optional[tuple]:
    """Return (datetime, dict) or None. Handles both log formats:
    - UNHANDLED_RVC: "2026-03-13 15:19:35 Msg {...}"
    - FULL_BUS_TRACE: "2026-03-13 15:19:35 {...}"
    """
    line = line.strip()
    if not line:
        return None
    try:
        # Try UNHANDLED format first
        parts = line.split(" Msg ", 1)
        if len(parts) == 2:
            ts = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M:%S")
            msg = ast.literal_eval(parts[1].strip())
            if isinstance(msg, dict) and "dgn" in msg:
                return ts, msg
        # Try FULL_BUS_TRACE format
        parts = line.split(" ", 2)
        if len(parts) == 3:
            ts = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S")
            msg = ast.literal_eval(parts[2].strip())
            if isinstance(msg, dict) and "dgn" in msg:
                return ts, msg
    except Exception:
        pass
    return None


def should_include(msg: dict, sources: Optional[list], unknown_only: bool) -> bool:
    if sources and msg.get("source_id", "").upper() not in [s.upper() for s in sources]:
        return False
    if unknown_only and msg.get("decoder_pending") != 1:
        return False
    return True


def update_record(rec: DgnRecord, ts: datetime, data) -> list:
    """
    Incorporate a new message into a DgnRecord.
    data may be a hex string or integer.
    Returns list of byte indices that changed value.
    """
    hex_str = data_to_hex(data)
    new_bytes = list(data_to_bytes(data))

    rec.count += 1
    rec.payloads[hex_str] += 1
    rec.recent_ts.append(ts)
    if rec.first_ts is None:
        rec.first_ts = ts
    rec.last_ts = ts

    changed = []
    for i, val in enumerate(new_bytes):
        rec.byte_values[i][val] += 1
        if rec.last_bytes[i] is None:
            rec.last_bytes[i] = val
        elif rec.last_bytes[i] != val:
            rec.changes.append((ts, i, rec.last_bytes[i], val))
            rec.flash[i] = time.time()
            changed.append(i)
            rec.last_bytes[i] = val

    return changed


def load_logs(log_dir: str, sources: Optional[list], unknown_only: bool) -> dict:
    """Parse all UNHANDLED_RVC.log* files chronologically. Returns dict keyed by (dgn, source_id)."""
    pattern = os.path.join(log_dir, "UNHANDLED_RVC.log*")
    files = sorted(glob.glob(pattern))
    # Put rotated files (oldest) first: .log.2, .log.1, then .log
    rotated = [f for f in files if not f.endswith(".log")]
    rotated.sort(key=lambda f: -int(f.rsplit(".", 1)[-1]) if f.rsplit(".", 1)[-1].isdigit() else 0)
    current = [f for f in files if f.endswith(".log")]
    ordered = rotated + current

    records = {}
    for filepath in ordered:
        try:
            with open(filepath, "r", errors="replace") as fh:
                for line in fh:
                    result = parse_log_line(line)
                    if result is None:
                        continue
                    ts, msg = result
                    if not should_include(msg, sources, unknown_only):
                        continue
                    k = (msg["dgn"], msg["source_id"])
                    if k not in records:
                        records[k] = DgnRecord(
                            dgn=msg["dgn"],
                            source_id=msg["source_id"],
                            name=msg.get("name", f"UNKNOWN-{msg['dgn']}"),
                        )
                    update_record(records[k], ts, msg.get("data", "FFFFFFFFFFFFFFFF"))
        except OSError as e:
            print(f"Warning: could not read {filepath}: {e}")

    return records


# ---------------------------------------------------------------------------
# Byte analysis helpers
# ---------------------------------------------------------------------------

def classify_byte(counter: Counter) -> str:
    """Return human-readable classification for a byte position."""
    if not counter:
        return "?"
    values = set(counter.keys())
    if values == {NA_VALUE}:
        return "N/A (FF)"
    non_na = {v for v in values if v != NA_VALUE}
    if not non_na:
        return "N/A (FF)"
    if len(non_na) == 1:
        v = next(iter(non_na))
        if NA_VALUE in values:
            return f"CONST {v:02X} (or FF)"
        return f"CONST {v:02X}"
    if len(non_na) <= ENUM_THRESHOLD:
        vals_str = ", ".join(f"{v:02X}" for v in sorted(non_na))
        return f"ENUM  {{{vals_str}}}"
    lo = min(non_na)
    hi = max(non_na)
    return f"VARIES {lo:02X}–{hi:02X}  ({len(non_na)} unique)"


def is_printable_ascii(data_hex: str) -> Optional[str]:
    """If bytes contain mostly printable ASCII, return annotated string; else None."""
    try:
        raw = bytes.fromhex(data_hex)
        printable_count = sum(1 for b in raw if 0x20 <= b < 0x7F)
        if printable_count >= 4:
            return ''.join(chr(b) if 0x20 <= b < 0x7F else f'[{b:02X}]' for b in raw)
    except Exception:
        pass
    return None


def calc_rate(rec: DgnRecord) -> float:
    """Messages per minute over the full log period."""
    if rec.first_ts is None or rec.last_ts is None:
        return 0.0
    span = (rec.last_ts - rec.first_ts).total_seconds()
    if span < 1:
        return 0.0
    return rec.count / span * 60


# ---------------------------------------------------------------------------
# J1939 Transport Protocol reassembly
# ---------------------------------------------------------------------------

def reassemble_j1939_tp(log_dir: str) -> list:
    """
    Scan all log files (UNHANDLED + FULL_BUS_TRACE) and reassemble J1939 TP
    multi-packet messages.

    Returns list of dicts:
        {src, pgn, total_bytes, data: bytes, ascii: str, ts: datetime}
    """
    # Collect all log files
    patterns = [
        os.path.join(log_dir, "UNHANDLED_RVC.log*"),
        os.path.join(log_dir, "RVC_FULL_BUS_TRACE.log*"),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    files = sorted(set(files))

    # sessions[src] = {total, pgn, packets: {seq: bytes(7)}, ts}
    sessions = {}
    completed = []

    for filepath in files:
        try:
            fh = open(filepath, "r", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                result = parse_log_line(line)
                if not result:
                    continue
                ts, msg = result
                dgn = msg.get("dgn", "")
                src = msg.get("source_id", "?")

                if dgn == "0ECFF":  # INITIAL_PACKET (TP.CM BAM)
                    raw = data_to_bytes(msg.get("data"))
                    if raw[0] == 0x20:  # BAM control byte
                        total = int.from_bytes(raw[1:3], "little")
                        n_packets = raw[3]
                        pgn = int.from_bytes(raw[5:8], "little")
                        sessions[src] = {
                            "total": total,
                            "pgn": pgn,
                            "packets": {},
                            "ts": ts,
                        }

                elif dgn == "0EBFF" and src in sessions:  # DATA_PACKET (TP.DT)
                    raw = data_to_bytes(msg.get("data"))
                    # packet_number is already decoded as a separate field;
                    # the data integer represents the 7 payload bytes (LE).
                    seq = msg.get("packet_number", raw[0])
                    payload = raw[:7]  # 7 payload bytes
                    sess = sessions[src]
                    sess["packets"][seq] = payload
                    # Check if all packets received
                    expected = (sess["total"] + 6) // 7  # ceil(total/7)
                    if len(sess["packets"]) >= expected:
                        assembled = b""
                        for i in range(1, expected + 1):
                            assembled += sess["packets"].get(i, b"\xff" * 7)
                        assembled = assembled[: sess["total"]]
                        ascii_str = "".join(
                            chr(b) if 0x20 <= b < 0x7F else f"[{b:02X}]"
                            for b in assembled
                        )
                        completed.append({
                            "src": src,
                            "pgn": sess["pgn"],
                            "total_bytes": sess["total"],
                            "data": assembled,
                            "ascii": ascii_str,
                            "ts": sess["ts"],
                        })
                        del sessions[src]

    return completed


# ---------------------------------------------------------------------------
# String search across all payloads + TP sessions
# ---------------------------------------------------------------------------

def search_strings(log_dir: str, targets: list):
    """Search for target strings in all log payloads and reassembled TP messages."""
    target_bytes = [t.encode("utf-8") for t in targets]

    print(f"Searching for: {targets}")
    print()

    # 1. Search raw payloads in all log files
    patterns = [
        os.path.join(log_dir, "UNHANDLED_RVC.log*"),
        os.path.join(log_dir, "RVC_FULL_BUS_TRACE.log*"),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    files = sorted(set(files))

    hits = []
    for filepath in files:
        try:
            fh = open(filepath, "r", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                result = parse_log_line(line)
                if not result:
                    continue
                ts, msg = result
                raw = data_to_bytes(msg.get("data"))
                for i, tb in enumerate(target_bytes):
                    if tb in raw:
                        hits.append({
                            "type": "single",
                            "ts": ts,
                            "dgn": msg.get("dgn", "?"),
                            "src": msg.get("source_id", "?"),
                            "name": msg.get("name", "?"),
                            "data": raw,
                            "match": targets[i],
                        })

    if hits:
        print(f"  Direct payload matches ({len(hits)} hits):")
        seen = set()
        for h in hits:
            key = (h["dgn"], h["src"], h["data"].hex())
            if key in seen:
                continue
            seen.add(key)
            ascii_str = "".join(
                chr(b) if 0x20 <= b < 0x7F else f"[{b:02X}]" for b in h["data"]
            )
            print(f"    DGN={h['dgn']} src={h['src']} name={h['name']}")
            print(f"      {h['data'].hex().upper()}  |  {ascii_str}")
            print(f"      Match: {h['match']!r}")
    else:
        print("  Direct payload matches: none")

    print()

    # 2. Search reassembled TP messages
    print("  Scanning J1939 TP multi-packet messages...")
    sessions = reassemble_j1939_tp(log_dir)
    if not sessions:
        print("  No TP sessions found.")
    else:
        tp_hits = []
        for sess in sessions:
            for i, tb in enumerate(target_bytes):
                if tb in sess["data"]:
                    tp_hits.append({**sess, "match": targets[i]})
                    break
        if tp_hits:
            seen_tp = set()
            for h in tp_hits:
                key = (h["src"], h["pgn"], h["data"].hex())
                if key in seen_tp:
                    continue
                seen_tp.add(key)
                print(f"    src={h['src']} PGN=0x{h['pgn']:05X} ({h['total_bytes']}B)  {h['ts']}")
                print(f"      {h['ascii']}")
                print(f"      Match: {h['match']!r}")
        else:
            matches = [f"src={s['src']} PGN=0x{s['pgn']:05X}" for s in sessions[:5]]
            print(f"  No target strings found in {len(sessions)} TP sessions.")
            print(f"  TP sessions found: {', '.join(matches)}")
            print()
            print("  All reassembled TP messages:")
            seen_tp = set()
            for sess in sessions:
                key = (sess["src"], sess["pgn"], sess["data"][:20].hex())
                if key in seen_tp:
                    continue
                seen_tp.add(key)
                print(f"    src={sess['src']} PGN=0x{sess['pgn']:05X} ({sess['total_bytes']}B):")
                print(f"      {sess['ascii'][:120]}")


# ---------------------------------------------------------------------------
# analyze subcommand
# ---------------------------------------------------------------------------

def cmd_analyze(args):
    log_dir = args.log_dir or DEFAULT_LOG_DIR

    # String search mode
    if args.search:
        search_strings(log_dir, args.search)
        return

    sources = [s.upper() for s in args.source] if args.source else None

    print(f"Loading logs from: {log_dir}")
    print(f"Filters — source: {sources or 'all'}  unknown-only: {args.unknown_only}")
    print()

    records = load_logs(log_dir, sources, args.unknown_only)
    if not records:
        print("No matching messages found.")
        return

    sorted_recs = sorted(records.values(), key=lambda r: -r.count)

    total = sum(r.count for r in sorted_recs)
    print(f"Total matching messages: {total:,}  |  Unique DGNs: {len(sorted_recs)}")
    print()

    for rec in sorted_recs:
        _print_record(rec, args.max_changes)


def _print_record(rec: DgnRecord, max_changes: int = 50):
    W = 68
    print("=" * W)
    span_str = ""
    if rec.first_ts and rec.last_ts:
        span_str = f"  |  Period: {rec.first_ts.strftime('%H:%M:%S')} → {rec.last_ts.strftime('%H:%M:%S')}"
    rate = calc_rate(rec)
    print(f"DGN: {rec.dgn}  src={rec.source_id}  name={rec.name}")
    print(f"Messages: {rec.count:,}{span_str}  |  Rate: ~{rate:.0f}/min  |  Unique payloads: {len(rec.payloads)}")
    print()

    # Byte analysis
    print("  Byte analysis:")
    for i in range(8):
        cls = classify_byte(rec.byte_values[i])
        changed = any(c[1] == i for c in rec.changes)
        flag = "  <-- changes!" if changed else ""
        print(f"    B{i}: {cls}{flag}")

    # Printable ASCII check on all unique payloads
    ascii_payloads = []
    for payload_hex, cnt in rec.payloads.most_common(10):
        asc = is_printable_ascii(payload_hex)
        if asc:
            ascii_payloads.append((cnt, payload_hex, asc))
    if ascii_payloads:
        print(f"\n  ASCII-readable payloads:")
        for cnt, phex, asc in ascii_payloads:
            print(f"    [{cnt:>5}x] {phex}  →  {asc}")

    # Change timeline
    changed_bytes = sorted({c[1] for c in rec.changes})
    if not changed_bytes:
        print("\n  Change timeline: (no changes observed)")
    else:
        print(f"\n  Change timeline (B{', B'.join(str(b) for b in changed_bytes)}):")
        hdr = "  {:<22}".format("Time")
        for b in changed_bytes:
            hdr += f" B{b}  "
        print(hdr)

        # First-seen row
        first_row = "  {:<22}".format(
            rec.first_ts.strftime("%H:%M:%S.000") if rec.first_ts else "?"
        )
        for b in changed_bytes:
            first_change = next((c for c in rec.changes if c[1] == b), None)
            first_val = first_change[2] if first_change else next(iter(rec.byte_values[b]), None)
            first_row += f" {first_val:02X}   " if first_val is not None else "  ?  "
        print(first_row + "  (first seen)")

        shown = 0
        for ts, bidx, old_val, new_val in rec.changes:
            if shown >= max_changes:
                remaining = len(rec.changes) - max_changes
                print(f"  ... ({remaining} more changes)")
                break
            row = "  {:<22}".format(ts.strftime("%H:%M:%S"))
            for b in changed_bytes:
                if b == bidx:
                    row += f" {new_val:02X}   "
                else:
                    row += " --   "
            print(row)
            shown += 1

    print()


# ---------------------------------------------------------------------------
# monitor subcommand (curses TUI)
# ---------------------------------------------------------------------------

def cmd_monitor(args):
    log_file = args.log or DEFAULT_LOG_FILE
    sources = [s.upper() for s in args.source] if args.source else None
    unknown_only = args.unknown_only
    curses.wrapper(_monitor_main, log_file, sources, unknown_only)


def _monitor_main(stdscr, log_file: str, sources, unknown_only: bool):
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)    # header
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)   # selected row
    curses.init_pair(3, curses.COLOR_YELLOW, -1)                  # changed highlight
    curses.init_pair(4, curses.COLOR_GREEN, -1)                   # rate/count

    records = {}
    order = []
    selected = 0
    scroll_top = 0

    try:
        fh = open(log_file, "r", errors="replace")
        fh.seek(0, 2)
    except OSError as e:
        stdscr.addstr(0, 0, f"Cannot open {log_file}: {e}")
        stdscr.refresh()
        time.sleep(3)
        return

    POLL_INTERVAL = 0.2

    while True:
        # Read new log lines
        while True:
            line = fh.readline()
            if not line:
                break
            result = parse_log_line(line)
            if result is None:
                continue
            ts, msg = result
            if not should_include(msg, sources, unknown_only):
                continue
            k = (msg["dgn"], msg["source_id"])
            if k not in records:
                records[k] = DgnRecord(
                    dgn=msg["dgn"],
                    source_id=msg["source_id"],
                    name=msg.get("name", f"UNKNOWN-{msg['dgn']}"),
                )
                order.append(k)
                if selected >= len(order):
                    selected = len(order) - 1
            update_record(records[k], ts, msg.get("data", "FFFFFFFFFFFFFFFF"))

        # Handle input
        key_press = stdscr.getch()
        if key_press == ord("q"):
            break
        elif key_press == curses.KEY_DOWN:
            if selected < len(order) - 1:
                selected += 1
            if selected >= scroll_top + _top_panel_rows(stdscr) - 2:
                scroll_top += 1
        elif key_press == curses.KEY_UP:
            if selected > 0:
                selected -= 1
            if selected < scroll_top:
                scroll_top = selected
        elif key_press == ord("r"):
            records.clear()
            order.clear()
            selected = 0
            scroll_top = 0
        elif key_press == ord("f"):
            unknown_only = not unknown_only

        _render(stdscr, records, order, selected, scroll_top, log_file, sources, unknown_only)
        time.sleep(POLL_INTERVAL)

    fh.close()


def _top_panel_rows(stdscr) -> int:
    h, _ = stdscr.getmaxyx()
    return max(4, h // 2)


def _render(stdscr, records, order, selected, scroll_top, log_file, sources, unknown_only):
    h, w = stdscr.getmaxyx()
    stdscr.erase()
    top_rows = _top_panel_rows(stdscr)

    title = f" RV-C Reverse Eng Monitor  |  {os.path.basename(log_file)}"
    if unknown_only:
        title += "  [unknown-only]"
    _draw_header(stdscr, 0, w, title, curses.color_pair(1))

    hdr = f"{'DGN':<6} {'SRC':<4} {'Count':<8} {'Rate':>7}  {'Last payload':<23} {'Last change'}"
    try:
        stdscr.addstr(1, 0, hdr[:w-1], curses.A_BOLD)
    except curses.error:
        pass

    visible = top_rows - 3
    now = time.time()
    for rel_idx in range(visible):
        abs_idx = scroll_top + rel_idx
        row_y = rel_idx + 2
        if abs_idx >= len(order):
            break
        k = order[abs_idx]
        rec = records[k]
        rate = calc_rate(rec)
        lbytes = rec.last_bytes if rec.last_bytes[0] is not None else [0] * 8
        payload_str = " ".join(f"{b:02X}" for b in lbytes)[:23]

        if rec.changes:
            ts, bidx, old_v, new_v = rec.changes[-1]
            chg = f"B{bidx}:{old_v:02X}→{new_v:02X} {ts.strftime('%H:%M:%S')}"
        else:
            chg = "(no changes)"

        row_str = f"{rec.dgn:<6} {rec.source_id:<4} {rec.count:<8,} {rate:>6.0f}/m  {payload_str:<23} {chg}"
        attr = curses.color_pair(2) if abs_idx == selected else 0
        if any(now - t < 1.0 for t in rec.flash.values()):
            attr = curses.color_pair(3) | curses.A_BOLD
        prefix = ">" if abs_idx == selected else " "
        try:
            stdscr.addstr(row_y, 0, (prefix + row_str)[:w-1], attr)
        except curses.error:
            pass

    try:
        stdscr.addstr(top_rows - 1, 0, "─" * (w - 1))
    except curses.error:
        pass

    # Detail panel
    det_start = top_rows
    if order and 0 <= selected < len(order):
        rec = records[order[selected]]
        _draw_header(stdscr, det_start, w,
                     f" {rec.dgn} / {rec.source_id}  {rec.name} ",
                     curses.color_pair(1))

        row_y = det_start + 1
        for i in range(8):
            if row_y >= h - 1:
                break
            cls = classify_byte(rec.byte_values[i])
            byte_changes = [(ts, o, n) for ts, bidx, o, n in rec.changes if bidx == i]
            if byte_changes:
                recent = byte_changes[-3:]
                recent_str = "  ".join(
                    f"{o:02X}→{n:02X} {ts.strftime('%H:%M:%S')}"
                    for ts, o, n in reversed(recent)
                )
            else:
                recent_str = "(no changes)"
            ln = f"  B{i}  {cls:<30} {recent_str}"
            attr = 0
            if i in rec.flash and now - rec.flash[i] < 1.0:
                attr = curses.color_pair(3) | curses.A_BOLD
            try:
                stdscr.addstr(row_y, 0, ln[:w-1], attr)
            except curses.error:
                pass
            row_y += 1

    footer = " [↑↓]select  [q]quit  [r]reset  [f]toggle-filter "
    try:
        stdscr.addstr(h - 1, 0, footer[:w-1], curses.color_pair(1))
    except curses.error:
        pass

    stdscr.refresh()


def _draw_header(stdscr, y: int, w: int, text: str, attr):
    line = text.ljust(w - 1)[:w-1]
    try:
        stdscr.addstr(y, 0, line, attr)
    except curses.error:
        pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Reverse-engineer unknown RV-C CAN bus messages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # -- analyze --
    p_analyze = sub.add_parser("analyze", help="Offline analysis of log files")
    p_analyze.add_argument(
        "log_dir",
        nargs="?",
        default=DEFAULT_LOG_DIR,
        help=f"Directory containing log files (default: {DEFAULT_LOG_DIR})",
    )
    p_analyze.add_argument(
        "--source", "-s",
        nargs="+",
        metavar="SRC",
        help="Filter to specific source IDs (e.g. 9C 9D 9F)",
    )
    p_analyze.add_argument(
        "--unknown-only", "-u",
        action="store_true",
        help="Only include truly unknown DGNs (decoder_pending=1)",
    )
    p_analyze.add_argument(
        "--max-changes",
        type=int,
        default=50,
        metavar="N",
        help="Max change events to show per DGN (default: 50)",
    )
    p_analyze.add_argument(
        "--search",
        nargs="+",
        metavar="STR",
        help="Search all log files and TP sessions for these strings "
             "(e.g. --search '3.0d' '1.6r' '13.6' 'G12')",
    )

    # -- monitor --
    p_monitor = sub.add_parser("monitor", help="Live curses TUI tailing the log file")
    p_monitor.add_argument(
        "--log", "-l",
        default=DEFAULT_LOG_FILE,
        help=f"Log file to tail (default: {DEFAULT_LOG_FILE})",
    )
    p_monitor.add_argument(
        "--source", "-s",
        nargs="+",
        metavar="SRC",
        help="Filter to specific source IDs (e.g. 9C 9D 9F)",
    )
    p_monitor.add_argument(
        "--unknown-only", "-u",
        action="store_true",
        help="Only include truly unknown DGNs (decoder_pending=1)",
    )

    args = parser.parse_args()
    if args.cmd == "analyze":
        cmd_analyze(args)
    elif args.cmd == "monitor":
        cmd_monitor(args)


if __name__ == "__main__":
    main()
