"""
A light switch

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


import queue
import logging
import struct
import json
from datetime import datetime
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class Datetime_DATE_TIME_STATUS(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "DATE_TIME_STATUS", "type": "system_clock"}
    """
    Device that is tied to RVC DGN of DATE_TIME_STATUS and SET_DATE_TIME_COMMAND

    TODO: Add support for GPS_DATE_TIME_STATUS

    """


    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "datetime-1FFFF" + str(data["source_id"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # Allow MQTT to set teh time
        self.command_topic = mqtt_support.make_device_topic_string(
            self.id, None, False)
        self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        # RVC message must match the following to be this device
        self.rvc_match_status = { "name": "DATE_TIME_STATUS", "source_id": data['source_id']}
        self.rvc_match_command= { "name": "SET_DATE_TIME_COMMAND"}

        self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")

        # save these for later to send rvc msg
        self.name = data['instance_name']
        self.source_id = data['source_id']
        self.state = "unknown"

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False

        Messages look like:

            RV-C message for DATE_TIME_STATUS

        {'arbitration_id': '0x19ffff9c', 'data': '0001020202370AFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'FF', 'dgn': '1FFFF',
        'source_id': '9C', 'name': 'DATE_TIME_STATUS',
        'year': 0,
        'month': 1,
        'date': 2,
        'day_of_week': 2, 'day_of_week_definition': 'Monday',
        'hour': 2,
        'minute': 55,
        'second': 10,
        'time_zone': 255}

        """

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            '''
            TODO: Process message and publish date and time??

            self.mqtt_support.client.publish(
                self.status_topic, self.state, retain=True)
            '''
            return True

        elif self._is_entry_match(self.rvc_match_command, new_message):
            # This is the command.  Just eat the message so it doesn't show up
            # as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            return True
        return False

    def _make_rvc_payload(self, thedatetime:datetime):
        ''' Make 8 byte buffer in SET_DATE_TIME_COMMAND format.
        e.x. 20240929T19:20:30
        {   'arbitration_id': '0x19fffe44', 'data': '0200645824582400',
            'priority': '5', 'dgn_h': '1FF', 'dgn_l': 'FE', 'dgn': '1FFFE',
            'source_id': '44',
            'name': 'THERMOSTAT_COMMAND_1',
            'year': 24,
            'month': '9',
            'date': '29',
            'day_of_week': '1', 'day_of_week_definition': 'Sunday'
            'hour': '19',
            'minute': '20',
            'second': '30',
            'time_zone': '255'
         '''
        # python days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        # python day_of_week=["0","1","2","3","4","5","6"]

        # RV-C days=["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
        RVC_DAY_OF_WEEK = ["2","3","4","5","6","7","1"]

        msg_bytes = bytearray(8)
        year = (thedatetime.year - 2000)
        month = thedatetime.month
        date = thedatetime.day
        rvc_day_of_week = RVC_DAY_OF_WEEK[thedatetime.weekday()]
        hour = thedatetime.hour
        minute = thedatetime.minute
        second = thedatetime.second
        timezone = 255 #firefly seems to only set timezone to 255

        struct.pack_into("<BBBBBBBB", msg_bytes, year, month, date, rvc_day_of_week, hour, minute, second, time_zone )
        return msg_bytes

    def process_mqtt_msg(self, topic, payload):
        self.Logger.debug(
            f"MQTT Msg Received on topic {topic} with payload {payload}")

        if topic == self.command_topic:
            try:
                dt = datetime.fromisoformat(payload)
                pl = self._make_rvc_payload(dt)
                self.send_queue.put({"dgn": "1FFFE", "data": pl})
            except Exception as e:
                self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")
        else:
            self.Logger.warning(
            f"Invalid payload {payload} for topic {topic}")

    def initialize(self):
        """ Optional function 
        Will get called once when the object is loaded.  
        RVC canbus tx queue is available
        mqtt client is ready.  

        This can be a good place to request data

        """

        # publish info to mqtt
        self.mqtt_support.client.publish(
            self.status_topic, self.state, retain=True)

