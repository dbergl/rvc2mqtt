"""
DC system sensor from DC_SOURCE_STATUS_G12


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

import queue
import logging
import struct
import json
import time
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes


class DcSystemSensor_DC_SOURCE_STATUS_1(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"type": "dc_system", "name": "APS-500"}

    """ Provide basic DC system information as published by the APS-500
        using DC_SOURCE_STATUS_1 - 5, CHARGER_STATUS, CHARGER_STATUS_2,
        and CHARGER_EQUALIZATION_STATUS
    """
    apcfaults = {
        "0":  "No Fault",
        "12": "Battery Temperature greatly exceeded configured upper limit.",
        "13": "Battery Voltage greatly exceeded upper limit, measured by VBat+",
        "14": "Battery Voltage too low to operate as measured on VBat+. Damaged or missing sensing wire or fuse? (or engine not started!)",
        "15": "Voltage at Vbat+ exceeded Max Bat Volts as defined by $CPB:",
        "16": "Battery Temperature is shorted (Defective)",
        "21": "Alternator Temperature greatly exceeded configured upper limit.",
        "24": "Alternator Temperature greatly exceeded configured upper limit. (2nd temp reached / exceeded while ramping - this can NOT be right, to reach target while ramping means way too risky.)",
        "25": "Alt Temp is rising REALLY fast, damaged?",
        "41": "Internal Field FET temperature exceed limit.",
        "42": "A \'Required\' sensor is missing, and we are configured to FAULT out.",
        "43": "No voltage has been sensed on the VAlt+ line, blown fuse?",
        "44": "There is excessive voltage offset between VAlt+ and VBat+ sense lines - 2.5v. (Not checked in \"Split\" voltage systems)",
        "45": "Voltage at VAlt+ exceeded Max Bat Volts (Plus additional allowance for IR drop) as defined by $CPB:",
        "46": "Voltage greatly exceeded expected upper limit battery limit as measured at VAlt+",
        "51": "Received a generic CAN message that the battery charging bus has been disconnected.",
        "52": "A CAN command has been received asking for the battery bus to be disconnected due to High Voltage. (Note that depending on the BMS, other alarms may trigger this same fault, ala, high charge current)",
        "53": "Battery Instance number is out of range (needs to be from 1..100)",
        "54": "Too many different BMS\'s are asking to be aggregated.",
        "55": "AEBus device (Discovery battery) has send a warning or fault status. As there is no fore-warning of a disconnect, treat all warnings as a pending disconnect and fault. But then do auto-restart to see if it clears.",
        "56": "Too many VEreg (Victron) devices present to track",
        "57": "A CAN command has been received asking for the battery bus to be disconnected due to Low Voltage.",
        "58": "A CAN command has been received asking for the battery bus to be disconnected due to High Current.",
        "59": "A CAN command has been received asking for the battery bus to be disconnected due to High Battery Temperature.",
        "61": "A CAN command has been received asking for the battery bus to be disconnected due to Low Battery Temperature.",
        "62": "A CAN status has been received that the battery has reached its upper limit, but not yet disconnecting. Charging should stop.",
        "82": "Primary Battery (HS) of DC-DC converter Over-voltage trip",
        "83": "Primary Battery (HS) of DC-DC converter Under-voltage trip",
        "84": "Secondary Battery (LS) of DC-DC converter Over-voltage trip",
        "85": "Secondary Battery (LS) of DC-DC converter Under-voltage trip",
        "86": "DCDC Convert too hot.",
        "87": "A configuration value has exceeded the selected DC-DC converter limits.",
        "88": "More than one device seems to be trying to control the DCDC converter.",
        "89": "Attached DCDC Converter is not same as make/model specified",
        "4095": "No Fault"
    }

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "aps-500-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # RVC message must match the following to be this device
        self.rvc_match_source_status_1 = {'name': 'DC_SOURCE_STATUS_1', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_2 = {'name': 'DC_SOURCE_STATUS_2', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_3 = {'name': 'DC_SOURCE_STATUS_3', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_4 = {'name': 'DC_SOURCE_STATUS_4', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_5 = {'name': 'DC_SOURCE_STATUS_5', 'source_id': str(data['source_id'])}

        self.rvc_match_battery_status_11 = {'name': 'BATTERY_STATUS_11', 'source_id': str(data['source_id'])}

        self.rvc_match_charger_status = {'name': 'CHARGER_STATUS', 'source_id': str(data['source_id'])}
        self.rvc_match_charger_status_2 = {'name': 'CHARGER_STATUS_2', 'source_id': str(data['source_id'])}

        self.rvc_match_charger_configuration_status = {'name': 'CHARGER_CONFIGURATION_STATUS', 'source_id': str(data['source_id'])}

        self.rvc_match_charger_equalization_status = {'name': 'CHARGER_EQUALIZATION_STATUS', 'source_id': str(data['source_id'])}

        self.rvc_match_dm_rv = {'name': 'DM_RV', 'source_id': str(data['source_id'])}

        self.rvc_match_terminal = {'name': 'TERMINAL', 'source_id': str(data['source_id'])}

        # According to Wakespeed these may be J1939 messages. We will just do
        # nothing with them, so the don't show as decoder pending
        self.rvc_match_0ef80 = {'name': 'UNKNOWN-0EF80'} # ignore id since it is 70 on this one message from the APS
        self.rvc_match_0ef70 = {'name': 'UNKNOWN-0EF70', 'source_id': str(data['source_id'])}
        self.rvc_match_0fed5 = {'name': 'UNKNOWN-0FED5', 'source_id': str(data['source_id'])}

        self.Logger.debug(f"Must match: {str(self.rvc_match_source_status_1)}")

        self.name = data['instance_name']

        # class specific values that change
        self._dc_voltage             = 5  # should never be this low
        self._dc_current             = 50  # should not be this high
        #DC_SOURCE_STATUS_4
        self._desired_charge_state   = "unknown"
        self._desired_dc_voltage     = "unknown" # expected is 54.7 volts
        self._desired_dc_current     = "unknown" # expected is 90 A
        #DC_SOURCE_STATUS_5
        self._hp_dc_voltage          = "unknown"
        #CHARGER_CONFIGURATION_STATUS
        self._charging_algorithm     = "unknown"
        self._charging_mode          = "unknown"
        self._battery_sensor_present = "unknown"
        #BATTERY_STATUS_11
        self._charge_detected        = "unknown"
        self._reserve_status         = "unknown"
        #CHARGER_STATUS
        self._charge_voltage         = "unknown"
        self._charge_current         = "unknown"
        self._charge_current_pct     = "unknown"
        self._operating_state        = "unknown"
        self._power_up_default_state = "unknown"
        self._auto_recharge_enable   = "unknown"
        self._force_charge           = "unknown"

        #CHARGER_STATUS_2
        self._charging_voltage       = "unknown"
        self._charging_current       = "unknown"
        self._charger_temperature    = "unknown"

        #DM_RV
        self._fault_code             = "unknown"
        self._fault_description      = "unknown"
        self._lamp                   = "unknown"

        #TERMINAL
        self._terminal_message_call  = {}
        self._terminalmessage        = ""

        if 'command_topic' in data:
            topic_base                            = str(data['command_topic'])
            self.reset_command_topic              = str(f"{topic_base}/reset")
            self.reboot_command_topic             = str(f"{topic_base}/reboot")
            self.request_last_fault_command_topic = str(f"{topic_base}/request_last_fault")
            self.terminal_command_topic           = str(f"{topic_base}/terminal")

        else:
            self.command_topic = mqtt_support.make_device_topic_string(
                self.id, None, False)

        self.mqtt_support.register(self.reset_command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.reboot_command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.request_last_fault_command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.terminal_command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base= str(data['status_topic'])

            # DC_SOURCE_STATUS_1
            #dc_voltage
            #dc_current - does not seem to actually be reported ??

            # DC_SOURCE_STATUS_4
            self.desired_charge_state_topic = str(f"{topic_base}/desired_charge_state")
            self.desired_dc_voltage_topic = str(f"{topic_base}/desired_dc_voltage")
            self.desired_dc_current_topic = str(f"{topic_base}/desired_dc_current")

            # DC_SOURCE_STATUS_5 (non-standard though)
            self.hp_dc_voltage_topic = str(f"{topic_base}/hp_dc_voltage")

            # CHARGER_STATUS
            self.charge_voltage_topic            = str(f"{topic_base}/charge_voltage")
            self.charge_current_topic            = str(f"{topic_base}/charge_current")
            self.charge_current_pct_topic        = str(f"{topic_base}/charge_current_pct")
            self.operating_state_topic           = str(f"{topic_base}/operating_state")
            self.power_up_default_state_topic    = str(f"{topic_base}/power_up_default_state")
            self.auto_recharge_enable_topic      = str(f"{topic_base}/auto_recharge_enable")
            self.force_charge_topic              = str(f"{topic_base}/force_charge")

            # CHARGER_STATUS_2
            self.charging_voltage_topic          = str(f"{topic_base}/charging_voltage")
            self.charging_current_topic          = str(f"{topic_base}/charging_current")
            self.charger_temperature_topic       = str(f"{topic_base}/charger_temp")

            # CHARGER_CONFIGURATION_STATUS
            self.charging_algorithm_topic        = str(f"{topic_base}/charging_algorithm")
            self.charging_mode_topic             = str(f"{topic_base}/charging_mode")
            self.battery_sensor_present_topic    = str(f"{topic_base}/battery_sensor_present")

            # BATTERY_STATUS_11
            self.charge_detected_topic           = str(f"{topic_base}/charge_detected")
            self.reserve_status_topic            = str(f"{topic_base}/reserve_status")

            # DM_RV
            self.dm_rv_fault_code_topic          = str(f"{topic_base}/fault/code")
            self.dm_rv_fault_description_topic   = str(f"{topic_base}/fault/description")
            self.dm_rv_lamp_topic                = str(f"{topic_base}/fault/lamp")

            # ???
            self.max_charging_current_topic      = str(f"{topic_base}/max_charging_current")
            self.max_charging_current_pct_topic  = str(f"{topic_base}/max_charging_current_pct")

            self.request_last_fault_status_topic = str(f"{topic_base}/fault/rlf_message")
            self.terminal_status_topic           = str(f"{topic_base}/danger/terminal_message")


        else:
            self.status_dc_voltage_topic = mqtt_support.make_device_topic_string(self.id, "missing_status_topic", True)

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False

        """

        if self._is_entry_match(self.rvc_match_source_status_1, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_source_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_source_status_3, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_source_status_4, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["desired_charge_state"] != self._desired_charge_state:
                self._desired_charge_state = new_message["desired_charge_state"]
                self.mqtt_support.client.publish(
                    self.desired_charge_state_topic, new_message.get("desired_charge_state_definition", "unknown").title(), retain=True)
            if new_message["desired_dc_voltage"] != self._desired_dc_voltage:
                self._desired_dc_voltage = new_message["desired_dc_voltage"]
                self.mqtt_support.client.publish(
                    self.desired_dc_voltage_topic, self._desired_dc_voltage, retain=True)
            if new_message["desired_dc_current"] != self._desired_dc_current:
                self._desired_dc_current = new_message["desired_dc_current"]
                self.mqtt_support.client.publish(
                    self.desired_dc_current_topic, self._desired_dc_current, retain=True)

            return True

        if self._is_entry_match(self.rvc_match_source_status_5, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._hp_dc_voltage != new_message["hp_dc_voltage"]:
                self._hp_dc_voltage = new_message["hp_dc_voltage"]
                self.mqtt_support.client.publish(
                    self.hp_dc_voltage_topic, f"{self._hp_dc_voltage:.3f}",
                    retain=True)
            return True

        if self._is_entry_match(self.rvc_match_charger_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charge_voltage != new_message["charge_voltage"]:
                self._charge_voltage = new_message["charge_voltage"]
                self.mqtt_support.client.publish(
                    self.charge_voltage_topic, self._charge_voltage, retain=True)
            if self._charge_current != new_message["charge_current"]:
                self._charge_current = new_message["charge_current"]
                self.mqtt_support.client.publish(
                    self.charge_current_topic, self._charge_current, retain=True)
            if self._charge_current_pct != new_message["charge_current_percent_of_maximum"]:
                self._charge_current_pct = new_message["charge_current_percent_of_maximum"]
                self.mqtt_support.client.publish(
                    self.charge_current_pct_topic, self._charge_current_pct, retain=True)
            if self._operating_state != new_message["operating_state"]:
                self._operating_state = new_message["operating_state"]
                self.mqtt_support.client.publish(
                    self.operating_state_topic, new_message.get("operating_state_definition", "unknown").title(), retain=True)
            if self._power_up_default_state != new_message["default_state_on_power-up"]:
                self._power_up_default_state = new_message["default_state_on_power-up"]
                self.mqtt_support.client.publish(
                    self.power_up_default_state_topic, new_message.get("default_state_on_power-up_definition", "unknown").title(), retain=True)
            if self._auto_recharge_enable != new_message["auto_recharge_enable"]:
                self._auto_recharge_enable = new_message["auto_recharge_enable"]
                self.mqtt_support.client.publish(
                    self.auto_recharge_enable_topic, new_message.get("auto_recharge_enable_definition", "unknown").title(), retain=True)
            if self._force_charge != new_message["force_charge"]:
                self._force_charge = new_message["force_charge"]
                self.mqtt_support.client.publish(
                    self.force_charge_topic, new_message.get("force_charge_definition", "unknown").title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_charger_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charging_voltage != new_message["charging_voltage"]:
                self._charging_voltage = new_message["charging_voltage"]
                self.mqtt_support.client.publish(
                    self.charging_voltage_topic, self._charging_voltage, retain=True)
            if self._charging_current != new_message["charging_current"]:
                self._charging_current = new_message["charging_current"]
                self.mqtt_support.client.publish(
                    self.charging_current_topic, self._charging_current, retain=True)
            if self._charger_temperature != new_message["charger_temperature"]:
                self._charger_temperature = new_message["charger_temperature"]
                self.mqtt_support.client.publish(
                    self.charger_temperature_topic, self._charger_temperature, retain=True)

            return True


        if self._is_entry_match(self.rvc_match_charger_configuration_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charging_algorithm != new_message["charging_algorithm"]:
                self._charging_algorithm = new_message["charging_algorithm"]
                self.mqtt_support.client.publish(
                    self.charging_algorithm_topic, new_message.get("charging_algorithm_definition", "unknown").title(), retain=True)

            if self._charging_mode != new_message["charger_mode"]:
                self._charging_mode = new_message["charger_mode"]
                self.mqtt_support.client.publish(
                    self.charging_mode_topic, new_message.get("charger_mode_definition", "unknown").title(), retain=True)

            if self._battery_sensor_present != new_message["battery_sensor_present"]:
                self._battery_sensor_present = new_message["battery_sensor_present"]
                self.mqtt_support.client.publish(
                    self.battery_sensor_present_topic, new_message.get("battery_sensor_present_definition", "unknown").title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_battery_status_11, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charge_detected != new_message["charge_detected"]:
                self._charge_detected = new_message["charge_detected"]
                self.mqtt_support.client.publish(
                self.charge_detected_topic, new_message.get("charge_detected_definition", "unknown").title(), retain=True)

            if self._reserve_status != new_message["reserve_status"]:
                self._reserve_status = new_message["reserve_status"]
                self.mqtt_support.client.publish(
                self.reserve_status_topic, new_message.get("reserve_status_definition", "unknown").title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_dm_rv, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            message_fault_code = str(
                int(f"{new_message['spn-msb']:08b}"
                    f"{new_message['spn-isb']:08b}"
                    f"{new_message['spn-lsb']:03b}"
                ,2) - 0x7F000)

            fault_description = self.apcfaults.get(str(message_fault_code), "Internal Error")
            lamp_status = "n/a"

            if int(new_message["red_lamp_status"]) > 0:
                lamp_status = "red"
            elif int(new_message["yellow_lamp_status"]) > 0:
                lamp_status = "yellow"
            else:
                lamp_status = "off"

            if self._fault_code != message_fault_code:
                self._fault_code = message_fault_code
                self._fault_description = fault_description
                # Fault_code 4095 actually means "No Fault" so publish "" instead
                self.mqtt_support.client.publish(
                    self.dm_rv_fault_code_topic,
                    "00" if self._fault_code == "4095" else str(self._fault_code),
                    retain=True)

                self.mqtt_support.client.publish(
                    self.dm_rv_fault_description_topic,
                    self._fault_description, retain=True)

            if self._lamp != lamp_status:
                self._lamp = lamp_status
                self.mqtt_support.client.publish(
                self.dm_rv_lamp_topic, self._lamp, retain=True)

            return True

        if self._is_entry_match(self.rvc_match_terminal, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            # Set CorrelationData and ResponseTopic
            messageproperties = Properties(PacketTypes.PUBLISH)
            if hasattr(self._terminal_message_call["properties"],'CorrelationData'):
                messageproperties.CorrelationData = self._terminal_message_call["properties"].CorrelationData
            messageproperties.ResponseTopic = self._terminal_message_call.get("responsetopic")

            response_timestamp = time.time()
            if response_timestamp > self._terminal_message_call.get("timestamp") and response_timestamp - self._terminal_message_call.get("timestamp") < 10.0:
                self._terminalmessage =  self._terminalmessage + new_message["data"]
                messages = bytearray.fromhex(self._terminalmessage).decode()
                publish_msg = False

                if "AOK;" in messages:
                    self.Logger.debug(f"Terminal message: {bytearray.fromhex(self._terminalmessage).decode()}")
                    publish_msg = True

                elif "RST;" in messages:
                    self.Logger.debug(f"Terminal message: {bytearray.fromhex(self._terminalmessage).decode()}")
                    publish_msg = True

                if publish_msg:
                    # Pubish full TERMINAL response
                    self.mqtt_support.client.publish(topic=self.terminal_status_topic,
                        payload=messages, retain=False, properties=messageproperties)
                    # Publish payload to responsetopic if it exists
                    if self._terminal_message_call.get("responsetopic") is not None:
                        self.mqtt_support.client.publish(topic=self._terminal_message_call.get("responsetopic"),
                            payload=self._terminal_message_call.get("payload"), retain=True, properties=messageproperties)

                    self._terminal_message_call = {}
                    self._terminalmessage = ""

                return True
            return True

        if self._is_entry_match(self.rvc_match_0ef80, new_message):
            # likely J1939 message so do nothing
            return True
        if self._is_entry_match(self.rvc_match_0ef70, new_message):
            # likely J1939 message so do nothing
            return True
        if self._is_entry_match(self.rvc_match_0fed5, new_message):
            # likely J1939 message so do nothing
            return True

        return False


    def format_terminal_message(data: str) -> list[bytearray]:
        """
        Splits a string into 8 byte byte arrays.
        Appends CR/LF which is expected by APS-500
        Pads bytes with 0xFF if < 8 bytes
        to match RV-C spec for TERMINAL messages
        """

        try:
            # Append CRLF and encode to ASCII
            data += '\x0d\x0a'
            byte_data = data.encode('ascii')
        except UnicodeEncodeError as e:
            raise ValueError("Input string contains non-ASCII characters.") from e

        # Initialize the result list
        chunks = []

        # Process in chunks of 8 bytes
        for i in range(0, len(byte_data), 8):
            chunk = byte_data[i:i+8]
            if len(chunk) < 8:
                # Pad with 0xFF if less than 8 bytes
                chunk += b'\xFF' * (8 - len(chunk))
            chunks.append(bytearray(chunk))

        return chunks


    def send_terminal_message(self, message: list[bytearray]):
        """
        Sends message(s) to the APS-500 using the TERMINAL DGN
        """
        for msg_bytes in message:
            self.send_queue.put({"dgn": "17E80", "data": msg_bytes})
            time.sleep(.10)


    def reset_aps(self, properties = None):
        """
        Sends GENERAL_RESET dgn = 17F00 to the APS-500
        Only sends reset message
        """
        self.Logger.debug("Sending GENERAL_RESET message")
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0x05,
            0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)

        self._terminal_message_call["payload"] = ""
        self._terminal_message_call["responsetopic"] = None
        if properties is not None:
            self._terminal_message_call["properties"] = properties
        self._terminal_message_call["timestamp"] = time.time()

        self.send_queue.put({"dgn": "17F80", "data": msg_bytes})


    def request_last_fault(self, properties = None):
        """
        Sends $RLF: to TERMINAL dgn = 17E80 to the APS-500
        $RLF: = 24 52 4C 46 3A
        """
        self.Logger.debug("Sending Request Last Fault ASCII message")

        message = format_terminal_message('$RLF:')

        self._terminal_message_call["payload"] = "requested"
        self._terminal_message_call["responsetopic"] = self.request_last_fault_status_topic
        self._terminal_message_call["properties"] = properties
        self._terminal_message_call["timestamp"] = time.time()

        self.send_terminal_message(message)


    def reboot_aps(self, properties = None):
        """
        Sends $RBT: to TERMINAL dgn = 17E80 to the APS-500
        $RBT: = 24 52 42 54 3A
        """
        self.Logger.debug("Sending reboot ASCII message")

        message = format_terminal_message('$RBT:')

        self._terminal_message_call["payload"] = 0
        self._terminal_message_call["responsetopic"] = None
        if properties is not None:
            self._terminal_message_call["properties"] = properties
        self._terminal_message_call["timestamp"] = time.time()

        self.send_terminal_message(message)


    def process_mqtt_msg(self, topic, payload, properties = None):
        self.Logger.info(
            f"MQTT Msg Received on topic {topic} with payload {payload}")
        match topic:
            case self.reset_command_topic:
                try:
                    match payload:
                        case '1':
                            self.reset_aps(properties) if properties is not None else self.reset_aps()
                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")

            case self.reboot_command_topic:
                try:
                    match payload:
                        case '1':
                            self.reboot_aps(properties)
                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")

            case self.request_last_fault_command_topic:
                try:
                    match payload:
                        case '1':
                            self.request_last_fault(properties) if properties is not None else self.request_last_fault()
                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")

            case self.terminal_command_topic:
                try:
                    match payload:
                        case s if s.startswith('$'):
                            self.Logger.debug("Sending ASCII message")

                            message = format_terminal_message(payload)

                            self._terminal_message_call["payload"] = payload
                            if responsetopic is not None:
                                self._terminal_message_call["responsetopic"] = responsetopic
                            if properties is not None:
                                self._terminal_message_call["properties"] = properties
                            self._terminal_message_call["timestamp"] = time.time()

                            self.send_terminal_message(message)

                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")


    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """

        self.mqtt_support.client.publish(
            self.request_last_fault_status_topic, "unknown", retain=True)


        # request dgn report - this should trigger this device to report
        # dgn = 1FFC6 which is actually  C6 FF 01 <instance> 00 00 00 00
        # where instance = FF for all
        self.Logger.debug("Sending Request for DGN")
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0xC6,
            0xFF, 1, 0xFF, 0, 0, 0, 0)

        self.send_queue.put({"dgn": "0EA80", "data": msg_bytes})

