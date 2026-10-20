import serial
import time
import statistics
import logging
from collections import deque
from controllers.controller import Controller

class AlicatMFMController(Controller):
    def __init__(self, config):
        self.serial = None
        self.port = None
        self.unit = "A"
        self.name = None
        self.setpoint_param = None
        self.setpoint_readout_param = None
        self.device_unit = "sccm"
        self.gas = "air"
        self.moving_avg_time = 0.0
        self.filter_type = "median"   # "mean", "median"
        self.samples = deque()
        self.config = config
        self.parseConfig()

    def parseConfig(self):
        for param in self.config.params:
            if param.type == "value":
                self.name = param.name
                # odczyt opcjonalnego deviceUnit z configu (mg/s albo sccm)
                try:
                    self.device_unit = param.json["deviceUnit"]
                except KeyError:
                    self.device_unit = "sccm"
                try:
                    self.gas = param.json["gas"]
                except KeyError:
                    self.gas = "air"
                try:
                    self.moving_avg_time = float(param.json["movingAverageTime"])
                except KeyError:
                    self.moving_avg_time = 0.0
                try:
                    self.filter_type = param.json["filterType"]
                except KeyError:
                    self.filter_type = "median"
            elif param.type == "setpoint":
                self.setpoint_param = param.name
            elif param.type == "setpoint_readout":
                self.setpoint_readout_param = param.name
        self.port = self.config.json["port"]
        self.unit = self.config.json.get("unit", "A")
        if len(self.unit) != 1:
            logging.warning(f"Invalid Alicat unit ID: {self.unit}, falling back to A")
            self.unit = "A"

    @staticmethod
    def mg_s_to_sccm(mg_s: float, gas: str = "n2") -> float:
        densities = {
            "n2":  1.145,
            "air": 1.184,
            "o2":  1.308,
            "ar":  1.633,
            "he":  0.164,
            "h2":  0.0838,
            "co2": 1.799,
        }
        rho = densities.get(gas.lower(), 1.145)
        return (mg_s * 60) / rho

    @staticmethod
    def sccm_to_mg_s(sccm: float, gas: str = "n2") -> float:
        densities = {
            "n2":  1.145,
            "air": 1.184,
            "o2":  1.308,
            "ar":  1.633,
            "he":  0.164,
            "h2":  0.0838,
            "co2": 1.799,
        }
        rho = densities.get(gas.lower(), 1.145)
        return (sccm * rho) / 60

    @staticmethod
    def getName() -> str:
        return "alicat_mfm"

    @staticmethod
    def getIsEditableDict() -> dict[str, bool]:
        return {"value": False, "setpoint": True, "setpoint_readout": False}

    @staticmethod
    def getUnitDict() -> dict[str, str]:
        return {"value": "sccm", "setpoint": "sccm", "setpoint_readout": "sccm"}

    @staticmethod
    def getMinDict() -> dict[str, float]:
        return {"setpoint": 0}

    @staticmethod
    def getMaxDict() -> dict[str, float]:
        return {"setpoint": 1000}

    def connect(self) -> bool:
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=19200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0
            )
            time.sleep(0.2)
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

            try:
                self.serial.write(b"AF2\r")
                time.sleep(0.1)
                self.serial.read_all()
            except Exception:
                pass

            return True
        except Exception:
            return False

    def read(self, param: str) -> float:
        if self.serial is None or not self.serial.is_open:
            return 0.0

        try:
            self.serial.reset_input_buffer()
            self.serial.write(f"{self.unit}\r".encode())
            time.sleep(0.05)

            raw = self.serial.read_until(b'\r').decode('ascii').strip()
            if not raw:
                return 0.0

            parts = raw.split()
            if len(parts) < 6:
                return 0.0

            if param == self.name:
                idx = 4
            elif param == self.setpoint_readout_param:
                idx = 5
            else:
                return 0.0

            val = float(parts[idx])

            if self.device_unit == "mg/s":
                val = self.mg_s_to_sccm(val, self.gas)

            # --- filtr kroczący (tylko dla odczytów przepływu) ---
            if param != self.name or self.moving_avg_time <= 0:
                return val

            now = time.time()
            self.samples.append((now, val))

            cutoff = now - self.moving_avg_time
            while self.samples and self.samples[0][0] < cutoff:
                self.samples.popleft()

            if not self.samples:
                return val

            values = [v for _, v in self.samples]

            if self.filter_type == "mean":
                return statistics.mean(values)
            elif self.filter_type == "median":
                return statistics.median(values)

            return val

        except (ValueError, IndexError, Exception):
            return 0.0

    def adjust(self, param: str, value: float) -> None:
        if param != self.setpoint_param or self.serial is None or not self.serial.is_open:
            return

        try:
            # Konwersja sccm (jednostki GUI) na jednostki urządzenia (mg/s)
            if self.device_unit == "mg/s":
                value = self.sccm_to_mg_s(value, self.gas)

            self.serial.reset_input_buffer()
            self.serial.write(f"{self.unit}S{value:.3f}\r".encode())
        except Exception:
            logging.error("Couldn't set Alicat setpoint")

    def enable(self, state: bool) -> None:
        pass
