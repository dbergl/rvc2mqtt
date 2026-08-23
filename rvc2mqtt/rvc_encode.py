"""
Encoders for RV-C numeric fields.

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

Inverse of RVC_Decoder._convert_unit for the uint16 types used by the
virtual inverter.  See RV-C spec table 5.3.
"""

import math

U16_NA = 0xFFFF


def _clamp_u16(value: float) -> int:
    """Clamp to the valid data range; 0xFFFF is reserved for 'not available'.

    Never raises on a non-finite float: NaN maps to "not available", and
    +/-inf clamp to the same range boundary a huge-but-finite value would.
    """
    if math.isnan(value):
        return U16_NA
    if math.isinf(value):
        return 0 if value < 0 else 0xFFFE
    return max(0, min(0xFFFE, int(round(value))))


def encode_voltage_u16(volts) -> int:
    """0.05 V/bit, no offset."""
    if volts is None:
        return U16_NA
    return _clamp_u16(volts / 0.05)


def encode_current_u16(amps) -> int:
    """0.05 A/bit, -1600 A offset."""
    if amps is None:
        return U16_NA
    return _clamp_u16((amps + 1600) / 0.05)


def encode_frequency_u16(hz) -> int:
    """1/128 Hz/bit."""
    if hz is None:
        return U16_NA
    return _clamp_u16(hz * 128)


def u16_le(value: int) -> bytes:
    """Two little-endian bytes (RV-C byte order)."""
    return bytes((value & 0xFF, (value >> 8) & 0xFF))
