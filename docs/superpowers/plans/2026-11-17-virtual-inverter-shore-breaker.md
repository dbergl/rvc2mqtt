# Virtual Inverter Shore Breaker / Charge Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the panel's Shore Brkr Size button set the Modbus inverter's AC input limit, show the real value (and the charge rate) back on the panel, and keep the G12's copy in step with the inverter.

**Architecture:** Everything lives in the existing `VirtualInverter` entity. Two new opt-in fields feed one new status frame (1FF96); one new command branch (1FF95) writes modbus; an optional sync state machine, evaluated in `tick()`, pushes the inverter's value into G12 selector 0x90 and confirms it from the G12's 1FF95 relay.

**Tech Stack:** Python, pytest/unittest, paho-mqtt mock, `RVC_Decoder` for frame round-trips.

**Spec:** `docs/superpowers/specs/2026-11-17-virtual-inverter-shore-breaker-design.md`

## Global Constraints

- All of it is off unless the floorplan maps a field. The existing 81 tests in `test/virtual_inverter_test.py` must pass unchanged, including the exact default frame list.
- Never act on any 1FF95 byte other than byte 3. Byte 3 = 0xFF means no change.
- The inverter is the authority: no modbus write while state is unknown or the source is offline.
- G12 push frames, DGN `1FED9`, no `source_id` key (bridge address): `FF 96 90 0F <lo> <hi> D1 EA` then `FF 96 90 0F FF FF D3 FF`. Never D2.
- Clamp 5..30 A (floorplan-overridable). Confirm window 1.0 s. Three consecutive failed pushes (silence or mismatch) latch the sync off.
- 1FF96: `<charger_config_2_instance> <rate> FF <amps> FF FF FF FF`, rate = `round(min(limit/rated, 1) * 200)`.
- `process_rvc_msg` must return `False` for anything it does not consume (first-match dispatch).
- No commits unless the owner asks.

## Review Focus

- Inverter state above the clamp (32 A) and the G12 relays 30: the 32 must not be overwritten.
- Two quick presses (30→25→20) with modbus reporting 25 then 20: no push to the G12, no bounce.
- 0x90 behaving as a delta: retries must stop after three failures and never write the inverter.
- 1FF95 carrying only byte 1 (G12 soft-start): no write, `g12_value` untouched.
- Modbus offline when a press arrives: no write; when state returns the G12 is corrected.

---

### Task 1: Configuration and state ingest

**Files:**
- Modify: `rvc2mqtt/entity/virtual_inverter.py` (`FIELD_DEFAULTS`, `__init__`, `_NUMERIC_MIRROR`)
- Test: `test/virtual_inverter_test.py` (new `Test_ShoreBreakerConfig`)

**Interfaces — Produces:**
- `FIELD_DEFAULTS["shore_breaker_size"] = None`, `FIELD_DEFAULTS["charge_current_limit"] = None`
- attributes: `charger_config_2_instance: int` (default `rvc_instance`), `shore_breaker_set_topic: str` (default `<base>/set/max_ac_input_current`), `shore_breaker_min: int = 5`, `shore_breaker_max: int = 30`, `shore_breaker_g12_sync: bool = False`, `shore_breaker_settle: float = 2.0`, `charger_rated_current: float | None`
- `_shore_breaker_target() -> int | None`: `clamp(round(values['shore_breaker_size']))`, `None` when unknown
- mirror rows: `shore_breaker_size` → `shore_breaker_size` (current, A, precision 0); `charge_current_limit` → `charge_current_limit` (current, A, precision 1)

- [ ] Tests: defaults (both fields unmapped, attribute defaults above); `charge_current_limit` mapped without `charger_rated_current` raises `ValueError`; `charger_rated_current: 0` raises; `shore_breaker_min > shore_breaker_max` raises; negative settle raises; feeding `'150'` to `state/max_ac_input_current` with scale 0.1 gives `values['shore_breaker_size'] == 15.0`, target 15; `'320'` gives target 30; mirror publishes `rvc/state/inverter/shore_breaker_size`.
- [ ] Run, see them fail; implement; run the whole file.

### Task 2: 1FF96 status frame and echo

**Files:** same two.

**Interfaces — Produces:** `_charger_config_2_frame() -> dict | None` (dgn `1FF96`, `source_id` ours); appended last in `build_frames()` when not `None`.

- [ ] Tests (decode with `_decode`): 15 A + limit 15 A of rated 40 at `charger_config_2_instance: 3` → instance 3, `shore_breaker_size` 15, `maximum_charge_current_as_percent` 37.5 (raw 75), raw data `034BFF0FFFFFFFFF`; limit 50 of 40 → raw byte 1 `C8`; only breaker known → byte 1 `FF`; only limit known → byte 3 `FF`; neither known → `None` and default frame list unchanged; default instance = entity instance; own echo (name `CHARGER_CONFIGURATION_STATUS_2`, instance 3, source `42`) claimed; same frame from source `9C` not claimed; not claimed when neither field mapped.
- [ ] Fail, implement, pass.

### Task 3: 1FF95 command

**Files:** same two.

**Interfaces — Produces:** `_handle_charger_config_command_2(msg: dict) -> bool`; sets `_g12_value: int | None`; restarts `_settle_until: float` on a press.

- [ ] Tests (messages built by decoding `1FF95` payloads from source `9C`): state 30, byte 3 = 25 → publishes `('modbus/inverter/set/max_ac_input_current', '250')`, not retained, returns `True`; byte 3 `FF` with byte 1 `64` → no publish, `_g12_value` unchanged, `True`; byte 3 = 2 → writes `50`; byte 3 = 200 → state 15 writes `300`; equal to target → no publish; state 32, byte 3 = 30 → no publish; state unknown → no publish, `_g12_value` set; source offline → no publish; instance 2 → `False`; field unmapped → `False`; custom `shore_breaker_set_topic`.
- [ ] Fail, implement, pass.

### Task 4: G12 sync

**Files:** same two.

**Interfaces — Consumes:** `_shore_breaker_target()`, `_g12_value`, `_settle_until`. **Produces:** `_g12_sync_tick(now: float)`, called at the top of `tick()` before the interval gate; `_push_pending: int | None`, `_push_deadline: float`, `_push_failures: int`, `_sync_latched: bool`. Settle restarts on every `shore_breaker_size` change (in `_ingest`), every press, and every failed push.

- [ ] Tests: sync off → never a `1FED9`; first state 15 → after settle, frames `FF96900F0F00D1EA` and `FF96900FFFFFD3FF` with no `source_id`; nothing before settle expires; relay of 15 within 1 s → `_g12_value == 15`, no modbus write, no further push; no relay → second push after settle, third, then latched with one error logged and no fourth; mismatched relay inside window → not written to modbus, counts as failure; confirmation resets the failure count; single press (relay 25, state then 25) → no push; two quick presses with state 25 then 20 → no push; refused write (state stays 30 after press to 25) → push 30; state change 15→20 from HA → push 20; no push while source offline.
- [ ] Fail, implement, pass.

### Task 5: Documentation

**Files:** `docs/configuration.md` (virtual inverter section), module docstring of `virtual_inverter.py`.

- [ ] Add the options table rows, the two fields, mirrored topics, a "Shore breaker size and charge rate" subsection covering authority, the 1 s window, the latch, and deploy notes: instance 3 on the coach; `charger_rated_current: 40`; the mandatory 0x90 coach test before `shore_breaker_g12_sync`; until sync is on the first panel press steps from the G12's own value (probably 30), not the inverter's.
- [ ] Run the full test suite.

### Task 6 (added after firmware cross-check): ask the G12 before writing

The G12 relays 1FF95 only on a change, so a write of an unchanged value cannot
be confirmed by the relay. See the spec's "Why ask first".

**Files:** `rvc2mqtt/entity/virtual_inverter.py`, `rvc2mqtt/entity/g12_configuration.py`, both test files.

- [x] `g12_configuration.process_rvc_msg` returns `False` for 15FCE selector `90` (`_PASS_THROUGH_SELECTORS`).
- [x] `VirtualInverter._handle_g12_report(msg) -> bool`, option `g12_source_id` (default `9C`), `_query_pending: bool`; read-back only while `_g12_value` is unknown; report confirms; silence clears `_g12_value`.
- [x] Tests: startup already in sync never pushes or fails; silent G12 → three read-backs then latch; delta-like answers latch without an inverter write.
