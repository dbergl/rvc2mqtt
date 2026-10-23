"""
Virtual air conditioner: presents a Home-Assistant-controlled air conditioner
as RV-C thermostat instance 7 for the Firefly panel's Climate page.

Design: docs/superpowers/specs/2026-10-22-virtual-aircon-design.md

Copyright 2022 Sean Brogan
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""

import logging
import math
import threading
import time
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass
from rvc2mqtt.rvc_encode import U16_NA, encode_temperature_u16, decode_temperature_u16, u16_le


# RV-C source address the virtual thermostat transmits from (spec thermostat
# range 0x58-0x5D).  Must not collide with any other node on the coach.
DEFAULT_SOURCE_ID = "58"

# Fields with both a state topic (HA -> us) and a set topic (us -> HA).
COMMAND_FIELDS = ("mode", "fan", "setpoint", "preset", "oscillate", "display")
# Report-only fields.
STATE_ONLY_FIELDS = ("temperature",)
ALL_FIELDS = COMMAND_FIELDS + STATE_ONLY_FIELDS

# temperature_unit -> (setpoint_min, setpoint_max, setpoint_default).  The C
# range is velit-hass's AC_MIN_TEMP_C/AC_MAX_TEMP_C.
SETPOINT_DEFAULTS = {"C": (17, 30, 24), "F": (62, 86, 75)}

# THERMOSTAT_COMMAND_1 cool-setpoint step codes the panel's arrow buttons send,
# -> +1/-1 whole degree.  Which code is up/down is NOT confirmed (see the
# panel interface spec); override per floorplan with step_codes.
DEFAULT_STEP_CODES = {0xFFFC: +1, 0xFFFA: +1, 0xFFFB: -1, 0xFFF9: -1}

# THERMOSTAT_STATUS_1 / COMMAND_1 operating mode codes (byte 1 bits 0-3).
MODE_CODES = {"off": 0, "cool": 1, "auto": 3, "fan_only": 4, "dry": 6}
CODE_MODES = {code: mode for mode, code in MODE_CODES.items()}
# Fan speed n (1-5) <-> THERMOSTAT_STATUS_1 byte 2 in 0.5 % units; the panel
# lights bar n when the byte is >= 40*n.
FAN_STEP = 40
# THERMOSTAT_STATUS_2 byte 3 / COMMAND_2 byte 2 bit position of each preset.
PRESET_SHIFT = {"sleep": 0, "eco": 2, "turbo": 4}

# Our own status DGNs: claim the echo at our instance, nothing else.
OWN_STATUS_DGNS = ("1FFE2", "1FEFA", "1FF9C", "0FFA1")

# HA publishes these when an entity is unavailable; ignore them quietly.
_HA_PLACEHOLDERS = ("unavailable", "unknown", "none", "")

_MODE_ALIASES = {"off": "off", "cool": "cool", "auto": "auto", "heat_cool": "auto",
                 "dry": "dry", "fan_only": "fan_only", "fan": "fan_only"}
_PRESET_ALIASES = {"none": "none", "cooling": "none", "eco": "eco", "energy_saving": "eco",
                   "sleep": "sleep", "turbo": "turbo", "boost": "turbo"}


def _norm(payload) -> str:
    return str(payload).strip().lower()


def parse_number(payload):
    try:
        value = float(_norm(payload))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_mode(payload):
    return _MODE_ALIASES.get(_norm(payload))


def parse_fan(payload):
    """'auto' or a speed 1-5 (accepts '3', '3.0')."""
    p = _norm(payload)
    if p == "auto":
        return "auto"
    value = parse_number(p)
    if value is None or value != int(value) or not 1 <= value <= 5:
        return None
    return int(value)


def parse_preset(payload):
    return _PRESET_ALIASES.get(_norm(payload))


def parse_onoff(payload):
    p = _norm(payload)
    if p in ("1", "on", "true"):
        return True
    if p in ("0", "off", "false"):
        return False
    return None


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


class OptimisticState:
    """Per-field reported value plus an optional pending (optimistic) value.

    A panel command makes its value effective at once (command()).  It stays
    effective until the AC reports the same value (confirmed) or `timeout`
    seconds pass (expire() reverts to the last reported value).  While a field
    is pending, a non-matching report is recorded but not shown, so a late
    report of the old setpoint can't snap a held arrow back.

    MQTT callbacks (paho thread) and the main loop both call in, hence the lock.
    """

    def __init__(self, timeout: float, clock, logger):
        self.timeout = timeout
        self._clock = clock
        self.Logger = logger
        self._lock = threading.Lock()
        self._reported = {}
        self._pending = {}   # field -> (value, deadline)

    def _effective_locked(self, field, default=None):
        if field in self._pending:
            return self._pending[field][0]
        return self._reported.get(field, default)

    def report(self, field: str, value) -> bool:
        """Record a value reported by the AC.  True if effective() changed."""
        with self._lock:
            before = self._effective_locked(field)
            self._reported[field] = value
            if field in self._pending and self._pending[field][0] == value:
                del self._pending[field]
            return self._effective_locked(field) != before

    def command(self, field: str, value) -> None:
        with self._lock:
            self._pending[field] = (value, self._clock() + self.timeout)

    def effective(self, field: str, default=None):
        with self._lock:
            return self._effective_locked(field, default)

    def reported(self, field: str, default=None):
        with self._lock:
            return self._reported.get(field, default)

    def is_pending(self, field: str) -> bool:
        with self._lock:
            return field in self._pending

    def expire(self) -> list:
        """Drop pending values past their deadline; return the reverted fields."""
        now = self._clock()
        reverted = []
        with self._lock:
            for field, (value, deadline) in list(self._pending.items()):
                if now >= deadline:
                    del self._pending[field]
                    reverted.append(field)
                    self.Logger.info(f"{field}: {value!r} not confirmed within {self.timeout}s, "
                                     f"reverting to {self._reported.get(field)!r}")
        return reverted


class VirtualAircon(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "VIRTUAL_AIRCON", "type": "virtual_aircon"}

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = int(data['instance'])
        self.id = "virtual-aircon-1FFE2-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        self.name = data.get('instance_name', f"virtual aircon {self.rvc_instance}")
        self.source_id = str(data.get('source_id', DEFAULT_SOURCE_ID))
        self.topic_base = str(data.get('topic_base', 'rvc2mqtt/aircon')).rstrip('/')
        self.interval = float(data.get('interval', 1.0))
        if self.interval <= 0:
            raise ValueError(f"interval must be > 0, got {self.interval}")
        self.confirm_timeout = float(data.get('confirm_timeout', 35.0))
        if self.confirm_timeout <= 0:
            raise ValueError(f"confirm_timeout must be > 0, got {self.confirm_timeout}")
        self.temperature_unit = str(data.get('temperature_unit', 'C')).strip().upper()
        if self.temperature_unit not in SETPOINT_DEFAULTS:
            raise ValueError(f"temperature_unit must be C or F, got {self.temperature_unit!r}")
        lo, hi, default = SETPOINT_DEFAULTS[self.temperature_unit]
        self.setpoint_min = int(data.get('setpoint_min', lo))
        self.setpoint_max = int(data.get('setpoint_max', hi))
        self.setpoint_default = int(data.get('setpoint_default', default))
        self.availability_topic = data.get('availability_topic')
        self.step_codes = self._resolve_step_codes(data.get('step_codes') or {})
        self.state_topics, self.set_topics = self._resolve_topics(data.get('fields') or {})

        # Runtime state.  MQTT callbacks (paho thread) and the main loop share
        # self.state (locked internally); available/_dirty are plain attribute
        # assignments, atomic in CPython.
        self._clock = time.monotonic
        self.state = OptimisticState(self.confirm_timeout, lambda: self._clock(), self.Logger)
        self.available = True
        self._dirty = True
        self.next_tx = 0.0
        self._warned = set()

        # Subscriptions.  State topics MUST use retain_ok=True: the default
        # clears the retained value on the broker, wiping HA's published state.
        self._topic_fields = {}
        for field, topic in self.state_topics.items():
            self._topic_fields.setdefault(topic, []).append(field)
        for topic in self._topic_fields:
            self.mqtt_support.register(topic, self.process_mqtt_msg, retain_ok=True)
        if self.availability_topic:
            self.mqtt_support.register(self.availability_topic, self.process_mqtt_msg, retain_ok=True)

    # ---- configuration -------------------------------------------------

    def _join_topic(self, topic: str) -> str:
        topic = str(topic)
        if topic.startswith(self.topic_base + "/"):
            return topic
        return f"{self.topic_base}/{topic}"

    def _resolve_topics(self, fields_cfg: dict):
        """Return ({field: state_topic}, {field: set_topic})."""
        state = {f: f"{self.topic_base}/state/{f}" for f in ALL_FIELDS}
        sets = {f: f"{self.topic_base}/set/{f}" for f in COMMAND_FIELDS}
        for field, cfg in fields_cfg.items():
            if field not in ALL_FIELDS:
                raise ValueError(f"unknown virtual aircon field {field!r}; valid: {', '.join(ALL_FIELDS)}")
            if not isinstance(cfg, dict) or not set(cfg) <= {'state', 'set'}:
                raise ValueError(f"field {field!r} mapping must be a dict with 'state' and/or 'set'")
            if 'state' in cfg:
                state[field] = self._join_topic(cfg['state'])
            if 'set' in cfg:
                if field not in COMMAND_FIELDS:
                    raise ValueError(f"field {field!r} is report-only and has no set topic")
                sets[field] = self._join_topic(cfg['set'])
        return state, sets

    @staticmethod
    def _resolve_step_codes(cfg: dict) -> dict:
        codes = dict(DEFAULT_STEP_CODES)
        for code, direction in cfg.items():
            code = int(code, 0) if isinstance(code, str) else int(code)
            d = str(direction).strip().lower()
            if d not in ("up", "down"):
                raise ValueError(f"step code {code:#06x} direction must be up or down, got {direction!r}")
            codes[code] = +1 if d == "up" else -1
        return codes

    # ---- MQTT in --------------------------------------------------------

    def process_mqtt_msg(self, topic, payload, properties=None):
        try:
            if topic == self.availability_topic:
                p = _norm(payload)
                available = p == "online" or parse_onoff(p) is True
                if available != self.available:
                    self.available = available
                    self._dirty = True
                    self.Logger.info(f"{self.name}: AC is {'online' if available else 'offline'}")
                return
            for field in self._topic_fields.get(topic, ()):
                self._ingest(field, payload)
        except Exception:
            self.Logger.exception(f"{self.name}: failed handling {topic} = {payload!r}")

    def _parse_field(self, field: str, payload):
        if field == "mode":
            return parse_mode(payload)
        if field == "fan":
            return parse_fan(payload)
        if field == "preset":
            return parse_preset(payload)
        if field in ("oscillate", "display"):
            return parse_onoff(payload)
        value = parse_number(payload)
        if value is None:
            return None
        return _round_half_up(value) if field == "setpoint" else value

    def _ingest(self, field: str, payload):
        value = self._parse_field(field, payload)
        if value is None:
            if _norm(payload) in _HA_PLACEHOLDERS:
                self.Logger.debug(f"{self.name}: ignoring placeholder {payload!r} for {field}")
            elif field not in self._warned:
                # Once per field until a good value arrives: bounded however
                # many distinct bad payloads a misbehaving source sends.
                self._warned.add(field)
                self.Logger.warning(f"{self.name}: ignoring bad payload {str(payload)[:60]!r} for {field}")
            return
        self._warned.discard(field)
        if self.state.report(field, value):
            self._dirty = True

    # ---- RV-C in (panel commands) ---------------------------------------

    def process_rvc_msg(self, new_message: dict) -> bool:
        # Decode from the raw bytes: the setpoint step codes are not
        # temperatures, and 0FFA0 isn't in rvc-spec.yml.
        try:
            data = bytes.fromhex(new_message.get("data") or "")
        except ValueError:
            return False
        if not data or data[0] != self.rvc_instance:
            return False
        dgn = new_message.get("dgn")
        handler = {"1FEF9": self._on_command_1,
                   "1FEF8": self._on_command_2,
                   "0FFA0": self._on_proprietary}.get(dgn)
        if handler is not None:
            self.Logger.debug(f"{self.name}: {dgn} {data.hex().upper()} from "
                              f"source {new_message.get('source_id')}")
            handler(data)
            return True
        if dgn in OWN_STATUS_DGNS:
            self.Logger.debug(f"{self.name}: ignoring {dgn} echo for our instance from "
                              f"source {new_message.get('source_id')}")
            return True
        return False

    @staticmethod
    def _byte(data: bytes, index: int):
        """Byte at index, or None (no change) when the payload is short."""
        return data[index] if len(data) > index else None

    def _command(self, field: str, value):
        """Make value effective now, publish it to HA and rebroadcast."""
        self.state.command(field, value)
        if isinstance(value, bool):
            payload = "on" if value else "off"
        else:
            payload = str(value)
        topic = self.set_topics[field]
        self.Logger.info(f"{self.name}: {field} -> {payload} ({topic})")
        self.mqtt_support.client.publish(topic, payload, retain=False)
        self._dirty = True

    def _clamp_setpoint(self, value: int) -> int:
        return max(self.setpoint_min, min(self.setpoint_max, value))

    def _on_command_1(self, data: bytes):
        """THERMOSTAT_COMMAND_1: mode, fan mode/speed, cool setpoint."""
        byte1 = self._byte(data, 1)
        if byte1 is not None:
            mode_code = byte1 & 0x0F
            if mode_code in CODE_MODES:
                self._command("mode", CODE_MODES[mode_code])
            elif mode_code != 0x0F:
                self.Logger.info(f"{self.name}: ignoring unsupported operating mode {mode_code}")
            fan_mode = (byte1 >> 4) & 0b11
            if fan_mode == 0b00:
                self._command("fan", "auto")
            elif fan_mode == 0b01:
                speed = self._byte(data, 2)
                if speed is not None and 1 <= speed <= 250:
                    self._command("fan", max(1, min(5, _round_half_up(speed / FAN_STEP))))
        if len(data) >= 7:
            self._on_cool_setpoint(data[5] | data[6] << 8)

    def _on_cool_setpoint(self, raw: int):
        if raw == U16_NA:
            return
        if raw in self.step_codes:
            step = self.step_codes[raw]
            base = self.state.effective("setpoint", self.setpoint_default)
            new = self._clamp_setpoint(base + step)
            self.Logger.info(f"{self.name}: setpoint step code {raw:#06x} "
                             f"({'up' if step > 0 else 'down'}): {base} -> {new}")
            self._command("setpoint", new)
            return
        celsius = decode_temperature_u16(raw)
        if celsius is None:
            self.Logger.info(f"{self.name}: ignoring reserved cool setpoint {raw:#06x}")
            return
        value = celsius * 9 / 5 + 32 if self.temperature_unit == "F" else celsius
        self._command("setpoint", self._clamp_setpoint(_round_half_up(value)))

    def _on_command_2(self, data: bytes):
        """THERMOSTAT_COMMAND_2 byte 2: the panel's independent Sleep/Eco/Turbo
        toggles, folded onto the AC's single preset."""
        byte2 = self._byte(data, 2)
        if byte2 is None:
            return
        # Fixed order so a malformed frame with several "on"s ends deterministically.
        for preset in ("turbo", "eco", "sleep"):
            bits = (byte2 >> PRESET_SHIFT[preset]) & 0b11
            if bits == 0b01:
                self._command("preset", preset)
            elif bits == 0b00 and self.state.effective("preset") == preset:
                self._command("preset", "none")

    def _on_proprietary(self, data: bytes):
        """0FFA0 (ours): byte 1 bits 0-1 oscillate, bits 2-3 display."""
        byte1 = self._byte(data, 1)
        if byte1 is None:
            return
        for field, shift in (("oscillate", 0), ("display", 2)):
            bits = (byte1 >> shift) & 0b11
            if bits in (0b00, 0b01):
                self._command(field, bits == 0b01)

    # ---- RV-C out -------------------------------------------------------

    def _to_celsius(self, value):
        if value is None:
            return None
        if self.temperature_unit == "F":
            return (value - 32) * 5 / 9
        return value

    def _frame(self, dgn: str, body: bytes) -> dict:
        return {"dgn": dgn, "data": bytes([self.rvc_instance & 0xFF]) + body,
                "source_id": self.source_id}

    def _status_1_frame(self) -> dict:
        """THERMOSTAT_STATUS_1: mode, fan mode, fan speed, cool setpoint."""
        mode = self.state.effective("mode", "off") if self.available else "off"
        fan = self.state.effective("fan")
        manual_fan = isinstance(fan, int)
        byte1 = (MODE_CODES[mode]
                 | ((0b01 if manual_fan else 0b00) << 4)   # fan mode: on / auto
                 | (0b00 << 6))                            # schedule mode: disabled
        byte2 = fan * FAN_STEP if manual_fan else 0
        setpoint = encode_temperature_u16(self._to_celsius(self.state.effective("setpoint")))
        return self._frame("1FFE2", bytes([byte1, byte2]) + u16_le(U16_NA)   # heat setpoint: n/a
                           + u16_le(setpoint) + b"\xff")

    def _status_2_frame(self) -> dict:
        """THERMOSTAT_STATUS_2: byte 3 holds the (single) Sleep/Eco/Turbo preset."""
        byte3 = 0xC0
        preset = self.state.effective("preset")
        if preset in PRESET_SHIFT:
            byte3 |= 0b01 << PRESET_SHIFT[preset]
        return self._frame("1FEFA", bytes([0xFF, 0xFF, byte3]) + b"\xff" * 4)

    def _ambient_frame(self) -> dict:
        temp = encode_temperature_u16(self._to_celsius(self.state.effective("temperature")))
        return self._frame("1FF9C", u16_le(temp) + b"\xff" * 5)

    def _proprietary_status_frame(self) -> dict:
        """0FFA1 (ours, mirrored in the panel firmware): byte 1 bits 0-1
        oscillate, bits 2-3 display.  Unknown reads as off so the panel's
        toggle sends "on"."""
        byte1 = (0xF0
                 | (0b01 if self.state.effective("oscillate") else 0b00)
                 | ((0b01 if self.state.effective("display") else 0b00) << 2))
        return self._frame("0FFA1", bytes([byte1]) + b"\xff" * 6)

    def build_frames(self) -> list:
        """The full status set the panel reads."""
        return [self._status_1_frame(),
                self._status_2_frame(),
                self._ambient_frame(),
                self._proprietary_status_frame()]

    # ---- lifecycle ------------------------------------------------------

    def initialize(self):
        self._dirty = True

    def tick(self, now: float):
        if self.state.expire():
            self._dirty = True
        if not self._dirty and now < self.next_tx:
            return
        self._dirty = False
        self.next_tx = now + self.interval
        for frame in self.build_frames():
            self.send_queue.put(frame)
