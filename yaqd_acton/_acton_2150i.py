__all__ = ["Acton2150I"]

import asyncio
from typing import Dict, Any, List
import math
import re

import serial  # type: ignore

from yaqd_core import ContinuousHardware, aserial

from .__version__ import __branch__


class Acton2150I(ContinuousHardware):
    _kind = "acton-2150i"
    _version = "0.1.0" + f"+{__branch__}" if __branch__ else ""
    traits: List[str] = ["uses-uart", "has-turret", "uses-serial"]
    defaults: Dict[str, Any] = {"baud_rate": 9600}

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        self.ser = aserial.ASerial(config["serial_port"], baudrate=config["baud_rate"])
        # ensure that echo state is as default
        self.ser.write("ECHO".encode())
        self.ser.readline()

    def close(self):
        self.ser.close()

    def direct_serial_write(self, message):
        self._busy = True
        self.ser.write(message.encode())

    def get_state(self):
        state = super().get_state()
        state["turret"] = self._turret
        return state

    def _load_state(self, state):
        super()._load_state(state)
        self._turret = state.get("turret", 1)

    def _set_position(self, position):
        self._busy = True
        self.ser.write(f"{position} GOTO\r".encode())

    def set_turret(self, index):
        self._busy = True
        self.ser.write(f"{index} GRATING\r".encode())
        self._turret = index
        print(self._turret)

    def get_turret(self):
        return self._turret

    async def update_state(self):
        while True:
            # get current position
            try:
                self.ser.clear_input_buffer()
                now = await self.ser.awrite_then_readline("?NM\r".encode())
                now = re.findall(r"[\d\.\d]+", now.decode())
                now = float(now[0])
            except:
                await asyncio.sleep(1)
                continue
            # assess busy state
            if math.isclose(now, self._position):
                self._busy = False
                await self._busy_sig.wait()
            else:
                self._position = now
                await asyncio.sleep(0.1)
