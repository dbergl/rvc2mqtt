"""

EntityPluginBaseClass

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
import os
import queue
import threading
import ruyaml
from rvc2mqtt.mqtt import MQTT_Support

# Marker for "nothing has ever been published under this key".  A dedicated
# sentinel - not None/0/False - so that a legitimate falsy first value is never
# mistaken for "unchanged".
_UNSET = object()

# Escape hatch: RVC2MQTT_PUBLISH_ALWAYS=1 disables all change gating and restores
# the un-gated firehose, for A/B comparison against a live rig.
_PUBLISH_ALWAYS = os.environ.get("RVC2MQTT_PUBLISH_ALWAYS", "").lower() in ("1", "true", "yes")


class EntityPluginBaseClass(object):
    """ Baseclass for all device entities
    
    Make a subclass for a new object
    and define 

    """  
    def __init__(self, data:dict, mqtt_support: MQTT_Support):

        if not hasattr(self, "id"):
            # this seems like a bad code pattern..but ok for now
            raise Exception("self.id must be defined")
        
        self.Logger = logging.getLogger(__class__.__name__)
        self.mqtt_support: MQTT_Support = mqtt_support

        # Make the required one status/state topic
        self.status_topic: str = mqtt_support.make_device_topic_string(self.id, None, True)
        self.unique_device_id = mqtt_support.TOPIC_BASE + "_" + mqtt_support.client_id + "_" + self.id 

        self.link_id = None     # id for this entity so if other objects want a link
        if "link_id" in data:
            self.link_id = data["link_id"]

        self.entity_links = [] # list of link_ids that this object needs a reference to once the entity has been created
        if "entity_links" in data:
            self.entity_links.extend(data["entity_links"])

        # Override-file persistence (populated by app.py for floorplan1 entities only)
        self._override_file: str = None
        self._override_name = data.get('name')
        self._override_type = data.get('type')
        self._override_instance = data.get('instance', None)
        self._pending_override_updates: dict = {}
        self._override_timer: threading.Timer = None
        self._override_lock = threading.Lock()

        # Change tracking for publish().  key -> last value published.
        self._published_values: dict = {}
        self._publish_lock = threading.Lock()


    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming rvc message and determine if it
        is of interest to this instance of this object.
        
        If relevant - Process the message and return True
        else - return False
        """
        raise NotImplementedError()

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """
        pass

    def teardown(self):
        """Called before entity is removed (e.g., on floorplan reload).
        Flushes any pending override writes and cancels the debounce timer.
        Override in subclasses that need additional cleanup."""
        with self._override_lock:
            if self._override_timer is not None:
                self._override_timer.cancel()
                self._override_timer = None
        if self._pending_override_updates:
            self._write_override()

    def set_override_file(self, path: str):
        """Set the override file path. Called by app.py for floorplan1 entities only."""
        self._override_file = path

    def _persist_override(self, updates: dict, debounce: float = 2.0):
        """Schedule a debounced write of updates to the override file.
        Multiple calls within the debounce window are merged into a single write."""
        if self._override_file is None:
            return
        with self._override_lock:
            self._pending_override_updates.update(updates)
            if self._override_timer is not None:
                self._override_timer.cancel()
            self._override_timer = threading.Timer(debounce, self._write_override)
            self._override_timer.daemon = True
            self._override_timer.start()

    def _write_override(self):
        """Write pending override updates to the override YAML file using round-trip
        parsing to preserve existing formatting and comments."""
        with self._override_lock:
            self._override_timer = None
            updates = dict(self._pending_override_updates)
            self._pending_override_updates.clear()
        if not updates:
            return
        try:
            yaml = ruyaml.YAML()
            yaml.preserve_quotes = True
            override_file = self._override_file
            if os.path.isfile(override_file):
                with open(override_file, 'r') as f:
                    data = yaml.load(f)
                if data is None:
                    data = ruyaml.CommentedMap()
            else:
                data = ruyaml.CommentedMap()
            if 'overrides' not in data or data['overrides'] is None:
                data['overrides'] = ruyaml.CommentedSeq()
            overrides = data['overrides']
            match_idx = next(
                (i for i, e in enumerate(overrides)
                 if e.get('name') == self._override_name
                 and e.get('type') == self._override_type
                 and e.get('instance', None) == self._override_instance),
                -1,
            )
            if match_idx >= 0:
                overrides[match_idx].update(updates)
            else:
                entry = ruyaml.CommentedMap()
                entry['name'] = self._override_name
                entry['type'] = self._override_type
                if self._override_instance is not None:
                    entry['instance'] = self._override_instance
                entry.update(updates)
                overrides.append(entry)
            with open(override_file, 'w') as f:
                yaml.dump(data, f)
            self.Logger.info(f"Persisted override to {override_file!r}: {updates}")
        except Exception as e:
            self.Logger.error(f"Failed to write override file {self._override_file!r}: {e}")

    def publish_ha_discovery_config(self):
        """Publish Home Assistant MQTT auto-discovery config.
        Override in subclasses that support HA discovery."""
        pass
    
    def add_entity_link(self, obj):
        """ optional function
        If the data of the object has an entity_links list this function 
        will get called with each entity"""
        pass

    ########
    # MQTT PUBLISH
    # All entities publish through these.  Do not call
    # self.mqtt_support.client.publish directly.
    ########
    def publish(self, topic, payload, retain=True, force=None, key=None,
                value=_UNSET, deadband=None, properties=None) -> bool:
        """Publish to mqtt, skipping a repeat of a value we already published.

        topic    - mqtt topic
        payload  - what goes on the wire
        retain   - passed to paho.  Defaults True (state topics).
        force    - True  : always publish
                   False : always change-gate
                   None  : (default) change-gate retained publishes, always send
                           non-retained ones.  Non-retained traffic is HA
                           discovery config and RPC-style responses, which must
                           re-fire on every boot, every floorplan reload and
                           every HA birth message.
        key      - identity of the tracked value.  Defaults to `topic`.  Pass an
                   explicit key when several logical values share a topic.
        value    - the value to compare, when that is not the payload itself.
                   Use it to gate on a raw RVC field while publishing its
                   human-readable definition string, or to apply a deadband to a
                   number while publishing JSON.
        deadband - numeric.  Publish only when abs(value - last) >= deadband.
                   The first value under a key always publishes.
        properties - mqtt v5 properties, passed to paho.

        Only immutable payloads/values are safe to track - the cache holds a
        reference, so a mutated dict would never register as a change.  Every
        current caller passes str/int/float/bool.

        ret True if published, False if suppressed as unchanged.
        """
        if force is None:
            force = not retain

        cache_key = topic if key is None else key
        cmp_value = payload if value is _UNSET else value

        if force:
            # A forced publish still records what it sent, so that the next
            # un-forced publish of the same value is correctly suppressed.
            self.note_published(cache_key, cmp_value)
        elif not self.value_changed(cache_key, cmp_value, deadband=deadband):
            self.Logger.debug(f"Unchanged, not publishing to {topic}")
            return False

        self._do_publish(topic, payload, retain, properties)
        return True

    def value_changed(self, key, value, deadband=None) -> bool:
        """Record `value` under `key` and report whether it differs from what was
        recorded before.  Nothing recorded yet always counts as a change, so a
        first reading of 0 / False / "" is never swallowed.

        publish() is built on this.  Call it directly when one change has to gate
        several publishes that move as a unit: pass a tuple of the source fields
        as `value` and force=True on the publishes inside the branch.
        """
        with self._publish_lock:
            last = self._published_values.get(key, _UNSET)
            if not _PUBLISH_ALWAYS and last is not _UNSET \
                    and not self._value_differs(last, value, deadband):
                return False
            self._published_values[key] = value
            return True

    def publish_forget(self, key=None):
        """Forget the last published value so the next publish() for that key
        goes out even if unchanged.  Pass no key to forget every key.

        Use when something outside our view invalidates the broker's retained
        copy - an optimistic echo of an mqtt command, or a units change.
        """
        with self._publish_lock:
            if key is None:
                self._published_values.clear()
            else:
                self._published_values.pop(key, None)

    def note_published(self, key, value):
        """Record `value` as already published without sending anything.

        For seeding the cache from a retained value the broker hands back on
        startup, so the first RVC report of an unchanged value is suppressed.
        """
        with self._publish_lock:
            self._published_values[key] = value

    def _do_publish(self, topic, payload, retain, properties=None):
        """The single place that touches the mqtt client.  topic and payload stay
        positional and retain stays a keyword, so _RetainTracker and every
        existing test assertion see the call shape they always have."""
        if properties is not None:
            self.mqtt_support.client.publish(topic, payload, retain=retain,
                                             properties=properties)
        else:
            self.mqtt_support.client.publish(topic, payload, retain=retain)

    @staticmethod
    def _value_differs(last, new, deadband) -> bool:
        """True when `new` should be treated as a change from `last`."""
        if deadband:
            try:
                diff = abs(float(new) - float(last))
            except (TypeError, ValueError):
                diff = None                  # not numeric - fall back to equality
            if diff is not None and diff == diff:   # diff == diff excludes NaN
                return diff >= float(deadband)
        return new != last

    ########
    # HELPER FUNCTIONS
    # NOT EXPECTING TO NEED TO BE OVERRIDDEN
    ########
    def _is_entry_match(self, match_entries: dict, rvc_msg: dict) -> bool:
        '''
        Determine if a RVC message matches the map_entries.  
        All fields in match_entries must match the same fields in rvc_msg.

        ret True if match
        ret False if no match
        
        '''
        for k,v in match_entries.items():
            if k not in rvc_msg:
                return False
            
            if rvc_msg[k] != v:
                return False
        
        return True

    def set_rvc_send_queue(self, send_queue: queue):
        """ Provide queue for sending RVC messages.  Queue requires 
        items be formatted as python-can messages"""
        self.send_queue: queue = send_queue

    def get_availability_discovery_info_for_ha(self) -> dict:
        """ return the availability fields in dict format"""
        return { "availability_topic": self.mqtt_support.bridge_state_topic }

