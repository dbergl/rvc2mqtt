"""
Firefly G12 Configuration entity

Copyright 2025 Dan Berglund
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
import struct
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class G12_Configuration(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "G12", "type": "g12_configuration"}

    """
    Entity for the Firefly G12 controller configuration messages.

    Listens to G12_CONFIGURATION (DGN 15FCE) which uses usefirstbyte: true.
    Messages are filtered by source_id (G12 broadcasts on 0x9C).

    Message types handled:
      0x01, 0x03, 0x05, 0x9B - involves AES enabled (no parameters decoded)
      0x0C - time at stop volts (duration, sec)
      0x0D - stop at voltage (volts, v)
      0x0E - time at stop volts (duration, sec)
      0x16 - max engine run time (minutes, min)
      0x2B - quiet time start (hours, minutes)
      0x2C - quiet time stop (hours, minutes)
      0x31 - start at voltage (volts, v)
      0xCC - 0%-33% tank threshold (value)
      0xCD - 33%-67% tank threshold (value)
      0xCE - 67%-100% tank threshold (value)

    Also handles INITIAL_PACKET / DATA_PACKET multi-packet transport to
    assemble and publish PRODUCT_IDENTIFICATION, filtered by source_id.

    Floorplan entry example:
      - name: G12
        type: g12_configuration
        source_id: '9C'
        instance_name: "Generator Controller"
        status_topic: "rvc/g12/config"
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "g12-configuration-15FCE-" + str(data['source_id'])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        self.name = data.get('instance_name', 'Generator Controller')
        self.device = {
            'mf': 'Firefly Integrations',
            'ids': self.unique_device_id,
            'mdl': 'Firefly G12 Control Module',
            'name': self.name
        }

        self.source_id = str(data['source_id'])

        # RVC message must match the following to be this device
        self.rvc_match_g12_config     = {"name": "G12_CONFIGURATION", "source_id": self.source_id}
        self.rvc_match_initial_packet = {"name": "INITIAL_PACKET", "source_id": self.source_id}
        self.rvc_match_data_packet    = {"name": "DATA_PACKET", "source_id": self.source_id}
        self.rvc_match_dm_rv          = {"name": "DM_RV", "source_id": self.source_id}
        self.rvc_match_input_status   = {"name": "G12_INPUT_STATUS", "source_id": self.source_id}
        # 1FED9 comes from touchscreen (0x9F), not G12 (0x9C) — no source_id filter
        self.rvc_match_g12_indicator  = {"name": "GENERIC_INDICATOR_COMMAND"}
        # DC_DIMMER_STATUS_3 (1FEDA) from G12 — instance 18 = engine relay
        self.rvc_match_engine_status  = {"name": "DC_DIMMER_STATUS_3", "source_id": self.source_id}

        # DM_RV
        self._fault_code = "unknown"
        self._fault_description = "unknown"
        self._lamp = "unknown"

        # INITIAL_PACKET / DATA_PACKET (multi-packet transport for PRODUCT_IDENTIFICATION)
        self._mp_expected_count = 0
        self._mp_message_length = 0
        self._mp_packets = {}
        self._product_id = None

        # G12_INPUT_STATUS (1FBDA) — set of input numbers currently active (empty = idle)
        self._active_inputs = set()
        # Inputs currently active that were seen with aux_12v_active=1.  These need an
        # explicit aux=0 deactivation frame rather than disappearing from the cycle.
        self._12v_inputs = set()
        # Input numbers ever confirmed as 12V-type (persists across deactivations so that
        # trailing AA00 frames after FB00 are still recognised as deactivation, not activation).
        self._known_12v_codes = set()

        # Internal state - initialized to "unknown" so first received value always publishes
        self._max_engine_run_time = "unknown"
        self._time_at_start_volts = "unknown"
        self._stop_at_voltage = "unknown"
        self._time_at_stop_volts = "unknown"
        self._quiet_time_start = "unknown"
        self._quiet_time_stop = "unknown"
        self._start_at_voltage = "unknown"
        self._threshold_cc = "unknown"
        self._threshold_cd = "unknown"
        self._threshold_ce = "unknown"

        # Newly discovered settings (from log analysis)
        self._ags_low_volts_trigger  = "unknown"  # 0x2F
        self._ags_gen_start_retries  = "unknown"  # 0x15 byte 2
        self._ags_config_mode        = "unknown"  # 0x15 byte 3
        self._go_power_controllers   = "unknown"  # 0xD7
        self._num_batteries          = "unknown"  # 0xD8
        self._cargo_bath_light       = "unknown"  # 0xE3
        self._bunk_accent            = "unknown"  # 0xE5
        self._progressive_inverter   = "unknown"  # 0xE6
        self._bath_fan               = "unknown"  # 0xE9
        self._black_tank_setting     = "unknown"  # 0xEC
        self._gen_aes_mode           = "unknown"  # 0xEF
        self._selected_floorplan     = "unknown"  # 0xF5
        self._ags_retry_interval     = "unknown"  # 0xF7
        self._aes_enabled            = "unknown"  # 0x9B (on/off)
        self._engine_running         = "unknown"  # engine on/off (from DC_DIMMER_STATUS_3 instance 18)

        if 'status_topic' in data:
            topic_base = str(data['status_topic'])
            self.max_engine_run_time_topic   = str(f"{topic_base}/aes/max_engine_run_time")
            self.time_at_start_volts_topic = str(f"{topic_base}/aes/time_at_start_volts")
            self.time_at_stop_volts_topic = str(f"{topic_base}/aes/time_at_stop_volts")
            self.stop_at_voltage_topic       = str(f"{topic_base}/aes/stop_at_voltage")
            self.quiet_time_start_topic      = str(f"{topic_base}/aes/quiet_time_start")
            self.quiet_time_stop_topic       = str(f"{topic_base}/aes/quiet_time_stop")
            self.start_at_voltage_topic      = str(f"{topic_base}/aes/start_at_voltage")
            self.threshold_cc_topic          = str(f"{topic_base}/tanks/threshold_33_pct")
            self.threshold_cd_topic          = str(f"{topic_base}/tanks/threshold_66_pct")
            self.threshold_ce_topic          = str(f"{topic_base}/tanks/threshold_100_pct")
            self.product_id_topic            = str(f"{topic_base}/product_id")
            self.dm_rv_fault_code_topic      = str(f"{topic_base}/fault/code")
            self.dm_rv_fault_description_topic = str(f"{topic_base}/fault/description")
            self.dm_rv_lamp_topic            = str(f"{topic_base}/fault/lamp")
            self._input_topic_base           = topic_base
            # Newly discovered settings
            self.ags_low_volts_trigger_topic = str(f"{topic_base}/ags/low_volts_trigger")
            self.ags_gen_start_retries_topic = str(f"{topic_base}/ags/gen_start_retries")
            self.ags_config_mode_topic       = str(f"{topic_base}/ags/config_mode")
            self.go_power_controllers_topic  = str(f"{topic_base}/go_power/controller_count")
            self.num_batteries_topic         = str(f"{topic_base}/batteries/count")
            self.cargo_bath_light_topic      = str(f"{topic_base}/lights/cargo_bath_ch25")
            self.bunk_accent_topic           = str(f"{topic_base}/lights/bunk_accent")
            self.progressive_inverter_topic  = str(f"{topic_base}/inverter/progressive")
            self.bath_fan_topic              = str(f"{topic_base}/fans/bath")
            self.black_tank_setting_topic    = str(f"{topic_base}/tanks/black_setting")
            self.gen_aes_mode_topic          = str(f"{topic_base}/gen/mode")
            self.selected_floorplan_topic    = str(f"{topic_base}/floorplan")
            self.ags_retry_interval_topic    = str(f"{topic_base}/ags/retry_interval")
            self.aes_enabled_topic           = str(f"{topic_base}/aes/enabled")
            self.engine_running_topic        = str(f"{topic_base}/engine/running")

        if 'command_topic' in data:
            topic_base = str(data['command_topic'])
            self.max_engine_run_time_set_topic   = str(f"{topic_base}/aes/max_engine_run_time")
            self.time_at_start_volts_set_topic   = str(f"{topic_base}/aes/time_at_start_volts")
            self.time_at_stop_volts_set_topic    = str(f"{topic_base}/aes/time_at_stop_volts")
            self.stop_at_voltage_set_topic       = str(f"{topic_base}/aes/stop_at_voltage")
            self.quiet_time_start_set_topic      = str(f"{topic_base}/aes/quiet_time_start")
            self.quiet_time_stop_set_topic       = str(f"{topic_base}/aes/quiet_time_stop")
            self.start_at_voltage_set_topic      = str(f"{topic_base}/aes/start_at_voltage")
            self.threshold_cc_set_topic          = str(f"{topic_base}/tanks/threshold_33_pct")
            self.threshold_cd_set_topic          = str(f"{topic_base}/tanks/threshold_66_pct")
            self.threshold_ce_set_topic          = str(f"{topic_base}/tanks/threshold_100_pct")
            # Newly discovered settings
            self.ags_low_volts_trigger_set_topic = str(f"{topic_base}/ags/low_volts_trigger")
            self.cargo_bath_light_set_topic      = str(f"{topic_base}/lights/cargo_bath_ch25")
            self.bunk_accent_set_topic           = str(f"{topic_base}/lights/bunk_accent")
            self.progressive_inverter_set_topic  = str(f"{topic_base}/inverter/progressive")
            self.bath_fan_set_topic              = str(f"{topic_base}/fans/bath")
            self.black_tank_setting_set_topic    = str(f"{topic_base}/tanks/black_setting")
            self.gen_aes_mode_set_topic          = str(f"{topic_base}/gen/mode")
            self.selected_floorplan_set_topic    = str(f"{topic_base}/floorplan")
            self.num_batteries_set_topic         = str(f"{topic_base}/batteries/count")
            self.go_power_controllers_set_topic  = str(f"{topic_base}/go_power/controller_count")
            self.ags_retry_interval_set_topic    = str(f"{topic_base}/ags/retry_interval")
            self.aes_enabled_set_topic           = str(f"{topic_base}/aes/enabled")
            self.engine_start_set_topic          = str(f"{topic_base}/engine/start")

            self.mqtt_support.register(self.max_engine_run_time_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.time_at_start_volts_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.time_at_stop_volts_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.stop_at_voltage_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.quiet_time_start_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.quiet_time_stop_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.start_at_voltage_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.threshold_cc_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.threshold_cd_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.threshold_ce_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.ags_low_volts_trigger_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.cargo_bath_light_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.bunk_accent_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.progressive_inverter_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.bath_fan_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.black_tank_setting_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.gen_aes_mode_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.selected_floorplan_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.num_batteries_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.go_power_controllers_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.ags_retry_interval_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.aes_enabled_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.engine_start_set_topic, self.process_mqtt_msg)

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming RVC message and determine if it is of interest.

        Returns True if the message was handled (even if no state changed).
        """
        if self._is_entry_match(self.rvc_match_initial_packet, new_message):
            count = new_message["packet_count"]
            if count <= 0:
                self.Logger.warning(f"INITIAL_PACKET: invalid packet_count {count}, ignoring")
                return True
            self._mp_expected_count = count
            self._mp_message_length = new_message["message_length"]
            self._mp_packets = {}
            self.Logger.debug(
                f"INITIAL_PACKET: expecting {self._mp_expected_count} packets, "
                f"{self._mp_message_length} bytes"
            )
            return True

        if self._is_entry_match(self.rvc_match_data_packet, new_message):
            if self._mp_expected_count == 0:
                self.Logger.debug("DATA_PACKET received without INITIAL_PACKET, discarding")
                return True
            packet_num = new_message["packet_number"]
            if packet_num in self._mp_packets:
                self.Logger.warning(f"Duplicate DATA_PACKET #{packet_num}, ignoring")
                return True
            # Guard against unbounded growth from malformed/stray packets
            if len(self._mp_packets) >= self._mp_expected_count:
                self.Logger.warning(
                    f"DATA_PACKET overflow: received more packets than expected "
                    f"({self._mp_expected_count}), resetting assembly buffer"
                )
                self._mp_packets = {}
                self._mp_expected_count = 0
                return True
            data_bytes = int(new_message["data"]).to_bytes(7, 'little')
            self._mp_packets[packet_num] = data_bytes
            self.Logger.debug(
                f"DATA_PACKET #{packet_num}: "
                f"{len(self._mp_packets)}/{self._mp_expected_count}"
            )
            if len(self._mp_packets) >= self._mp_expected_count:
                try:
                    all_bytes = b''.join(
                        self._mp_packets[i] for i in range(1, self._mp_expected_count + 1)
                    )
                    trimmed = all_bytes[:self._mp_message_length]
                    product_id = trimmed.decode('ascii').strip('\x00')
                    if product_id != self._product_id:
                        self._product_id = product_id
                        self.Logger.info(f"PRODUCT_IDENTIFICATION: {product_id}")
                        if hasattr(self, 'product_id_topic'):
                            self.mqtt_support.client.publish(
                                self.product_id_topic, product_id, retain=True)
                except Exception as e:
                    self.Logger.error(f"Failed to decode PRODUCT_IDENTIFICATION: {e}")
                finally:
                    self._mp_packets = {}
                    self._mp_expected_count = 0
            return True

        if self._is_entry_match(self.rvc_match_dm_rv, new_message):
            self.Logger.debug(f"Msg Match DM_RV: {str(new_message)}")
            message_fault_code = str(
                int(f"{new_message['spn-msb']:08b}"
                    f"{new_message['spn-isb']:08b}"
                    f"{new_message['spn-lsb']:03b}"
                ,2))
            fault_description = new_message.get("fmi_definition", "unknown")
            lamp_status = "on" if int(new_message["red_lamp_status"]) > 0 else "off"

            if self._fault_code != message_fault_code:
                self._fault_code = message_fault_code
                self._fault_description = fault_description
                if hasattr(self, 'dm_rv_fault_code_topic'):
                    self.mqtt_support.client.publish(
                        self.dm_rv_fault_code_topic,
                        str(self._fault_code),
                        retain=True)
                    self.mqtt_support.client.publish(
                        self.dm_rv_fault_description_topic,
                        self._fault_description, retain=True)
            if self._lamp != lamp_status:
                self._lamp = lamp_status
                if hasattr(self, 'dm_rv_lamp_topic'):
                    self.mqtt_support.client.publish(
                        self.dm_rv_lamp_topic, self._lamp, retain=True)
            return True

        if self._is_entry_match(self.rvc_match_input_status, new_message):
            self.Logger.debug(f"Msg Match G12_INPUT_STATUS: {str(new_message)}")
            code = int(new_message["active_input_code"])
            aux = int(new_message.get("aux_12v_active", 0))

            if 0xA1 <= code <= 0xAF:
                n = code & 0x0F
                if aux:
                    # aux_12v_active=1: the 12V line is energized — either by this input
                    # itself OR by another simultaneously-held 12V input (e.g. ignition).
                    # Record it as a known-12V code so the matching aux=0 frame is later
                    # recognised as deactivation rather than a GND-type activation.
                    self._known_12v_codes.add(n)
                    if n not in self._active_inputs:
                        self._active_inputs.add(n)
                        self._12v_inputs.add(n)
                        if hasattr(self, '_input_topic_base'):
                            self.mqtt_support.client.publish(
                                f"{self._input_topic_base}/inputs/{n}/active", "true", retain=True)
                    # Already active — repeated heartbeat frame, ignore.
                else:
                    if n in self._known_12v_codes:
                        # Known 12V-type input with aux dropped — deactivation frame.
                        # Publish false only if it was actually still marked active (avoids
                        # double-publish when FB00 already cleared it before AA00 arrives).
                        was_active = n in self._active_inputs
                        self._active_inputs.discard(n)
                        self._12v_inputs.discard(n)
                        if was_active and hasattr(self, '_input_topic_base'):
                            self.mqtt_support.client.publish(
                                f"{self._input_topic_base}/inputs/{n}/active", "false", retain=True)
                    else:
                        # GND-type input (aux=0 is normal while active) — mark as active.
                        if n not in self._active_inputs:
                            self._active_inputs.add(n)
                            if hasattr(self, '_input_topic_base'):
                                self.mqtt_support.client.publish(
                                    f"{self._input_topic_base}/inputs/{n}/active", "true", retain=True)
            else:
                # Idle or unknown code.
                if aux and self._12v_inputs:
                    # At least one 12V input is still held — this is the G12's normal
                    # heartbeat alternation.  Suppress until the 12V input sends its
                    # own aux=0 deactivation frame.
                    return True
                if code != 0xFB:
                    self.Logger.debug(f"G12_INPUT_STATUS code {hex(code)}, treating as idle")
                # All inputs released — clear everything active.
                if hasattr(self, '_input_topic_base'):
                    for prev in self._active_inputs:
                        self.mqtt_support.client.publish(
                            f"{self._input_topic_base}/inputs/{prev}/active", "false", retain=True)
                self._active_inputs.clear()
                self._12v_inputs.clear()
                # _known_12v_codes is intentionally preserved so that any trailing AA00
                # frames that arrive after FB00 are still recognised as deactivation
                # (not mistakenly treated as a new GND-type activation).
            return True

        if self._is_entry_match(self.rvc_match_engine_status, new_message):
            # DC_DIMMER_STATUS_3 instance 18 = engine relay state
            if int(new_message.get("instance", -1)) == 18:
                val = "on" if new_message.get("operating_status_brightness", 0) > 0 else "off"
                if val != self._engine_running:
                    self._engine_running = val
                    if hasattr(self, 'engine_running_topic'):
                        self.mqtt_support.client.publish(
                            self.engine_running_topic, val, retain=True)
            return True

        if self._is_entry_match(self.rvc_match_g12_indicator, new_message):
            group_str = new_message.get("group", "0")
            try:
                group_val = int(group_str, 2)
            except (ValueError, TypeError):
                return False
            if group_val != 0x96:
                return False

            raw = bytes.fromhex(new_message["data"])
            if len(raw) < 7:
                return False

            selector = raw[2]
            value_le = int.from_bytes(raw[4:6], 'little')
            function = raw[6]

            self.Logger.debug(
                f"GENERIC_INDICATOR_COMMAND (G12): selector={hex(selector)}, "
                f"value={value_le}, function={hex(function)}"
            )

            if function in (0xD1, 0xD2):
                if selector == 0x2B:
                    val = f"{raw[5]:02d}:{raw[4]:02d}"
                    if val != self._quiet_time_start:
                        self._quiet_time_start = val
                        if hasattr(self, 'quiet_time_start_topic'):
                            self.mqtt_support.client.publish(
                                self.quiet_time_start_topic, val, retain=True)
                elif selector == 0x2C:
                    val = f"{raw[5]:02d}:{raw[4]:02d}"
                    if val != self._quiet_time_stop:
                        self._quiet_time_stop = val
                        if hasattr(self, 'quiet_time_stop_topic'):
                            self.mqtt_support.client.publish(
                                self.quiet_time_stop_topic, val, retain=True)
                elif selector == 0x16:
                    val = value_le
                    if val != self._max_engine_run_time:
                        self._max_engine_run_time = val
                        if hasattr(self, 'max_engine_run_time_topic'):
                            self.mqtt_support.client.publish(
                                self.max_engine_run_time_topic, val, retain=True)
                elif selector == 0x0C:
                    val = value_le
                    if val != self._time_at_start_volts:
                        self._time_at_start_volts = val
                        if hasattr(self, 'time_at_start_volts_topic'):
                            self.mqtt_support.client.publish(
                                self.time_at_start_volts_topic, val, retain=True)
                elif selector == 0x0D:
                    val = round(value_le * 0.05, 2)
                    if val != self._stop_at_voltage:
                        self._stop_at_voltage = val
                        if hasattr(self, 'stop_at_voltage_topic'):
                            self.mqtt_support.client.publish(
                                self.stop_at_voltage_topic, val, retain=True)
                elif selector == 0x0E:
                    val = value_le
                    if val != self._time_at_stop_volts:
                        self._time_at_stop_volts = val
                        if hasattr(self, 'time_at_stop_volts_topic'):
                            self.mqtt_support.client.publish(
                                self.time_at_stop_volts_topic, val, retain=True)
                elif selector == 0x31:
                    val = round(value_le * 0.05, 2)
                    if val != self._start_at_voltage:
                        self._start_at_voltage = val
                        if hasattr(self, 'start_at_voltage_topic'):
                            self.mqtt_support.client.publish(
                                self.start_at_voltage_topic, val, retain=True)
                elif selector == 0xCC:
                    val = value_le
                    if val != self._threshold_cc:
                        self._threshold_cc = val
                        if hasattr(self, 'threshold_cc_topic'):
                            self.mqtt_support.client.publish(
                                self.threshold_cc_topic, val, retain=True)
                elif selector == 0xCD:
                    val = value_le
                    if val != self._threshold_cd:
                        self._threshold_cd = val
                        if hasattr(self, 'threshold_cd_topic'):
                            self.mqtt_support.client.publish(
                                self.threshold_cd_topic, val, retain=True)
                elif selector == 0xCE:
                    val = value_le
                    if val != self._threshold_ce:
                        self._threshold_ce = val
                        if hasattr(self, 'threshold_ce_topic'):
                            self.mqtt_support.client.publish(
                                self.threshold_ce_topic, val, retain=True)
                elif selector == 0x9B:
                    # AES enable/disable command — byte 4 is 0x01=enabled, 0x00=disabled
                    val = "on" if raw[4] == 0x01 else "off"
                    if val != self._aes_enabled:
                        self._aes_enabled = val
                        if hasattr(self, 'aes_enabled_topic'):
                            self.mqtt_support.client.publish(
                                self.aes_enabled_topic, val, retain=True)
            return True

        if not self._is_entry_match(self.rvc_match_g12_config, new_message):
            return False

        self.Logger.debug(f"G12_CONFIGURATION match: {str(new_message)}")
        msg_type = new_message.get("message_type", "")

        if msg_type in ("1", "3", "5", "9B"):
            # AES-related messages — type 9B carries the enabled state in byte 4
            self.Logger.debug(f"G12 AES message type {msg_type}: {str(new_message)}")
            if msg_type == "9B":
                try:
                    raw_data = bytes.fromhex(new_message["data"])
                    val = "on" if raw_data[4] == 0x01 else "off"
                    if val != self._aes_enabled:
                        self._aes_enabled = val
                        if hasattr(self, 'aes_enabled_topic'):
                            self.mqtt_support.client.publish(
                                self.aes_enabled_topic, val, retain=True)
                except Exception:
                    pass

        elif msg_type == "16":  # 0x16 - max engine run time
            val = new_message.get("minutes")
            if val is not None and val != self._max_engine_run_time:
                self._max_engine_run_time = val
                if hasattr(self, 'max_engine_run_time_topic'):
                    self.mqtt_support.client.publish(
                        self.max_engine_run_time_topic, val, retain=True)

        elif msg_type == "C":  # 0x0C - time at start volts (duration)
            # rvc.py applies *2 for sec/uint16; G12 stores raw seconds, so undo it
            raw = new_message.get("duration")
            val = raw // 2 if raw is not None else None
            if val is not None and val != self._time_at_start_volts:
                self._time_at_start_volts = val
                if hasattr(self, 'time_at_start_volts_topic'):
                    self.mqtt_support.client.publish(
                        self.time_at_start_volts_topic, val, retain=True)

        elif msg_type == "D":  # 0x0D - stop at voltage
            val = new_message.get("volts")
            if val is not None and val != self._stop_at_voltage:
                self._stop_at_voltage = val
                if hasattr(self, 'stop_at_voltage_topic'):
                    self.mqtt_support.client.publish(
                        self.stop_at_voltage_topic, val, retain=True)

        elif msg_type == "E":  # 0x0E - time at stop volts (duration)
            # rvc.py applies *2 for sec/uint16; G12 stores raw seconds, so undo it
            raw = new_message.get("duration")
            val = raw // 2 if raw is not None else None
            if val is not None and val != self._time_at_stop_volts:
                self._time_at_stop_volts = val
                if hasattr(self, 'time_at_stop_volts_topic'):
                    self.mqtt_support.client.publish(
                        self.time_at_stop_volts_topic, val, retain=True)

        elif msg_type == "2B":  # 0x2B - quiet time start
            hours = new_message.get("hours")
            minutes = new_message.get("minutes")
            if hours is not None and minutes is not None:
                val = f"{int(hours):02d}:{int(minutes):02d}"
                if val != self._quiet_time_start:
                    self._quiet_time_start = val
                    if hasattr(self, 'quiet_time_start_topic'):
                        self.mqtt_support.client.publish(
                            self.quiet_time_start_topic, val, retain=True)

        elif msg_type == "2C":  # 0x2C - quiet time stop
            hours = new_message.get("hours")
            minutes = new_message.get("minutes")
            if hours is not None and minutes is not None:
                val = f"{int(hours):02d}:{int(minutes):02d}"
                if val != self._quiet_time_stop:
                    self._quiet_time_stop = val
                    if hasattr(self, 'quiet_time_stop_topic'):
                        self.mqtt_support.client.publish(
                            self.quiet_time_stop_topic, val, retain=True)

        elif msg_type == "31":  # 0x31 - start at voltage
            val = new_message.get("volts")
            if val is not None and val != self._start_at_voltage:
                self._start_at_voltage = val
                if hasattr(self, 'start_at_voltage_topic'):
                    self.mqtt_support.client.publish(
                        self.start_at_voltage_topic, val, retain=True)

        elif msg_type == "CC":  # 0xCC - 0%-33% tank threshold
            val = new_message.get("value")
            if val is not None and val != self._threshold_cc:
                self._threshold_cc = val
                if hasattr(self, 'threshold_cc_topic'):
                    self.mqtt_support.client.publish(
                        self.threshold_cc_topic, val, retain=True)

        elif msg_type == "CD":  # 0xCD - 33%-67% tank threshold
            val = new_message.get("value")
            if val is not None and val != self._threshold_cd:
                self._threshold_cd = val
                if hasattr(self, 'threshold_cd_topic'):
                    self.mqtt_support.client.publish(
                        self.threshold_cd_topic, val, retain=True)

        elif msg_type == "CE":  # 0xCE - 67%-100% tank threshold
            val = new_message.get("value")
            if val is not None and val != self._threshold_ce:
                self._threshold_ce = val
                if hasattr(self, 'threshold_ce_topic'):
                    self.mqtt_support.client.publish(
                        self.threshold_ce_topic, val, retain=True)

        elif msg_type == "15":  # 0x15 - AGS config (gen start retries / mode)
            retries = new_message.get("gen_start_retries")
            mode    = new_message.get("mode_indicator_definition", new_message.get("mode_indicator"))
            if retries is not None and retries != self._ags_gen_start_retries:
                self._ags_gen_start_retries = retries
                if hasattr(self, 'ags_gen_start_retries_topic'):
                    self.mqtt_support.client.publish(
                        self.ags_gen_start_retries_topic, retries, retain=True)
            if mode is not None and mode != self._ags_config_mode:
                self._ags_config_mode = mode
                if hasattr(self, 'ags_config_mode_topic'):
                    self.mqtt_support.client.publish(
                        self.ags_config_mode_topic, mode, retain=True)

        elif msg_type == "2F":  # 0x2F - AGS low volts trigger
            val = new_message.get("enabled_definition", new_message.get("enabled"))
            if val is not None and val != self._ags_low_volts_trigger:
                self._ags_low_volts_trigger = val
                if hasattr(self, 'ags_low_volts_trigger_topic'):
                    self.mqtt_support.client.publish(
                        self.ags_low_volts_trigger_topic, val, retain=True)

        elif msg_type == "D7":  # 0xD7 - number of Go Power! controllers
            val = new_message.get("controller_count")
            if val is not None and val != self._go_power_controllers:
                self._go_power_controllers = val
                if hasattr(self, 'go_power_controllers_topic'):
                    self.mqtt_support.client.publish(
                        self.go_power_controllers_topic, val, retain=True)

        elif msg_type == "D8":  # 0xD8 - number of batteries
            val = new_message.get("battery_count_definition", new_message.get("battery_count"))
            if val is not None and val != self._num_batteries:
                self._num_batteries = val
                if hasattr(self, 'num_batteries_topic'):
                    self.mqtt_support.client.publish(
                        self.num_batteries_topic, val, retain=True)

        elif msg_type == "E3":  # 0xE3 - cargo/bath light ch.25
            val = new_message.get("enabled_definition", new_message.get("enabled"))
            if val is not None and val != self._cargo_bath_light:
                self._cargo_bath_light = val
                if hasattr(self, 'cargo_bath_light_topic'):
                    self.mqtt_support.client.publish(
                        self.cargo_bath_light_topic, val, retain=True)

        elif msg_type == "E5":  # 0xE5 - bunk accent
            val = new_message.get("enabled_definition", new_message.get("enabled"))
            if val is not None and val != self._bunk_accent:
                self._bunk_accent = val
                if hasattr(self, 'bunk_accent_topic'):
                    self.mqtt_support.client.publish(
                        self.bunk_accent_topic, val, retain=True)

        elif msg_type == "E6":  # 0xE6 - progressive inverter
            val = new_message.get("enabled_definition", new_message.get("enabled"))
            if val is not None and val != self._progressive_inverter:
                self._progressive_inverter = val
                if hasattr(self, 'progressive_inverter_topic'):
                    self.mqtt_support.client.publish(
                        self.progressive_inverter_topic, val, retain=True)

        elif msg_type == "E9":  # 0xE9 - bath fan
            val = new_message.get("enabled_definition", new_message.get("enabled"))
            if val is not None and val != self._bath_fan:
                self._bath_fan = val
                if hasattr(self, 'bath_fan_topic'):
                    self.mqtt_support.client.publish(
                        self.bath_fan_topic, val, retain=True)

        elif msg_type == "EC":  # 0xEC - black tank
            val = new_message.get("enabled_definition", new_message.get("enabled"))
            if val is not None and val != self._black_tank_setting:
                self._black_tank_setting = val
                if hasattr(self, 'black_tank_setting_topic'):
                    self.mqtt_support.client.publish(
                        self.black_tank_setting_topic, val, retain=True)

        elif msg_type == "EF":  # 0xEF - generator/AES mode
            val = new_message.get("mode_definition", new_message.get("mode"))
            if val is not None and val != self._gen_aes_mode:
                self._gen_aes_mode = val
                if hasattr(self, 'gen_aes_mode_topic'):
                    self.mqtt_support.client.publish(
                        self.gen_aes_mode_topic, val, retain=True)

        elif msg_type == "F5":  # 0xF5 - selected floorplan
            val = new_message.get("floorplan_definition", new_message.get("floorplan"))
            if val is not None and val != self._selected_floorplan:
                self._selected_floorplan = val
                if hasattr(self, 'selected_floorplan_topic'):
                    self.mqtt_support.client.publish(
                        self.selected_floorplan_topic, val, retain=True)

        elif msg_type == "F7":  # 0xF7 - AGS time between retries
            val = new_message.get("retry_interval")
            if val is not None and val != self._ags_retry_interval:
                self._ags_retry_interval = val
                if hasattr(self, 'ags_retry_interval_topic'):
                    self.mqtt_support.client.publish(
                        self.ags_retry_interval_topic, val, retain=True)

        else:
            self.Logger.debug(f"G12_CONFIGURATION unhandled message type {msg_type}: {str(new_message)}")

        return True

    def process_mqtt_msg(self, topic, payload, properties=None):
        """ Handle an inbound MQTT set message by sending a 1FED9 G12 config command. """
        if not payload:
            return

        self.Logger.info(f"MQTT set received: topic={topic} payload={payload}")

        if not hasattr(self, 'send_queue'):
            self.Logger.warning("send_queue not available, cannot send 1FED9 command")
            return

        try:
            if topic == self.quiet_time_start_set_topic:
                parts = payload.split(':')
                hours, minutes = int(parts[0]), int(parts[1])
                minutes = round(minutes / 5) * 5
                if minutes == 60:
                    minutes = 0
                    hours = (hours + 1) % 24
                frame = struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x2B, 0x0F, minutes, hours, 0xD1, 0xEA)

            elif topic == self.quiet_time_stop_set_topic:
                parts = payload.split(':')
                hours, minutes = int(parts[0]), int(parts[1])
                minutes = round(minutes / 5) * 5
                if minutes == 60:
                    minutes = 0
                    hours = (hours + 1) % 24
                frame = struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x2C, 0x0F, minutes, hours, 0xD1, 0xEA)

            elif topic == self.max_engine_run_time_set_topic:
                raw_value = round(float(payload))
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0x16, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.time_at_start_volts_set_topic:
                raw_value = round(float(payload))
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0x0C, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.time_at_stop_volts_set_topic:
                raw_value = round(float(payload))
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0x0E, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.stop_at_voltage_set_topic:
                raw_value = round(float(payload) / 0.05)
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0x0D, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.start_at_voltage_set_topic:
                raw_value = round(float(payload) / 0.05)
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0x31, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.threshold_cc_set_topic:
                raw_value = round(float(payload))
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xCC, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.threshold_cd_set_topic:
                raw_value = round(float(payload))
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xCD, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.threshold_ce_set_topic:
                raw_value = round(float(payload))
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xCE, 0x0F, raw_value, 0xD1, 0xEA)

            elif topic == self.ags_low_volts_trigger_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0x2F, 0x0F,
                                    1 if payload.lower() == 'on' else 0, 0xD1, 0xEA)

            elif topic == self.cargo_bath_light_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xE3, 0x0F,
                                    1 if payload.lower() == 'on' else 0, 0xD1, 0xEA)

            elif topic == self.bunk_accent_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xE5, 0x0F,
                                    1 if payload.lower() == 'on' else 0, 0xD1, 0xEA)

            elif topic == self.progressive_inverter_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xE6, 0x0F,
                                    1 if payload.lower() == 'on' else 0, 0xD1, 0xEA)

            elif topic == self.bath_fan_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xE9, 0x0F,
                                    1 if payload.lower() == 'on' else 0, 0xD1, 0xEA)

            elif topic == self.black_tank_setting_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xEC, 0x0F,
                                    1 if payload.lower() == 'on' else 0, 0xD1, 0xEA)

            elif topic == self.gen_aes_mode_set_topic:
                mode_map = {'ags': 1, 'aes': 2, 'aes single output': 3}
                val = mode_map.get(payload.lower())
                if val is None:
                    self.Logger.warning(f"Unknown gen/aes mode: {payload}")
                    return
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xEF, 0x0F, val, 0xD1, 0xEA)

            elif topic == self.selected_floorplan_set_topic:
                fp_map = {'sy': 4, 'wa': 7, 'wd': 8, 'wt': 9}
                val = fp_map.get(payload.lower())
                if val is None:
                    self.Logger.warning(f"Unknown floorplan: {payload}")
                    return
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xF5, 0x0F, val, 0xD1, 0xEA)

            elif topic == self.num_batteries_set_topic:
                battery_map = {'1 battery': 0, '2 batteries': 1}
                val = battery_map.get(payload.lower())
                if val is None:
                    try:
                        val = int(payload)
                    except ValueError:
                        self.Logger.warning(f"Unknown battery count: {payload}")
                        return
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xD8, 0x0F, val, 0xD1, 0xEA)

            elif topic == self.go_power_controllers_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xD7, 0x0F,
                                    round(float(payload)), 0xD1, 0xEA)

            elif topic == self.ags_retry_interval_set_topic:
                frame = struct.pack("<BBBBHBB", 0xFF, 0x96, 0xF7, 0x0F,
                                    round(float(payload)), 0xD1, 0xEA)

            elif topic == self.aes_enabled_set_topic:
                enable = payload.lower() == 'on'
                if enable:
                    frames = [
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x00, 0x0F, 0x01, 0x00, 0xD1, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x2F, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x2E, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x33, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x2B, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x2C, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x31, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x0C, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x0D, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x0E, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x0F, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x16, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x15, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x01, 0x0F, 0x01, 0x00, 0xD1, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x01, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x9B, 0x0F, 0x01, 0x00, 0xD1, 0xFF),
                    ]
                else:
                    frames = [
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x01, 0x0F, 0x00, 0x00, 0xD1, 0xEA),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x06, 0x0F, 0x00, 0x00, 0xD1, 0xEA),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x58, 0x0F, 0x00, 0x00, 0xD1, 0xEA),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x58, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x4F, 0x0F, 0x00, 0x00, 0xD1, 0xEA),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0xB8, 0x0F, 0x00, 0x00, 0xD1, 0xEA),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x01, 0x0F, 0xFF, 0xFF, 0xD3, 0xFF),
                        struct.pack("<BBBBBBBB", 0xFF, 0x96, 0x9B, 0x0F, 0x00, 0x00, 0xD1, 0xFF),
                    ]
                for f in frames:
                    self.send_queue.put({"dgn": "1FED9", "data": bytearray(f)})
                return

            elif topic == self.engine_start_set_topic:
                if payload.lower() == 'on':
                    # Start engine: DC_DIMMER_COMMAND_2 instance=18, level=100%, command=on_duration
                    frame = struct.pack("<BBBBBBBB", 0x12, 0xFF, 0xC8, 0x01, 0xFF, 0x00, 0xFF, 0xFF)
                else:
                    # Stop engine: DC_DIMMER_COMMAND_2 instance=18, level=0%, command=off
                    frame = struct.pack("<BBBBBBBB", 0x12, 0xFF, 0x00, 0x03, 0xFF, 0x00, 0xFF, 0xFF)
                self.send_queue.put({"dgn": "1FEDB", "data": bytearray(frame)})
                return

            else:
                self.Logger.warning(f"Unhandled set topic: {topic}")
                return

            self.send_queue.put({"dgn": "1FED9", "data": bytearray(frame)})

        except Exception as e:
            self.Logger.error(f"Failed to process MQTT set message on {topic}: {e}")

    def publish_ha_discovery_config(self):
        """Publish Home Assistant MQTT auto-discovery config for all G12 entities."""
        if not hasattr(self, 'max_engine_run_time_topic'):
            return

        has_cmd = hasattr(self, 'max_engine_run_time_set_topic')
        origin = {'name': self.mqtt_support.get_bridge_ha_name()}
        cmps = {}

        # --- number entities ---
        number_specs = [
            ('max_engine_run_time',  self.max_engine_run_time_topic,
             self.max_engine_run_time_set_topic if has_cmd else None,
             'Max Engine Run Time', {'unit_of_measurement': 'min', 'min': 60, 'max': 115, 'step': 1, 'mode': 'auto'}),
            ('time_at_start_volts',  self.time_at_start_volts_topic,
             self.time_at_start_volts_set_topic if has_cmd else None,
             'Time at Start Volts',  {'unit_of_measurement': 's',   'min': 10, 'max': 300, 'step': 10, 'mode': 'auto'}),
            ('time_at_stop_volts',   self.time_at_stop_volts_topic,
             self.time_at_stop_volts_set_topic if has_cmd else None,
             'Time at Stop Volts',   {'unit_of_measurement': 's',   'min': 600, 'max': 3600, 'step': 300, 'mode': 'auto'}),
            ('stop_at_voltage',      self.stop_at_voltage_topic,
             self.stop_at_voltage_set_topic if has_cmd else None,
             'Stop at Voltage',
             {'unit_of_measurement': 'V', 'device_class': 'voltage', 'min': 50.0, 'max': 58.8, 'step': 0.1, 'mode': 'auto'}),
            ('start_at_voltage',     self.start_at_voltage_topic,
             self.start_at_voltage_set_topic if has_cmd else None,
             'Start at Voltage',
             {'unit_of_measurement': 'V', 'device_class': 'voltage', 'min': 51.0, 'max': 54.8, 'step': 0.1, 'mode': 'auto'}),
            ('threshold_33_pct',     self.threshold_cc_topic,
             self.threshold_cc_set_topic if has_cmd else None,
             'Tank Threshold 33%',   {'unit_of_measurement': '',    'min': 0, 'max': 65535, 'step': 1, 'mode': 'auto'}),
            ('threshold_66_pct',     self.threshold_cd_topic,
             self.threshold_cd_set_topic if has_cmd else None,
             'Tank Threshold 66%',   {'unit_of_measurement': '',    'min': 0, 'max': 65535, 'step': 1, 'mode': 'auto'}),
            ('threshold_100_pct',    self.threshold_ce_topic,
             self.threshold_ce_set_topic if has_cmd else None,
             'Tank Threshold 100%',  {'unit_of_measurement': '',    'min': 0, 'max': 65535, 'step': 1, 'mode': 'auto'}),
        ]
        for sub_id, state_topic, cmd_topic, label, extra in number_specs:
            cmp = {'p': 'number', 'name': label,
                   'state_topic': state_topic,
                   'unique_id': self.unique_device_id + '_' + sub_id}
            cmp.update(extra)
            if cmd_topic:
                cmp['command_topic'] = cmd_topic
            cmps[sub_id] = cmp

        # --- text entities (quiet time) ---
        text_specs = [
            ('quiet_time_start', self.quiet_time_start_topic,
             self.quiet_time_start_set_topic if has_cmd else None,
             'Quiet Time Start'),
            ('quiet_time_stop',  self.quiet_time_stop_topic,
             self.quiet_time_stop_set_topic if has_cmd else None,
             'Quiet Time Stop'),
        ]
        for sub_id, state_topic, cmd_topic, label in text_specs:
            cmp = {'p': 'text', 'name': label,
                   'state_topic': state_topic,
                   'pattern': r'^([01]\d|2[0-3]):[0-5]\d$',
                   'unique_id': self.unique_device_id + '_' + sub_id}
            if cmd_topic:
                cmp['command_topic'] = cmd_topic
            cmps[sub_id] = cmp

        # --- read-only sensors ---
        cmps['product_id'] = {
            'p': 'sensor', 'name': 'Product ID',
            'state_topic': self.product_id_topic,
            'enabled_by_default': False,
            'unique_id': self.unique_device_id + '_product_id'}

        cmps['fault_code'] = {
            'p': 'sensor', 'name': 'Fault Code',
            'state_topic': self.dm_rv_fault_code_topic,
            'unique_id': self.unique_device_id + '_fault_code'}

        cmps['fault_description'] = {
            'p': 'sensor', 'name': 'Fault Description',
            'state_topic': self.dm_rv_fault_description_topic,
            'enabled_by_default': False,
            'unique_id': self.unique_device_id + '_fault_description'}

        cmps['fault_lamp'] = {
            'p': 'binary_sensor', 'name': 'Fault Lamp',
            'state_topic': self.dm_rv_lamp_topic,
            'device_class': 'problem',
            'payload_on': 'on', 'payload_off': 'off',
            'unique_id': self.unique_device_id + '_fault_lamp'}

        # --- input binary sensors (1–15, all disabled by default) ---
        for n in range(1, 16):
            cmps[f'input_{n}'] = {
                'p': 'binary_sensor', 'name': f' Input {n}',
                'state_topic': f'{self._input_topic_base}/inputs/{n}/active',
                'payload_on': 'true', 'payload_off': 'false',
                'enabled_by_default': False,
                'unique_id': self.unique_device_id + f'_input_{n}'}

        has_new_cmd = hasattr(self, 'ags_low_volts_trigger_set_topic')

        # --- engine start/stop buttons + status sensor ---
        if hasattr(self, 'engine_running_topic'):
            cmps['engine_status'] = {
                'p': 'binary_sensor',
                'name': 'Engine Starting Status',
                'state_topic': self.engine_running_topic,
                'payload_on': 'on', 'payload_off': 'off',
                'unique_id': self.unique_device_id + '_engine_status',
            }
        if hasattr(self, 'engine_start_set_topic'):
            cmps['engine_start'] = {
                'p': 'button',
                'name': 'Start Engine',
                'command_topic': self.engine_start_set_topic,
                'payload_press': 'on',
                'unique_id': self.unique_device_id + '_engine_start',
            }
            cmps['engine_stop'] = {
                'p': 'button',
                'name': 'Stop Engine',
                'command_topic': self.engine_start_set_topic,
                'payload_press': 'off',
                'unique_id': self.unique_device_id + '_engine_stop',
            }

        # --- AES enabled switch ---
        if hasattr(self, 'aes_enabled_topic'):
            aes_cmp = {
                'name': 'AES Enabled',
                'state_topic': self.aes_enabled_topic,
                'payload_on': 'on', 'payload_off': 'off',
                'unique_id': self.unique_device_id + '_aes_enabled',
            }
            if hasattr(self, 'aes_enabled_set_topic'):
                aes_cmp['p'] = 'switch'
                aes_cmp['command_topic'] = self.aes_enabled_set_topic
            else:
                aes_cmp['p'] = 'binary_sensor'
            cmps['aes_enabled'] = aes_cmp

        # --- newly discovered on/off settings (switch when writable) ---
        onoff_specs = [
            ('ags_low_volts_trigger', self.ags_low_volts_trigger_topic,
             self.ags_low_volts_trigger_set_topic if has_new_cmd else None, 'AGS Low Volts Trigger'),
            ('cargo_bath_light',      self.cargo_bath_light_topic,
             self.cargo_bath_light_set_topic if has_new_cmd else None,      'Cargo/Bath Light (CH.25)'),
            ('bunk_accent',           self.bunk_accent_topic,
             self.bunk_accent_set_topic if has_new_cmd else None,           'Bunk Accent'),
            ('progressive_inverter',  self.progressive_inverter_topic,
             self.progressive_inverter_set_topic if has_new_cmd else None,  'Progressive Inverter'),
            ('bath_fan',              self.bath_fan_topic,
             self.bath_fan_set_topic if has_new_cmd else None,              'Bath Fan'),
            ('black_tank_setting',    self.black_tank_setting_topic,
             self.black_tank_setting_set_topic if has_new_cmd else None,    'Black Tank'),
        ]
        for sub_id, state_topic, cmd_topic, label in onoff_specs:
            cmp = {'name': label, 'state_topic': state_topic,
                   'payload_on': 'on', 'payload_off': 'off',
                   'unique_id': self.unique_device_id + '_' + sub_id}
            if cmd_topic:
                cmp['p'] = 'switch'
                cmp['command_topic'] = cmd_topic
            else:
                cmp['p'] = 'binary_sensor'
            cmps[sub_id] = cmp

        # --- newly discovered numeric settings ---
        cmps['ags_gen_start_retries'] = {
            'p': 'sensor', 'name': 'AGS Gen Start Retries',
            'state_topic': self.ags_gen_start_retries_topic,
            'unique_id': self.unique_device_id + '_ags_gen_start_retries'}

        cmps['go_power_controllers'] = {
            'p': 'number' if has_new_cmd else 'sensor',
            'name': 'Go Power! Controllers',
            'state_topic': self.go_power_controllers_topic,
            'min': 0, 'max': 5, 'step': 1, 'mode': 'auto',
            'unique_id': self.unique_device_id + '_go_power_controllers'}
        if has_new_cmd:
            cmps['go_power_controllers']['command_topic'] = self.go_power_controllers_set_topic

        cmps['ags_retry_interval'] = {
            'p': 'number' if has_new_cmd else 'sensor',
            'name': 'AGS Retry Interval',
            'state_topic': self.ags_retry_interval_topic,
            'unit_of_measurement': 's',
            'min': 25, 'max': 65, 'step': 5, 'mode': 'auto',
            'unique_id': self.unique_device_id + '_ags_retry_interval'}
        if has_new_cmd:
            cmps['ags_retry_interval']['command_topic'] = self.ags_retry_interval_set_topic

        # --- newly discovered text/enum settings ---
        cmps['num_batteries'] = {
            'p': 'select' if has_new_cmd else 'sensor',
            'name': 'Number of Batteries',
            'state_topic': self.num_batteries_topic,
            'options': ['1 battery', '2 batteries'],
            'unique_id': self.unique_device_id + '_num_batteries'}
        if has_new_cmd:
            cmps['num_batteries']['command_topic'] = self.num_batteries_set_topic

        cmps['ags_config_mode'] = {
            'p': 'sensor', 'name': 'AGS Config Mode',
            'state_topic': self.ags_config_mode_topic,
            'unique_id': self.unique_device_id + '_ags_config_mode'}

        cmps['gen_aes_mode'] = {
            'p': 'select' if has_new_cmd else 'sensor',
            'name': 'Generator/AES Mode',
            'state_topic': self.gen_aes_mode_topic,
            'options': ['AGS', 'AES', 'AES Single Output'],
            'unique_id': self.unique_device_id + '_gen_aes_mode'}
        if has_new_cmd:
            cmps['gen_aes_mode']['command_topic'] = self.gen_aes_mode_set_topic

        cmps['selected_floorplan'] = {
            'p': 'select' if has_new_cmd else 'sensor',
            'name': 'Selected Floorplan',
            'state_topic': self.selected_floorplan_topic,
            'options': ['SY', 'WA', 'WD', 'WT'],
            'unique_id': self.unique_device_id + '_selected_floorplan'}
        if has_new_cmd:
            cmps['selected_floorplan']['command_topic'] = self.selected_floorplan_set_topic

        config = {'dev': self.device, 'o': origin, 'cmps': cmps, 'qos': 1}
        config.update(self.get_availability_discovery_info_for_ha())
        self.mqtt_support.client.publish(
            self.mqtt_support.make_ha_auto_discovery_config_topic(self.unique_device_id, 'device'),
            json.dumps(config),
            retain=False)

    def initialize(self):
        self.publish_ha_discovery_config()
