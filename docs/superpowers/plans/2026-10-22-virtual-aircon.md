# Virtual Air Conditioner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `virtual_aircon` entity plugin that presents a Home-Assistant-controlled Bluetooth AC as RV-C thermostat instance 7 to the Firefly panel.

**Architecture:** One entity module modelled on `entity/virtual_inverter.py`. A small, clock-injected `OptimisticState` class holds per-field reported/pending values with confirm-or-revert. The entity decodes panel commands from raw CAN bytes, publishes MQTT set topics, ingests MQTT state topics, and broadcasts four status DGNs from `tick()`.

**Tech Stack:** Python 3, paho-mqtt (through `MQTT_Support`), unittest + pytest, socketcan/cansend for bench testing.

**Spec:** `docs/superpowers/specs/2026-10-22-virtual-aircon-design.md` and the panel interface it links, `docs/superpowers/specs/2026-10-22-virtual-aircon-panel-interface.md`. Read both.

## Global Constraints

- Branch `virtual-aircon`. `rvc2mqtt/rvc-spec.yml` has a teammate's uncommitted edits: **never stage it and never revert it**. Always `git add` named files; never `git add -A`, `-a` or `.`.
- No Home Assistant discovery. The entity publishes no `homeassistant/...` config.
- Thermostat instance 0 is never touched. Match only frames whose byte 0 equals the configured instance (default 7).
- Do not change the `0FFA0`/`0FFA1` bit layout (it is mirrored in the firmware). Do not add them to `rvc-spec.yml`; match them by `msg["dgn"]` (the decoder names them `UNKNOWN-0FFA0`).
- Decode panel commands from `msg["data"]` (hex string), not from decoded fields.
- The RV-C temperature encoding is u16 little-endian, 0.03125 °C/bit, offset −273 °C.
- The full suite must stay green. Baseline: `pytest -q` → `810 passed`.
- Code style follows `virtual_inverter.py`: module docstring with the Apache header, a `Logger` per class, and `self._clock` injected for tests.

## Review Focus

1. **Retained state on startup.** HA's state topics are retained. They must be registered with `retain_ok=True`, or `MQTT_Support` clears them on the broker. Test: `test_state_topics_registered_retain_ok` (Task 3).
2. **HA's `unavailable` / `unknown` strings.** Template automations publish these when the BT entity drops. Expect: ignored, logged at debug, last value kept, no exception. Test: `test_ha_unavailable_strings_ignored` (Task 3).
3. **Float-formatted numbers.** HA templates often render `24.0`, `3.0` or `"22.4"`. Expect them parsed (setpoint rounded to int, fan 1–5). Test: `test_float_formatted_payloads` (Task 3).
4. **Short or odd CAN payloads.** A frame shorter than 8 bytes (e.g. `07F1`) or with a reserved setpoint (`0xFE10`). Expect no exception and no publish for the missing or reserved fields. Test: `test_short_and_reserved_payloads` (Task 5).
5. **All-"no change" commands.** E.g. `07FFFFFFFFFFFFFF` on 1FEF9, or `07FFFFFFFFFFFFFF` on 1FEF8. Expect the frame claimed (True) but nothing published and no state change. Test: `test_all_no_change_publishes_nothing` (Task 5).

---

### Task 1: Temperature encode/decode helpers

**Files:**
- Modify: `rvc2mqtt/rvc_encode.py`
- Test: `test/rvc_encode_test.py`

**Interfaces:**
- Produces: `encode_temperature_u16(celsius: float | None) -> int` (None → `U16_NA`, otherwise `_clamp_u16((c + 273) / 0.03125)`) and `decode_temperature_u16(raw: int) -> float | None` (`raw * 0.03125 - 273`, None for raw ≥ `0xFE00`).

- [ ] **Step 1: Write failing tests** in `Test_Encoders`:
  - `test_temperature_known_values`: `encode_temperature_u16(24) == 0x2520`, `encode_temperature_u16(22.5) == 0x24F0`, `encode_temperature_u16(None) == U16_NA`.
  - `test_temperature_round_trips`: for `c in (-10.0, 0.0, 17.0, 24.0, 30.0)`, `self.dec._convert_unit(encode_temperature_u16(c), "deg c", "uint16") == c`.
  - `test_decode_temperature`: `decode_temperature_u16(0x2520) == 24.0`, `decode_temperature_u16(0xFFFF) is None`, `decode_temperature_u16(0xFFFC) is None`.
- [ ] **Step 2: Run** `pytest test/rvc_encode_test.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement both functions** in `rvc2mqtt/rvc_encode.py`, next to the other encoders. Update the module docstring, which currently says it serves only the virtual inverter.
- [ ] **Step 4: Run** `pytest test/rvc_encode_test.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add rvc2mqtt/rvc_encode.py test/rvc_encode_test.py && git commit -m "rvc_encode: temperature u16 encode/decode"`

---

### Task 2: `OptimisticState` — reported / pending / confirm / revert

**Files:**
- Create: `rvc2mqtt/entity/virtual_aircon.py` (module docstring plus this class only, for now)
- Test: `test/virtual_aircon_test.py`

**Interfaces:**
- Produces, in `virtual_aircon.py`:
  - `class OptimisticState:` `__init__(self, timeout: float, clock: Callable[[], float], logger)`
  - `report(field: str, value) -> bool`: record the reported value. If the field is pending and `value == pending`, clear the pending value (confirmed). Returns True if `effective(field)` changed.
  - `command(field: str, value) -> None`: set pending = value with deadline `clock() + timeout`.
  - `effective(field: str, default=None)`: the pending value if pending, else the reported value, else `default`.
  - `reported(field: str, default=None)`
  - `is_pending(field: str) -> bool`
  - `expire() -> list[str]`: drop pendings past their deadline, log `"<field>: not confirmed within <timeout>s, reverting to <reported>"` at info, and return the reverted field names.
- Values are compared with `==`. The entity normalises them (setpoint int, preset lowercase) before calling.
- The entity calls this from both the paho thread and the main thread, so guard internal dicts with one `threading.Lock`.

- [ ] **Step 1: Write failing tests** (`Test_OptimisticState`, fake clock dict as in `virtual_inverter_test.py`):
  - `test_effective_falls_back_to_default`: fresh state → `effective('mode', 'off') == 'off'`.
  - `test_report_sets_effective`: `report('mode','cool')` returns True, `effective('mode') == 'cool'`.
  - `test_command_is_effective_immediately`: after `report('mode','off')` and `command('mode','cool')`, `effective == 'cool'` and `is_pending('mode')`.
  - `test_matching_report_confirms`: then `report('mode','cool')` → `is_pending` False, and `effective` stays `'cool'`.
  - `test_nonmatching_report_held_while_pending`: `command('setpoint', 25)`, then `report('setpoint', 24)` → `effective == 25`, `reported('setpoint') == 24`, and `report` returned False.
  - `test_expire_reverts_after_timeout`: timeout 35. Command at t=0, `expire()` at t=34 → `[]`; at t=35.1 → `['setpoint']` and `effective == 24` (the last reported value).
  - `test_new_command_extends_deadline`: commands at t=0 and t=30 → still pending at t=40.
  - `test_unrelated_field_report_applies`: pending `mode`, `report('fan', 3)` → `effective('fan') == 3`.
- [ ] **Step 2: Run** `pytest test/virtual_aircon_test.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `OptimisticState`**, with dicts `_reported` and `_pending: {field: (value, deadline)}` under the lock.
- [ ] **Step 4: Run** `pytest test/virtual_aircon_test.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add rvc2mqtt/entity/virtual_aircon.py test/virtual_aircon_test.py && git commit -m "virtual_aircon: OptimisticState confirm/revert model"`

---

### Task 3: Entity configuration and MQTT state ingest

**Files:**
- Modify: `rvc2mqtt/entity/virtual_aircon.py`
- Test: `test/virtual_aircon_test.py`

**Interfaces:**
- Consumes: `OptimisticState` (Task 2).
- Produces: `class VirtualAircon(EntityPluginBaseClass)` with:
  - `FACTORY_MATCH_ATTRIBUTES = {"name": "VIRTUAL_AIRCON", "type": "virtual_aircon"}`
  - `self.id = "virtual-aircon-1FFE2-i" + str(instance)`
  - Config attributes, with defaults: `rvc_instance` (from `instance`, required), `name`, `source_id='58'`, `topic_base='rvc2mqtt/aircon'` (rstrip `/`), `interval=1.0` (>0, else ValueError), `confirm_timeout=35.0` (>0), `temperature_unit` (`'C'`/`'F'`, case-insensitive, else ValueError), `setpoint_min/max/default` (C: 17/30/24; F: 62/86/75), `availability_topic=None`, `step_codes` (default `{0xFFFC: +1, 0xFFFA: +1, 0xFFFB: -1, 0xFFF9: -1}`; the floorplan gives keys as ints or hex strings and values `up`/`down`), `fields` overrides.
  - `self.state_topics: dict[str, str]` and `self.set_topics: dict[str, str]`. Fields `mode, fan, setpoint, preset, oscillate, display` have both; `temperature` has state only. Defaults are `f"{topic_base}/state/{field}"` and `f"{topic_base}/set/{field}"`. `fields: {mode: {state: ..., set: ...}}` overrides either one; a relative path joins to `topic_base`, as in the inverter's `_join_topic`.
  - `self.state: OptimisticState`, `self.available: bool` (starts True), `self._dirty: bool`.
  - `process_mqtt_msg(topic, payload, properties=None)`: routes to `_ingest(field, payload)` or availability. Never raises: catch, then `Logger.warning` once per field and value.
  - Normalisers (module functions, unit-tested):
    - `parse_mode(p) -> str | None`: accepts `off cool auto dry fan_only`, plus `fan` → `fan_only` and `heat_cool` → `auto`, case-insensitive.
    - `parse_fan(p) -> int | str | None`: `auto`, or 1–5 from `"3"`, `"3.0"`, `" 3 "`.
    - `parse_preset(p) -> str | None`: `none eco sleep turbo`; velit's `Cooling` → `none`; also `boost` → `turbo` and `energy_saving` → `eco`.
    - `parse_onoff(p) -> bool | None`: same set as the inverter's `_parse_bool`, returning None instead of raising.
    - `parse_number(p) -> float | None`.
    - All return None for `unavailable`, `unknown`, `none`/`None` where not a valid value, or the empty string. Note that `none` is a valid preset.
  - Temperatures are stored in `temperature_unit`; the setpoint is stored as `int(round(x))`.
  - A report that changes `effective` sets `self._dirty = True`.
  - Availability payloads are `online`/`offline` (HA's convention); also accept `on/off/1/0/true/false`.

- [ ] **Step 1: Write failing tests** (`_make_entity(extra)` helper, adapted from `virtual_inverter_test.py`, with data `{'name':'VIRTUAL_AIRCON','type':'virtual_aircon','instance':7}`):
  - `test_defaults`: `source_id == '58'`, `set_topics['mode'] == 'rvc2mqtt/aircon/set/mode'`, `state_topics['temperature'] == 'rvc2mqtt/aircon/state/temperature'`, `'temperature' not in set_topics`, `confirm_timeout == 35.0`, `(setpoint_min, setpoint_max) == (17, 30)`.
  - `test_fahrenheit_defaults`: `temperature_unit: f` → `(62, 86, 75)`.
  - `test_bad_config_raises`: `interval: 0`, `temperature_unit: K` and `confirm_timeout: -1` each raise ValueError.
  - `test_field_override`: `fields: {setpoint: {set: 'velit/sp/set'}}` → `set_topics['setpoint'] == 'rvc2mqtt/aircon/velit/sp/set'`, and an absolute topic beginning with `topic_base/` is kept as is.
  - `test_step_codes_from_floorplan`: `step_codes: {'0xFFFC': 'down', 0xFFFB: 'up'}` → `{0xFFFC: -1, 0xFFFB: +1, 0xFFFA: +1, 0xFFF9: -1}` (merged over the defaults).
  - `test_state_topics_registered_retain_ok` (Review Focus 1): every `state_topics` value and `availability_topic` is registered with `retain_ok=True`.
  - `test_ingest_each_field`: publishing `cool`, `3`, `24`, `eco`, `on`, `off` and `22.5` to the respective state topics gives the matching `state.effective(...)` values, and `_dirty` is True.
  - `test_ha_unavailable_strings_ignored` (Review Focus 2): after mode `cool`, publish `unavailable` then `unknown` → still `cool`, no exception, nothing logged above debug.
  - `test_float_formatted_payloads` (Review Focus 3): setpoint `"24.0"` → 24, setpoint `"23.6"` → 24, fan `"3.0"` → 3, temperature `"22.4"` → 22.4.
  - `test_velit_preset_names`: `Cooling` → `none`, `Turbo` → `turbo`.
  - `test_availability`: `offline` → `available` False and `_dirty`; `online` → True.
  - `test_no_ha_discovery`: after `initialize()`, no `mock.client.publish` topic starts with `homeassistant/`.
- [ ] **Step 2: Run** `pytest test/virtual_aircon_test.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the config, topics, registration and normalisers in `__init__`, with `process_mqtt_msg`/`_ingest`. `initialize()` does nothing yet beyond what Task 4 adds.
- [ ] **Step 4: Run** `pytest test/virtual_aircon_test.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add rvc2mqtt/entity/virtual_aircon.py test/virtual_aircon_test.py && git commit -m "virtual_aircon: config, MQTT topics, state ingest"`

---

### Task 4: Status frames and broadcast cadence

**Files:**
- Modify: `rvc2mqtt/entity/virtual_aircon.py`
- Test: `test/virtual_aircon_test.py`

**Interfaces:**
- Consumes: Task 1 encoders; Task 3 `state`, `available`, `_dirty`.
- Produces:
  - `build_frames() -> list[dict]`: four dicts `{"dgn", "data": bytes(8), "source_id"}` for `1FFE2`, `1FEFA`, `1FF9C` and `0FFA1`, in that order.
  - `tick(now)`: calls `state.expire()` (a non-empty result sets `_dirty`). It sends `build_frames()` to `send_queue` when `_dirty` or `now >= next_tx`, then clears `_dirty` and sets `next_tx = now + interval`. Unlike the inverter it never goes silent.
  - `_to_celsius(x) -> float | None` converts from `temperature_unit`.
- Frame layout (byte 0 = instance in all four):
  - **1FFE2:** byte 1 = `mode_code | fan_mode << 4 | 0b00 << 6`, where mode codes are off 0, cool 1, auto 3, fan_only 4, dry 6, and `fan_mode` is 01 when the effective fan is an int and 00 otherwise. Byte 2 = `fan * 40`, or 0 for auto/unknown. Bytes 3–4 = `FFFF`. Bytes 5–6 = the setpoint, or `FFFF` if unknown. Byte 7 = `FF`. While `available` is False, mode is reported as 0 (the rest unchanged). Mode defaults to off.
  - **1FEFA:** bytes 1–2 = `FF FF`. Byte 3 = `0xC0 | sleep | eco << 2 | turbo << 4`, at most one of them 1, from `preset`; unknown preset → `0xC0`. Bytes 4–7 = `FF`.
  - **1FF9C:** bytes 1–2 = room temperature, or `FFFF`. Bytes 3–7 = `FF`.
  - **0FFA1:** byte 1 = `0xF0 | osc | display << 2` (unknown → 0, so the panel's toggle sends "on"). Bytes 2–7 = `FF`.

- [ ] **Step 1: Write failing tests** (compare `frame['data'].hex().upper()`):
  - `test_frames_before_any_report`: `["070000FFFFFFFFFF", "07FFFFC0FFFFFFFF", "07FFFFFFFFFFFFFF", "07F0FFFFFFFFFFFF"]`, with source_id `'58'` and dgns in order.
  - `test_frames_cool_fan3_24c`: mode cool, fan 3, setpoint 24, temperature 22.5 → 1FFE2 `"071178FFFF2025FF"`, 1FF9C `"07F024FFFFFFFFFF"`.
  - `test_fan_thresholds`: fan 1..5 → byte 2 is `0x28 0x50 0x78 0xA0 0xC8`. Fan auto → byte 2 `00` and byte 1 bits 4–5 = 00.
  - `test_mode_codes`: off/cool/auto/fan_only/dry → byte 1 low nibble 0/1/3/4/6.
  - `test_preset_bits`: none/sleep/eco/turbo → byte 3 `C0/C1/C4/D0`.
  - `test_osc_display_bits`: osc on with display off → `"07F1FFFFFFFFFFFF"`; both on → `F5`.
  - `test_fahrenheit_encoding`: `temperature_unit F`, setpoint 75 → bytes 5–6 encode 23.89 °C (`encode_temperature_u16((75-32)*5/9)`).
  - `test_offline_reports_mode_off`: mode cool, then availability `offline` → byte 1 low nibble 0.
  - `test_tick_cadence`: interval 1. `tick(0)` sends 4 frames; `tick(0.5)` sends 0; `tick(1.0)` sends 4. A state report at t=1.2 makes `tick(1.2)` send 4.
  - `test_tick_expiry_rebroadcasts`: `state.command('mode','cool')` at t=0 with mode reported `off`. `tick(35.1)` sends frames with mode 0 (reverted).
- [ ] **Step 2: Run** `pytest test/virtual_aircon_test.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `build_frames` (one small method per DGN, like the inverter's `_*_frame`), `tick`, `initialize` (sets `_dirty = True` so the first tick broadcasts) and `_to_celsius`.
- [ ] **Step 4: Run** `pytest test/virtual_aircon_test.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add rvc2mqtt/entity/virtual_aircon.py test/virtual_aircon_test.py && git commit -m "virtual_aircon: status frames and broadcast cadence"`

---

### Task 5: Panel command decode, set-topic publish, dispatch

**Files:**
- Modify: `rvc2mqtt/entity/virtual_aircon.py`
- Test: `test/virtual_aircon_test.py` (plus one test in `test/entity_factory_test.py` if that file has a per-plugin pattern; otherwise this test file covers it)

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `process_rvc_msg(msg) -> bool`. Look at `msg["dgn"]` and `bytes.fromhex(msg["data"])`; return False unless byte 0 == instance. `1FEF9` → `_on_command_1`, `1FEF8` → `_on_command_2`, `0FFA0` → `_on_proprietary`, then return True. For `1FFE2`/`1FEFA`/`1FF9C`/`0FFA1` (our echoes) log debug and return True. Anything else → False. Log every claimed command at debug with `source_id`.
  - `_command(field, value)`: `state.command(field, value)`, publish `set_topics[field]` with the payload (`retain=False`), log at info, set `_dirty`. Payloads: mode string, fan `"1"`–`"5"`/`"auto"`, setpoint as an integer string, preset string, `"on"`/`"off"`.
- Decode rules (an all-ones field means no change; a byte or field missing from a short payload means no change):
  - **1FEF9:** byte 1 bits 0–3: a value in {0,1,3,4,6} → mode command; 0xF → none; others → log and ignore. Bits 4–5: 00 → fan `auto`; 01 → fan `clamp(round(byte2 / 40), 1, 5)` if byte 2 is between 1 and 250, else nothing. Bytes 5–6 LE: `0xFFFF` none. A key of `step_codes` steps: `base = state.effective('setpoint', setpoint_default)`, `new = clamp(base + dir, min, max)`, then command `new` and log the code, direction and result at info. A value ≤ `0xFDFF` is absolute: decode, convert to `temperature_unit`, round to int, clamp, command. Anything else → log and ignore.
  - **1FEF8** byte 2 (pairs: bits 0–1 sleep, 2–3 eco, 4–5 turbo): 01 → command preset = that one. 00 → if the effective preset is that one, command `none`, else nothing. 11 → nothing. Handle the pairs in the order turbo, eco, sleep, so a malformed frame with several 01s ends deterministically.
  - **0FFA0** byte 1: bits 0–1 → oscillate, bits 2–3 → display; 01 → on, 00 → off, 11 → nothing.

- [ ] **Step 1: Write failing tests.** Feed `{'dgn':..., 'data':..., 'source_id':'9F', 'name':..., 'instance': 7}`. Every frame in the panel interface spec gets a test:
  - `test_power_cool_auto_dry_fan`: `07F1…` → set/mode `cool`. `07F0…` → `off`. `07C3…` → mode `auto` **and** set/fan `auto`. `07F6…` → `dry`. `07F4…` → `fan_only`.
  - `test_fan_speeds`: `07DF28FF…` through `07DFC8FF…` → set/fan `1`…`5`, and no mode publish.
  - `test_setpoint_steps`: setpoint reported 24, then `07FFFFFFFFFCFFFF` → set/setpoint `25`. Then `…FFFB…` → `24`. `…FFFA…` → `25`; `…FFF9…` → `24`.
  - `test_held_arrow_no_snapback`: reported 24; three `…FFFC…` frames → publishes `25, 26, 27`. A stale report of `24` arriving between them doesn't change the sequence.
  - `test_step_clamps`: reported 30 and `…FFFC…` → `30`. Reported 17 and `…FFFB…` → `17`.
  - `test_step_from_default_when_unknown`: nothing reported, `…FFFC…` → `25`.
  - `test_absolute_setpoint`: bytes 5–6 = `2025` (24 °C) → `24`. With `temperature_unit F` → `75`.
  - `test_presets`: `07FFDF…` → preset `turbo`. Then `07FFCF…` → `none`. `07FFF7…` → `eco`. With preset eco, `07FFCF…` (turbo off) publishes nothing. `07FFFD…` → `sleep`; `07FFFC…` → `none`.
  - `test_preset_exclusive_in_status`: eco active, then Turbo on → 1FEFA byte 3 `D0` on the next tick.
  - `test_oscillate_display`: dgn `0FFA0` `07FD…` → set/oscillate `on`; `07FC…` → `off`; `07F7…` → set/display `on`; `07F3…` → `off`.
  - `test_toggle_immediate_echo`: after `07FFDF…` (turbo on), `tick(now)` at the same instant sends a 1FEFA with turbo bits 01, without waiting for the interval.
  - `test_ignores_instance_0`: `1FEF9` `000000FFFFFFFFFF` → returns False and publishes nothing.
  - `test_claims_own_echo_only`: `1FFE2` with byte 0 = 07 → True. `1FFE2` with byte 0 = 00 → False. `1FEF9` from instance 7, any source → True. An unrelated dgn `1FFBD` with byte 0 = 07 → False.
  - `test_short_and_reserved_payloads` (Review Focus 4): data `07F1` → mode `cool` only, no exception. `07FFFFFFFF10FEFF` (reserved 0xFE10) → nothing published.
  - `test_all_no_change_publishes_nothing` (Review Focus 5): `07FFFFFFFFFFFFFF` on each of the three dgns → True, no publish, no state change.
  - `test_unconfirmed_command_reverts`: `07FFDF…`, no report, `tick(36)` → 1FEFA byte 3 back to `C0`.
  - `test_plugin_loads_via_factory`: use the `entity_factory_test.py` pattern to confirm `PluginSupport` finds `VIRTUAL_AIRCON`/`virtual_aircon` among the entity plugins.
- [ ] **Step 2: Run** `pytest test/virtual_aircon_test.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the decode and `_command` as specified.
- [ ] **Step 4: Run** `pytest test/virtual_aircon_test.py -v`. Expected: PASS.
- [ ] **Step 5: Run the full suite** `pytest -q`. Expected: `810 + N passed`, 0 failed.
- [ ] **Step 6: Commit** `git add rvc2mqtt/entity/virtual_aircon.py test/virtual_aircon_test.py [test/entity_factory_test.py] && git commit -m "virtual_aircon: decode panel commands, publish set topics"`

---

### Task 6: Handoff docs and bench script

**Files:**
- Create: `docs/virtual-aircon-mqtt.md`
- Create: `tools/virtual_aircon_bench.sh` (executable)
- Modify: `rvc2mqtt/entity/virtual_aircon.py` (module docstring: a summary, pointing at the doc)
- Modify: `CLAUDE.md` (one line under Dev Tools for the bench script)

**Interfaces:**
- Consumes: the final topics, payloads and config keys from Tasks 3–5. Copy them from the code, not from this plan.

- [ ] **Step 1: Write `docs/virtual-aircon-mqtt.md`**, the friend's reference:
  - Data flow and the "plumbing only" rule.
  - A table of every state and set topic with its payloads, marking the ones upstream velit-hass cannot act on (`auto`, `dry`, fan `auto`, oscillate, display).
  - Confirm/revert behaviour, with `confirm_timeout`.
  - That his automations should publish state retained and on change.
  - The full floorplan entry with every key and its default.
  - The source-address collision note (default `58`; check `candump` before choosing).
  - An example HA automation pair (`climate.set_hvac_mode`/`set_preset_mode`/`set_temperature`/`set_fan_mode` from the set topics; `mqtt.publish` retained state from the climate entity's state and attributes), marked as untested.
  - Open items: which arrow code is up/down, and the 0FFA0/0FFA1 layout being ours.
- [ ] **Step 2: Write `tools/virtual_aircon_bench.sh`**: takes an `IFACE` argument (default `vcan0`) and runs one `cansend $IFACE <id>#<data>` per panel frame in the interface spec, in a logical order. Before each, `echo` what to expect: the set topic and payload on `mosquitto_sub -v -t 'rvc2mqtt/aircon/#'`, and the status change in `candump $IFACE,19FFE258:1FFFFFFF` (and the matching ids for the other three DGNs). Add `sleep 1` between frames. Start with a header comment on setting up vcan and starting the app with a test floorplan.
- [ ] **Step 3: Bench smoke test on vcan.** Set up vcan per CLAUDE.md, write a scratch floorplan containing only the `VIRTUAL_AIRCON` entry, and start the app against a local broker if one is available. Run the script and confirm that each set topic appears and each status frame changes as expected. If no broker or vcan is available, say so in the hand-back. Don't claim it passed.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `git add docs/virtual-aircon-mqtt.md tools/virtual_aircon_bench.sh rvc2mqtt/entity/virtual_aircon.py CLAUDE.md && git commit -m "virtual_aircon: MQTT handoff doc and bench script"`
