"""
Virtual inverter: presents a Modbus inverter (published on MQTT by
modbus2mqtt) as an RV-C inverter node.

Subscribes to modbus2mqtt state topics, transmits INVERTER_STATUS,
INVERTER_AC_STATUS_1 and INVERTER_DC_STATUS on a schedule, answers
INVERTER_COMMAND by writing modbus2mqtt's set/onoff topic, and mirrors
state to the same rvc/state/inverter topics the real inverter entity uses.

Design: docs/superpowers/specs/2026-08-23-virtual-inverter-design.md

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
