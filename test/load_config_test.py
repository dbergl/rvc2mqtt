"""
Tests for load_the_config() in rvc2mqtt/app.py

Copyright 2025 Dan Berglund
SPDX-License-Identifier: Apache-2.0
"""

import logging
import pytest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.app import load_the_config, _get_override_path, _apply_overrides


class TestLoadTheConfig:

    def test_returns_none_for_missing_file(self):
        result = load_the_config("/nonexistent/path/floorplan.yaml")
        assert result is None

    def test_loads_basic_floorplan(self, tmp_path):
        fp = tmp_path / "floorplan.yaml"
        fp.write_text(
            "floorplan:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    instance: 1\n"
            "    type: light_switch\n"
            "    instance_name: Bedroom Light\n"
        )
        result = load_the_config(str(fp))
        assert result is not None
        assert "floorplan" in result
        assert len(result["floorplan"]) == 1
        entry = result["floorplan"][0]
        assert entry["name"] == "DC_LOAD_STATUS"
        assert entry["instance"] == 1
        assert entry["type"] == "light_switch"
        assert entry["instance_name"] == "Bedroom Light"

    def test_loads_multiple_floorplan_entries(self, tmp_path):
        fp = tmp_path / "floorplan.yaml"
        fp.write_text(
            "floorplan:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    instance: 1\n"
            "    type: light_switch\n"
            "    instance_name: Light A\n"
            "  - name: DC_LOAD_STATUS\n"
            "    instance: 2\n"
            "    type: light_switch\n"
            "    instance_name: Light B\n"
        )
        result = load_the_config(str(fp))
        assert len(result["floorplan"]) == 2
        assert result["floorplan"][1]["instance"] == 2
        assert result["floorplan"][1]["instance_name"] == "Light B"

    def test_comments_are_ignored(self, tmp_path):
        """YAML # comments must not affect parsing."""
        fp = tmp_path / "floorplan.yaml"
        fp.write_text(
            "# Top-level comment\n"
            "floorplan:\n"
            "  # Section comment\n"
            "  - name: DC_LOAD_STATUS\n"
            "    instance: 1  # inline comment\n"
            "    type: light_switch\n"
            "    instance_name: Bedroom Light  # another inline comment\n"
        )
        result = load_the_config(str(fp))
        assert result is not None
        assert "floorplan" in result
        assert len(result["floorplan"]) == 1
        entry = result["floorplan"][0]
        assert entry["instance"] == 1
        assert entry["instance_name"] == "Bedroom Light"

    def test_optional_fields_preserved(self, tmp_path):
        """Fields like source_id, status_topic, command_topic should come through."""
        fp = tmp_path / "floorplan.yaml"
        fp.write_text(
            "floorplan:\n"
            "  - name: G12\n"
            "    type: g12_configuration\n"
            "    source_id: '9C'\n"
            "    instance_name: Generator Controller\n"
            "    status_topic: rvc/g12/config\n"
            "    command_topic: rvc/g12/set\n"
        )
        result = load_the_config(str(fp))
        entry = result["floorplan"][0]
        assert entry["source_id"] == "9C"
        assert entry["status_topic"] == "rvc/g12/config"
        assert entry["command_topic"] == "rvc/g12/set"

    def test_empty_floorplan_list(self, tmp_path):
        fp = tmp_path / "floorplan.yaml"
        fp.write_text("floorplan: []\n")
        result = load_the_config(str(fp))
        assert result["floorplan"] == []

    def test_invalid_yaml_raises(self, tmp_path):
        """Malformed YAML should raise an exception rather than return garbage."""
        fp = tmp_path / "bad.yaml"
        fp.write_text(": invalid: yaml: {{\n")
        with pytest.raises(Exception):
            load_the_config(str(fp))


class TestGetOverridePath:

    def test_none_input_returns_none(self):
        assert _get_override_path(None) is None

    def test_yml_extension(self):
        assert _get_override_path("/config/floorplan.yml") == "/config/floorplan.override.yml"

    def test_yaml_extension(self):
        assert _get_override_path("/config/floorplan.yaml") == "/config/floorplan.override.yaml"

    def test_directory_with_dots_replaces_only_file_extension(self):
        assert _get_override_path("/my.config.dir/floorplan.yml") == "/my.config.dir/floorplan.override.yml"


class TestApplyOverrides:

    BASE = [
        {"name": "DC_LOAD_STATUS", "type": "light_switch", "instance": 1, "instance_name": "Bedroom Light"},
        {"name": "DC_LOAD_STATUS", "type": "light_switch", "instance": 2, "instance_name": "Living Room Light"},
        {"name": "DC_LOAD_STATUS", "type": "light_switch", "instance": 3, "instance_name": "Bath Light"},
    ]

    def _logger(self):
        return logging.getLogger("test")

    def test_none_path_returns_base(self):
        result = _apply_overrides(self.BASE, None, self._logger())
        assert result == self.BASE

    def test_missing_file_returns_base(self):
        result = _apply_overrides(self.BASE, "/nonexistent/floorplan.override.yml", self._logger())
        assert result == self.BASE

    def test_invalid_yaml_warns_and_returns_base(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(": invalid: yaml: {{\n")
        logger = MagicMock()
        result = _apply_overrides(self.BASE, str(ovr), logger)
        assert result == self.BASE
        logger.warning.assert_called_once()

    def test_missing_overrides_key_returns_base(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text("floorplan:\n  - name: X\n")
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert result == self.BASE

    def test_overrides_not_a_list_warns(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text("overrides: not-a-list\n")
        logger = MagicMock()
        result = _apply_overrides(self.BASE, str(ovr), logger)
        assert result == self.BASE
        logger.warning.assert_called_once()

    def test_empty_overrides_list(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text("overrides: []\n")
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert len(result) == len(self.BASE)
        assert result[0]["instance_name"] == "Bedroom Light"

    def test_update_matching_entry(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    instance_name: Master Bedroom\n"
        )
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert result[0]["instance_name"] == "Master Bedroom"

    def test_update_preserves_unspecified_keys(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    instance_name: Master Bedroom\n"
        )
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert result[0]["name"] == "DC_LOAD_STATUS"
        assert result[0]["type"] == "light_switch"
        assert result[0]["instance"] == 1

    def test_update_does_not_mutate_base(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    instance_name: Master Bedroom\n"
        )
        base_copy = [dict(e) for e in self.BASE]
        _apply_overrides(self.BASE, str(ovr), self._logger())
        assert self.BASE[0]["instance_name"] == base_copy[0]["instance_name"]

    def test_remove_matching_entry(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    _remove: true\n"
        )
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert len(result) == 2
        assert all(e["instance"] != 1 for e in result)

    def test_remove_no_match_ignored(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 99\n"
            "    _remove: true\n"
        )
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert len(result) == len(self.BASE)

    def test_new_entry_appended(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: TANK_STATUS\n"
            "    type: tank_level\n"
            "    instance: 5\n"
            "    instance_name: Gray Tank\n"
        )
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        assert len(result) == len(self.BASE) + 1
        assert result[-1]["name"] == "TANK_STATUS"
        assert result[-1]["instance_name"] == "Gray Tank"

    def test_remove_key_stripped_from_result(self, tmp_path):
        ovr = tmp_path / "floorplan.override.yml"
        ovr.write_text(
            "overrides:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    type: light_switch\n"
            "    instance: 1\n"
            "    instance_name: Master Bedroom\n"
        )
        result = _apply_overrides(self.BASE, str(ovr), self._logger())
        for entry in result:
            assert "_remove" not in entry
