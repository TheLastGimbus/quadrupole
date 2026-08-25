from PySide6.QtCore import QObject, Slot, QTimer, Signal
import time
import datetime
import csv
import logging
import os.path

from controllers.controller import Controller
from controllers.dummyController import DummyController
from controllers.keithleyController import KeithleyController
from controllers.spdController import SPDController
from controllers.sdmController import SDMController
from controllers.afgController import AFGController
from controllers.rudiController import RudiController
from controllers.impedanceController import ImpedanceController
from controllers.fyController import FYController
from controllers.euroController2 import EuroController
from controllers.pressureController import PressureController
from controllers.HP34401AController import HP34401AController
from controllers.HP34401AScannerController import HP34401AScannerController
from controllers.HamegHM5014Controller import HamegHM5014Controller
from controllers.UnixTimeController import UnixTimeController
from controllers.UT804 import UT804Controller
from controllers.bm252s import BM252sController
from config import Config, ControllerConfig, ParamConfig
from controllers.alicatMfmController import AlicatMFMController

from utils import DataPacket


class Executor(QObject):
    exited = Signal()
    measured = Signal(DataPacket)
    stoped = Signal()
    controllersConnected = Signal(object)

    def __init__(self, config, parent: QObject = None):
        super(Executor, self).__init__(parent)

        self.config: Config = config

        self.controllerTemplates: dict[str, Controller] = {}
        self.controllers: dict[str, Controller] = {}
        self.params: dict[str, ParamConfig] = {}
        self.timer = None
        self.delay = 0.1
        self.counter = 0
        self.startTime = time.time()
        self.paramValues: dict[str, float] = {}

        self.file = None
        self.title = None
        self.comment = None

        self.sweepOneEnabled: bool = False
        self.sweepOneParam: str = None
        self.sweepOneMin: float = 0
        self.sweepOneMax: float = 0
        self.sweepOneSteps: int = 2
        self.sweepOneLog: bool = False

        self.sweepTwoEnabled: bool = False
        self.sweepTwoParam: str = None
        self.sweepTwoMin: float = 0
        self.sweepTwoMax: float = 0
        self.sweepTwoSteps: int = 2
        self.sweepTwoLog: bool = False

        self.fileSweepEnabled: bool = False
        self.fileSweepName: str = ""

        self.fileSweepData: dict(str, list(float)) = {}
        self.fileSweepSteps: int = 0

        self.sweepTwoValue = 0

        self.a = 0
        self.b = 0
        self.c = 0
        self.d = 0
        self.depending = []

        for controller in self.config.controllers:
            for param in controller.params:
                self.params[param.name] = param
                self.paramValues[param.name] = None

        self.params = dict(
            sorted(self.params.items(), key=lambda x: x[1].json.get("priority", 0))
        )

    def initControllers(self) -> None:
        self.controllerTemplates[DummyController.getName()] = DummyController
        self.controllerTemplates[KeithleyController.getName()] = KeithleyController
        self.controllerTemplates[SPDController.getName()] = SPDController
        self.controllerTemplates[SDMController.getName()] = SDMController
        self.controllerTemplates[AFGController.getName()] = AFGController
        self.controllerTemplates[RudiController.getName()] = RudiController
        self.controllerTemplates[ImpedanceController.getName()] = ImpedanceController
        self.controllerTemplates[FYController.getName()] = FYController
        self.controllerTemplates[EuroController.getName()] = EuroController
        self.controllerTemplates[PressureController.getName()] = PressureController
        self.controllerTemplates[HP34401AController.getName()] = HP34401AController
        self.controllerTemplates[HP34401AScannerController.getName()] = (
            HP34401AScannerController
        )
        self.controllerTemplates[HamegHM5014Controller.getName()] = (
            HamegHM5014Controller
        )
        self.controllerTemplates[UnixTimeController.getName()] = UnixTimeController
        self.controllerTemplates[UT804Controller.getName()] = UT804Controller
        self.controllerTemplates[BM252sController.getName()] = BM252sController
        self.controllerTemplates[AlicatMFMController.getName()] = AlicatMFMController

        for controller in self.config.controllers:
            self.addController(
                self.controllerTemplates[controller.type](controller), controller
            )

    def addController(self, controller: Controller, config: ControllerConfig) -> None:
        if controller.connect():
            isEditableDict = controller.getIsEditableDict()
            unitDict = controller.getUnitDict()
            minDict = controller.getMinDict()
            maxDict = controller.getMaxDict()

            # For each param in config for this controller
            for param in config.params:

                # Assosiate name of param with controller
                self.controllers[param.name] = controller

                # Set whether editable in its paramConfig
                if self.params[param.name].editable is None:
                    if param.type in isEditableDict:
                        self.params[param.name].editable = isEditableDict[param.type]
                    else:
                        logging.warning(
                            f"No param type: {param.type} in isEditableDict for {config.type}"
                        )
                        self.params[param.name].editable = False

                # Set appropriate unit in its paramConfig
                if self.params[param.name].unit is None:
                    if param.type in unitDict:
                        self.params[param.name].unit = unitDict[param.type]
                    else:
                        logging.warning(
                            f"No param type: {param.type} in unitDict for {config.type}"
                        )
                        self.params[param.name].unit = "-"

                # Set minimal value in its paramConfig
                if self.params[param.name].editable:
                    if self.params[param.name].min is None:
                        if param.type in minDict:
                            self.params[param.name].min = minDict[param.type]
                        else:
                            logging.warning(
                                f"No param type: {param.type} in minDict for {config.type}"
                            )
                            self.params[param.name].min = -1e99

                # Set maximal value in its paramConfig
                if self.params[param.name].editable:
                    if self.params[param.name].max is None:
                        if param.type in maxDict:
                            self.params[param.name].max = maxDict[param.type]
                        else:
                            logging.warning(
                                f"No param type: {param.type} in maxDict for {config.type}"
                            )
                            self.params[param.name].max = 1e99

                if param.depending:
                    self.depending.append(param.name)

        else:
            logging.error(f'"{config.type}" controller did not connect')

        # Add delay param so that it can be editable
        self.params["Delay"] = ParamConfig()
        self.params["Delay"].name = "Delay"
        self.params["Delay"].unit = "s"
        self.params["Delay"].editable = True
        self.params["Delay"].default = self.config.defaults.get("delay", 0.1)
        self.params["Delay"].min = 0

        if self.config.json.get("uses_a", False):
            self.params["a"] = ParamConfig()
            self.params["a"].name = "a"
            self.params["a"].unit = "-"
            self.params["a"].editable = True
            self.params["a"].default = self.config.defaults.get("a", 0)

        if self.config.json.get("uses_b", False):
            self.params["b"] = ParamConfig()
            self.params["b"].name = "b"
            self.params["b"].unit = "-"
            self.params["b"].editable = True
            self.params["b"].default = self.config.defaults.get("b", 0)

        if self.config.json.get("uses_c", False):
            self.params["c"] = ParamConfig()
            self.params["c"].name = "c"
            self.params["c"].unit = "-"
            self.params["c"].editable = True
            self.params["c"].default = self.config.defaults.get("c", 0)

        if self.config.json.get("uses_d", False):
            self.params["d"] = ParamConfig()
            self.params["d"].name = "d"
            self.params["d"].unit = "-"
            self.params["d"].editable = True
            self.params["d"].default = self.config.defaults.get("d", 0)

    @Slot()
    def connectControllers(self):
        self.initControllers()

        for param in self.params.values():
            if param.editable:
                self.adjust(param.name, param.default)

        self.timer = QTimer()
        self.timer.timeout.connect(self.loop)
        self.timer.setInterval(10)

        self.controllersConnected.emit(self.params)

    def loop(self):
        self.timer.stop()

        self.setParameters()

        if self.file is None:
            self.openFile()

        time.sleep(self.delay)
        packet = DataPacket(time.time() - self.startTime, self.counter)
        print(self.params.keys())
        for param in self.params.keys():
            packet.addData(param, self.read(param))

        line = ""
        for param, value in packet.data.items():
            line += str(value) + "\t"
        line += datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S.%f")
        line += "\n"
        self.file.write(line)

        self.measured.emit(packet)
        self.counter += 1

        if self.sweepTwoEnabled:
            if self.counter % self.sweepOneSteps == 0:
                self.file.close()
                self.file = None

        # Handle stopping
        if self.sweepTwoEnabled and self.sweepOneEnabled:
            if self.counter == self.sweepOneSteps * self.sweepTwoSteps:
                self.stop()
            else:
                self.timer.start()
        elif self.sweepOneEnabled:
            if self.counter == self.sweepOneSteps:
                self.stop()
            else:
                self.timer.start()
        elif self.fileSweepEnabled:
            if self.counter == self.fileSweepSteps:
                self.stop()
            else:
                self.timer.start()
        else:
            self.timer.start()

    def read(self, param: str) -> float:
        if param == "Delay":
            return self.delay
        if param == "a":
            return self.a
        if param == "b":
            return self.b
        if param == "c":
            return self.c
        if param == "d":
            return self.d

        value = self.controllers[param].read(param)

        if self.params[param].eval_get is not None:
            print(value, self.a)
            value = eval(
                self.params[param].eval_get,
                {},
                {"x": value, "a": self.a, "b": self.b, "c": self.c, "d": self.d},
            )
        return value

    def setParameters(self) -> None:
        sweepOneIndex = self.counter % self.sweepOneSteps
        sweepTwoIndex = self.counter // self.sweepOneSteps

        if self.sweepOneEnabled:
            value = 0
            if self.sweepOneLog:
                value = self.sweepOneMin * (self.sweepOneMax / self.sweepOneMin) ** (
                    sweepOneIndex / (self.sweepOneSteps - 1)
                )
            else:
                value = (sweepOneIndex / (self.sweepOneSteps - 1)) * (
                    self.sweepOneMax - self.sweepOneMin
                ) + self.sweepOneMin
            self.adjust(self.sweepOneParam, value)

        if self.sweepTwoEnabled:
            value = 0
            if self.sweepTwoLog:
                value = self.sweepTwoMin * (self.sweepTwoMax / self.sweepTwoMin) ** (
                    sweepTwoIndex / (self.sweepTwoSteps - 1)
                )
            else:
                value = (sweepTwoIndex / (self.sweepTwoSteps - 1)) * (
                    self.sweepTwoMax - self.sweepTwoMin
                ) + self.sweepTwoMin
            self.sweepTwoValue = value
            self.adjust(self.sweepTwoParam, value)

        if self.fileSweepEnabled:
            for param, values in self.fileSweepData.items():
                self.adjust(param, values[self.counter])

        for param in self.depending:
            self.adjust(param, self.paramValues[param])

    @Slot(str, float)
    def adjust(self, param: str, value: float) -> None:
        if param == "Delay":
            self.delay = value
        elif param == "a":
            self.a = value
        elif param == "b":
            self.b = value
        elif param == "c":
            self.c = value
        elif param == "d":
            self.d = value
        else:
            self.paramValues[param] = value

            # Evaluate custom expression
            if self.params[param].eval_set is not None:
                value = eval(
                    self.params[param].eval_set,
                    {},
                    {"x": value, "a": self.a, "b": self.b, "c": self.c, "d": self.d},
                )

            # Check safety margins
            if self.params[param].min is not None:
                if value < self.params[param].min:
                    value = self.params[param].min
                    logging.warn(f"Minimal value for {param} exceeded")
            if self.params[param].max is not None:
                if value > self.params[param].max:
                    value = self.params[param].max
                    logging.warn(f"Maximal value for {param} exceeded")

            self.controllers[param].adjust(param, value)

    @Slot(str, str)
    def start(self, title, comment) -> None:
        self.timer.start()
        self.startTime = time.time()

        self.title = title
        self.comment = comment

    @Slot()
    def pause(self) -> None:
        self.timer.stop()

    @Slot()
    def stop(self) -> None:
        self.timer.stop()
        if self.file is not None:
            self.file.close()
            self.file = None

        self.counter = 0
        self.stoped.emit()

    @Slot()
    def restart(self) -> None:
        self.timer.start()

    @Slot()
    def exit(self):
        self.timer.stop()
        self.exited.emit()

    @Slot(bool, str, float, float, int, bool)
    def sweepOneSet(
        self,
        enabled: bool,
        param: str = None,
        minimum: float = 0,
        maximum: float = 0,
        steps: int = 2,
        log: bool = False,
    ):
        self.sweepOneEnabled = enabled
        self.sweepOneParam = param
        self.sweepOneMin = minimum
        self.sweepOneMax = maximum
        self.sweepOneSteps = steps
        self.sweepOneLog = log

    @Slot(bool, str, float, float, int, bool)
    def sweepTwoSet(
        self,
        enabled: bool,
        param: str = None,
        minimum: float = 0,
        maximum: float = 0,
        steps: int = 2,
        log: bool = False,
    ):
        self.sweepTwoEnabled = enabled
        self.sweepTwoParam = param
        self.sweepTwoMin = minimum
        self.sweepTwoMax = maximum
        self.sweepTwoSteps = steps
        self.sweepTwoLog = log

    @Slot(bool, str)
    def fileSweepSet(self, enabled: bool, filename: str):
        self.fileSweepEnabled = enabled
        self.fileSweepName = filename

        if enabled:
            with open(filename, encoding="utf-8-sig") as f:
                reader = csv.reader(f, skipinitialspace=True, dialect="excel")
                header = next(reader)

                # Read in header as list of parameter ID's
                list_of_params = []
                for name in header:
                    param = next(
                        (param for param in self.params.values() if param.name == name),
                        None,
                    )
                    if param is not None:
                        list_of_params.append(param.name)
                    else:
                        list_of_params.append(None)
                        logging.error(f'No param named "{name}" found')

                # Create empty list for each parameter
                for param in list_of_params:
                    self.fileSweepData[param] = []

                # Fill in values for parameters and count rows
                self.fileSweepSteps = 0
                for row in reader:
                    self.fileSweepSteps += 1
                    for index, value in enumerate(row):
                        self.fileSweepData[list_of_params[index]].append(float(value))

    def openFile(self):
        t = datetime.datetime.now().strftime("%m-%d")
        val = ""
        if self.sweepTwoEnabled:
            val = ("{0:.2E}".format(self.sweepTwoValue)).replace(".", "dot")

        count = 0
        name = (
            "data/"
            + t
            + "-"
            + str(count)
            + "-"
            + self.title
            + "-"
            + str(self.counter // self.sweepOneSteps)
            + "-"
            + val
            + ".csv"
        )
        while os.path.isfile(name):
            count += 1
            name = (
                "data/"
                + t
                + "-"
                + str(count)
                + "-"
                + self.title
                + "-"
                + str(self.counter // self.sweepOneSteps)
                + "-"
                + val
                + ".csv"
            )

        self.file = open(name, "w+")

        self.file.write(f"# {self.comment}\n")

        header = ""
        for param in self.params.values():
            header += param.name + "\t"

        self.file.write(header)
        self.file.write("\n")

    @Slot(bool)
    def enable(self, bool):
        controllerSet = set(self.controllers.values())
        for controller in controllerSet:
            controller.enable(bool)
