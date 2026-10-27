"""
Logging filters for tagging RVC log records with their CAN bus source_id.

Two filters are provided:

* :class:`RVCSourceFilter` — injects a ``source_id`` attribute onto every log
  record so formatters can reference ``%(source_id)s``. Always returns True,
  so a handler that only attaches this filter receives every record (useful
  for an "all bus trace" sink).

* :class:`RVCSourceMatchFilter` — gating filter that only passes records
  whose ``source_id`` matches a configured value (or one of a list of values).
  Attach this in addition to :class:`RVCSourceFilter` on handlers that should
  capture a specific source.

Both are intended to be wired up via ``logging.config.dictConfig`` from the
YAML referenced by ``LOG_CONFIG_FILE``.

Copyright 2026 Dan Berglund
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Iterable, Union


class RVCSourceFilter(logging.Filter):
    """Inject ``source_id`` onto log records.

    Looks at the first positional log arg; if it is a dict containing
    ``source_id``, that value is copied to the record. Otherwise the record
    gets ``source_id = "unknown"`` so formatters referencing
    ``%(source_id)s`` do not crash.

    Call sites should pass the RVC dict as a logging arg, e.g.
    ``logger.debug("%s", rvc_dict)``, rather than pre-formatting it into the
    message string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        source_id = "unknown"
        args = record.args
        # LogRecord.__init__ unwraps a single-mapping-arg tuple into the bare
        # mapping, so args may already be a dict-like.
        candidate = None
        if isinstance(args, dict):
            candidate = args
        elif isinstance(args, tuple) and args and isinstance(args[0], dict):
            candidate = args[0]
        if candidate is not None:
            source_id = candidate.get("source_id", "unknown")
        record.source_id = source_id
        return True


class RVCSourceMatchFilter(logging.Filter):
    """Pass only records whose ``source_id`` matches a configured value.

    Must be attached after :class:`RVCSourceFilter` on the same handler so
    that ``record.source_id`` has been populated.

    ``source_id`` may be a single hex string or an iterable of hex strings.
    Matching is case-insensitive.
    """

    def __init__(self, source_id: Union[str, Iterable[str]]):
        super().__init__()
        if isinstance(source_id, str):
            wanted = {source_id.upper()}
        else:
            wanted = {s.upper() for s in source_id}
        self._wanted = wanted

    def filter(self, record: logging.LogRecord) -> bool:
        value = getattr(record, "source_id", None)
        if not isinstance(value, str):
            return False
        return value.upper() in self._wanted
