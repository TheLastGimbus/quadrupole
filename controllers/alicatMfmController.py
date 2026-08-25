import serial
import time
from controllers.controller import Controller

class AlicatMFMController(Controller):
    def __init__(self, config):
        self.serial = None
        self.port = None
        self.name = None
        self.device_unit = "sccm"
        self.gas = "air"
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
        self.port = self.config.json["port"]

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
    def getName() -> str:
        return "alicat_mfm"

    @staticmethod
    def getIsEditableDict() -> dict[str, bool]:
        return {"value": False}

    @staticmethod
    def getUnitDict() -> dict[str, str]:
        return {"value": "sccm"}

    @staticmethod
    def getMinDict() -> dict[str, float]:
        return {}

    @staticmethod
    def getMaxDict() -> dict[str, float]:
        return {}

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
        if param != self.name or self.serial is None or not self.serial.is_open:
            return 0.0

        try:
            self.serial.reset_input_buffer()
            self.serial.write(b"A\r")
            time.sleep(0.05)

            raw = self.serial.read_until(b'\r').decode('ascii').strip()
            if not raw:
                return 0.0

            parts = raw.split()
            if len(parts) < 6:
                return 0.0

            val = float(parts[4])

            if self.device_unit == "mg/s":
                return self.mg_s_to_sccm(val, self.gas)
            return val

        except (ValueError, IndexError, Exception):
            return 0.0

    def adjust(self, param: str, value: float) -> None:
        pass

    def enable(self, state: bool) -> None:
        pass
