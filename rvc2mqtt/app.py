"""
Main app/entrypoint for RVC2MQTT

Thanks goes to the contributors of https://github.com/linuxkidd/rvc-monitor-py
This code is derived from parts of https://github.com/linuxkidd/rvc-monitor-py/blob/master/usr/bin/rvc2mqtt.py
which was licensed using Apache-2.0.  No copyright information was present in the above mentioned file but original
content is owned by the authors. 

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

import argparse
import logging
import logging.config
import queue
import signal
import threading
import time
import os
import sys
import ruyaml as YAML
from os import PathLike
import datetime
from typing import Optional
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.can_support import CAN_Watcher
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.plugin_support import PluginSupport
from rvc2mqtt.mqtt import *
from rvc2mqtt.entity_factory_support import entity_factory

PATH_TO_FOLDER = os.path.abspath(os.path.dirname(__file__))


def signal_handler(signal, frame):
    global MyApp
    logging.critical("shutting down.")
    MyApp.close()
    logging.shutdown()
    exit(0)


def sighup_handler(sig, frame):
    global MyApp
    MyApp._reload_requested.set()


class app(object):
    def main(self, argsns: argparse.Namespace):
        """main function.  Sets up the app services, creates
        the receive thread, and processes messages.

        Runs until kill/term signal is sent
        """

        self.Logger = logging.getLogger("app")
        self.mqtt_client: MQTT_Support = None
        self._reload_requested = threading.Event()
        self._floorplan_path1 = argsns.floorplan
        self._floorplan_path2 = argsns.floorplan2

        # make an receive queue of receive can bus messages
        self.rxQueue = queue.Queue()

        # For now lets buffer rVC formatted messages in this queue
        # which can then go thru the app to get encoded
        # and put into the txQueue for the canbus
        # this is a little hacky...so need to revisit
        self.tx_RVC_Buffer = queue.Queue()

        # make a transmit queue to send can bus messages
        self.txQueue = queue.Queue()

        # thread to receive can bus messages
        self.receiver = CAN_Watcher(
            argsns.can_interface, self.rxQueue, self.txQueue)
        self.receiver.start()

        # setup decoder
        self.rvc_decoder = RVC_Decoder()
        self.rvc_decoder.load_rvc_spec(os.path.join(
            PATH_TO_FOLDER, 'rvc-spec.yml'))  # load the RVC spec yaml

        # setup the mqtt broker connection
        if argsns.mqtt_host is not None:
            self.mqtt_client = MqttInitalize(
                argsns.mqtt_host, argsns.mqtt_port, argsns.mqtt_user, argsns.mqtt_pass, argsns.mqtt_client_id, argsns.mqtt_topic_base)
            if self.mqtt_client:
                self.mqtt_client.register(f"{MQTT_Support.HA_AUTO_BASE}/status", self.on_ha_birth_message)
                self.mqtt_client.client.loop_start()

        # Enable plugins
        self.PluginSupport: PluginSupport = PluginSupport(os.path.join(
            PATH_TO_FOLDER, "entity"), argsns.plugin_paths)

        # Use plugins to dynamically prepare the entity factory
        entity_factory_list = []
        self.PluginSupport.register_with_factory_the_entity_plugins(
            entity_factory_list)
        self._entity_factory_list = entity_factory_list

        # setup entity list using
        self.entity_list = []

        # initialize objects from the floorplan
        override_path = _get_override_path(argsns.floorplan)
        for item, source_file in argsns.fp:
            try:
                obj = entity_factory(
                    item, self.mqtt_client, entity_factory_list, source_file)
            except Exception as e:
                self.Logger.error(f"Unsupported entry in {source_file}: {str(e)}")
                continue
            if obj is not None:
                # add entity links if defined.  This allows one entity to reference another entity
                for link in obj.entity_links:
                    requested_entity = next(filter(lambda entry: entry.link_id == link, self.entity_list), None)
                    if requested_entity is not None:
                        obj.add_entity_link(requested_entity)

                if source_file == argsns.floorplan:
                    obj.set_override_file(override_path)
                obj.set_rvc_send_queue(self.tx_RVC_Buffer)
                obj.initialize()
                self.entity_list.append(obj)

        # Request product identification from all devices on the network
        self.tx_RVC_Buffer.put({
            "dgn": "0EAFF",
            "data": bytes([0xEB, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
        })

        # Our RVC message loop here
        while True:
            if self._reload_requested.is_set():
                self._do_reload()
            # process any received messages
            self.message_rx_loop()
            self.message_tx_loop()
            time.sleep(0.001)

    def _do_reload(self):
        self._reload_requested.clear()
        self.Logger.info("Reloading floorplan...")

        # 1. Unsubscribe all registered topics, then immediately re-register the HA
        #    birth handler so no birth messages are missed during reload.
        if self.mqtt_client:
            self.mqtt_client.unregister_all()
            self.mqtt_client.register(
                f"{MQTT_Support.HA_AUTO_BASE}/status", self.on_ha_birth_message)

        # 2. Snapshot discovery topics so we can remove only stale ones after reload.
        old_discovery_topics = self.mqtt_client.get_discovery_topics() if self.mqtt_client else set()

        # 3. Signal offline so HA marks entities unavailable during the reload window.
        #    We intentionally do NOT clear retained state topics here: publishing empty
        #    strings races with the offline signal and causes HA to record empty values
        #    then fail pattern validation (text/climate entities) when we go back online.
        #    Retained state topics keep their last good values; entities overwrite them
        #    naturally when the CAN bus re-broadcasts after reload.
        if self.mqtt_client:
            self.mqtt_client.publish_bridge_offline()

        # 4. Teardown old entities
        for entity in self.entity_list:
            entity.teardown()
        self.entity_list = []

        # 5. Reload floorplan files
        new_fp = []
        try:
            if self._floorplan_path1 and os.path.isfile(self._floorplan_path1):
                c = load_the_config(self._floorplan_path1)
                if c and "floorplan" in c:
                    entries = _apply_overrides(c["floorplan"], _get_override_path(self._floorplan_path1), self.Logger)
                    new_fp.extend((item, self._floorplan_path1) for item in entries)
            if self._floorplan_path2 and os.path.isfile(self._floorplan_path2):
                d = load_the_config(self._floorplan_path2)
                if d and "floorplan" in d:
                    new_fp.extend((item, self._floorplan_path2) for item in d["floorplan"])
        except Exception as e:
            self.Logger.error(f"Floorplan reload failure: {str(e)}")

        if not new_fp:
            self.Logger.error("Floorplan reload produced no entities — check floorplan files")

        # 6. Recreate entities
        override_path = _get_override_path(self._floorplan_path1)
        for item, source_file in new_fp:
            try:
                obj = entity_factory(item, self.mqtt_client, self._entity_factory_list, source_file)
            except Exception as e:
                self.Logger.error(f"Unsupported entry in {source_file}: {str(e)}")
                continue
            if obj is not None:
                for link in obj.entity_links:
                    requested_entity = next(
                        filter(lambda entry: entry.link_id == link, self.entity_list), None)
                    if requested_entity is not None:
                        obj.add_entity_link(requested_entity)
                if source_file == self._floorplan_path1:
                    obj.set_override_file(override_path)
                obj.set_rvc_send_queue(self.tx_RVC_Buffer)
                obj.initialize()
                self.entity_list.append(obj)

        # 7. Remove discovery topics for entities that were not re-published (removed from floorplan)
        if self.mqtt_client:
            self.mqtt_client.clear_stale_discovery_topics(old_discovery_topics)

        # 8. Signal online — re-publishes bridge availability so HA marks entities available again
        if self.mqtt_client:
            self.mqtt_client.publish_bridge_online()

        # 9. Request product identification from all devices on the network
        self.tx_RVC_Buffer.put({
            "dgn": "0EAFF",
            "data": bytes([0xEB, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
        })

        self.Logger.info(f"Floorplan reload complete: {len(self.entity_list)} entities loaded")

    def on_ha_birth_message(self, topic, payload, properties=None):
        """Re-publish HA discovery configs when Home Assistant comes online."""
        if payload == "online":
            self.Logger.info("Home Assistant birth message received - republishing discovery configs")
            for entity in self.entity_list:
                entity.publish_ha_discovery_config()

    def close(self):
        """Shutdown the app and any threads"""
        if self.receiver:
            self.receiver.kill_received = True
            self.receiver.join(timeout=2.0)
        # Drain queues so any retained objects are released
        for q in (self.rxQueue, self.tx_RVC_Buffer, self.txQueue):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        if self.mqtt_client is not None:
            self.mqtt_client.shutdown()
            self.mqtt_client.client.loop_stop()

    def message_tx_loop(self):
        """ hacky - translate RVC formatted dict from rvc_tx to canbus msg formatted tx"""
        if self.tx_RVC_Buffer.empty():
            return

        rvc_dict = self.tx_RVC_Buffer.get()

        # translate
        rvc_dict["arbitration_id"] = self.rvc_decoder._rvc_to_can_frame(
            rvc_dict)

        self.Logger.debug(f"Sending Msg: {str(rvc_dict)}")
        logging.getLogger("rvc_bus_trace").debug(str(rvc_dict))

        # put into canbus watcher
        self.txQueue.put(rvc_dict)

    def message_rx_loop(self):
        """Process any RVC received messages"""
        if self.rxQueue.empty():  # Check if there is a message in queue
            return

        message = self.rxQueue.get()

        try:
            MsgDict = self.rvc_decoder.rvc_decode(
                message.arbitration_id,
                "".join("{0:02X}".format(x) for x in message.data),
            )
        except Exception as e:
            self.Logger.warning(f"Failed to decode msg. {message}: {e}")
            return

        # Log all rvc bus messages to custom logger so it can be routed or ignored
        logging.getLogger("rvc_bus_trace").debug(str(MsgDict))

        # Find if this is a device entity in our list
        # Pass to object

        for item in self.entity_list:
            if item.process_rvc_msg(MsgDict):
                # Should we allow processing by more than one obj.
                ##
                return

        # Use a custom logger so it can be routed easily or ignored
        logging.getLogger("unhandled_rvc").debug(f"Msg {str(MsgDict)}")


def configure_logging(verbosity: int, config_file: Optional[os.PathLike]):
    if config_file is not None:
        if os.path.isfile(config_file):
            try:
                content = load_the_config(config_file)
                print("Trying to configuring  Logging from config file")
                logging.config.dictConfig(content["logger"])
                return
            except Exception as e:
                print("Exception trying to setup loggers: " + str(e.args))
                print(
                    "Review https://docs.python.org/3/library/logging.config.html#logging-config-dictschema for details")

    log_format = "%(levelname)s %(asctime)s - %(message)s"
    logging.basicConfig(stream=sys.stdout,
                        format=log_format, level=logging.ERROR)


def load_the_config(config_file_path: Optional[os.PathLike]):
    """ if config_file_path is a valid file load a yaml/json config file """
    if os.path.isfile(config_file_path):
        with open(config_file_path, "r") as content:
            yaml = YAML.YAML(typ='safe')
            return yaml.load(content.read())


def _get_override_path(floorplan_path: Optional[os.PathLike]) -> Optional[str]:
    if floorplan_path is None:
        return None
    stem, ext = os.path.splitext(floorplan_path)
    return stem + ".override" + ext


def _apply_overrides(base_entries: list, override_path: Optional[str], logger: logging.Logger) -> list:
    if override_path is None or not os.path.isfile(override_path):
        return base_entries
    try:
        raw = load_the_config(override_path)
    except Exception as e:
        logger.warning(f"Override file {override_path!r} could not be loaded: {e} — ignoring overrides")
        return base_entries
    if not raw or "overrides" not in raw:
        return base_entries
    override_list = raw["overrides"]
    if not isinstance(override_list, list):
        logger.warning(f"Override file {override_path!r}: 'overrides' key is not a list — ignoring overrides")
        return base_entries

    result = [dict(e) for e in base_entries]
    for ovr in override_list:
        name = ovr.get("name")
        type_ = ovr.get("type")
        instance = ovr.get("instance", None)
        match_idx = next(
            (i for i, e in enumerate(result)
             if e.get("name") == name and e.get("type") == type_ and e.get("instance", None) == instance),
            -1,
        )
        if ovr.get("_remove", False):
            if match_idx >= 0:
                del result[match_idx]
        else:
            update = {k: v for k, v in ovr.items() if k != "_remove"}
            if match_idx >= 0:
                result[match_idx].update(update)
            else:
                result.append(dict(update))
    return result


def main():
    """Entrypoint.
    Get the config and run the app
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--interface", "--INTERFACE", dest="can_interface",
                        help="can interface name like can0", default=os.environ.get("CAN_INTERFACE_NAME", "can0"))
    parser.add_argument("-f", "--floorplan", "--FLOORPLAN",
                        dest="floorplan", help="floorplan file path", default=os.environ.get("FLOORPLAN_FILE_1"))
    parser.add_argument("-g", "--floorplan2",
                        dest="floorplan2", help="filepath to more floorplan", default=os.environ.get("FLOORPLAN_FILE_2"))
    parser.add_argument("-p", "--plugin_path", dest="plugin_paths",
                        action="append", help="path to directory to load plugins", default=[])
    parser.add_argument("--MQTT_HOST", "--mqtt_host", dest="mqtt_host",
                        help="Host URL", default=os.environ.get("MQTT_HOST"))
    parser.add_argument("--MQTT_PORT", "--mqtt_port", dest="mqtt_port",
                        help="Port", type=int, default=os.environ.get("MQTT_PORT", "1883"))
    parser.add_argument("--MQTT_USERNAME", "--mqtt_username", dest="mqtt_user",
                        help="username for mqtt", default=os.environ.get("MQTT_USERNAME"))
    parser.add_argument("--MQTT_PASSWORD", "--mqtt_password", dest="mqtt_pass",
                        help="password for mqtt", default=os.environ.get("MQTT_PASSWORD"))

    # optional settings
    parser.add_argument("--MQTT_TOPIC_BASE", "--mqtt_topic_base", dest="mqtt_topic_base",
                        help="topic base for mqtt", default=os.environ.get("MQTT_TOPIC_BASE", "rvc2mqtt"))
    parser.add_argument("--MQTT_CLIENT_ID", "--mqtt_client_id", dest="mqtt_client_id",
                        help="client id for mqtt", default=os.environ.get("MQTT_CLIENT_ID", "bridge"))
    parser.add_argument("--MQTT_CA", "--mqtt_ca", dest="mqtt_ca",
                        help="ca for mqtt", default=os.environ.get("MQTT_CA"))
    parser.add_argument("--MQTT_CERT", "--mqtt_cert", dest="mqtt_cert",
                        help="cert for mqtt", default=os.environ.get("MQTT_CERT"))
    parser.add_argument("--MQTT_KEY", "--mqtt_key", dest="mqtt_key",
                        help="key for mqtt", default=os.environ.get("MQTT_KEY"))

    parser.add_argument("-v", "--verbose", "--VERBOSE", dest="verbose", action="count",
                        help="Increase verbosity of stdout logger. Add multiple times to increase",
                        default=0)

    parser.add_argument("-l", "--LOG_CONFIG_FILE", "--log_config_file", dest="log_config_file",
                        help="filepath to config file for logging", default=os.environ.get("LOG_CONFIG_FILE"))

    args = parser.parse_args()
    configure_logging(args.verbose, args.log_config_file)
    logging.info(
        "Log Started: "
        + datetime.datetime.strftime(datetime.datetime.now(),
                                     "%A, %B %d, %Y %I:%M%p")
    )

    args.fp = []
    try:
        if args.floorplan is not None:
            if os.path.isfile(args.floorplan):
                c = load_the_config(args.floorplan)
                if c and "floorplan" in c:
                    entries = _apply_overrides(c["floorplan"], _get_override_path(args.floorplan), logging.getLogger("app"))
                    args.fp.extend((item, args.floorplan) for item in entries)

        if args.floorplan2 is not None:
            d = load_the_config(args.floorplan2)
            if d and "floorplan" in d:
                args.fp.extend((item, args.floorplan2) for item in d["floorplan"])
    except Exception as e:
        logging.critical(f"Floorplan failure: {str(e)}")

    global MyApp
    MyApp = app()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, sighup_handler)
    MyApp.main(args)


if __name__ == "__main__":
    main()
