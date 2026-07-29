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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class Datetime_DATE_TIME_STATUS(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "DATE_TIME_STATUS", "type": "system_clock"}
    """
    Device that is tied to RVC DGN of DATE_TIME_STATUS and SET_DATE_TIME_COMMAND

    TODO: Add support for GPS_DATE_TIME_STATUS

    """


    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "datetime-1FFFF" + str(data["instance_name"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # Allow MQTT to set the time
        if 'command_topic' in data:
            self.command_topic = str(data['command_topic'])
        else:
            self.command_topic = mqtt_support.make_device_topic_string(
            self.id, None, False)

        if 'status_topic' in data:
            self.status_topic = str(data['status_topic'])

        self.timezone_topic = f"{self.status_topic}/tz"
        self.timezone_set_topic = f"{self.command_topic}/tz"

        self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.timezone_set_topic, self.process_mqtt_msg)

        # RVC message must match the following to be this device
        self.rvc_match_status = { "name": "DATE_TIME_STATUS" }
        self.rvc_match_command= { "name": "SET_DATE_TIME_COMMAND"}

        self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")

        # save these for later to send rvc msg
        self.name = data['instance_name']
        self.state = "unknown"

        # Optional IANA timezone (e.g. 'America/New_York') the RV-C clock
        # represents. When set, the published state is naive ISO and HA is
        # told to interpret it in this zone via the discovery `timezone`
        # field. When omitted, fall back to the container's local zone.
        self.tz_name = data.get('timezone')
        self.tz: ZoneInfo = None
        if self.tz_name:
            try:
                self.tz = ZoneInfo(self.tz_name)
            except ZoneInfoNotFoundError:
                self.Logger.error(
                    f"Unknown timezone {self.tz_name!r}; falling back to system local")
                self.tz_name = None

        self.device = {"manufacturer": "RV-C",
                       "via_device": self.mqtt_support.get_bridge_ha_name(),
                       "identifiers": self.unique_device_id,
                       "name": self.name,
                       "model": "RV-C System Clock from DATE_TIME_STATUS"
                       }

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
            Process RV-C message and publish date and time
            '''

            year = int(new_message["year"])+2000
            month = int(new_message["month"])
            day = int(new_message["date"])
            hour = int(new_message["hour"])
            minute = int(new_message["minute"])
            second = int(new_message["second"])

            try:
                dt = datetime(year, month, day, hour, minute, second)
                if self.tz is None:
                    # No configured zone — attach the container's local offset
                    # so HA receives a fully qualified ISO string.
                    dt = dt.astimezone()
                state = dt.isoformat(timespec='seconds')
            except ValueError:
                self.Logger.warning(
                    f"Invalid DATE_TIME_STATUS: {year}-{month}-{day} {hour}:{minute}:{second}")
                return True

            #only publish if the time or date has changed. This should be once a minute
            if self.publish(self.status_topic, state):
                self.state = state
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
            'name': 'SET_DATE_TIME_COMMAND',
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
        year = int(thedatetime.year - 2000)
        month = int(thedatetime.month)
        day = int(thedatetime.day)
        rvc_day_of_week = int(RVC_DAY_OF_WEEK[thedatetime.weekday()])
        hour = int(thedatetime.hour)
        minute = int(thedatetime.minute)
        second = int(thedatetime.second)
        timezone = int(255) #firefly seems to only set timezone to 255

        self.Logger.debug(
                f"payload: year:{year}, month:{month}, day:{day}, dayofweek:{rvc_day_of_week}, hour:{hour}, minute:{minute}, second:{second}, timezone:{timezone}")


        struct.pack_into("<BBBBBBBB", msg_bytes, 0, year, month, day, rvc_day_of_week, hour, minute, second, timezone )
        return msg_bytes

    def process_mqtt_msg(self, topic, payload, properties = None):
        self.Logger.debug(
            f"MQTT Msg Received on topic {topic} with payload {payload}")

        if topic == self.command_topic:
            try:
                # HA's mqtt.datetime publishes ISO format in UTC by default.
                # fromisoformat in Python <3.11 doesn't accept the 'Z' suffix.
                dt = datetime.fromisoformat(payload.replace('Z', '+00:00'))
                if dt.tzinfo is not None:
                    target = self.tz if self.tz is not None else None
                    dt = dt.astimezone(target).replace(tzinfo=None)
                pl = self._make_rvc_payload(dt)
                self.send_queue.put({"dgn": "1FFFE", "data": pl})
            except Exception as e:
                self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")
        elif topic == self.timezone_set_topic:
            self._handle_timezone_set(payload)
        else:
            self.Logger.warning(
            f"Invalid payload {payload} for topic {topic}")

    def _handle_timezone_set(self, payload: str):
        """ Update the configured IANA timezone, persist to the floorplan
        override, and republish discovery so HA picks up the new value. """
        new_name = payload.strip()
        if not new_name:
            self.tz = None
            self.tz_name = None
        else:
            try:
                self.tz = ZoneInfo(new_name)
                self.tz_name = new_name
            except ZoneInfoNotFoundError:
                self.Logger.error(f"Unknown timezone {new_name!r}; ignoring")
                return

        # echo the accepted value back even if it round-trips unchanged, so HA
        # sees a confirmation for the command it just sent
        self.publish(self.timezone_topic, self.tz_name or "", force=True)
        self._persist_override({'timezone': self.tz_name})
        # The retained status is stale under the new zone, so make the next
        # DATE_TIME_STATUS publish even if the wall-clock reading is unchanged.
        self.publish_forget(self.status_topic)
        self.publish_ha_discovery_config()

    def publish_ha_discovery_config(self):
        """ Publish HA MQTT auto-discovery as a `datetime` platform entity.

        When a `timezone` is configured, the state is published as a naive
        ISO datetime and HA is told (via the discovery `timezone` field) to
        interpret it in that zone. Otherwise the state carries the
        container's local UTC offset. """
        config = {"name": self.name,
                  "state_topic": self.status_topic,
                  "command_topic": self.command_topic,
                  "qos": 1, "retain": False,
                  "unique_id": self.unique_device_id + "_datetime",
                  "device": self.device}
        if self.tz_name:
            config["timezone"] = self.tz_name
        config.update(self.get_availability_discovery_info_for_ha())

        self.publish(
            self.mqtt_support.make_ha_auto_discovery_config_topic(
                self.unique_device_id, "datetime"),
            json.dumps(config), retain=False)

        # Companion `text` entity for editing the IANA timezone from HA.
        tz_config = {"name": self.name + " Timezone",
                     "state_topic": self.timezone_topic,
                     "command_topic": self.timezone_set_topic,
                     "qos": 1, "retain": False,
                     "unique_id": self.unique_device_id + "_tz",
                     "device": self.device}
        tz_config.update(self.get_availability_discovery_info_for_ha())

        self.publish(
            self.mqtt_support.make_ha_auto_discovery_config_topic(
                self.unique_device_id, "text", "tz"),
            json.dumps(tz_config), retain=False)

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data

        """

        self.publish_ha_discovery_config()

        # publish info to mqtt
        self.publish(
            self.status_topic, self.state)
        self.publish(
            self.timezone_topic, self.tz_name or "")

