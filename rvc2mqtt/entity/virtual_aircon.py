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
            elif (field, payload) not in self._warned:
                self._warned.add((field, payload))
                self.Logger.warning(f"{self.name}: ignoring bad payload {payload!r} for {field}")
            return
        if self.state.report(field, value):
            self._dirty = True
