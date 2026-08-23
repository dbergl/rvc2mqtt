import unittest
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.rvc_encode import (
    U16_NA, encode_voltage_u16, encode_current_u16, encode_frequency_u16, u16_le,
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

    def test_u16_le(self):
        self.assertEqual(u16_le(0x0410), b"\x10\x04")
        self.assertEqual(u16_le(U16_NA), b"\xff\xff")


if __name__ == "__main__":
    unittest.main()
