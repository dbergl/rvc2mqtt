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

        self.source_id = str(data['source_id'])

        # RVC message must match the following to be this device
        self.rvc_match_g12_config     = {"name": "G12_CONFIGURATION", "source_id": self.source_id}
        self.rvc_match_initial_packet = {"name": "INITIAL_PACKET", "source_id": self.source_id}
        self.rvc_match_data_packet    = {"name": "DATA_PACKET", "source_id": self.source_id}
        self.rvc_match_dm_rv          = {"name": "DM_RV", "source_id": self.source_id}
        self.rvc_match_input_status   = {"name": "G12_INPUT_STATUS", "source_id": self.source_id}
        # 1FED9 comes from touchscreen (0x9F), not G12 (0x9C) — no source_id filter
        self.rvc_match_g12_indicator  = {"name": "GENERIC_INDICATOR_COMMAND"}

        # DM_RV
        self._fault_code = "unknown"
        self._fault_description = "unknown"
        self._lamp = "unknown"

        # INITIAL_PACKET / DATA_PACKET (multi-packet transport for PRODUCT_IDENTIFICATION)
        self._mp_expected_count = 0
        self._mp_message_length = 0
        self._mp_packets = {}
        self._product_id = None

        # G12_INPUT_STATUS (1FBDA) — None=uninitialized, 0=idle, n=input n active
        self._active_input_num = None
        # aux_12v_active from the last active-input frame; used to suppress the G12's
        # normal FB/idle heartbeat that fires while a 12V input is held.
        self._last_aux_12v = 0
        # input number last confirmed as a 12V type (seen with aux_12v_active=1);
        # used to recognise the AA00 deactivation frame for 12V inputs.
        self._12v_input_num = None

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
                self.mqtt_support.client.publish(
                    self.dm_rv_fault_code_topic,
                    str(self._fault_code),
                    retain=True)
                self.mqtt_support.client.publish(
                    self.dm_rv_fault_description_topic,
                    self._fault_description, retain=True)
            if self._lamp != lamp_status:
                self._lamp = lamp_status
                self.mqtt_support.client.publish(
                    self.dm_rv_lamp_topic, self._lamp, retain=True)
            return True

        if self._is_entry_match(self.rvc_match_input_status, new_message):
            self.Logger.debug(f"Msg Match G12_INPUT_STATUS: {str(new_message)}")
            code = int(new_message["active_input_code"])
            aux = int(new_message.get("aux_12v_active", 0))

            if 0xA1 <= code <= 0xAF:
                new_input = code & 0x0F
                if aux:
                    # Confirmed 12V input active; record which input is the 12V type.
                    self._last_aux_12v = 1
                    self._12v_input_num = new_input
                elif new_input == self._12v_input_num:
                    # Known 12V input but aux_12v_active dropped — it is deactivating.
                    self._last_aux_12v = 0
                    new_input = 0
                # else: GND input (aux=0 is normal), treat as active
            else:
                # Idle or unknown code.  When aux_12v_active is still set AND the last
                # active-input frame also had aux_12v_active set, this is the G12's normal
                # heartbeat alternation while a 12V input is held — skip it.
                if aux and self._last_aux_12v:
                    return True
                self._last_aux_12v = 0
                if code != 0xFB:
                    self.Logger.debug(f"G12_INPUT_STATUS code {hex(code)}, treating as idle")
                new_input = 0

            if new_input != self._active_input_num:
                prev = self._active_input_num
                self._active_input_num = new_input
                if hasattr(self, '_input_topic_base'):
                    if prev is not None and prev != 0:
                        self.mqtt_support.client.publish(
                            f"{self._input_topic_base}/inputs/{prev}/active", "false", retain=True)
                    if new_input != 0:
                        self.mqtt_support.client.publish(
                            f"{self._input_topic_base}/inputs/{new_input}/active", "true", retain=True)
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
            return True

        if not self._is_entry_match(self.rvc_match_g12_config, new_message):
            return False

        self.Logger.debug(f"G12_CONFIGURATION match: {str(new_message)}")
        msg_type = new_message.get("message_type", "")

        if msg_type in ("1", "3", "5", "9B"):
            # AES-related messages - no decoded parameters, just acknowledge
            self.Logger.debug(f"G12 AES message type {msg_type}: {str(new_message)}")

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

        else:
            self.Logger.debug(f"G12_CONFIGURATION unhandled message type {msg_type}: {str(new_message)}")

        return True

    def process_mqtt_msg(self, topic, payload, properties=None):
        """ Handle an inbound MQTT set message by sending a 1FED9 G12 config command. """
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

            else:
                self.Logger.warning(f"Unhandled set topic: {topic}")
                return

            self.send_queue.put({"dgn": "1FED9", "data": bytearray(frame)})

        except Exception as e:
            self.Logger.error(f"Failed to process MQTT set message on {topic}: {e}")
