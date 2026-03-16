#!/usr/bin/env python3
"""
can_monitor.py — Live CAN ID Monitor TUI

Watches all instances broadcasting on a single CAN arbitration ID, with
per-cell flash highlighting when byte values change. Useful for reverse-
engineering unknown RV-C DGNs.

Usage:
    python3 tools/can_monitor.py [--interface can_rvc] [--can-id 0x195FCE9C] [--log-file changes.csv]
"""

import argparse
import curses
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import can
except ImportError:
    print("python-can not installed. Run: pip install python-can")
    raise


FLASH_DURATION = 2.5   # seconds a changed cell stays highlighted
POLL_INTERVAL  = 0.1   # 10 Hz main loop


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class InstanceRecord:
    instance: int
    last_bytes: list          # 7 elements: bytes 1-7
    flash: dict               # byte_idx (0-6) → (timestamp, old_val, new_val)
    last_seen: float
    count: int
    note: str = ""


# ---------------------------------------------------------------------------
# Background CAN reader thread
# ---------------------------------------------------------------------------

class CANReaderThread(threading.Thread):
    def __init__(self, interface: str, rx_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.interface  = interface
        self.rx_queue   = rx_queue
        self.stop_event = stop_event
        self.error: Optional[Exception] = None

    def run(self):
        try:
            bus = can.interface.Bus(channel=self.interface, interface="socketcan")
        except Exception as e:
            self.error = e
            return
        try:
            while not self.stop_event.is_set():
                msg = bus.recv(0.25)
                if msg is not None and not msg.is_error_frame:
                    self.rx_queue.put(msg)
        finally:
            bus.shutdown()


# ---------------------------------------------------------------------------
# Change log
# ---------------------------------------------------------------------------

def open_log_file(path: str):
    """Open CSV log file in append mode; write header if empty."""
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    fh = open(path, "a", buffering=1)
    if is_new:
        fh.write("timestamp_iso,instance_hex,byte_idx,old_hex,new_hex\n")
    return fh


def log_change(fh, instance: int, byte_idx: int, old_val: int, new_val: int):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"
    fh.write(f"{ts},{instance:02X},{byte_idx},{old_val:02X},{new_val:02X}\n")


# ---------------------------------------------------------------------------
# TUI helpers
# ---------------------------------------------------------------------------

def _edit_note(stdscr, h: int, w: int, prompt: str, current: str) -> Optional[str]:
    """Modal inline text editor rendered in the footer row.
    Returns the new string on Enter, or None if cancelled with Esc."""
    curses.curs_set(1)
    stdscr.nodelay(False)   # block during edit
    cp_header = curses.color_pair(1)
    text = list(current)

    try:
        while True:
            display = "".join(text)
            bar = f" {prompt}: {display}"
            padded = bar.ljust(w - 1)[:w - 1]
            try:
                stdscr.addstr(h - 1, 0, padded, cp_header)
                # Place cursor right after typed text
                cursor_col = min(len(bar), w - 2)
                stdscr.move(h - 1, cursor_col)
            except curses.error:
                pass
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                return "".join(text)
            elif key == 27:          # Esc — cancel
                return None
            elif key in (curses.KEY_BACKSPACE, 127, ord("\b")):
                if text:
                    text.pop()
            elif 32 <= key <= 126:   # printable ASCII
                text.append(chr(key))
    finally:
        curses.curs_set(0)
        stdscr.nodelay(True)


def _draw_bar(stdscr, row: int, w: int, text: str, attr):
    try:
        padded = text.ljust(w)[:w - 1]
        stdscr.addstr(row, 0, padded, attr)
    except curses.error:
        pass


def _safe_addstr(stdscr, row: int, col: int, text: str, attr=0):
    h, w = stdscr.getmaxyx()
    if row >= h - 1 or col >= w - 1:
        return
    avail = w - col - 1
    try:
        stdscr.addstr(row, col, text[:avail], attr)
    except curses.error:
        pass


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

CELL_W = 7     # width per byte column: "OO→NN " = 6 + 1 space, or "  XX  " + space

def _render(stdscr, instances: dict, order: list, scroll_top: int, selected: int,
            total_frames: int, interface: str, can_id: int):
    h, w = stdscr.getmaxyx()
    stdscr.erase()
    now = time.time()

    cp_header = curses.color_pair(1)
    cp_flash  = curses.color_pair(2) | curses.A_BOLD
    cp_count  = curses.color_pair(4)
    cp_note   = curses.color_pair(5)

    # ---- Header bar ----
    title = (
        f" CAN Monitor  0x{can_id:08X}  |  {interface}  |"
        f"  {len(order)} instance(s)  |  {time.strftime('%H:%M:%S')}"
        f"   {total_frames} frames total"
    )
    _draw_bar(stdscr, 0, w, title, cp_header)

    # ---- Column headers ----
    hdr_cols = "Inst  "
    for i in range(1, 8):
        hdr_cols += f"B{i}".center(CELL_W)
    hdr_cols += "  Last Seen   Count   Note"
    _safe_addstr(stdscr, 1, 0, hdr_cols[:w - 1], curses.A_BOLD)

    # ---- Instance rows (2 rows each) ----
    body_start = 2
    body_end   = h - 2          # leave footer
    max_visible_instances = (body_end - body_start) // 2

    for rel_i in range(max_visible_instances):
        abs_i = scroll_top + rel_i
        if abs_i >= len(order):
            break
        inst_id = order[abs_i]
        rec     = instances[inst_id]
        row_y   = body_start + rel_i * 2

        if row_y + 1 >= h - 1:
            break

        is_selected = (abs_i == selected)
        any_flash   = any(now - ts < FLASH_DURATION for ts, _, _ in rec.flash.values())

        # -- Row 1: decoded bytes with flash --
        marker    = "► " if any_flash else "  "
        inst_base = cp_flash | curses.A_BOLD if any_flash else 0
        inst_attr = inst_base | (curses.A_REVERSE if is_selected else 0)
        line1 = f"  {inst_id:02X}  "
        for bidx in range(7):
            cur_val = rec.last_bytes[bidx]
            if bidx in rec.flash:
                ts, old_v, new_v = rec.flash[bidx]
                if now - ts < FLASH_DURATION:
                    cell = f"{old_v:02X}→{new_v:02X} "
                else:
                    del rec.flash[bidx]
                    cell = f"  {cur_val:02X}  " if cur_val is not None else "  --  "
                    cell = cell[:CELL_W]
            else:
                cell = f"  {cur_val:02X}   " if cur_val is not None else "  --   "
                cell = cell[:CELL_W]
            line1 += cell

        elapsed = now - rec.last_seen
        if elapsed < 10:
            age_str = f"{elapsed:.1f}s"
        else:
            age_str = f"{int(elapsed)}s"

        _safe_addstr(stdscr, row_y, 0, f"{marker}{inst_id:02X}  ", inst_attr)
        _safe_addstr(stdscr, row_y, 6, line1[6:])

        # count in green at end
        count_col = 6 + 7 * CELL_W + 2
        age_text  = f"  {age_str:>5}"
        _safe_addstr(stdscr, row_y, count_col, age_text)
        count_text = f"  {rec.count:>8}"
        _safe_addstr(stdscr, row_y, count_col + len(age_text), count_text, cp_count)

        # -- Row 2: raw hex dump (dimmed) + note (cyan) --
        raw_bytes = [inst_id] + rec.last_bytes
        raw_str = "        " + " ".join(
            f"{b:02X}" if b is not None else "--" for b in raw_bytes
        )
        _safe_addstr(stdscr, row_y + 1, 0, raw_str, curses.A_DIM)
        if rec.note:
            note_col = len(raw_str) + 2
            _safe_addstr(stdscr, row_y + 1, note_col, rec.note, cp_note)

        # -- Flash cells: re-render in yellow+bold over the already-drawn line --
        for bidx in range(7):
            if bidx in rec.flash:
                ts, old_v, new_v = rec.flash[bidx]
                if now - ts < FLASH_DURATION:
                    cell = f"{old_v:02X}→{new_v:02X} "
                    col  = 6 + bidx * CELL_W
                    _safe_addstr(stdscr, row_y, col, cell, cp_flash)

    # ---- Footer bar ----
    scroll_info = f" {selected + 1}/{len(order)}" if order else " 0/0"
    footer = f" [q]quit  [r]reset  [c]clear  [n]note  [↑↓ select{scroll_info}]"
    _draw_bar(stdscr, h - 1, w, footer, cp_header)

    stdscr.refresh()


# ---------------------------------------------------------------------------
# Main TUI loop
# ---------------------------------------------------------------------------

def _monitor_main(stdscr, interface: str, can_id: int, log_file_path: Optional[str]):
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)   # header/footer bar
    curses.init_pair(2, curses.COLOR_YELLOW, -1)                 # flash highlight
    curses.init_pair(3, curses.COLOR_WHITE, -1)                  # normal
    curses.init_pair(4, curses.COLOR_GREEN, -1)                  # count
    curses.init_pair(5, curses.COLOR_CYAN, -1)                   # note

    instances: dict[int, InstanceRecord] = {}
    order: list[int] = []
    scroll_top   = 0
    selected     = 0
    total_frames = 0
    log_fh       = None

    if log_file_path:
        try:
            log_fh = open_log_file(log_file_path)
        except OSError as e:
            curses.endwin()
            print(f"Cannot open log file {log_file_path}: {e}")
            return

    rx_queue   = queue.Queue()
    stop_event = threading.Event()
    reader     = CANReaderThread(interface, rx_queue, stop_event)
    reader.start()

    # Brief pause to let thread start and surface any immediate errors
    time.sleep(0.15)
    if reader.error:
        stop_event.set()
        curses.endwin()
        print(f"CAN interface error on '{interface}': {reader.error}")
        return

    try:
        while True:
            # -- Drain incoming CAN frames --
            now = time.time()
            while True:
                try:
                    msg = rx_queue.get_nowait()
                except queue.Empty:
                    break
                if msg.arbitration_id != can_id:
                    continue
                total_frames += 1
                data = list(msg.data)
                if len(data) < 1:
                    continue
                inst_id   = data[0]
                raw_bytes = data[1:8]
                # Pad to 7 bytes if short frame
                while len(raw_bytes) < 7:
                    raw_bytes.append(None)

                if inst_id not in instances:
                    instances[inst_id] = InstanceRecord(
                        instance=inst_id,
                        last_bytes=[None] * 7,
                        flash={},
                        last_seen=now,
                        count=0,
                    )
                    order.append(inst_id)

                rec = instances[inst_id]
                rec.last_seen = now
                rec.count    += 1

                for bidx, new_val in enumerate(raw_bytes):
                    old_val = rec.last_bytes[bidx]
                    if new_val is not None and old_val != new_val:
                        rec.flash[bidx] = (now, old_val if old_val is not None else 0, new_val)
                        if log_fh:
                            log_change(log_fh, inst_id, bidx,
                                       old_val if old_val is not None else 0, new_val)
                    rec.last_bytes[bidx] = new_val

            # -- Keyboard input --
            key = stdscr.getch()
            if key == ord("q"):
                break
            elif key == ord("r"):
                instances.clear()
                order.clear()
                scroll_top   = 0
                selected     = 0
                total_frames = 0
            elif key == ord("c"):
                for rec in instances.values():
                    rec.flash.clear()
            elif key == ord("n"):
                if order:
                    inst_id = order[selected]
                    rec     = instances[inst_id]
                    h, w    = stdscr.getmaxyx()
                    result  = _edit_note(stdscr, h, w,
                                         f"Note for {inst_id:02X}", rec.note)
                    if result is not None:
                        rec.note = result
            elif key == curses.KEY_DOWN:
                if selected + 1 < len(order):
                    selected += 1
            elif key == curses.KEY_UP:
                if selected > 0:
                    selected -= 1

            # Keep selected in bounds
            if order:
                selected = max(0, min(selected, len(order) - 1))

            # Scroll to keep selected visible
            h, w = stdscr.getmaxyx()
            body_rows = h - 4   # header(2) + footer(1) + 1 slack
            max_visible = max(1, body_rows // 2)
            if selected < scroll_top:
                scroll_top = selected
            elif selected >= scroll_top + max_visible:
                scroll_top = selected - max_visible + 1

            _render(stdscr, instances, order, scroll_top, selected,
                    total_frames, interface, can_id)
            time.sleep(POLL_INTERVAL)

    finally:
        stop_event.set()
        if log_fh:
            log_fh.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Live CAN ID monitor TUI — watch all instances on one arbitration ID"
    )
    parser.add_argument(
        "--interface", "-i",
        default="can_rvc",
        help="SocketCAN interface name (default: can_rvc)",
    )
    parser.add_argument(
        "--can-id",
        default="0x195FCE9C",
        help="CAN arbitration ID, hex or decimal (default: 0x195FCE9C)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional path to append change log CSV",
    )
    args = parser.parse_args()

    can_id = int(args.can_id, 0)
    curses.wrapper(_monitor_main, args.interface, can_id, args.log_file)


if __name__ == "__main__":
    main()
