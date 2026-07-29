"""
Tests for EntityPluginBaseClass change-gated mqtt publishing.

Copyright 2025 Dan Berglund
SPDX-License-Identifier: Apache-2.0
"""

import json
import math
from unittest.mock import MagicMock, patch
import context  # add rvc2mqtt package to the python path using local reference

from rvc2mqtt.entity import EntityPluginBaseClass


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------

class _StubEntity(EntityPluginBaseClass):
    def __init__(self, data, mqtt_support):
        self.id = "stub-test"
        super().__init__(data, mqtt_support)

    def process_rvc_msg(self, msg):
        return False


def _make_entity():
    mock_mqtt = MagicMock()
    # Distinct topic per (id, field, state) so that a topic-keyed cache cannot
    # silently collapse unrelated fields onto one key.
    mock_mqtt.make_device_topic_string.side_effect = \
        lambda id, field, state: f"test/{id}/{field}/{'state' if state else 'set'}"
    mock_mqtt.TOPIC_BASE = "rvc2mqtt"
    mock_mqtt.client_id = "bridge"
    mock_mqtt.bridge_state_topic = "rvc2mqtt/bridge/state"
    data = {'name': 'DC_LOAD_STATUS', 'type': 'light_switch', 'instance': 1}
    return _StubEntity(data, mock_mqtt)


def _published(entity):
    """(topic, payload) of every real publish, in order."""
    return [(c[0][0], c[0][1]) for c in entity.mqtt_support.client.publish.call_args_list]


# ---------------------------------------------------------------------------
# Change gating
# ---------------------------------------------------------------------------

class TestChangeGating:
    def test_first_publish_always_fires(self):
        e = _make_entity()
        assert e.publish('a/b', 'on') is True
        assert _published(e) == [('a/b', 'on')]

    def test_repeat_is_suppressed(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        assert e.publish('a/b', 'on') is False
        assert len(_published(e)) == 1

    def test_change_republishes(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        e.publish('a/b', 'off')
        e.publish('a/b', 'off')
        e.publish('a/b', 'on')
        assert _published(e) == [('a/b', 'on'), ('a/b', 'off'), ('a/b', 'on')]

    def test_distinct_topics_tracked_independently(self):
        e = _make_entity()
        e.publish('a/volts', 12.5)
        e.publish('a/amps', 12.5)
        e.publish('a/volts', 12.5)
        e.publish('a/amps', 12.5)
        assert _published(e) == [('a/volts', 12.5), ('a/amps', 12.5)]

    def test_retain_passed_as_keyword(self):
        # ~241 existing assertion lines depend on retain being a keyword and
        # topic/payload being positional.
        e = _make_entity()
        e.publish('a/b', 'on')
        e.mqtt_support.client.publish.assert_called_once_with('a/b', 'on', retain=True)


# ---------------------------------------------------------------------------
# Falsy first values must never be mistaken for "unchanged"
# ---------------------------------------------------------------------------

class TestFalsyFirstValues:
    def test_zero_int_publishes(self):
        e = _make_entity()
        assert e.publish('a/b', 0) is True
        assert _published(e) == [('a/b', 0)]

    def test_zero_float_publishes(self):
        e = _make_entity()
        assert e.publish('a/b', 0.0) is True

    def test_false_publishes(self):
        e = _make_entity()
        assert e.publish('a/b', False) is True

    def test_empty_string_publishes(self):
        e = _make_entity()
        assert e.publish('a/b', "") is True

    def test_none_publishes(self):
        e = _make_entity()
        assert e.publish('a/b', None) is True

    def test_zero_then_zero_suppressed(self):
        e = _make_entity()
        e.publish('a/b', 0)
        assert e.publish('a/b', 0) is False


# ---------------------------------------------------------------------------
# force / retain interaction
# ---------------------------------------------------------------------------

class TestForce:
    def test_force_true_republishes_unchanged(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        assert e.publish('a/b', 'on', force=True) is True
        assert len(_published(e)) == 2

    def test_retain_false_implies_force(self):
        # HA discovery configs and RPC responses must re-fire on every boot,
        # every floorplan reload and every HA birth message.
        e = _make_entity()
        cfg = json.dumps({'name': 'x'})
        e.publish('homeassistant/light/x/config', cfg, retain=False)
        e.publish('homeassistant/light/x/config', cfg, retain=False)
        assert len(_published(e)) == 2

    def test_retain_false_passes_retain_false(self):
        e = _make_entity()
        e.publish('a/b', 'x', retain=False)
        e.mqtt_support.client.publish.assert_called_once_with('a/b', 'x', retain=False)

    def test_explicit_force_false_gates_non_retained(self):
        e = _make_entity()
        assert e.publish('a/b', 'x', retain=False, force=False) is True
        assert e.publish('a/b', 'x', retain=False, force=False) is False
        assert len(_published(e)) == 1

    def test_force_true_still_records_nothing_stale(self):
        # A forced publish must not leave the cache describing an older value.
        e = _make_entity()
        e.publish('a/b', 'on')
        e.publish('a/b', 'off', force=True)
        assert e.publish('a/b', 'off') is False


# ---------------------------------------------------------------------------
# key=
# ---------------------------------------------------------------------------

class TestKey:
    def test_key_isolates_values_sharing_a_topic(self):
        e = _make_entity()
        assert e.publish('a/b', 1, key='line1') is True
        assert e.publish('a/b', 1, key='line2') is True
        assert e.publish('a/b', 1, key='line1') is False
        assert e.publish('a/b', 1, key='line2') is False
        assert len(_published(e)) == 2

    def test_key_defaults_to_topic(self):
        e = _make_entity()
        e.publish('a/b', 1)
        assert e.publish('a/b', 1, key='a/b') is False


# ---------------------------------------------------------------------------
# value= decoupled from payload=
# ---------------------------------------------------------------------------

class TestValue:
    def test_gate_on_raw_while_publishing_definition(self):
        # aps500/timberline compare a raw RVC field but publish its .title()'d
        # definition string.
        e = _make_entity()
        assert e.publish('a/b', 'Automatic', value=2) is True
        assert e.publish('a/b', 'Automatic', value=2) is False
        # same definition string, different raw value -> must publish
        assert e.publish('a/b', 'Automatic', value=3) is True
        assert len(_published(e)) == 2

    def test_changed_payload_same_value_is_suppressed(self):
        e = _make_entity()
        e.publish('a/b', 'first', value=1)
        assert e.publish('a/b', 'second', value=1) is False


# ---------------------------------------------------------------------------
# deadband=
# ---------------------------------------------------------------------------

class TestDeadband:
    def test_first_value_always_publishes(self):
        e = _make_entity()
        assert e.publish('a/b', 22.0, deadband=0.25) is True

    def test_below_deadband_suppressed(self):
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        assert e.publish('a/b', 22.1, deadband=0.25) is False

    def test_exactly_at_deadband_publishes(self):
        # >= semantics, matching g12_tank_level_sensor's minimum_change.
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        assert e.publish('a/b', 22.25, deadband=0.25) is True

    def test_above_deadband_publishes(self):
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        assert e.publish('a/b', 30.0, deadband=0.25) is True

    def test_deadband_measured_from_last_published_not_last_seen(self):
        # A slow drift must eventually publish rather than being suppressed
        # forever by comparing against the most recent reading.
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        e.publish('a/b', 22.1, deadband=0.25)   # suppressed
        e.publish('a/b', 22.2, deadband=0.25)   # suppressed
        assert e.publish('a/b', 22.3, deadband=0.25) is True
        assert _published(e) == [('a/b', 22.0), ('a/b', 22.3)]

    def test_negative_direction(self):
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        assert e.publish('a/b', 21.7, deadband=0.25) is True

    def test_deadband_applies_to_value_while_payload_is_json(self):
        e = _make_entity()
        e.publish('a/b', json.dumps({'c': 22.0}), value=22.0, deadband=0.25)
        assert e.publish('a/b', json.dumps({'c': 22.1}), value=22.1,
                         deadband=0.25) is False
        assert e.publish('a/b', json.dumps({'c': 22.5}), value=22.5,
                         deadband=0.25) is True

    def test_int_and_float_mix(self):
        e = _make_entity()
        e.publish('a/b', 22, deadband=1)
        assert e.publish('a/b', 22.5, deadband=1) is False
        assert e.publish('a/b', 23.0, deadband=1) is True

    def test_non_numeric_falls_back_to_equality(self):
        # aps500 publishes "n/a" on numeric topics.
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        assert e.publish('a/b', 'n/a', deadband=0.25) is True
        assert e.publish('a/b', 'n/a', deadband=0.25) is False
        assert e.publish('a/b', 22.0, deadband=0.25) is True

    def test_nan_falls_back_to_equality(self):
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0.25)
        # abs(nan - 22.0) is nan, which is never >= deadband; fall back to !=
        assert e.publish('a/b', float('nan'), deadband=0.25) is True

    def test_zero_deadband_behaves_as_equality(self):
        e = _make_entity()
        e.publish('a/b', 22.0, deadband=0)
        assert e.publish('a/b', 22.0, deadband=0) is False
        assert e.publish('a/b', 22.1, deadband=0) is True


# ---------------------------------------------------------------------------
# value_changed group primitive
# ---------------------------------------------------------------------------

class TestValueChanged:
    def test_first_call_is_a_change(self):
        e = _make_entity()
        assert e.value_changed('g', (1, 2)) is True

    def test_repeat_is_not_a_change(self):
        e = _make_entity()
        e.value_changed('g', (1, 2))
        assert e.value_changed('g', (1, 2)) is False

    def test_any_member_change_is_a_change(self):
        e = _make_entity()
        e.value_changed('g', (1, 2, 'a'))
        assert e.value_changed('g', (1, 2, 'b')) is True

    def test_gates_a_group_of_forced_publishes(self):
        # diagnostic.py publishes json blobs that differ every frame, so one
        # change signature gates the whole group.
        e = _make_entity()
        for _ in range(3):
            if e.value_changed('g', ('fault', True)):
                e.publish('a/state', 'fault', force=True)
                e.publish('a/attrs', json.dumps({'seq': 1}), force=True)
        assert len(_published(e)) == 2

    def test_value_changed_shares_namespace_with_publish(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        assert e.value_changed('a/b', 'on') is False

    def test_does_not_publish(self):
        e = _make_entity()
        e.value_changed('g', 1)
        assert _published(e) == []


# ---------------------------------------------------------------------------
# publish_forget / note_published
# ---------------------------------------------------------------------------

class TestForget:
    def test_forget_key_lets_unchanged_value_through(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        e.publish_forget('a/b')
        assert e.publish('a/b', 'on') is True

    def test_forget_key_leaves_other_keys_alone(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        e.publish('a/c', 'on')
        e.publish_forget('a/b')
        assert e.publish('a/b', 'on') is True
        assert e.publish('a/c', 'on') is False

    def test_forget_all(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        e.publish('a/c', 'on')
        e.publish_forget()
        assert e.publish('a/b', 'on') is True
        assert e.publish('a/c', 'on') is True

    def test_forget_unknown_key_is_harmless(self):
        e = _make_entity()
        e.publish_forget('never/seen')


class TestNotePublished:
    def test_seeds_cache_without_publishing(self):
        e = _make_entity()
        e.note_published('a/b', 'on')
        assert _published(e) == []
        assert e.publish('a/b', 'on') is False

    def test_seeded_value_still_detects_a_change(self):
        e = _make_entity()
        e.note_published('a/b', 'on')
        assert e.publish('a/b', 'off') is True

    def test_overwrites_an_existing_entry(self):
        e = _make_entity()
        e.publish('a/b', 'on')
        e.note_published('a/b', 'off')
        assert e.publish('a/b', 'off') is False
        assert e.publish('a/b', 'on') is True


# ---------------------------------------------------------------------------
# properties passthrough
# ---------------------------------------------------------------------------

class TestProperties:
    def test_properties_forwarded_when_given(self):
        e = _make_entity()
        props = MagicMock()
        e.publish('a/b', 'x', retain=False, properties=props)
        e.mqtt_support.client.publish.assert_called_once_with(
            'a/b', 'x', retain=False, properties=props)

    def test_properties_omitted_when_none(self):
        # An unconditional properties=None would break existing
        # assert_called_once_with(topic, payload, retain=True) assertions.
        e = _make_entity()
        e.publish('a/b', 'x')
        e.mqtt_support.client.publish.assert_called_once_with('a/b', 'x', retain=True)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

class TestPublishAlways:
    def test_gating_disabled_republishes_everything(self):
        e = _make_entity()
        with patch('rvc2mqtt.entity._PUBLISH_ALWAYS', True):
            e.publish('a/b', 'on')
            e.publish('a/b', 'on')
            e.publish('a/b', 'on')
        assert len(_published(e)) == 3

    def test_deadband_ignored_when_disabled(self):
        e = _make_entity()
        with patch('rvc2mqtt.entity._PUBLISH_ALWAYS', True):
            e.publish('a/b', 22.0, deadband=10)
            e.publish('a/b', 22.1, deadband=10)
        assert len(_published(e)) == 2


# ---------------------------------------------------------------------------
# Isolation between entity instances
# ---------------------------------------------------------------------------

class TestInstanceIsolation:
    def test_cache_is_per_instance(self):
        # _do_reload builds new entity objects; a fresh entity must publish its
        # first decoded value even if the previous instance published the same.
        a = _make_entity()
        b = _make_entity()
        a.publish('a/b', 'on')
        assert b.publish('a/b', 'on') is True


# ---------------------------------------------------------------------------
# Enforcement: entities must not reach past publish() to the mqtt client
# ---------------------------------------------------------------------------

class TestNoReachThrough:
    def test_entities_do_not_call_client_publish_directly(self):
        """publish() is the only gate. An entity that calls
        mqtt_support.client.publish directly bypasses change tracking, which is
        invisible at the call site and hard to notice in review."""
        import os
        entity_dir = os.path.join(os.path.dirname(__file__), '..', 'rvc2mqtt', 'entity')
        offenders = []
        for name in sorted(os.listdir(entity_dir)):
            if not name.endswith('.py') or name == '__init__.py':
                continue
            with open(os.path.join(entity_dir, name)) as f:
                for lineno, line in enumerate(f, 1):
                    if 'client.publish' in line:
                        offenders.append(f"{name}:{lineno}")
        assert offenders == [], \
            "use self.publish() instead of client.publish: " + ", ".join(offenders)

