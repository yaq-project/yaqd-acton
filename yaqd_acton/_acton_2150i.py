__all__ = ["Acton2150I"]

import asyncio
from typing import Dict, Any, List
import math
import re

import serial  # type: ignore

from yaqd_core import HasTurret, UsesUart, UsesSerial, HasLimits, HasPosition, IsDaemon, aserial

from .__version__ import __branch__


class Acton2150I(HasTurret, UsesUart, UsesSerial, HasLimits, HasPosition, IsDaemon):
    _kind = "acton-2150i"

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

    def _set_position(self, position):
        self._busy = True
        self.ser.write(f"{round(position, 1)} GOTO\r".encode())

    def set_turret(self, identifier):
        self._busy = True
        self.ser.write(f"{int(identifier)%2+1} GRATING\r".encode())
        self.ser.write(f"{int(identifier)//2+1} TURRET\r".encode())
        self._state["turret"] = identifier

    def get_turret_options(self):
        return [str(i) for i in range(1, 7)]

    def get_turret(self):
        return self._state["turret"]

    async def update_state(self):
        while True:
            # get current position
            try:
                now = await self.ser.awrite_then_readline("?NM\r".encode())
                now = re.findall(r"[\d\.\d]+", now.decode())
                now = float(now[0])
            except Exception as e:
                self.logger.debug(e)
                await asyncio.sleep(1)
                continue
            # assess busy state
            if abs(now - self._state["destination"]) > 0.2:
                self._busy = True
                self._state["position"] = now
            elif math.isclose(now, self._state["position"]):
                self._busy = False
                await self._busy_sig.wait()
            else:
                self._state["position"] = now
                await asyncio.sleep(0.1)
