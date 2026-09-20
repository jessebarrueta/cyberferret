import unittest
from unittest.mock import patch

from cyberferret_tof import FrontDownToF


class FakeSensor:
    range = 253


class FrontDownToFTests(unittest.TestCase):
    def test_read_preserves_raw_measurement(self):
        tof = FrontDownToF()
        tof._sensor = FakeSensor()
        tof._available = True

        sample = tof.read()

        self.assertEqual(sample["distance_mm"], 253)
        self.assertEqual(sample["distance_m"], 0.253)
        self.assertTrue(sample["available"])

    def test_unavailable_sensor_returns_none(self):
        sample = FrontDownToF().read()

        self.assertIsNone(sample["distance_mm"])
        self.assertIsNone(sample["distance_m"])
        self.assertFalse(sample["available"])

    def test_read_failure_does_not_invent_distance(self):
        class BrokenSensor:
            @property
            def range(self):
                raise OSError("i2c trouble")

        tof = FrontDownToF()
        tof._sensor = BrokenSensor()
        tof._available = True

        sample = tof.read()

        self.assertIsNone(sample["distance_mm"])
        self.assertIsNone(sample["distance_m"])
        self.assertTrue(sample["available"])
        self.assertEqual(tof.last_error, "i2c trouble")


if __name__ == "__main__":
    unittest.main()
