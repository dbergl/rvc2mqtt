"""
Tests for EntityPluginBaseClass override-file persistence.

Copyright 2025 Dan Berglund
SPDX-License-Identifier: Apache-2.0
"""

import threading
import time
import pytest
from unittest.mock import MagicMock, patch
import context  # add rvc2mqtt package to the python path using local reference
import ruyaml

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


def _make_entity(data=None):
    mock_mqtt = MagicMock()
    mock_mqtt.make_device_topic_string.return_value = "test/topic"
    mock_mqtt.TOPIC_BASE = "rvc2mqtt"
    mock_mqtt.client_id = "bridge"
    mock_mqtt.bridge_state_topic = "rvc2mqtt/bridge/state"
    if data is None:
        data = {'name': 'DC_LOAD_STATUS', 'type': 'light_switch', 'instance': 1}
    return _StubEntity(data, mock_mqtt)


# ---------------------------------------------------------------------------
# set_override_file
# ---------------------------------------------------------------------------

class TestSetOverrideFile:
    def test_default_is_none(self):
        e = _make_entity()
        assert e._override_file is None

    def test_set_stores_path(self):
        e = _make_entity()
        e.set_override_file('/tmp/test.override.yml')
        assert e._override_file == '/tmp/test.override.yml'


# ---------------------------------------------------------------------------
# _persist_override
# ---------------------------------------------------------------------------

class TestPersistOverride:
    def test_no_op_when_override_file_not_set(self):
        e = _make_entity()
        e._persist_override({'key': 'val'})
        assert e._override_timer is None
        assert e._pending_override_updates == {}

    def test_starts_timer(self):
        e = _make_entity()
        e.set_override_file('/tmp/x.yml')
        e._persist_override({'key': 'val'}, debounce=10.0)
        assert e._override_timer is not None
        e._override_timer.cancel()

    def test_merges_updates(self):
        e = _make_entity()
        e.set_override_file('/tmp/x.yml')
        e._persist_override({'a': 1}, debounce=10.0)
        e._persist_override({'b': 2}, debounce=10.0)
        assert e._pending_override_updates == {'a': 1, 'b': 2}
        e._override_timer.cancel()

    def test_second_call_resets_timer(self):
        e = _make_entity()
        e.set_override_file('/tmp/x.yml')
        e._persist_override({'a': 1}, debounce=10.0)
        first_timer = e._override_timer
        e._persist_override({'b': 2}, debounce=10.0)
        assert e._override_timer is not first_timer
        e._override_timer.cancel()


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------

class TestTeardown:
    def test_cancels_pending_timer(self):
        e = _make_entity()
        e.set_override_file('/tmp/x.yml')
        e._persist_override({'a': 1}, debounce=10.0)
        assert e._override_timer is not None
        with patch.object(e, '_write_override'):
            e.teardown()
        assert e._override_timer is None

    def test_flushes_pending_updates_on_teardown(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        e = _make_entity()
        e.set_override_file(str(fp))
        e._persist_override({'33_custom_threshold': 50000}, debounce=10.0)
        e.teardown()  # should flush synchronously
        assert fp.exists()
        yaml = ruyaml.YAML(typ='safe')
        data = yaml.load(fp.read_text())
        assert data['overrides'][0]['33_custom_threshold'] == 50000

    def test_teardown_no_op_without_pending(self):
        e = _make_entity()
        e.teardown()  # should not raise


# ---------------------------------------------------------------------------
# _write_override
# ---------------------------------------------------------------------------

class TestWriteOverride:
    def test_creates_file_if_missing(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {'33_custom_threshold': 57400}
        e._write_override()
        assert fp.exists()

    def test_adds_new_entry_when_no_match(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {'33_custom_threshold': 57400}
        e._write_override()
        yaml = ruyaml.YAML(typ='safe')
        data = yaml.load(fp.read_text())
        assert len(data['overrides']) == 1
        assert data['overrides'][0]['33_custom_threshold'] == 57400
        assert data['overrides'][0]['name'] == 'DC_LOAD_STATUS'
        assert data['overrides'][0]['type'] == 'light_switch'
        assert data['overrides'][0]['instance'] == 1

    def test_updates_existing_matching_entry(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        fp.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    33_custom_threshold: 57400\n"
        )
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {'33_custom_threshold': 50000}
        e._write_override()
        yaml = ruyaml.YAML(typ='safe')
        data = yaml.load(fp.read_text())
        assert len(data['overrides']) == 1
        assert data['overrides'][0]['33_custom_threshold'] == 50000

    def test_preserves_other_entries(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        fp.write_text(
            "overrides:\n"
            "  - name: SOME_OTHER\n"
            "    type: other_type\n"
            "    instance: 5\n"
            "    instance_name: Other\n"
        )
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {'33_custom_threshold': 57400}
        e._write_override()
        yaml = ruyaml.YAML(typ='safe')
        data = yaml.load(fp.read_text())
        assert len(data['overrides']) == 2
        names = [entry['name'] for entry in data['overrides']]
        assert 'SOME_OTHER' in names
        assert 'DC_LOAD_STATUS' in names

    def test_preserves_comments(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        fp.write_text(
            "# My override file\n"
            "overrides:\n"
            "  # existing entry\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    33_custom_threshold: 57400\n"
        )
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {'33_custom_threshold': 50000}
        e._write_override()
        content = fp.read_text()
        assert '# My override file' in content
        assert '# existing entry' in content

    def test_no_write_when_updates_empty(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {}
        e._write_override()
        assert not fp.exists()

    def test_logs_error_on_write_failure(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        e = _make_entity()
        e.set_override_file(str(fp))
        e._pending_override_updates = {'key': 'val'}
        e.Logger = MagicMock()
        with patch('builtins.open', side_effect=OSError("disk full")):
            e._write_override()
        e.Logger.error.assert_called()

    def test_instance_omitted_when_none(self, tmp_path):
        fp = tmp_path / "floorplan.override.yml"
        data = {'name': 'WATER_PUMP_STATUS', 'type': 'water_pump'}
        e = _make_entity(data)
        e.set_override_file(str(fp))
        e._pending_override_updates = {'some_key': 'val'}
        e._write_override()
        yaml = ruyaml.YAML(typ='safe')
        result = yaml.load(fp.read_text())
        assert 'instance' not in result['overrides'][0]
