"""
Tests for rvc2mqtt.logging_support filters.

Copyright 2026 Dan Berglund
SPDX-License-Identifier: Apache-2.0
"""

import logging

import context  # noqa: F401 - add rvc2mqtt package to python path
from rvc2mqtt.logging_support import RVCSourceFilter, RVCSourceMatchFilter


def _make_record(msg="msg", args=None):
    return logging.LogRecord(
        name="rvc_bus_trace",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


class TestRVCSourceFilter:
    def test_injects_source_id_from_dict_arg(self):
        f = RVCSourceFilter()
        record = _make_record(msg="%s", args=({"source_id": "9C", "dgn": "1FFBD"},))
        assert f.filter(record) is True
        assert record.source_id == "9C"

    def test_falls_back_to_unknown_when_no_args(self):
        f = RVCSourceFilter()
        record = _make_record(msg="hello", args=None)
        assert f.filter(record) is True
        assert record.source_id == "unknown"

    def test_falls_back_when_dict_lacks_source_id(self):
        f = RVCSourceFilter()
        record = _make_record(msg="%s", args=({"dgn": "1FFBD"},))
        assert f.filter(record) is True
        assert record.source_id == "unknown"

    def test_falls_back_when_first_arg_is_not_dict(self):
        f = RVCSourceFilter()
        record = _make_record(msg="Msg %s", args=("some string",))
        assert f.filter(record) is True
        assert record.source_id == "unknown"

    def test_never_drops_records(self):
        # Filter is for injection only; it must always return True so the
        # all-bus-trace handler receives every record.
        f = RVCSourceFilter()
        for args in [None, (), ({},), ({"source_id": "7A"},), ("x",)]:
            record = _make_record(args=args)
            assert f.filter(record) is True


class TestRVCSourceMatchFilter:
    def test_passes_record_with_matching_source_id(self):
        f = RVCSourceMatchFilter(source_id="9C")
        record = _make_record()
        record.source_id = "9C"
        assert f.filter(record) is True

    def test_drops_record_with_different_source_id(self):
        f = RVCSourceMatchFilter(source_id="9C")
        record = _make_record()
        record.source_id = "7A"
        assert f.filter(record) is False

    def test_case_insensitive(self):
        f = RVCSourceMatchFilter(source_id="9c")
        record = _make_record()
        record.source_id = "9C"
        assert f.filter(record) is True

    def test_drops_when_source_id_missing(self):
        # If the injection filter wasn't run first there's nothing to match;
        # be safe and drop rather than raise.
        f = RVCSourceMatchFilter(source_id="9C")
        record = _make_record()
        assert f.filter(record) is False

    def test_accepts_list_of_source_ids(self):
        f = RVCSourceMatchFilter(source_id=["9C", "7A"])
        rec_a = _make_record()
        rec_a.source_id = "9C"
        rec_b = _make_record()
        rec_b.source_id = "7A"
        rec_c = _make_record()
        rec_c.source_id = "11"
        assert f.filter(rec_a) is True
        assert f.filter(rec_b) is True
        assert f.filter(rec_c) is False
