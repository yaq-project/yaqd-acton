__all__ = ["ActonMono"]

import asyncio
import re
import time
from math import isnan

from yaqd_core import UsesUart, HasTurret, HasLimits, aserial

from .__version__ import __branch__


gpmm_re = re.compile(r"\d+(?=\s*g/mm)")
nm_re = re.compile(r"[\d\.\d]+(?=\s*[nN][mM])")
slit_re = re.compile(r"(?P<facing>(FRONT)|(SIDE))-(?P<end>(ENT)|(EXIT))-SLIT")
mirror_re = re.compile(r"(?P<facing>(ENT)|(EXIT))-MIRROR")
facing_re = re.compile(r"(?P<side>(FRONT)|(SIDE))")

eol = b"ok\r\n"


class ActonMono(UsesUart, HasTurret, HasLimits):
    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        self.ser = aserial.ASerial(
            config["serial_port"],
            baudrate=config["baud_rate"],
            eol=eol
        )
        self.ser.timeout = 1
        # TODO: grab gratings per turret (mono-eestatus)
        # --- find active grating
        self.ser.write(b"?GRATINGS\r")
        _gratings = self.ser.read_until(eol).decode()
        _gratings = _gratings.split("\r\n")[1:-2]
        self.logger.debug(_gratings)
        gratings = []
        for i, gi in enumerate(_gratings):
            self.logger.debug(f"grating {gi}")
            if gi.startswith("\x1a"):
                grating = i
            if "not installed" in gi.lower():
                gratings.append("")
            elif "mirror" in gi.lower():
                gratings.append("Mirror")
            elif "g/mm" in gi.lower():
                try:
                    gpmm = gpmm_re.search(gi)[0]
                    blz = nm_re.search(gi)[0]
                    gratings.append(f"{gpmm} g/mm, {blz} nm blaze")
                except TypeError as e:
                    gratings.append(gi)
                    self.logger.warning(f"could not parse identifier {gi}")
            else:
                continue
        self._state["gratings"] = gratings
        self._state["grating"] = self._grating_destination = gratings[grating]
        # --- slits: designate motorized slits, positions
        slits = []
        self.slit_names = []
        for divert in ["FRONT", "SIDE"]:
            for end in ["ENT", "EXIT"]:
                self.slit_names.append(f"{divert}-{end}")
                slit = f"{divert}-{end}-SLIT"
                self.ser.write(slit.encode() + b"\r")
                reply = self.ser.read_until(eol).decode()
                if "no motor" in reply:
                    slits.append("None")
                else:
                    while True:
                        # extract position
                        self.ser.write(b"?MICRONS\r")
                        time.sleep(0.1)
                        reply = [x.decode() for x in self.ser.readlines()]
                        slit_position = re.search(r"(?<=\?MICRONS)\s*\d+", reply[0])[0]
                        if slit_position:
                            slits.append(int(slit_position))
                            break
                        else:
                            self.logger.error("no slit position found")
                            time.sleep(0.1)
        self._active_slit = 3
        self._state["slits"] = slits
        self._slit_ids = [i for i in range(len(slits)) if slits[i] != "None"]
        self._slit_destinations = [i for i in self._state["slits"]]
        # --- mirrors: find motorized mirrors, query direction
        mirrors = []
        self._mirror_moves = []
        for end in ["ENT", "EXIT"]:
            self.ser.write(f"{end}-MIRROR".encode() + b"\r")
            x = self.ser.read_until(eol).decode()
            has_motor = "no motor" not in x
            self._mirror_moves.append(has_motor)
            if has_motor:
                self.ser.write(b"?MIRROR\r")
                reply = self.ser.read_until(eol)
                reply = re.search(r"(?<=\?MIRROR )\w+", reply.decode())
                mirrors.append(reply[0].upper())
            else:
                mirrors.append("None")
        self._active_mirror = 1
        self._state["mirrors"] = mirrors
        self._mirror_destinations = [i for i in mirrors]
        # --- find grating position
        if isnan(self._state["position"]):  # get an initial position
            self.ser.write(b"?NM\r")
            reply = self.ser.read_until(eol)
            reply = nm_re.search(reply.decode())
            if reply is not None:
                self._state["position"] = float(reply[0])
        self._state["destination"] = self._state["position"]
        self.ser.timeout = 0
        self._queue = []
        self._units = "nm"
        self._loop.create_task(self._write())

    async def update_state(self):
        while True:
            busy:bool = False
            try:
                if abs(self._state["position"] - self._state["destination"]) > 0.1:
                    busy = True
                    if "?NM\r".encode() not in self._queue:
                        self._queue += ["?NM\r".encode()]
                if self._state["grating"] != self._grating_destination:
                    busy = True
                    if "?GRATING\r".encode() not in self._queue:
                        self._queue += ["?GRATING\r".encode()]
                if self._state["slits"] != self._slit_destinations:
                    busy = True
                    for i in self._slit_ids:
                        facing = ["FRONT", "SIDE"][i//2]
                        end = ["ENT", "EXIT"][i%2]
                        if f"{facing}-{end}-SLIT\r".encode() not in self._queue:
                            self._queue += [
                                f"{facing}-{end}-SLIT\r".encode(),
                                f"?MICRONS\r".encode()
                            ]
                if self._state["mirrors"] != self._mirror_destinations:
                    busy = True
                    for i, end in enumerate(["ENT", "EXIT"]):
                        if self._mirror_moves[i] and f"{end}-MIRROR\r".encode() not in self._queue:
                            self._queue += [f"{end}-MIRROR\r".encode(), f"?MIRROR\r".encode()]
            except Exception as e:
                self.logger.error("update state")
                self.logger.error(e)
            if not busy:
                self.logger.debug("not busy")
                self._busy = False
                try:
                    await asyncio.wait_for(self._busy_sig.wait(), 5)
                except asyncio.TimeoutError:
                    continue
            else:
                self.logger.debug("busy")
                await asyncio.sleep(1)

    def direct_serial_write(self, message:bytes) -> None:
        self.ser.timeout = 1
        self.ser.write(message)
        out = self.ser.read_until(eol)
        self.ser.timeout = 0
        self.logger.debug(f"direct serial write: {out.decode()}")

    def close(self):
        self.ser.close()

    def _set_position(self, position):
        if "mirror" in self._state["grating"].lower():
            self._state["destination"] = 0
            self.logger.warn("changing position with mirror in: know what you are doing")
        self._state["destination"] = position
        self._queue += [f"{position} GOTO\r".encode()]

    def set_turret(self, id:str) -> None:
        i = self._state["gratings"].index(id)
        self._grating_destination = id
        self._set_hw_limits(id)
        if "Mirror" in id:
            if self._state["position"] != 0:
                self._set_position(0.0)
        self.logger.info(self._state["gratings"][i])
        self._queue += [f"{i//3+1} TURRET\r".encode(), f"{i%3+1} GRATING\r".encode()]

    def get_turret(self) -> str:
        return self._state["grating"]

    def get_turret_options(self):
        return [i for i in self._state["gratings"]]

    def set_front_entrance_slit(self, width:int):
        self._loop.create_task(
            self._aset_slit_width("ENT", "FRONT", width)
        )

    def set_side_entrance_slit(self, width:int) -> None:
        self._loop.create_task(
            self._aset_slit_width("ENT", "SIDE", width)
        )

    def set_front_exit_slit(self, width:int) -> None:
        self._loop.create_task(
            self._aset_slit_width("EXIT", "FRONT", width)
        )

    def set_side_exit_slit(self, width:int) -> None:
        self._loop.create_task(
            self._aset_slit_width("EXIT", "SIDE", width)
        )

    def get_front_entrance_slit(self) -> int:
        return self._state["slits"][0]

    def get_side_entrance_slit(self) -> int:
        return self._state["slits"][2]

    def get_front_exit_slit(self) -> int:
        return self._state["slits"][1]

    def get_side_exit_slit(self) -> int:
        return self._state["slits"][3]

    def get_slit_units(self) -> str:
        return "um"

    def get_slit_limits(self) -> list:
        return [10, 8000]

    def get_entrance_mirror(self) -> str:
        return self._state["mirrors"][0]

    def set_entrance_mirror(self, facing:str) -> None:
        if self._mirror_moves[0]:
            self._loop.create_task(self._aset_mirror("ENT", facing))
        else:
            self.logger.error(f"entrance mirror is not motorized")

    def get_exit_mirror(self) -> str:
        return self._state["mirrors"][1]

    def set_exit_mirror(self, facing:str) -> None:
        if self._mirror_moves[1]:
            self._loop.create_task(self._aset_mirror("EXIT", facing))
        else:
            self.logger.error(f"exit mirror is not motorized")

    async def _aset_mirror(self, end:str, facing:str):
        i = ["ENT", "EXIT"].index(end)
        self._queue += [f"{end}-MIRROR\r".encode(), f"{facing}\r".encode()]

    async def _aset_slit_width(self, end:str, facing:str, position:float):
        i = self.slit_names.index(f"{facing}-{end}")
        self._slit_destinations[i] = 5 * round(position / 5)  # sets to nearest 5 um
        self._busy = True
        if self._state["slits"][i] == "None":
            self.logger.error(f"slit {facing}-{end} is not motorized")
            return
        self._queue += [f"{facing}-{end}-SLIT\r".encode(), f"{position} MICRONS\r".encode()]

    async def _write(self):
        while True:
            if self._queue:
                cmd = self._queue.pop(0)
                self.logger.debug(f"Writing: {cmd}")
                line = await self.ser.awrite_then_readline(cmd)
                self._parse_line(line.decode())
            await asyncio.sleep(0.1)

    def _parse_line(self, line:str):
        """
        parses serial response and applies info to state
        """
        if line.endswith("?"):
            self.logger.error(f"Improper command: {line}")
            return
        split = line.split(" ")
        cmd = split[0]
        self.logger.debug(f"parse line: {line}")
        try:
            if "?GRATING" == cmd:
                grating = split[1]
                self.logger.debug("?GRATING" + grating)
                self._state["grating"] = self._state["gratings"][int(grating)-1]
            elif "?nm" == cmd.lower():
                position = split[1]
                self.logger.debug("?nm" + position)
                self._state["position"] = float(position)
            elif "?MICRONS" == cmd:
                slit = split[1]
                self.logger.debug(f"microns {slit} active slit {self._active_slit}")
                self._state["slits"][self._active_slit] = int(slit)
                self._state.updated = True
            elif "?MIRROR" == cmd:
                facing = split[1]
                self.logger.debug("?MIRROR" + facing)
                self._state["mirrors"][self._active_mirror] = facing.upper()
                self._state.updated = True
            elif any([s in line.upper() for s in ["GRATING", "TURRET", "MICRONS", "NM", "GOTO"]]):
                self.logger.debug(f"cmd recieved: {line}")
                self._busy = True
                return
            else:
                change_slit = slit_re.match(cmd)
                select_mirror = mirror_re.match(cmd)
                mirror_facing = facing_re.match(cmd)
                self.logger.debug(f"change_slit: {change_slit}")
                self.logger.debug(f"select_mirror: {select_mirror}")
                self.logger.debug(f"mirror_facing: {mirror_facing}")
                if change_slit:
                    facing = change_slit["facing"]
                    end = change_slit["end"]
                    self._active_slit = self.slit_names.index(f"{facing}-{end}")
                elif select_mirror:
                    self._active_mirror = 0 if select_mirror["facing"] == "ENT" else 1
                elif mirror_facing:
                    self._mirror_destinations[self._active_mirror] = mirror_facing["side"]
                    self._busy = True                    
                else:
                    self.logger.error(f"could not parse: {line}")
        except Exception as e:
            self.logger.error(f"parser error: {e}")

    def _set_hw_limits(self, id):
        limit = 11200
        gpmm = re.search(r"(?P<gpmm>\d*) g/mm", id)
        if "mirror" in id.lower():
            limit = 3
        elif gpmm:
            # mechanical limits from manual
            gpmm = int(gpmm["gpmm"])
            limit = 11200 * 150 / max(150, gpmm)
        self._state["hw_limits"] = [-limit, limit]


