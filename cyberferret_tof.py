import threading
import time


class FrontDownToF:
    """VL53L0X front/down range sensor.

    Hardware imports are intentionally lazy so the rest of Cyber Ferret,
    including simulation and unit tests, does not require Raspberry Pi I2C
    libraries to import successfully.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sensor = None
        self._available = False
        self._last_error = None

    @property
    def available(self):
        with self._lock:
            return self._available

    @property
    def last_error(self):
        with self._lock:
            return self._last_error

    def start(self):
        try:
            import board
            import busio
            import adafruit_vl53l0x

            i2c = busio.I2C(board.SCL, board.SDA)
            sensor = adafruit_vl53l0x.VL53L0X(i2c)
        except Exception as exc:
            with self._lock:
                self._sensor = None
                self._available = False
                self._last_error = str(exc)
            print(f"[TOF] front/down unavailable: {exc}")
            return False

        with self._lock:
            self._sensor = sensor
            self._available = True
            self._last_error = None

        print("[TOF] front/down VL53L0X online at 0x29")
        return True

    def read(self):
        """Return one measurement snapshot.

        Distance is deliberately kept raw. No obstacle/drop inference belongs
        here; interpretation can be added later from recorded driving data.
        """
        with self._lock:
            sensor = self._sensor
            available = self._available

        now = time.monotonic()
        epoch = time.time()

        if not available or sensor is None:
            return {
                "distance_mm": None,
                "distance_m": None,
                "captured_at": now,
                "captured_at_epoch": epoch,
                "available": False,
            }

        try:
            mm = int(sensor.range)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            return {
                "distance_mm": None,
                "distance_m": None,
                "captured_at": now,
                "captured_at_epoch": epoch,
                "available": True,
            }

        return {
            "distance_mm": mm,
            "distance_m": mm / 1000.0,
            "captured_at": now,
            "captured_at_epoch": epoch,
            "available": True,
        }

    def stop(self):
        with self._lock:
            self._sensor = None
            self._available = False
