# Virtual Inverter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Modbus-only Renogy inverter (exposed on MQTT by modbus2mqtt) appear on the RV-C bus as inverter instance 1 — status, AC/DC readings, and on/off control — via a new rvc2mqtt entity plugin.

**Architecture:** A `VirtualInverter` entity subscribes to `modbus/inverter/state/*` topics, keeps the latest values, and on a main-loop `tick()` pushes `INVERTER_STATUS` / `INVERTER_AC_STATUS_1` (input + output) / `INVERTER_DC_STATUS` frames onto the existing send queue. It answers `INVERTER_COMMAND` from the bus (and `rvc/set/inverter/enable` from MQTT) by publishing to `modbus/inverter/set/onoff`, and mirrors state to `rvc/state/inverter/*` so dashboards are model-agnostic. The only framework change is a no-op `tick(now)` hook on the entity base class, called from `app.py`'s loop.

**Tech Stack:** Python 3, `python-can` (already used), `paho-mqtt` via `MQTT_Support`, `pytest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-08-23-virtual-inverter-design.md`

## Global Constraints

- Work in the `rvc2mqtt` repo (`/home/dan/projects/rv/rvc2mqtt`), current branch `unknown-dgns`. Activate the venv first: `source venv/bin/activate`.
- Run tests with `pytest test/<file> -v` (all: `pytest -v`). Tests import `context` to put the package on the path.
- Commit messages: plain imperative subject; end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. **Do not** add a `Claude-Session:` trailer (public repo).
- Apache-2.0 header on new source files (copy the block from `rvc2mqtt/entity/water_pump.py` lines 1-20, adjusting the docstring).
- RV-C byte encodings for uint16: voltage `0.05 V/bit`, current `0.05 A/bit, −1600 A offset`, frequency `1/128 Hz/bit`, `0xFFFF` = not available, little-endian.
- DGN ids: `INVERTER_STATUS` = `1FFD4`, `INVERTER_COMMAND` = `1FFD3`, `INVERTER_AC_STATUS_1` = `1FFD7`, `INVERTER_DC_STATUS` = `1FEE8`.
- Send-queue contract (unchanged): entities `put` dicts `{"dgn": "<hex str>", "data": <bytes/bytearray len 8>, "source_id": "<hex str>"}`; `app.message_tx_loop` computes `arbitration_id`.
- State topics that we subscribe to **must** be registered with `retain_ok=True`; `MQTT_Support.register(topic, func)` with the default `retain_ok=False` publishes an empty retained payload to the topic, which would wipe modbus2mqtt's retained state.
- The virtual inverter's default transmit source address is `'42'` (module constant `DEFAULT_INVERTER_SOURCE_ID`), NOT the bridge default `'82'`; the Lyra panel expects the inverter on 0x42. `source_id` in the entry overrides it.

---

## File structure

| File | Responsibility |
|---|---|
| `rvc2mqtt/rvc_encode.py` (create) | Three pure uint16 encoders (V/A/Hz) — inverse of `RVC_Decoder._convert_unit`. Seed for a future generic encoder. |
| `rvc2mqtt/entity/__init__.py` (modify) | Add no-op `tick(now: float)` to `EntityPluginBaseClass`. |
| `rvc2mqtt/app.py` (modify) | Extract `_loop_once(now)` from `main()`'s `while True`; call `entity.tick(now)`; add `_warn_instance_collisions()` after entity build in `main()` and `_do_reload()`. |
| `rvc2mqtt/entity/virtual_inverter.py` (create) | `VirtualInverter` entity: config parsing, MQTT ingestion, status mapping, frame building, tick cadence, command path, mirror, HA discovery. |
| `test/rvc_encode_test.py` (create) | Encoder tests. |
| `test/virtual_inverter_test.py` (create) | Entity tests. |
| `test/app_loop_test.py` (create) | `tick` dispatch + collision warning tests. |
| `docs/configuration.md` (modify) | New "Virtual inverter (`virtual_inverter`)" section. |

---

### Task 1: uint16 encoders

**Files:**
- Create: `rvc2mqtt/rvc_encode.py`
- Test: `test/rvc_encode_test.py`

**Interfaces:**
- Produces:
  - `U16_NA: int = 0xFFFF`
  - `encode_voltage_u16(volts: float | None) -> int`
  - `encode_current_u16(amps: float | None) -> int`
  - `encode_frequency_u16(hz: float | None) -> int`
  - `u16_le(value: int) -> bytes` (2 bytes, little-endian)

- [ ] **Step 1: Write the failing tests**

```python
# test/rvc_encode_test.py
import unittest
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.rvc_encode import (
    U16_NA, encode_voltage_u16, encode_current_u16, encode_frequency_u16, u16_le,
)


class Test_Encoders(unittest.TestCase):

    def setUp(self):
        self.dec = RVC_Decoder()

    def test_none_is_not_available(self):
        self.assertEqual(encode_voltage_u16(None), U16_NA)
        self.assertEqual(encode_current_u16(None), U16_NA)
        self.assertEqual(encode_frequency_u16(None), U16_NA)

    def test_voltage_round_trips(self):
        for v in (0.0, 12.8, 52.0, 120.0, 228.8):
            raw = encode_voltage_u16(v)
            self.assertEqual(self.dec._convert_unit(raw, "v", "uint16"), v)

    def test_current_round_trips(self):
        for a in (-50.0, 0.0, 3.8, 40.0):
            raw = encode_current_u16(a)
            self.assertEqual(self.dec._convert_unit(raw, "a", "uint16"), a)

    def test_frequency_round_trips(self):
        for hz in (0.0, 50.0, 60.0):
            raw = encode_frequency_u16(hz)
            self.assertEqual(self.dec._convert_unit(raw, "hz", "uint16"), hz)

    def test_clamps_to_valid_range(self):
        self.assertEqual(encode_voltage_u16(-5), 0)
        self.assertEqual(encode_voltage_u16(99999), 0xFFFE)
        self.assertEqual(encode_current_u16(-2000), 0)
        self.assertEqual(encode_frequency_u16(99999), 0xFFFE)

    def test_u16_le(self):
        self.assertEqual(u16_le(0x0410), b"\x10\x04")
        self.assertEqual(u16_le(U16_NA), b"\xff\xff")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/rvc_encode_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rvc2mqtt.rvc_encode'`

- [ ] **Step 3: Write the implementation**

```python
# rvc2mqtt/rvc_encode.py
"""
Encoders for RV-C numeric fields.

Inverse of RVC_Decoder._convert_unit for the uint16 types used by the
virtual inverter.  See RV-C spec table 5.3.

SPDX-License-Identifier: Apache-2.0
(Apache-2.0 license block as in rvc2mqtt/entity/water_pump.py)
"""

U16_NA = 0xFFFF


def _clamp_u16(value: float) -> int:
    """Clamp to the valid data range; 0xFFFF is reserved for 'not available'."""
    return max(0, min(0xFFFE, int(round(value))))


def encode_voltage_u16(volts) -> int:
    """0.05 V/bit, no offset."""
    if volts is None:
        return U16_NA
    return _clamp_u16(volts / 0.05)


def encode_current_u16(amps) -> int:
    """0.05 A/bit, -1600 A offset."""
    if amps is None:
        return U16_NA
    return _clamp_u16((amps + 1600) / 0.05)


def encode_frequency_u16(hz) -> int:
    """1/128 Hz/bit."""
    if hz is None:
        return U16_NA
    return _clamp_u16(hz * 128)


def u16_le(value: int) -> bytes:
    """Two little-endian bytes (RV-C byte order)."""
    return bytes((value & 0xFF, (value >> 8) & 0xFF))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/rvc_encode_test.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add rvc2mqtt/rvc_encode.py test/rvc_encode_test.py
git commit -m "Add uint16 V/A/Hz encoders for RV-C transmit

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `tick()` hook in the entity base class and app loop

**Files:**
- Modify: `rvc2mqtt/entity/__init__.py` (after `initialize()`, ~line 80)
- Modify: `rvc2mqtt/app.py:147-153` (the `while True` loop in `main()`)
- Test: `test/app_loop_test.py`

**Interfaces:**
- Produces:
  - `EntityPluginBaseClass.tick(self, now: float) -> None` — default no-op. `now` is `time.monotonic()` seconds.
  - `app._loop_once(self, now: float) -> None` — one iteration of the main loop: reload check, rx, tick all entities, tx.

- [ ] **Step 1: Write the failing tests**

```python
# test/app_loop_test.py
"""
Tests for the app main-loop helpers: entity tick dispatch and
instance-collision warnings.
"""
import threading
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.app import app as AppClass
from rvc2mqtt.entity import EntityPluginBaseClass


def _make_app():
    a = AppClass.__new__(AppClass)
    a.Logger = MagicMock()
    a._reload_requested = threading.Event()
    a.message_rx_loop = MagicMock()
    a.message_tx_loop = MagicMock()
    a._do_reload = MagicMock()
    a.entity_list = []
    return a


class Test_LoopOnce(unittest.TestCase):

    def test_ticks_every_entity_with_now(self):
        a = _make_app()
        e1, e2 = MagicMock(), MagicMock()
        a.entity_list = [e1, e2]
        a._loop_once(123.5)
        e1.tick.assert_called_once_with(123.5)
        e2.tick.assert_called_once_with(123.5)

    def test_rx_then_tick_then_tx_order(self):
        a = _make_app()
        order = []
        a.message_rx_loop.side_effect = lambda: order.append("rx")
        a.message_tx_loop.side_effect = lambda: order.append("tx")
        e = MagicMock()
        e.tick.side_effect = lambda now: order.append("tick")
        a.entity_list = [e]
        a._loop_once(1.0)
        self.assertEqual(order, ["rx", "tick", "tx"])

    def test_reload_runs_when_requested(self):
        a = _make_app()
        a._reload_requested.set()
        a._loop_once(1.0)
        a._do_reload.assert_called_once()

    def test_reload_not_run_when_not_requested(self):
        a = _make_app()
        a._loop_once(1.0)
        a._do_reload.assert_not_called()


class Test_BaseTick(unittest.TestCase):

    def test_base_tick_is_noop(self):
        class Dummy(EntityPluginBaseClass):
            def __init__(self):
                self.id = "dummy"
                mock = MagicMock()
                mock.make_device_topic_string.return_value = "t"
                mock.TOPIC_BASE = "rvc2mqtt"
                mock.client_id = "bridge"
                super().__init__({}, mock)
        Dummy().tick(0.0)  # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/app_loop_test.py -v`
Expected: `Test_LoopOnce` FAIL with `AttributeError: 'app' object has no attribute '_loop_once'`; `Test_BaseTick` FAIL with `AttributeError: ... 'tick'`.

- [ ] **Step 3: Add `tick` to the base class**

In `rvc2mqtt/entity/__init__.py`, directly after the `initialize()` method:

```python
    def tick(self, now: float):
        """ Optional function
        Called once per main-loop iteration with time.monotonic() seconds.
        Entities that transmit periodically override this; the default does nothing.
        Keep it cheap: it runs roughly every millisecond.
        """
        pass
```

- [ ] **Step 4: Extract `_loop_once` in `app.py`**

Replace the `while True:` block in `app.main()` (currently):

```python
        # Our RVC message loop here
        while True:
            if self._reload_requested.is_set():
                self._do_reload()
            # process any received messages
            self.message_rx_loop()
            self.message_tx_loop()
            time.sleep(0.001)
```

with:

```python
        # Our RVC message loop here
        while True:
            self._loop_once(time.monotonic())
            time.sleep(0.001)
```

and add this method to the `app` class, immediately before `def _do_reload(self):`:

```python
    def _loop_once(self, now: float):
        """One iteration of the main loop: reload if requested, drain rx,
        give every entity a periodic tick, then drain tx."""
        if self._reload_requested.is_set():
            self._do_reload()
        # process any received messages
        self.message_rx_loop()
        for entity in self.entity_list:
            entity.tick(now)
        self.message_tx_loop()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest test/app_loop_test.py test/reload_test.py -v`
Expected: all pass (reload tests confirm the refactor didn't disturb `_do_reload`).

- [ ] **Step 6: Commit**

```bash
git add rvc2mqtt/entity/__init__.py rvc2mqtt/app.py test/app_loop_test.py
git commit -m "Add per-loop tick() hook for entities

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `VirtualInverter` construction, config parsing and MQTT ingestion

**Files:**
- Create: `rvc2mqtt/entity/virtual_inverter.py`
- Test: `test/virtual_inverter_test.py`

**Interfaces:**
- Consumes: `EntityPluginBaseClass`, `MQTT_Support.register(topic, func, retain_ok=...)`.
- Produces (used by Tasks 4-7):
  - class `VirtualInverter(EntityPluginBaseClass)`, `FACTORY_MATCH_ATTRIBUTES = {"name": "VIRTUAL_INVERTER", "type": "virtual_inverter"}`
  - module constants `FIELD_DEFAULTS: dict`, `NUMERIC_FIELDS: tuple`, `BOOL_FIELDS: tuple`
  - module constant `DEFAULT_INVERTER_SOURCE_ID = "42"`
  - attributes: `rvc_instance: int`, `name: str`, `source_topic_base: str`, `interval: float`, `stale_timeout: float`, `source_id: str`, `field_topics: dict[str, tuple[str, float]]`, `values: dict[str, object]`, `connected: bool`, `last_status_update: float`, `next_tx: float`, `topic_base: str` (mirror base), `command_topic: str`, `connected_topic: str`, `onoff_set_topic: str`, `_clock: callable` (defaults to `time.monotonic`; tests replace it)
  - `process_mqtt_msg(topic, payload, properties=None)`
  - `_ingest(field: str, payload: str) -> bool` (True if state changed)

- [ ] **Step 1: Write the failing tests**

```python
# test/virtual_inverter_test.py
"""
Unit tests for the virtual inverter entity.
"""
import os
import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
import rvc2mqtt
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.entity.virtual_inverter import VirtualInverter, FIELD_DEFAULTS


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.side_effect = (
        lambda id, comp, sub=None: f'homeassistant/{comp}/{id}/{sub}/config')
    return mock


def _make_entity(extra: dict = None, now: float = 1000.0):
    mock = _make_mock()
    data = {
        'name': 'VIRTUAL_INVERTER',
        'type': 'virtual_inverter',
        'instance': 1,
        'instance_name': 'renogy',
        'status_topic': 'rvc/state/inverter',
        'command_topic': 'rvc/set/inverter',
    }
    if extra:
        data.update(extra)
    entity = VirtualInverter(data, mock)
    clock = {'now': now}
    entity._clock = lambda: clock['now']
    entity.set_rvc_send_queue(queue.Queue())
    return entity, mock, clock


def _registered(mock) -> dict:
    """topic -> (callback, retain_ok) from mock.register calls."""
    out = {}
    for c in mock.register.call_args_list:
        args, kwargs = c
        topic, func = args[0], args[1]
        retain_ok = kwargs.get('retain_ok', args[2] if len(args) > 2 else False)
        out[topic] = (func, retain_ok)
    return out


def _published(mock) -> list:
    """[(topic, payload, retain)] from mock.client.publish calls."""
    out = []
    for c in mock.client.publish.call_args_list:
        args, kwargs = c
        out.append((args[0], args[1], kwargs.get('retain', False)))
    return out


class Test_Construction(unittest.TestCase):

    def test_defaults(self):
        e, mock, _ = _make_entity()
        self.assertEqual(e.rvc_instance, 1)
        self.assertEqual(e.source_topic_base, 'modbus/inverter')
        self.assertEqual(e.interval, 1.0)
        self.assertEqual(e.stale_timeout, 30.0)
        self.assertEqual(e.source_id, '42')
        self.assertEqual(e.topic_base, 'rvc/state/inverter')
        self.assertEqual(e.command_topic, 'rvc/set/inverter/enable')
        self.assertEqual(e.onoff_set_topic, 'modbus/inverter/set/onoff')
        self.assertEqual(e.connected_topic, 'modbus/inverter/connected')

    def test_default_field_topics(self):
        e, _, _ = _make_entity()
        self.assertEqual(e.field_topics['status'], ('modbus/inverter/state/status', 1.0))
        self.assertEqual(e.field_topics['enabled'], ('modbus/inverter/state/onoff', 1.0))
        self.assertEqual(e.field_topics['fault'], ('modbus/inverter/state/fault', 1.0))
        self.assertEqual(e.field_topics['ac_in_voltage'],
                         ('modbus/inverter/state/AC_Input_Voltage', 0.1))
        for f in ('ac_out_voltage', 'ac_out_current', 'ac_out_frequency',
                  'dc_voltage', 'dc_current'):
            self.assertNotIn(f, e.field_topics)

    def test_state_topics_registered_with_retain_ok(self):
        e, mock, _ = _make_entity()
        reg = _registered(mock)
        for topic, _scale in e.field_topics.values():
            self.assertIn(topic, reg)
            self.assertTrue(reg[topic][1], f"{topic} must be retain_ok=True")
        self.assertTrue(reg['modbus/inverter/connected'][1])
        self.assertIn('rvc/set/inverter/enable', reg)
        self.assertFalse(reg['rvc/set/inverter/enable'][1])

    def test_fields_string_form_joins_base_with_scale_1(self):
        e, _, _ = _make_entity({'fields': {'dc_voltage': 'state/battery_voltage'}})
        self.assertEqual(e.field_topics['dc_voltage'],
                         ('modbus/inverter/state/battery_voltage', 1.0))

    def test_fields_mapping_form_with_scale(self):
        e, _, _ = _make_entity({'fields': {'dc_voltage': {'topic': 'state/bv', 'scale': 0.1}}})
        self.assertEqual(e.field_topics['dc_voltage'], ('modbus/inverter/state/bv', 0.1))

    def test_fields_absolute_topic_used_verbatim(self):
        e, _, _ = _make_entity({'fields': {'dc_voltage': 'modbus/inverter/state/x'}})
        self.assertEqual(e.field_topics['dc_voltage'][0], 'modbus/inverter/state/x')

    def test_fields_null_unmaps_default(self):
        e, _, _ = _make_entity({'fields': {'ac_in_voltage': None}})
        self.assertNotIn('ac_in_voltage', e.field_topics)

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            _make_entity({'fields': {'bogus': 'state/x'}})

    def test_bad_interval_raises(self):
        with self.assertRaises(ValueError):
            _make_entity({'interval': 0})
        with self.assertRaises(ValueError):
            _make_entity({'stale_timeout': -1})

    def test_custom_source_base_and_source_id(self):
        e, _, _ = _make_entity({'source_topic_base': 'mb/inv/', 'source_id': 'A0'})
        self.assertEqual(e.source_topic_base, 'mb/inv')
        self.assertEqual(e.field_topics['status'][0], 'mb/inv/state/status')
        self.assertEqual(e.source_id, 'A0')


class Test_Ingest(unittest.TestCase):

    def _feed(self, e, mock, topic, payload):
        _registered(mock)[topic][0](topic, payload)

    def test_status_int_parsed_and_timestamps(self):
        e, mock, clock = _make_entity(now=50.0)
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        self.assertEqual(e.values['status'], 5)
        self.assertEqual(e.last_status_update, 50.0)

    def test_enabled_bool_forms(self):
        e, mock, _ = _make_entity()
        for p, want in (('1', True), ('0', False), ('on', True), ('OFF', False),
                        ('true', True), ('False', False)):
            self._feed(e, mock, 'modbus/inverter/state/onoff', p)
            self.assertEqual(e.values['enabled'], want, p)

    def test_enabled_updates_status_timestamp(self):
        e, mock, clock = _make_entity(now=7.0)
        self._feed(e, mock, 'modbus/inverter/state/onoff', '1')
        self.assertEqual(e.last_status_update, 7.0)

    def test_numeric_scaled(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', '1208')
        self.assertAlmostEqual(e.values['ac_in_voltage'], 120.8)

    def test_bad_payload_keeps_previous(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '4')
        self._feed(e, mock, 'modbus/inverter/state/status', 'banana')
        self.assertEqual(e.values['status'], 4)
        self._feed(e, mock, 'modbus/inverter/state/onoff', 'maybe')
        self.assertIsNone(e.values['enabled'])
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', '')
        self.assertIsNone(e.values['ac_in_voltage'])

    def test_connected_topic(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.connected)
        self._feed(e, mock, 'modbus/inverter/connected', 'offline')
        self.assertFalse(e.connected)
        self._feed(e, mock, 'modbus/inverter/connected', 'online')
        self.assertTrue(e.connected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/virtual_inverter_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rvc2mqtt.entity.virtual_inverter'`

- [ ] **Step 3: Write the entity skeleton with config parsing and ingestion**

```python
# rvc2mqtt/entity/virtual_inverter.py
"""
Virtual inverter: presents a Modbus inverter (published on MQTT by
modbus2mqtt) as an RV-C inverter node.

Subscribes to modbus2mqtt state topics, transmits INVERTER_STATUS,
INVERTER_AC_STATUS_1 and INVERTER_DC_STATUS on a schedule, answers
INVERTER_COMMAND by writing modbus2mqtt's set/onoff topic, and mirrors
state to the same rvc/state/inverter topics the real inverter entity uses.

Design: docs/superpowers/specs/2026-08-23-virtual-inverter-design.md

SPDX-License-Identifier: Apache-2.0
(Apache-2.0 license block as in rvc2mqtt/entity/water_pump.py)
"""

import json
import logging
import time
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass
from rvc2mqtt.rvc_encode import (
    encode_voltage_u16, encode_current_u16, encode_frequency_u16, u16_le)


# field -> default {"topic": <relative to source_topic_base>, "scale": float} or None (unmapped)
FIELD_DEFAULTS = {
    "status":           {"topic": "state/status", "scale": 1.0},
    "enabled":          {"topic": "state/onoff", "scale": 1.0},
    "fault":            {"topic": "state/fault", "scale": 1.0},
    "ac_in_voltage":    {"topic": "state/AC_Input_Voltage", "scale": 0.1},
    "ac_out_voltage":   None,
    "ac_out_current":   None,
    "ac_out_frequency": None,
    "dc_voltage":       None,
    "dc_current":       None,
}
BOOL_FIELDS = ("enabled", "fault")
NUMERIC_FIELDS = ("ac_in_voltage", "ac_out_voltage", "ac_out_current",
                  "ac_out_frequency", "dc_voltage", "dc_current")

# Modbus (SRNE register 4405) status code -> RV-C INVERTER_STATUS.status
SRNE_TO_RVC_STATUS = {
    0: 0,   # Power-up delay           -> disabled
    1: 0,   # Waiting state            -> disabled
    2: 0,   # Initialization           -> disabled
    3: 5,   # Soft start               -> waiting to invert
    4: 2,   # Mains powered operation  -> ac passthru
    5: 1,   # Inverter powered         -> invert
    6: 5,   # Inverter to mains        -> waiting to invert
    7: 5,   # Mains to inverter        -> waiting to invert
    10: 0,  # Shutdown                 -> disabled
    11: 0,  # Fault                    -> disabled
}
RVC_STATUS_DEFINITION = {0: "disabled", 1: "invert", 2: "ac passthru",
                         5: "waiting to invert"}
RVC_STATUS_PASSTHRU = 2

# RV-C source address the virtual inverter transmits from.  The Lyra panel
# looks for the inverter on 0x42; the bridge's own frames stay on 0x82.
DEFAULT_INVERTER_SOURCE_ID = "42"


def _parse_bool(payload: str) -> bool:
    p = str(payload).strip().lower()
    if p in ("1", "on", "true"):
        return True
    if p in ("0", "off", "false"):
        return False
    raise ValueError(f"not a boolean payload: {payload!r}")


class VirtualInverter(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "VIRTUAL_INVERTER", "type": "virtual_inverter"}

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = int(data['instance'])
        self.id = "virtual-inverter-1FFD4-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        self.name = data.get('instance_name', f"virtual inverter {self.rvc_instance}")
        self.source_topic_base = str(data.get('source_topic_base', 'modbus/inverter')).rstrip('/')
        self.interval = float(data.get('interval', 1.0))
        self.stale_timeout = float(data.get('stale_timeout', 30.0))
        if self.interval <= 0:
            raise ValueError(f"interval must be > 0, got {self.interval}")
        if self.stale_timeout <= 0:
            raise ValueError(f"stale_timeout must be > 0, got {self.stale_timeout}")
        self.source_id = str(data.get('source_id', DEFAULT_INVERTER_SOURCE_ID))
        self.field_topics = self._resolve_fields(data.get('fields') or {})

        # Runtime state.  MQTT callbacks (paho thread) write single items into
        # self.values; tick() (main thread) reads them one at a time.  Single
        # dict-item assignment is atomic in CPython, so no lock is needed.
        self.values = {name: None for name in FIELD_DEFAULTS}
        self.connected = True
        self.last_status_update = float('-inf')
        self.next_tx = 0.0
        self._clock = time.monotonic
        self._silent = False
        self._warned_codes = set()
        self._mirror_cache = {}

        # Topics
        if 'status_topic' in data:
            self.topic_base = str(data['status_topic'])
        else:
            self.topic_base = mqtt_support.make_device_topic_string(self.id, None, True)
        if 'command_topic' in data:
            self.command_topic = f"{data['command_topic']}/enable"
        else:
            self.command_topic = mqtt_support.make_device_topic_string(self.id, None, False)
        self.connected_topic = f"{self.source_topic_base}/connected"
        self.onoff_set_topic = f"{self.source_topic_base}/set/onoff"

        # Subscriptions.  State topics MUST use retain_ok=True: the default
        # clears the retained value on the broker, which would wipe
        # modbus2mqtt's published state.
        self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.connected_topic, self.process_mqtt_msg, retain_ok=True)
        self._topic_fields = {}
        for field, (topic, _scale) in self.field_topics.items():
            self._topic_fields.setdefault(topic, []).append(field)
        for topic in self._topic_fields:
            self.mqtt_support.register(topic, self.process_mqtt_msg, retain_ok=True)

        self.device = {"manufacturer": "RV-C",
                       "via_device": self.mqtt_support.get_bridge_ha_name(),
                       "identifiers": self.unique_device_id,
                       "name": self.name,
                       "model": "Virtual RV-C inverter bridged from Modbus"}

    # ---- configuration -------------------------------------------------

    def _join_topic(self, topic: str) -> str:
        topic = str(topic)
        if topic.startswith(self.source_topic_base + "/"):
            return topic
        return f"{self.source_topic_base}/{topic}"

    def _resolve_fields(self, fields_cfg: dict) -> dict:
        """Return {field: (absolute_topic, scale)} for every mapped field."""
        resolved = {}
        for field, default in FIELD_DEFAULTS.items():
            if default is not None:
                resolved[field] = (self._join_topic(default["topic"]), float(default["scale"]))
        for field, cfg in fields_cfg.items():
            if field not in FIELD_DEFAULTS:
                raise ValueError(
                    f"unknown virtual inverter field {field!r}; "
                    f"valid: {', '.join(FIELD_DEFAULTS)}")
            if cfg is None:
                resolved.pop(field, None)
            elif isinstance(cfg, dict):
                if 'topic' not in cfg:
                    raise ValueError(f"field {field!r} mapping needs a 'topic'")
                resolved[field] = (self._join_topic(cfg['topic']), float(cfg.get('scale', 1.0)))
            else:
                resolved[field] = (self._join_topic(cfg), 1.0)
        return resolved

    # ---- MQTT in --------------------------------------------------------

    def process_mqtt_msg(self, topic, payload, properties=None):
        if topic == self.command_topic:
            self._handle_enable_command(payload)
            return
        if topic == self.connected_topic:
            self.connected = str(payload).strip().lower() == "online"
            self.Logger.info(f"{self.name}: modbus source is "
                             f"{'online' if self.connected else 'offline'}")
            return
        for field in self._topic_fields.get(topic, ()):
            self._ingest(field, payload)

    def _ingest(self, field: str, payload) -> bool:
        """Parse payload for field; update self.values.  Returns True if changed."""
        try:
            if field == "status":
                value = int(str(payload).strip())
            elif field in BOOL_FIELDS:
                value = _parse_bool(payload)
            else:
                _topic, scale = self.field_topics[field]
                value = float(str(payload).strip()) * scale
        except (ValueError, TypeError):
            self.Logger.warning(f"{self.name}: ignoring bad payload {payload!r} for {field}")
            return False
        if field in ("status", "enabled"):
            self.last_status_update = self._clock()
        changed = self.values[field] != value
        self.values[field] = value
        return changed

    def _handle_enable_command(self, payload):
        # Implemented in Task 6
        pass

    # ---- RV-C in --------------------------------------------------------

    def process_rvc_msg(self, new_message: dict) -> bool:
        # Implemented in Task 6
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/virtual_inverter_test.py -v`
Expected: all `Test_Construction` and `Test_Ingest` tests pass (17 passed).

- [ ] **Step 5: Confirm the plugin loader picks it up**

Run: `pytest test/plugin_support_test.py test/entity_factory_test.py -v`
Expected: pass (the loader imports every module in `rvc2mqtt/entity/`; an import error here would show up).

- [ ] **Step 6: Commit**

```bash
git add rvc2mqtt/entity/virtual_inverter.py test/virtual_inverter_test.py
git commit -m "Add virtual inverter entity: config parsing and MQTT ingestion

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Status mapping and frame building

**Files:**
- Modify: `rvc2mqtt/entity/virtual_inverter.py`
- Test: `test/virtual_inverter_test.py`

**Interfaces:**
- Consumes: `SRNE_TO_RVC_STATUS`, `RVC_STATUS_PASSTHRU`, encoders from Task 1.
- Produces:
  - `rvc_status(self) -> int`
  - `build_frames(self) -> list[dict]` — four send-queue dicts in order: `INVERTER_STATUS`, `INVERTER_AC_STATUS_1` (input), `INVERTER_AC_STATUS_1` (output), `INVERTER_DC_STATUS`.

- [ ] **Step 1: Write the failing tests** (append to `test/virtual_inverter_test.py`)

```python
SPEC = os.path.join(os.path.dirname(rvc2mqtt.__file__), 'rvc-spec.yml')


def _decoder():
    d = RVC_Decoder()
    d.load_rvc_spec(SPEC)
    return d


def _decode(frame: dict) -> dict:
    d = _decoder()
    arb = d._rvc_to_can_frame(frame)
    return d.rvc_decode(arb, bytes(frame["data"]).hex().upper())


class Test_StatusMapping(unittest.TestCase):

    def _with_status(self, code, fault=None):
        e, _, _ = _make_entity()
        e.values['status'] = code
        e.values['fault'] = fault
        return e

    def test_table(self):
        expected = {0: 0, 1: 0, 2: 0, 3: 5, 4: 2, 5: 1, 6: 5, 7: 5, 10: 0, 11: 0}
        for code, want in expected.items():
            self.assertEqual(self._with_status(code).rvc_status(), want, code)

    def test_unknown_and_none_are_disabled(self):
        self.assertEqual(self._with_status(None).rvc_status(), 0)
        self.assertEqual(self._with_status(8).rvc_status(), 0)
        self.assertEqual(self._with_status(99).rvc_status(), 0)

    def test_fault_forces_disabled(self):
        self.assertEqual(self._with_status(5, fault=True).rvc_status(), 0)
        self.assertEqual(self._with_status(5, fault=False).rvc_status(), 1)

    def test_unknown_code_warns_once(self):
        e = self._with_status(42)
        e.Logger = MagicMock()
        e.rvc_status()
        e.rvc_status()
        self.assertEqual(e.Logger.warning.call_count, 1)


class Test_Frames(unittest.TestCase):

    def test_four_frames_with_source_id(self):
        e, _, _ = _make_entity({'source_id': 'A5'})
        frames = e.build_frames()
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FEE8'])
        for f in frames:
            self.assertEqual(f['source_id'], 'A5')
            self.assertEqual(len(f['data']), 8)

    def test_inverter_status_inverting_enabled(self):
        e, _, _ = _make_entity()
        e.values.update(status=5, enabled=True)
        msg = _decode(e.build_frames()[0])
        self.assertEqual(msg['name'], 'INVERTER_STATUS')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['status_definition'], 'invert')
        self.assertEqual(msg['inverter_enabled'], '01')
        self.assertEqual(msg['pass-through_enabled'], '00')
        self.assertEqual(msg['load_sense_enabled'], '11')
        self.assertEqual(msg['battery_temperature_sensor_present'], '11')
        self.assertEqual(msg['generator_support_enabled'], '11')
        self.assertEqual(msg['data'][6:], 'FFFFFFFFFF')  # bytes 3-7 (byte 3 = 0xFF incl. gen support bits)

    def test_inverter_status_passthru_disabled(self):
        e, _, _ = _make_entity()
        e.values.update(status=4, enabled=False)
        msg = _decode(e.build_frames()[0])
        self.assertEqual(msg['status_definition'], 'ac passthru')
        self.assertEqual(msg['inverter_enabled'], '00')
        self.assertEqual(msg['pass-through_enabled'], '01')

    def test_inverter_status_unknown_enabled_is_11(self):
        e, _, _ = _make_entity()
        e.values.update(status=0)
        msg = _decode(e.build_frames()[0])
        self.assertEqual(msg['inverter_enabled'], '11')

    def test_ac_status_input_frame(self):
        e, _, _ = _make_entity()
        e.values.update(ac_in_voltage=120.8)
        msg = _decode(e.build_frames()[1])
        self.assertEqual(msg['name'], 'INVERTER_AC_STATUS_1')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['line_definition'], 1)
        self.assertEqual(msg['input_output_definition'], 'input')
        self.assertEqual(msg['rms_voltage'], 120.8)
        self.assertEqual(msg['rms_current'], 'n/a')
        self.assertEqual(msg['frequency'], 0xFFFF)  # decoder returns raw 0xFFFF for Hz n/a
        self.assertEqual(msg['data'][14:], 'FF')

    def test_ac_status_output_frame(self):
        e, _, _ = _make_entity()
        e.values.update(ac_out_voltage=119.5, ac_out_current=3.8, ac_out_frequency=60.0)
        msg = _decode(e.build_frames()[2])
        self.assertEqual(msg['input_output_definition'], 'output')
        self.assertEqual(msg['rms_voltage'], 119.5)
        self.assertEqual(msg['rms_current'], 3.8)
        self.assertEqual(msg['frequency'], 60.0)

    def test_ac_status_all_unmapped_still_sent(self):
        e, _, _ = _make_entity()
        msg = _decode(e.build_frames()[2])
        self.assertEqual(msg['rms_voltage'], 'n/a')
        self.assertEqual(msg['rms_current'], 'n/a')

    def test_dc_status_frame(self):
        e, _, _ = _make_entity()
        e.values.update(dc_voltage=52.0, dc_current=-12.5)
        msg = _decode(e.build_frames()[3])
        self.assertEqual(msg['name'], 'INVERTER_DC_STATUS')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['dc_voltage'], 52.0)
        self.assertEqual(msg['dc_amperage'], -12.5)
        self.assertEqual(msg['data'][10:], 'FFFFFF')

    def test_dc_status_not_available(self):
        e, _, _ = _make_entity()
        msg = _decode(e.build_frames()[3])
        self.assertEqual(msg['dc_voltage'], 'n/a')
        self.assertEqual(msg['dc_amperage'], 'n/a')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/virtual_inverter_test.py -k "StatusMapping or Frames" -v`
Expected: FAIL with `AttributeError: 'VirtualInverter' object has no attribute 'rvc_status'` / `'build_frames'`.

- [ ] **Step 3: Implement mapping and frame building**

Add to `VirtualInverter` (after the `# ---- RV-C in` section):

```python
    # ---- RV-C out -------------------------------------------------------

    def rvc_status(self) -> int:
        """Map the Modbus status code (plus fault flag) to INVERTER_STATUS.status."""
        if self.values.get('fault') is True:
            return 0
        code = self.values.get('status')
        if code in SRNE_TO_RVC_STATUS:
            return SRNE_TO_RVC_STATUS[code]
        if code is not None and code not in self._warned_codes:
            self._warned_codes.add(code)
            self.Logger.warning(f"{self.name}: unknown modbus status code {code}; reporting disabled")
        return 0

    @staticmethod
    def _bit2(value) -> int:
        """RV-C 2-bit field: 00 off, 01 on, 11 not available."""
        if value is None:
            return 0b11
        return 0b01 if value else 0b00

    def _inverter_status_frame(self) -> dict:
        status = self.rvc_status()
        byte2 = (0b11                                   # bits 0-1 battery temp sensor: n/a
                 | (0b11 << 2)                          # bits 2-3 load sense: n/a
                 | (self._bit2(self.values['enabled']) << 4)   # bits 4-5 inverter enabled
                 | ((0b01 if status == RVC_STATUS_PASSTHRU else 0b00) << 6))  # bits 6-7 pass-through
        data = bytes([self.rvc_instance & 0xFF, status & 0xFF, byte2,
                      0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        return {"dgn": "1FFD4", "data": data, "source_id": self.source_id}

    def _ac_status_frame(self, output: bool) -> dict:
        if output:
            volts = self.values['ac_out_voltage']
            amps = self.values['ac_out_current']
            hz = self.values['ac_out_frequency']
        else:
            volts, amps, hz = self.values['ac_in_voltage'], None, None
        byte0 = (self.rvc_instance & 0x0F) | (0b00 << 4) | ((0b01 if output else 0b00) << 6)
        data = (bytes([byte0])
                + u16_le(encode_voltage_u16(volts))
                + u16_le(encode_current_u16(amps))
                + u16_le(encode_frequency_u16(hz))
                + bytes([0xFF]))
        return {"dgn": "1FFD7", "data": data, "source_id": self.source_id}

    def _dc_status_frame(self) -> dict:
        data = (bytes([self.rvc_instance & 0xFF])
                + u16_le(encode_voltage_u16(self.values['dc_voltage']))
                + u16_le(encode_current_u16(self.values['dc_current']))
                + bytes([0xFF, 0xFF, 0xFF]))
        return {"dgn": "1FEE8", "data": data, "source_id": self.source_id}

    def build_frames(self) -> list:
        """The full status set transmitted each interval."""
        return [self._inverter_status_frame(),
                self._ac_status_frame(output=False),
                self._ac_status_frame(output=True),
                self._dc_status_frame()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/virtual_inverter_test.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rvc2mqtt/entity/virtual_inverter.py test/virtual_inverter_test.py
git commit -m "Virtual inverter: status mapping and RV-C frame building

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `tick()` cadence, staleness and offline silence

**Files:**
- Modify: `rvc2mqtt/entity/virtual_inverter.py`
- Test: `test/virtual_inverter_test.py`

**Interfaces:**
- Consumes: `build_frames()`, `send_queue` (set by `set_rvc_send_queue`), `_clock`.
- Produces: `tick(self, now: float)`, `initialize(self)`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _drain(q: queue.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get())
    return out


class Test_Tick(unittest.TestCase):

    def _ready(self, now=100.0):
        e, mock, clock = _make_entity(now=now)
        e.initialize()
        # a fresh status arrived "now"
        _registered(mock)['modbus/inverter/state/status'][0]('modbus/inverter/state/status', '5')
        return e, mock, clock

    def test_nothing_before_first_status(self):
        e, _, _ = _make_entity(now=100.0)
        e.initialize()
        e.tick(100.0)
        e.tick(200.0)
        self.assertEqual(_drain(e.send_queue), [])

    def test_first_tick_sends_full_set(self):
        e, _, _ = self._ready(100.0)
        e.tick(100.0)
        frames = _drain(e.send_queue)
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FEE8'])

    def test_respects_interval(self):
        e, _, _ = self._ready(100.0)
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(100.5)
        self.assertEqual(_drain(e.send_queue), [])
        e.tick(101.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_custom_interval(self):
        e, mock, clock = _make_entity({'interval': 5.0}, now=100.0)
        e.initialize()
        _registered(mock)['modbus/inverter/state/status'][0]('modbus/inverter/state/status', '4')
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(104.9)
        self.assertEqual(_drain(e.send_queue), [])
        e.tick(105.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_silent_when_stale(self):
        e, _, clock = self._ready(100.0)
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(131.0)  # > stale_timeout (30 s) since last status
        self.assertEqual(_drain(e.send_queue), [])

    def test_resumes_after_fresh_status(self):
        e, mock, clock = self._ready(100.0)
        e.tick(131.0)
        self.assertEqual(_drain(e.send_queue), [])
        clock['now'] = 131.5
        _registered(mock)['modbus/inverter/state/onoff'][0]('modbus/inverter/state/onoff', '1')
        e.tick(132.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_silent_when_offline(self):
        e, mock, _ = self._ready(100.0)
        _registered(mock)['modbus/inverter/connected'][0]('modbus/inverter/connected', 'offline')
        e.tick(100.0)
        self.assertEqual(_drain(e.send_queue), [])
        _registered(mock)['modbus/inverter/connected'][0]('modbus/inverter/connected', 'online')
        e.tick(101.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_silence_transition_logged_once(self):
        e, _, _ = self._ready(100.0)
        e.Logger = MagicMock()
        e.tick(100.0)
        e.tick(131.0)
        e.tick(132.0)
        e.tick(133.0)
        self.assertEqual(e.Logger.info.call_count, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/virtual_inverter_test.py -k Tick -v`
Expected: FAIL — `AttributeError: ... 'tick'` (the base-class no-op is inherited, so actually: assertions fail because nothing is queued). Either way, red.

- [ ] **Step 3: Implement `tick` and `initialize`**

Add to `VirtualInverter`:

```python
    # ---- lifecycle ------------------------------------------------------

    def initialize(self):
        # Do NOT reset last_status_update/next_tx here: subscriptions were made
        # in __init__, so a retained status may already have arrived on the
        # paho thread before initialize() runs.
        self.publish_ha_discovery_config()

    def _should_transmit(self, now: float) -> bool:
        return self.connected and (now - self.last_status_update) <= self.stale_timeout

    def tick(self, now: float):
        if now < self.next_tx:
            return
        self.next_tx = now + self.interval
        if not self._should_transmit(now):
            if not self._silent:
                self._silent = True
                reason = "modbus source offline" if not self.connected else "status stale"
                self.Logger.info(f"{self.name}: going silent on RV-C ({reason})")
            return
        if self._silent:
            self._silent = False
            self.Logger.info(f"{self.name}: resuming RV-C transmission")
        for frame in self.build_frames():
            self.send_queue.put(frame)
```

`publish_ha_discovery_config()` is still the base-class no-op at this point; Task 7 fills it in.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/virtual_inverter_test.py -v`
Expected: all pass.

Note on `test_silence_transition_logged_once`: the `_ready` helper feeds status before `e.Logger` is replaced, so the only `info` call counted is the "going silent" one. If the count is 2, check that `_ingest` does not log at info level.

- [ ] **Step 5: Commit**

```bash
git add rvc2mqtt/entity/virtual_inverter.py test/virtual_inverter_test.py
git commit -m "Virtual inverter: periodic transmit with stale/offline silence

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Command path — RV-C `INVERTER_COMMAND` and MQTT `…/enable`

**Files:**
- Modify: `rvc2mqtt/entity/virtual_inverter.py`
- Test: `test/virtual_inverter_test.py`

**Interfaces:**
- Consumes: `onoff_set_topic`, `command_topic`, `mqtt_support.client.publish`.
- Produces: `process_rvc_msg(msg) -> bool`, `_handle_enable_command(payload)`, `_set_onoff(enable: bool)`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _cmd(instance=1, enable='01'):
    """A decoded INVERTER_COMMAND dict as produced by RVC_Decoder."""
    return {'name': 'INVERTER_COMMAND', 'dgn': '1FFD3', 'instance': instance,
            'inverter_enable': enable, 'load_sense_enable': '00',
            'pass-through_enable': '01', 'inverter_enable_on_startup': '01',
            'source_id': '9F'}


def _onoff_publishes(mock):
    return [(t, p) for (t, p, _r) in _published(mock) if t == 'modbus/inverter/set/onoff']


class Test_Command(unittest.TestCase):

    def test_rvc_enable_writes_1(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.process_rvc_msg(_cmd(enable='01')))
        self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', '1')])

    def test_rvc_disable_writes_0(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.process_rvc_msg(_cmd(enable='00')))
        self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', '0')])

    def test_rvc_no_change_bits_do_not_write(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.process_rvc_msg(_cmd(enable='11')))
        self.assertTrue(e.process_rvc_msg(_cmd(enable='10')))
        self.assertEqual(_onoff_publishes(mock), [])

    def test_other_instance_not_handled(self):
        e, mock, _ = _make_entity()
        self.assertFalse(e.process_rvc_msg(_cmd(instance=2)))
        self.assertEqual(_onoff_publishes(mock), [])

    def test_onoff_publish_is_not_retained(self):
        e, mock, _ = _make_entity()
        e.process_rvc_msg(_cmd(enable='01'))
        retained = [r for (t, _p, r) in _published(mock) if t == 'modbus/inverter/set/onoff']
        self.assertEqual(retained, [False])

    def test_own_status_dgns_swallowed(self):
        e, mock, _ = _make_entity()
        e.values.update(status=5, enabled=True)
        for frame in e.build_frames():
            self.assertTrue(e.process_rvc_msg(_decode(frame)))
        self.assertEqual(_onoff_publishes(mock), [])

    def test_other_instance_status_not_swallowed(self):
        e, _, _ = _make_entity()
        msg = {'name': 'INVERTER_STATUS', 'dgn': '1FFD4', 'instance': 2}
        self.assertFalse(e.process_rvc_msg(msg))

    def test_unrelated_dgn_not_handled(self):
        e, _, _ = _make_entity()
        self.assertFalse(e.process_rvc_msg({'name': 'DC_SOURCE_STATUS_1', 'instance': 1}))

    def test_mqtt_enable_topic(self):
        e, mock, _ = _make_entity()
        cb = _registered(mock)['rvc/set/inverter/enable'][0]
        for payload, want in (('on', '1'), ('OFF', '0'), ('1', '1'), ('0', '0'),
                              ('true', '1'), ('false', '0')):
            mock.client.publish.reset_mock()
            cb('rvc/set/inverter/enable', payload)
            self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', want)], payload)

    def test_mqtt_enable_bad_payload_warns_no_write(self):
        e, mock, _ = _make_entity()
        e.Logger = MagicMock()
        _registered(mock)['rvc/set/inverter/enable'][0]('rvc/set/inverter/enable', 'maybe')
        self.assertEqual(_onoff_publishes(mock), [])
        e.Logger.warning.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/virtual_inverter_test.py -k Command -v`
Expected: FAIL — `process_rvc_msg` returns `False`, no publishes.

- [ ] **Step 3: Implement the command path**

Replace the two stubs from Task 3 (`_handle_enable_command` and `process_rvc_msg`) with:

```python
    def _set_onoff(self, enable: bool):
        payload = "1" if enable else "0"
        self.Logger.info(f"{self.name}: writing {self.onoff_set_topic} = {payload}")
        self.mqtt_support.client.publish(self.onoff_set_topic, payload, retain=False)

    def _handle_enable_command(self, payload):
        try:
            self._set_onoff(_parse_bool(payload))
        except ValueError:
            self.Logger.warning(f"{self.name}: invalid payload {payload!r} for {self.command_topic}")

    # ---- RV-C in --------------------------------------------------------

    _OWN_STATUS_DGNS = ("INVERTER_STATUS", "INVERTER_AC_STATUS_1", "INVERTER_DC_STATUS")

    def process_rvc_msg(self, new_message: dict) -> bool:
        if new_message.get("instance") != self.rvc_instance:
            return False
        name = new_message.get("name")
        if name == "INVERTER_COMMAND":
            self.Logger.debug(f"{self.name}: INVERTER_COMMAND {new_message}")
            enable = new_message.get("inverter_enable")
            if enable == "01":
                self._set_onoff(True)
            elif enable == "00":
                self._set_onoff(False)
            return True
        if name in self._OWN_STATUS_DGNS:
            # Our own echo (or a misconfigured real node at this instance):
            # keep it out of the unhandled log.
            self.Logger.debug(f"{self.name}: ignoring {name} for our instance from "
                              f"source {new_message.get('source_id')}")
            return True
        return False
```

Note: `INVERTER_AC_STATUS_1` decodes `instance` from the low nibble of byte 0, so an output frame for instance 1 still decodes with `instance == 1` — the instance check above works for all three DGNs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/virtual_inverter_test.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rvc2mqtt/entity/virtual_inverter.py test/virtual_inverter_test.py
git commit -m "Virtual inverter: INVERTER_COMMAND and MQTT enable -> modbus onoff

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: MQTT mirror to `rvc/state/inverter/*` and HA discovery

**Files:**
- Modify: `rvc2mqtt/entity/virtual_inverter.py`
- Test: `test/virtual_inverter_test.py`

**Interfaces:**
- Consumes: `_ingest` return value, `topic_base`, `device`, `unique_device_id`, `get_availability_discovery_info_for_ha()`, `mqtt_support.make_ha_auto_discovery_config_topic(id, component, sub)`.
- Produces: `_mirror_values() -> dict[str, str]`, `_publish_mirror()`, `publish_ha_discovery_config()`.

Mirror topic names (relative to `topic_base`), matching `entity/inverter.py` and the coach2mqtt topics doc:

| field(s) | topic | payload |
|---|---|---|
| status (+fault) | `status` | RV-C status int |
| | `status_definition` | e.g. `Invert` |
| enabled | `onoff` | `on` / `off` |
| fault | `fault` | `on` / `off` |
| ac_in_voltage | `line1/input/rms_voltage` | float, 2 dp |
| ac_out_voltage | `line1/output/rms_voltage` | |
| ac_out_current | `line1/output/rms_current` | |
| ac_out_frequency | `line1/output/frequency` | |
| dc_voltage | `dc_voltage` | |
| dc_current | `dc_amperage` | |

- [ ] **Step 1: Write the failing tests** (append)

```python
def _state_publishes(mock):
    return [(t, p, r) for (t, p, r) in _published(mock) if t.startswith('rvc/state/inverter/')]


class Test_Mirror(unittest.TestCase):

    def _feed(self, e, mock, topic, payload):
        _registered(mock)[topic][0](topic, payload)

    def test_status_mirrors_code_and_definition(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        pubs = _state_publishes(mock)
        self.assertIn(('rvc/state/inverter/status', 1, True), pubs)
        self.assertIn(('rvc/state/inverter/status_definition', 'Invert', True), pubs)

    def test_onoff_and_fault_mirror(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/onoff', '1')
        self._feed(e, mock, 'modbus/inverter/state/fault', '0')
        pubs = _state_publishes(mock)
        self.assertIn(('rvc/state/inverter/onoff', 'on', True), pubs)
        self.assertIn(('rvc/state/inverter/fault', 'off', True), pubs)

    def test_fault_changes_mirrored_status(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        mock.client.publish.reset_mock()
        self._feed(e, mock, 'modbus/inverter/state/fault', '1')
        pubs = _state_publishes(mock)
        self.assertIn(('rvc/state/inverter/status', 0, True), pubs)
        self.assertIn(('rvc/state/inverter/status_definition', 'Disabled', True), pubs)

    def test_numeric_mirror_topics(self):
        e, mock, _ = _make_entity({'fields': {
            'ac_out_voltage': 'state/ov', 'ac_out_current': 'state/oc',
            'ac_out_frequency': 'state/of', 'dc_voltage': 'state/dv', 'dc_current': 'state/dc'}})
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', '1208')
        self._feed(e, mock, 'modbus/inverter/state/ov', '119.5')
        self._feed(e, mock, 'modbus/inverter/state/oc', '3.8')
        self._feed(e, mock, 'modbus/inverter/state/of', '60')
        self._feed(e, mock, 'modbus/inverter/state/dv', '52')
        self._feed(e, mock, 'modbus/inverter/state/dc', '-12.5')
        pubs = {t: p for (t, p, _r) in _state_publishes(mock)}
        self.assertEqual(pubs['rvc/state/inverter/line1/input/rms_voltage'], 120.8)
        self.assertEqual(pubs['rvc/state/inverter/line1/output/rms_voltage'], 119.5)
        self.assertEqual(pubs['rvc/state/inverter/line1/output/rms_current'], 3.8)
        self.assertEqual(pubs['rvc/state/inverter/line1/output/frequency'], 60.0)
        self.assertEqual(pubs['rvc/state/inverter/dc_voltage'], 52.0)
        self.assertEqual(pubs['rvc/state/inverter/dc_amperage'], -12.5)

    def test_unchanged_value_not_republished(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        mock.client.publish.reset_mock()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        self.assertEqual(_state_publishes(mock), [])

    def test_unmapped_fields_never_published(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        topics = [t for (t, _p, _r) in _state_publishes(mock)]
        self.assertNotIn('rvc/state/inverter/dc_voltage', topics)
        self.assertNotIn('rvc/state/inverter/line1/output/rms_voltage', topics)


class Test_HADiscovery(unittest.TestCase):

    def _configs(self, mock):
        out = {}
        for (t, p, _r) in _published(mock):
            if t.startswith('homeassistant/'):
                out[t] = json.loads(p)
        return out

    def test_core_components(self):
        e, mock, _ = _make_entity()
        e.publish_ha_discovery_config()
        cfgs = self._configs(mock)
        uid = e.unique_device_id
        self.assertIn(f'homeassistant/switch/{uid}/enable/config', cfgs)
        self.assertIn(f'homeassistant/sensor/{uid}/status/config', cfgs)
        self.assertIn(f'homeassistant/binary_sensor/{uid}/fault/config', cfgs)
        self.assertIn(f'homeassistant/sensor/{uid}/ac_in_voltage/config', cfgs)
        sw = cfgs[f'homeassistant/switch/{uid}/enable/config']
        self.assertEqual(sw['command_topic'], 'rvc/set/inverter/enable')
        self.assertEqual(sw['state_topic'], 'rvc/state/inverter/onoff')
        self.assertEqual(sw['payload_on'], 'on')
        self.assertEqual(sw['unique_id'], uid + '_enable')
        self.assertEqual(sw['availability_topic'], 'rvc2mqtt/bridge/state')
        self.assertEqual(sw['device']['identifiers'], uid)

    def test_numeric_sensors_only_for_mapped_fields(self):
        e, mock, _ = _make_entity({'fields': {'dc_voltage': 'state/dv', 'ac_in_voltage': None}})
        e.publish_ha_discovery_config()
        cfgs = self._configs(mock)
        uid = e.unique_device_id
        self.assertIn(f'homeassistant/sensor/{uid}/dc_voltage/config', cfgs)
        self.assertNotIn(f'homeassistant/sensor/{uid}/ac_in_voltage/config', cfgs)
        dv = cfgs[f'homeassistant/sensor/{uid}/dc_voltage/config']
        self.assertEqual(dv['state_topic'], 'rvc/state/inverter/dc_voltage')
        self.assertEqual(dv['device_class'], 'voltage')
        self.assertEqual(dv['unit_of_measurement'], 'V')

    def test_initialize_publishes_discovery(self):
        e, mock, _ = _make_entity()
        e.initialize()
        self.assertTrue(self._configs(mock))
```

Add `import json` to the test file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/virtual_inverter_test.py -k "Mirror or HADiscovery" -v`
Expected: FAIL — no `rvc/state/inverter/*` or `homeassistant/*` publishes.

- [ ] **Step 3: Implement mirror and discovery**

In `process_mqtt_msg`, change the field loop so a change triggers the mirror:

```python
        changed = False
        for field in self._topic_fields.get(topic, ()):
            changed = self._ingest(field, payload) or changed
        if changed:
            self._publish_mirror()
```

Add these class-level tables and methods to `VirtualInverter`:

```python
    # numeric field -> (mirror sub-topic, HA device_class, unit)
    _NUMERIC_MIRROR = {
        "ac_in_voltage":    ("line1/input/rms_voltage",  "voltage",   "V"),
        "ac_out_voltage":   ("line1/output/rms_voltage", "voltage",   "V"),
        "ac_out_current":   ("line1/output/rms_current", "current",   "A"),
        "ac_out_frequency": ("line1/output/frequency",   "frequency", "Hz"),
        "dc_voltage":       ("dc_voltage",               "voltage",   "V"),
        "dc_current":       ("dc_amperage",              "current",   "A"),
    }

    # ---- MQTT mirror ----------------------------------------------------

    @staticmethod
    def _onoff(value) -> str:
        return "on" if value else "off"

    def _mirror_values(self) -> dict:
        """Current mirror topic -> payload for every field that has a value."""
        out = {}
        if self.values['status'] is not None or self.values['fault'] is not None:
            status = self.rvc_status()
            out[f"{self.topic_base}/status"] = status
            out[f"{self.topic_base}/status_definition"] = RVC_STATUS_DEFINITION.get(status, "unknown").title()
        if self.values['enabled'] is not None:
            out[f"{self.topic_base}/onoff"] = self._onoff(self.values['enabled'])
        if self.values['fault'] is not None:
            out[f"{self.topic_base}/fault"] = self._onoff(self.values['fault'])
        for field, (sub, _dc, _unit) in self._NUMERIC_MIRROR.items():
            value = self.values[field]
            if value is not None:
                out[f"{self.topic_base}/{sub}"] = round(value, 2)
        return out

    def _publish_mirror(self):
        for topic, payload in self._mirror_values().items():
            if self._mirror_cache.get(topic) != payload:
                self._mirror_cache[topic] = payload
                self.mqtt_support.client.publish(topic, payload, retain=True)

    # ---- Home Assistant -------------------------------------------------

    def _publish_discovery(self, component: str, sub: str, config: dict):
        config = dict(config)
        config["unique_id"] = self.unique_device_id + "_" + sub
        config["device"] = self.device
        config.update(self.get_availability_discovery_info_for_ha())
        topic = self.mqtt_support.make_ha_auto_discovery_config_topic(
            self.unique_device_id, component, sub)
        self.mqtt_support.client.publish(topic, json.dumps(config), retain=False)

    def publish_ha_discovery_config(self):
        self._publish_discovery("switch", "enable", {
            "name": self.name + " power",
            "state_topic": f"{self.topic_base}/onoff",
            "command_topic": self.command_topic,
            "payload_on": "on", "payload_off": "off",
            "qos": 1, "retain": False})
        self._publish_discovery("sensor", "status", {
            "name": self.name + " status",
            "state_topic": f"{self.topic_base}/status_definition",
            "device_class": "enum",
            "options": [v.title() for v in RVC_STATUS_DEFINITION.values()] + ["Unknown"]})
        self._publish_discovery("binary_sensor", "fault", {
            "name": self.name + " fault",
            "state_topic": f"{self.topic_base}/fault",
            "device_class": "problem",
            "payload_on": "on", "payload_off": "off"})
        for field, (sub, device_class, unit) in self._NUMERIC_MIRROR.items():
            if field not in self.field_topics:
                continue
            self._publish_discovery("sensor", field, {
                "name": self.name + " " + field.replace("_", " "),
                "state_topic": f"{self.topic_base}/{sub}",
                "device_class": device_class,
                "unit_of_measurement": unit,
                "state_class": "measurement"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/virtual_inverter_test.py -v`
Expected: all pass. (`Test_Tick.test_silence_transition_logged_once` still counts one `info`: `_publish_mirror` does not log.)

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add rvc2mqtt/entity/virtual_inverter.py test/virtual_inverter_test.py
git commit -m "Virtual inverter: mirror state to rvc topics and HA discovery

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Instance-collision warning in `app.py`

**Files:**
- Modify: `rvc2mqtt/app.py` (after the entity-build loop in `main()`, ~line 140, and after step 6's loop in `_do_reload()`, ~line 221)
- Test: `test/app_loop_test.py`

**Interfaces:**
- Produces: `app._warn_instance_collisions(self) -> None`

- [ ] **Step 1: Write the failing tests** (append to `test/app_loop_test.py`)

```python
from rvc2mqtt.entity.virtual_inverter import VirtualInverter
from rvc2mqtt.entity.inverter import InverterCharger_INVERTER_STATUS


def _mock_support():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    return mock


class Test_InstanceCollision(unittest.TestCase):

    def _virtual(self, instance):
        return VirtualInverter({'instance': instance, 'instance_name': 'v'}, _mock_support())

    def _real(self, instance):
        return InverterCharger_INVERTER_STATUS(
            {'instance': instance, 'instance_name': 'r',
             'status_topic': 'rvc/state/inverter', 'command_topic': 'rvc/set/inverter'},
            _mock_support())

    def test_same_instance_logs_error(self):
        a = _make_app()
        a.entity_list = [self._real(1), self._virtual(1)]
        a._warn_instance_collisions()
        a.Logger.error.assert_called_once()
        self.assertIn("instance 1", a.Logger.error.call_args[0][0])

    def test_different_instances_silent(self):
        a = _make_app()
        a.entity_list = [self._real(1), self._virtual(2)]
        a._warn_instance_collisions()
        a.Logger.error.assert_not_called()

    def test_virtual_alone_silent(self):
        a = _make_app()
        a.entity_list = [self._virtual(1)]
        a._warn_instance_collisions()
        a.Logger.error.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/app_loop_test.py -k Collision -v`
Expected: FAIL — `AttributeError: 'app' object has no attribute '_warn_instance_collisions'`

- [ ] **Step 3: Implement**

Add to the `app` class (next to `_loop_once`):

```python
    def _warn_instance_collisions(self):
        """A VirtualInverter and a real INVERTER_STATUS entity on the same
        instance would both own rvc/state/inverter/*; the override floorplan
        should _remove the real one.  Both are kept loaded; just make it loud."""
        from rvc2mqtt.entity.virtual_inverter import VirtualInverter
        from rvc2mqtt.entity.inverter import InverterCharger_INVERTER_STATUS
        virtual = {e.rvc_instance for e in self.entity_list if isinstance(e, VirtualInverter)}
        real = {e.rvc_instance for e in self.entity_list
                if isinstance(e, InverterCharger_INVERTER_STATUS)}
        for instance in sorted(virtual & real):
            self.Logger.error(
                f"Floorplan has both a VIRTUAL_INVERTER and an INVERTER_STATUS entity on "
                f"instance {instance}; they will fight over the same MQTT topics. "
                f"Remove one (override: `_remove: true`).")
```

Call it in `main()` right after the entity-build `for item, source_file in argsns.fp:` loop (before the `# Request product identification` block):

```python
        self._warn_instance_collisions()
```

and in `_do_reload()` right after step 6's entity-build loop (before `# 7. Remove discovery topics`):

```python
        self._warn_instance_collisions()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/app_loop_test.py test/reload_test.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rvc2mqtt/app.py test/app_loop_test.py
git commit -m "Warn when a virtual and real inverter share an RV-C instance

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Documentation and end-to-end smoke test on vcan

**Files:**
- Modify: `docs/configuration.md` (insert a new `###` section before `### Example`, ~line 263)

- [ ] **Step 1: Add the configuration section**

Insert into `docs/configuration.md`:

````markdown
### Virtual inverter (`virtual_inverter`)

Presents an inverter that only speaks Modbus (published on MQTT by
[modbus2mqtt](https://github.com/dbergl/modbus2mqtt)) as an RV-C inverter, so
the coach panel can show and switch it.  rvc2mqtt transmits
`INVERTER_STATUS`, `INVERTER_AC_STATUS_1` (line 1 input and output) and
`INVERTER_DC_STATUS` every `interval` seconds, and answers `INVERTER_COMMAND`
(inverter enable/disable) by writing modbus2mqtt's `set/onoff` topic.  State is
also mirrored to the same `rvc/state/inverter/*` topics the real `inverter`
entity uses, and `rvc/set/inverter/enable` (`on`/`off`) works the same way.

A coach has either a real RV-C inverter or a virtual one on a given instance,
never both.  On Lithium coaches put this in the override floorplan and
`_remove` the factory `INVERTER_STATUS` entry.

```yaml
overrides:
  - name: INVERTER_STATUS
    type: inverter
    instance: 1
    _remove: true

  - name: VIRTUAL_INVERTER
    type: virtual_inverter
    instance: 1
    instance_name: renogy
    status_topic: rvc/state/inverter
    command_topic: rvc/set/inverter
    source_topic_base: modbus/inverter     # default
    interval: 1.0                          # seconds between transmissions (default 1.0)
    stale_timeout: 30.0                    # seconds (default 30.0)
    source_id: "42"                        # RV-C source address, hex (default "42")
    fields:
      dc_voltage: {topic: state/battery_voltage, scale: 0.1}
      dc_current: state/battery_current
```

| Field | Required | Description |
|---|---|---|
| `source_topic_base` | no | modbus2mqtt device base topic. The entity subscribes to `<base>/connected` and writes `<base>/set/onoff`. Default `modbus/inverter` |
| `interval` | no | Seconds between RV-C status transmissions. Default `1.0` |
| `stale_timeout` | no | Stop transmitting if no `status`/`enabled` update arrives for this many seconds, or if `<base>/connected` is `offline`. Silence is how RV-C signals absence. Default `30.0` |
| `source_id` | no | Hex source address used for transmitted frames. Default `42`, the inverter address the Lyra panel expects; the bridge's other frames stay on `82` |
| `fields` | no | Map of RV-C field → MQTT topic. A value is either a topic string (scale 1.0) or `{topic: …, scale: …}`. Relative topics are joined to `source_topic_base`. Set a field to `~` to unmap it. Unmapped fields are sent as RV-C "not available" |

Fields, with defaults:

| Field | Default topic | Scale | Used in |
|---|---|---|---|
| `status` | `state/status` | — | `INVERTER_STATUS.status` (SRNE code, see below) |
| `enabled` | `state/onoff` | — | `INVERTER_STATUS` inverter-enabled bits |
| `fault` | `state/fault` | — | forces status `disabled`; mirrored to `…/fault` |
| `ac_in_voltage` | `state/AC_Input_Voltage` | `0.1` | `INVERTER_AC_STATUS_1` (input) |
| `ac_out_voltage` | unmapped | `1.0` | `INVERTER_AC_STATUS_1` (output) |
| `ac_out_current` | unmapped | `1.0` | `INVERTER_AC_STATUS_1` (output) |
| `ac_out_frequency` | unmapped | `1.0` | `INVERTER_AC_STATUS_1` (output) |
| `dc_voltage` | unmapped | `1.0` | `INVERTER_DC_STATUS` |
| `dc_current` | unmapped | `1.0` | `INVERTER_DC_STATUS` |

`scale` multiplies the raw MQTT payload (modbus2mqtt publishes raw register
values; the `/10` in the CSV templates only affects Home Assistant display).

Modbus status code (SRNE register 4405) → RV-C status:

| Code | Meaning | RV-C status |
|---|---|---|
| 4 | Mains powered operation | 2 `ac passthru` |
| 5 | Inverter powered operation | 1 `invert` |
| 3, 6, 7 | Soft start / transitions | 5 `waiting to invert` |
| 0, 1, 2, 10 | Power-up, waiting, init, shutdown | 0 `disabled` |
| 11 or `fault` on | Fault | 0 `disabled` |
| other | unknown (warned once) | 0 `disabled` |

Mirrored topics under `status_topic`: `status`, `status_definition`, `onoff`,
`fault`, `line1/input/rms_voltage`, `line1/output/{rms_voltage,rms_current,frequency}`,
`dc_voltage`, `dc_amperage` — only for fields that are mapped.
````

- [ ] **Step 2: Smoke test on a virtual CAN interface**

Requires a local MQTT broker (`mosquitto` on localhost) and `can-utils`. If either is unavailable, skip this step and say so in the task report — the unit tests cover the logic.

```bash
sudo ip link add dev vcan0 type vcan 2>/dev/null; sudo ip link set vcan0 up
cat > /tmp/claude-1000/-home-dan-projects-rv/59e3a1ca-a3ad-4b96-be6b-e6055208ddfb/scratchpad/vi.yml <<'EOF'
floorplan:
  - name: VIRTUAL_INVERTER
    type: virtual_inverter
    instance: 1
    instance_name: renogy
    status_topic: rvc/state/inverter
    command_topic: rvc/set/inverter
EOF
source venv/bin/activate
CAN_INTERFACE_NAME=vcan0 MQTT_HOST=localhost MQTT_TOPIC_BASE=rvc \
  FLOORPLAN_FILE_1=/tmp/claude-1000/-home-dan-projects-rv/59e3a1ca-a3ad-4b96-be6b-e6055208ddfb/scratchpad/vi.yml \
  python3 -m rvc2mqtt.app &
APP=$!
sleep 2
candump vcan0 -n 8 &          # should print nothing yet (no status received)
mosquitto_pub -h localhost -t modbus/inverter/state/status -m 5 -r
mosquitto_pub -h localhost -t modbus/inverter/state/onoff -m 1 -r
sleep 2                        # candump should now show 19FFD442 / 19FFD742 ×2 / 19FEE842 each second
mosquitto_sub -h localhost -t 'modbus/inverter/set/#' -C 1 &
cansend vcan0 19FFD39F#0110FFFFFFFFFF11   # INVERTER_COMMAND disable from source 9F
sleep 1                        # mosquitto_sub should print "0"
mosquitto_sub -h localhost -t 'rvc/state/inverter/#' -v -C 3   # status 1 / Invert / onoff on
kill $APP
```

Expected:
- After the status/onoff publishes: `candump` shows `19FFD442 [8] 01 01 1x FF FF FF FF FF` and the AC/DC frames once per second.
- After `cansend`: `modbus/inverter/set/onoff 0`.
- `rvc/state/inverter/status 1`, `…/status_definition Invert`, `…/onoff on`.

- [ ] **Step 3: Run the full suite one more time**

Run: `pytest -v --cov=rvc2mqtt --cov-report term-missing:skip-covered | tail -30`
Expected: all pass; `rvc2mqtt/entity/virtual_inverter.py` and `rvc2mqtt/rvc_encode.py` near 100% covered.

- [ ] **Step 4: Commit**

```bash
git add docs/configuration.md
git commit -m "Document the virtual inverter entity

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Follow-ups outside this plan (separate repo)

- **coach2mqtt**: add the `_remove` + `VIRTUAL_INVERTER` override to the Lithium override floorplan and a note in `2021-2024_swift-ethos-launch-terrain-topics.md` that `rvc/state/inverter/*` is fed from Modbus on Lithium coaches.
- **jayco.csv**: add SRNE registers for AC output V/A/Hz and battery V/A, then map them via `fields:`.
