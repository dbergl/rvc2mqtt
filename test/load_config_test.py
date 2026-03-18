"""
Tests for load_the_config() in rvc2mqtt/app.py

Copyright 2025 Dan Berglund
SPDX-License-Identifier: Apache-2.0
"""

import pytest
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.app import load_the_config


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
