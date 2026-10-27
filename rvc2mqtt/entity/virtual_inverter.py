"""
Virtual inverter: presents a Modbus inverter (published on MQTT by
modbus2mqtt) as an RV-C inverter node.

Subscribes to modbus2mqtt state topics, transmits INVERTER_STATUS,
INVERTER_AC_STATUS_1, CHARGER_AC_STATUS_1 (AC input, so panels that read
shore power from the charger side see it), CHARGER_CONFIGURATION_STATUS
(battery type and bank size) and INVERTER_DC_STATUS on a schedule, answers
INVERTER_COMMAND by writing modbus2mqtt's set/onoff topic,
and mirrors state to the same rvc/state/inverter topics the real inverter
entity uses.

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
import math
import time
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass
from rvc2mqtt.rvc_encode import (
    encode_voltage_u16, encode_current_u16, encode_frequency_u16,
    encode_amp_hours_u16, u16_le)


# field -> default {"topic": <relative to source_topic_base>, "scale": float} or None (unmapped)
FIELD_DEFAULTS = {
    "status":           {"topic": "state/status", "scale": 1.0},
    "enabled":          {"topic": "state/onoff", "scale": 1.0},
    "fault":            {"topic": "state/fault", "scale": 1.0},
    "ac_in_voltage":    {"topic": "state/AC_Input_Voltage", "scale": 0.1},
    "ac_in_current":    None,
    "ac_in_frequency":  {"topic": "state/AC_Input_Frequency", "scale": 0.01},
    "ac_out_voltage":   None,
    "ac_out_current":   None,
    "ac_out_frequency": None,
    "dc_voltage":       None,
    "dc_current":       None,
    "battery_type":     {"topic": "state/battery_type", "scale": 1.0},
    "battery_capacity": {"topic": "state/BattCapacity", "scale": 1.0},
}
BOOL_FIELDS = ("enabled", "fault")
INT_FIELDS = ("status", "battery_type")   # enumerated codes, no scaling

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

# Modbus (SRNE register 4424) battery type code -> RV-C battery type
# (CHARGER_CONFIGURATION_STATUS byte 3 bits 4-7).  None = RV-C has no code
# for this chemistry (UserDef, Li-Ion); sent as "not available" without a
# warning.  Codes absent from the table are unknown and warned once.
SRNE_TO_RVC_BATTERY_TYPE = {
    0: None,  # UserDef                      -> n/a
    1: 2,     # Sealed Lead-Acid             -> agm
    2: 0,     # Flooded Lead-Acid            -> flooded
    3: 1,     # Gel Lead-Acid                -> gel
    4: 3,     # Lithium Iron Phosphate (14s) -> lithium iron phosphate
    5: 3,     # Lithium Iron Phosphate (15s) -> lithium iron phosphate
    6: 3,     # Lithium Iron Phosphate (16s) -> lithium iron phosphate
    12: None, # Lithium-Ion (13s)            -> n/a
    13: None, # Lithium-Ion (14s)            -> n/a
}
RVC_BATTERY_TYPE_DEFINITION = {0: "flooded", 1: "gel", 2: "agm",
                               3: "lithium iron phosphate"}
RVC_BATTERY_TYPE_NA = 0xF

# DM_RV (1FECA) constants.  DSA 66 is the RV-C default service address class
# for inverters; panels key latched faults on it, so the virtual inverter must
# broadcast an all-clear (or the fault) every interval or the panel holds the
# last fault it ever saw (e.g. a stale E2 over-voltage).
DM_RV_DSA_INVERTER = 66
DM_RV_FMI_NOT_IDENTIFIABLE = 11

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
        # Liveness comes from <source_topic_base>/connected (modbus2mqtt sets
        # it offline on poll failures and via its MQTT last-will).  Message
        # recency is NOT liveness — modbus2mqtt publishes on change only, so a
        # healthy-but-steady inverter can be silent on MQTT indefinitely.
        # stale_timeout is therefore disabled by default; set it only when the
        # source has no connected/LWT topic.
        raw_stale = data.get('stale_timeout', None)
        self.stale_timeout = None if raw_stale is None else float(raw_stale)
        if self.interval <= 0:
            raise ValueError(f"interval must be > 0, got {self.interval}")
        if self.stale_timeout is not None and self.stale_timeout <= 0:
            raise ValueError(f"stale_timeout must be > 0, got {self.stale_timeout}")
        self.source_id = str(data.get('source_id', DEFAULT_INVERTER_SOURCE_ID))
        self.field_topics = self._resolve_fields(data.get('fields') or {})

        # Runtime state.  MQTT callbacks (paho thread) write single items into
        # self.values, self.connected, self.last_status_update, and
        # self._warned_codes; tick() (main thread) reads them one at a time.
        # Single dict-item assignment, plain attribute assignment, and
        # set.add are all atomic in CPython, so no lock is needed. (Worst
        # case for _warned_codes: a duplicate warning if two threads race
        # adding the same code — harmless.)
        self.values = {name: None for name in FIELD_DEFAULTS}
        self.connected = True
        self.last_status_update = float('-inf')
        self.next_tx = 0.0
        self._clock = time.monotonic
        self._silent = False
        self._warned_codes = set()
        self._warned_battery_codes = set()
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
            new_connected = str(payload).strip().lower() == "online"
            if new_connected != self.connected:
                self.connected = new_connected
                self.Logger.info(f"{self.name}: modbus source is "
                                 f"{'online' if self.connected else 'offline'}")
            return
        changed = False
        for field in self._topic_fields.get(topic, ()):
            changed = self._ingest(field, payload) or changed
        if changed:
            self._publish_mirror()

    def _ingest(self, field: str, payload) -> bool:
        """Parse payload for field; update self.values.  Returns True if changed."""
        try:
            if field in INT_FIELDS:
                value = int(str(payload).strip())
            elif field in BOOL_FIELDS:
                value = _parse_bool(payload)
            else:
                _topic, scale = self.field_topics[field]
                value = float(str(payload).strip()) * scale
                if not math.isfinite(value):
                    raise ValueError(f"non-finite value {value!r} for {field}")
        except (ValueError, TypeError):
            self.Logger.warning(f"{self.name}: ignoring bad payload {payload!r} for {field}")
            return False
        if field in ("status", "enabled"):
            self.last_status_update = self._clock()
        changed = self.values[field] != value
        self.values[field] = value
        return changed

    # numeric field -> (mirror sub-topic, HA device_class, unit, suggested display precision)
    _NUMERIC_MIRROR = {
        "ac_in_voltage":    ("line1/input/rms_voltage",  "voltage",   "V",  None),
        "ac_in_current":    ("line1/input/rms_current",  "current",   "A",  None),
        "ac_in_frequency":  ("line1/input/frequency",    "frequency", "Hz", None),
        "ac_out_voltage":   ("line1/output/rms_voltage", "voltage",   "V",  None),
        "ac_out_current":   ("line1/output/rms_current", "current",   "A",  None),
        "ac_out_frequency": ("line1/output/frequency",   "frequency", "Hz", None),
        "dc_voltage":       ("dc_voltage",               "voltage",   "V",  None),
        "dc_current":       ("dc_amperage",              "current",   "A",  None),
        "battery_capacity": ("battery_capacity",         None,        "Ah", 0),
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
        if self.values['battery_type'] is not None:
            out[f"{self.topic_base}/battery_type"] = RVC_BATTERY_TYPE_DEFINITION.get(
                self.rvc_battery_type(), "unknown").title()
        for field, (sub, _dc, _unit, _precision) in self._NUMERIC_MIRROR.items():
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
        if 'battery_type' in self.field_topics:
            self._publish_discovery("sensor", "battery_type", {
                "name": self.name + " battery type",
                "state_topic": f"{self.topic_base}/battery_type",
                "device_class": "enum",
                "options": [v.title() for v in RVC_BATTERY_TYPE_DEFINITION.values()] + ["Unknown"]})
        for field, (sub, device_class, unit, precision) in self._NUMERIC_MIRROR.items():
            if field not in self.field_topics:
                continue
            config = {
                "name": self.name + " " + field.replace("_", " "),
                "state_topic": f"{self.topic_base}/{sub}",
                "unit_of_measurement": unit,
                "state_class": "measurement"}
            if device_class is not None:
                config["device_class"] = device_class
            if precision is not None:
                config["suggested_display_precision"] = precision
            self._publish_discovery("sensor", field, config)

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

    _OWN_STATUS_DGNS = ("INVERTER_STATUS", "INVERTER_AC_STATUS_1",
                        "CHARGER_AC_STATUS_1", "CHARGER_CONFIGURATION_STATUS",
                        "INVERTER_DC_STATUS")

    def process_rvc_msg(self, new_message: dict) -> bool:
        # DM_RV carries no instance field; claim only our own echo (matched
        # by source address) so it stays out of the unhandled log while DM_RV
        # from every other node flows on to the entities that watch it.
        if (new_message.get("name") == "DM_RV"
                and new_message.get("source_id", "").lower() == self.source_id.lower()):
            self.Logger.debug(f"{self.name}: ignoring our own DM_RV echo")
            return True
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

    def rvc_battery_type(self) -> int:
        """Map the Modbus battery type code to the RV-C 4-bit battery type."""
        code = self.values.get('battery_type')
        if code is None:
            return RVC_BATTERY_TYPE_NA
        if code in SRNE_TO_RVC_BATTERY_TYPE:
            rvc = SRNE_TO_RVC_BATTERY_TYPE[code]
            return RVC_BATTERY_TYPE_NA if rvc is None else rvc
        if code not in self._warned_battery_codes:
            self._warned_battery_codes.add(code)
            self.Logger.warning(f"{self.name}: unknown modbus battery type code {code}; "
                                "reporting not available")
        return RVC_BATTERY_TYPE_NA

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

    def _ac_status_data(self, output: bool) -> bytes:
        """Shared AC_STATUS_1 layout (RV-C alias Z0000): line 1, input or output."""
        side = "out" if output else "in"
        volts = self.values[f'ac_{side}_voltage']
        amps = self.values[f'ac_{side}_current']
        hz = self.values[f'ac_{side}_frequency']
        byte0 = (self.rvc_instance & 0x0F) | (0b00 << 4) | ((0b01 if output else 0b00) << 6)
        return (bytes([byte0])
                + u16_le(encode_voltage_u16(volts))
                + u16_le(encode_current_u16(amps))
                + u16_le(encode_frequency_u16(hz))
                + bytes([0xFF]))

    def _ac_status_frame(self, output: bool) -> dict:
        return {"dgn": "1FFD7", "data": self._ac_status_data(output),
                "source_id": self.source_id}

    def _charger_ac_status_frame(self) -> dict:
        """CHARGER_AC_STATUS_1 for the AC input: same payload as the
        INVERTER_AC_STATUS_1 input frame, on the charger DGN for panels that
        read shore power from the charger side of an inverter-charger."""
        return {"dgn": "1FFCA", "data": self._ac_status_data(output=False),
                "source_id": self.source_id}

    def _charger_config_frame(self) -> dict:
        """CHARGER_CONFIGURATION_STATUS: battery type and bank size are the
        only fields the Modbus side exposes; algorithm, mode, sensor and max
        charging current are sent "not available".  Installation line is 1,
        matching the AC status frames."""
        byte3 = (0b11                                  # bits 0-1 battery sensor: n/a
                 | (0b00 << 2)                         # bits 2-3 installation line 1
                 | ((self.rvc_battery_type() & 0xF) << 4))  # bits 4-7 battery type
        data = (bytes([self.rvc_instance & 0xFF, 0xFF, 0xFF, byte3])
                + u16_le(encode_amp_hours_u16(self.values['battery_capacity']))
                + bytes([0xFF, 0xFF]))
        return {"dgn": "1FFC6", "data": data, "source_id": self.source_id}

    def _dc_status_frame(self) -> dict:
        data = (bytes([self.rvc_instance & 0xFF])
                + u16_le(encode_voltage_u16(self.values['dc_voltage']))
                + u16_le(encode_current_u16(self.values['dc_current']))
                + bytes([0xFF, 0xFF, 0xFF]))
        return {"dgn": "1FEE8", "data": data, "source_id": self.source_id}

    def _dm_rv_frame(self) -> dict:
        """Diagnostic message: red lamp + generic fault while faulted,
        otherwise an all-clear so panels release latched fault codes."""
        faulted = self.values.get('fault') is True or self.values.get('status') == 11
        if faulted:
            # byte0: operating status 0000 "off fault", red lamp 01
            # SPN 0 with FMI "failure not identifiable" — the Modbus fault
            # flag carries no more detail than "faulted".
            data = bytes([0x40, DM_RV_DSA_INVERTER, 0x00, 0x00,
                          DM_RV_FMI_NOT_IDENTIFIABLE, 0xFF, 0xFF, 0xFF])
        else:
            # byte0: "on normal" (0101) while inverting/passthru/waiting,
            # "off normal" (0100) while disabled; lamps off; SPN/FMI all-1s
            # = no active fault.
            on = 0x05 if self.rvc_status() != 0 else 0x04
            data = bytes([on, DM_RV_DSA_INVERTER, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        return {"dgn": "1FECA", "data": data, "source_id": self.source_id}

    def build_frames(self) -> list:
        """The full status set transmitted each interval."""
        return [self._inverter_status_frame(),
                self._ac_status_frame(output=False),
                self._ac_status_frame(output=True),
                self._charger_ac_status_frame(),
                self._charger_config_frame(),
                self._dc_status_frame(),
                self._dm_rv_frame()]

    # ---- lifecycle ------------------------------------------------------

    def initialize(self):
        # Do NOT reset last_status_update/next_tx here: subscriptions were made
        # in __init__, so a retained status may already have arrived on the
        # paho thread before initialize() runs.
        self.publish_ha_discovery_config()

    def _should_transmit(self, now: float) -> bool:
        if not self.connected:
            return False
        if self.last_status_update == float('-inf'):
            return False  # never seen a status; nothing real to announce
        if self.stale_timeout is not None and (now - self.last_status_update) > self.stale_timeout:
            return False
        return True

    def tick(self, now: float):
        if now < self.next_tx:
            return
        self.next_tx = now + self.interval
        if not self._should_transmit(now):
            if not self._silent:
                self._silent = True
                if not self.connected:
                    reason = "modbus source offline"
                elif self.last_status_update == float('-inf'):
                    reason = "no status received yet"
                else:
                    reason = "status stale"
                self.Logger.info(f"{self.name}: going silent on RV-C ({reason})")
            return
        if self._silent:
            self._silent = False
            self.Logger.info(f"{self.name}: resuming RV-C transmission")
        for frame in self.build_frames():
            self.send_queue.put(frame)
