"""
Touchscreen control panel entity

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
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class Touchscreen(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "TOUCHSCREEN", "type": "touchscreen"}

    """
    Entity for a touchscreen control panel.

    Listens to INITIAL_PACKET / DATA_PACKET multi-packet transport filtered
    by source_id (default 0x9F) and publishes PRODUCT_IDENTIFICATION.
    Also handles DM_RV for fault reporting.

    Floorplan entry example:
      - name: TOUCHSCREEN
        type: touchscreen
        source_id: '9F'
        instance_name: "Touchscreen"
        status_topic: "rvc2mqtt/touchscreen"
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "touchscreen-" + str(data['source_id'])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        self.source_id = str(data['source_id'])

        self.rvc_match_initial_packet = {"name": "INITIAL_PACKET", "source_id": self.source_id}
        self.rvc_match_data_packet    = {"name": "DATA_PACKET",    "source_id": self.source_id}
        self.rvc_match_dm_rv          = {"name": "DM_RV",          "source_id": self.source_id}

        # INITIAL_PACKET / DATA_PACKET (multi-packet transport for PRODUCT_IDENTIFICATION)
        self._mp_expected_count = 0
        self._mp_message_length = 0
        self._mp_packets = {}
        self._product_id = None

        # DM_RV
        self._fault_code = "unknown"
        self._fault_description = "unknown"
        self._lamp = "unknown"

        if 'status_topic' in data:
            topic_base = str(data['status_topic'])
            self.product_id_topic              = str(f"{topic_base}/product_id")
            self.dm_rv_fault_code_topic        = str(f"{topic_base}/fault/code")
            self.dm_rv_fault_description_topic = str(f"{topic_base}/fault/description")
            self.dm_rv_lamp_topic              = str(f"{topic_base}/fault/lamp")

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming RVC message and determine if it is of interest.

        Returns True if the message was handled, False otherwise.
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
            try:
                data_bytes = int(new_message["data"]).to_bytes(7, 'little')
            except OverflowError:
                self.Logger.warning(
                    f"DATA_PACKET #{packet_num}: data value too large, discarding packet")
                return True
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
                ,2) - 0x7F000)
            fault_description = new_message.get("fmi_definition", "unknown")

            if int(new_message["red_lamp_status"]) > 0:
                lamp_status = "red"
            elif int(new_message["yellow_lamp_status"]) > 0:
                lamp_status = "yellow"
            else:
                lamp_status = "off"

            if self._fault_code != message_fault_code:
                self._fault_code = message_fault_code
                self._fault_description = fault_description
                if hasattr(self, 'dm_rv_fault_code_topic'):
                    self.mqtt_support.client.publish(
                        self.dm_rv_fault_code_topic,
                        "00" if self._fault_code == "4095" else str(self._fault_code),
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

        return False
