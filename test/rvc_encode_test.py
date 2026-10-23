import unittest
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.rvc_encode import (
    U16_NA, encode_voltage_u16, encode_current_u16, encode_frequency_u16, u16_le,
    encode_temperature_u16, decode_temperature_u16,
)


class Test_Encoders(unittest.TestCase):

    def setUp(self):
        self.dec = RVC_Decoder()

    def test_none_is_not_available(self):
        self.assertEqual(encode_voltage_u16(None), U16_NA)
        self.assertEqual(encode_current_u16(None), U16_NA)
        self.assertEqual(encode_frequency_u16(None), U16_NA)

    def test_voltage_round_trips(self):
        for v in (0.0, 12.8, 52.0, 120.0, 228.8):
            raw = encode_voltage_u16(v)
            self.assertEqual(self.dec._convert_unit(raw, "v", "uint16"), v)

    def test_current_round_trips(self):
        for a in (-50.0, 0.0, 3.8, 40.0):
            raw = encode_current_u16(a)
            self.assertEqual(self.dec._convert_unit(raw, "a", "uint16"), a)

    def test_frequency_round_trips(self):
        for hz in (0.0, 50.0, 60.0):
            raw = encode_frequency_u16(hz)
            self.assertEqual(self.dec._convert_unit(raw, "hz", "uint16"), hz)

    def test_clamps_to_valid_range(self):
        self.assertEqual(encode_voltage_u16(-5), 0)
        self.assertEqual(encode_voltage_u16(99999), 0xFFFE)
        self.assertEqual(encode_current_u16(-2000), 0)
        self.assertEqual(encode_frequency_u16(99999), 0xFFFE)

    def test_non_finite_values_do_not_raise(self):
        self.assertEqual(encode_voltage_u16(float('nan')), U16_NA)
        self.assertEqual(encode_voltage_u16(float('inf')), 0xFFFE)
        self.assertEqual(encode_current_u16(float('-inf')), 0)

    def test_u16_le(self):
        self.assertEqual(u16_le(0x0410), b"\x10\x04")
        self.assertEqual(u16_le(U16_NA), b"\xff\xff")

    def test_temperature_known_values(self):
        self.assertEqual(encode_temperature_u16(24), 0x2520)
        self.assertEqual(encode_temperature_u16(22.5), 0x24F0)
        self.assertEqual(encode_temperature_u16(None), U16_NA)

    def test_temperature_round_trips(self):
        for c in (-10.0, 0.0, 17.0, 24.0, 30.0):
            raw = encode_temperature_u16(c)
            self.assertEqual(self.dec._convert_unit(raw, "deg c", "uint16"), c)

    def test_decode_temperature(self):
        self.assertEqual(decode_temperature_u16(0x2520), 24.0)
        self.assertIsNone(decode_temperature_u16(0xFFFF))
        self.assertIsNone(decode_temperature_u16(0xFFFC))


if __name__ == "__main__":
    unittest.main()
