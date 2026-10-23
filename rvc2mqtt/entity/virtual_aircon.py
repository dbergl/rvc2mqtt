"""
Virtual air conditioner: presents a Home-Assistant-controlled air conditioner
as RV-C thermostat instance 7 for the Firefly panel's Climate page.

Design: docs/superpowers/specs/2026-10-22-virtual-aircon-design.md

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

import threading


class OptimisticState:
    """Per-field reported value plus an optional pending (optimistic) value.

    A panel command makes its value effective at once (command()).  It stays
    effective until the AC reports the same value (confirmed) or `timeout`
    seconds pass (expire() reverts to the last reported value).  While a field
    is pending, a non-matching report is recorded but not shown, so a late
    report of the old setpoint can't snap a held arrow back.

    MQTT callbacks (paho thread) and the main loop both call in, hence the lock.
    """

    def __init__(self, timeout: float, clock, logger):
        self.timeout = timeout
        self._clock = clock
        self.Logger = logger
        self._lock = threading.Lock()
        self._reported = {}
        self._pending = {}   # field -> (value, deadline)

    def _effective_locked(self, field, default=None):
        if field in self._pending:
            return self._pending[field][0]
        return self._reported.get(field, default)

    def report(self, field: str, value) -> bool:
        """Record a value reported by the AC.  True if effective() changed."""
        with self._lock:
            before = self._effective_locked(field)
            self._reported[field] = value
            if field in self._pending and self._pending[field][0] == value:
                del self._pending[field]
            return self._effective_locked(field) != before

    def command(self, field: str, value) -> None:
        with self._lock:
            self._pending[field] = (value, self._clock() + self.timeout)

    def effective(self, field: str, default=None):
        with self._lock:
            return self._effective_locked(field, default)

    def reported(self, field: str, default=None):
        with self._lock:
            return self._reported.get(field, default)

    def is_pending(self, field: str) -> bool:
        with self._lock:
            return field in self._pending

    def expire(self) -> list:
        """Drop pending values past their deadline; return the reverted fields."""
        now = self._clock()
        reverted = []
        with self._lock:
            for field, (value, deadline) in list(self._pending.items()):
                if now >= deadline:
                    del self._pending[field]
                    reverted.append(field)
                    self.Logger.info(f"{field}: {value!r} not confirmed within {self.timeout}s, "
                                     f"reverting to {self._reported.get(field)!r}")
        return reverted
