# yaqd-acton

[![PyPI](https://img.shields.io/pypi/v/yaqd-acton)](https://pypi.org/project/yaqd-acton)
[![Conda](https://img.shields.io/conda/vn/conda-forge/yaqd-acton)](https://anaconda.org/conda-forge/yaqd-acton)
[![yaq](https://img.shields.io/badge/framework-yaq-orange)](https://yaq.fyi/)
[![black](https://img.shields.io/badge/code--style-black-black)](https://black.readthedocs.io/)
[![ver](https://img.shields.io/badge/calver-YYYY.0M.MICRO-blue)](https://calver.org/)
[![log](https://img.shields.io/badge/change-log-informational)](https://gitlab.com/yaq/yaqd-acton/-/blob/main/CHANGELOG.md)

yaq daemons for Acton Research Corporation instruments

This package contains the following daemon(s):

- https://yaq.fyi/daemons/acton-2150i
- https://yaq.fyi/daemons/acton-sp2300i

## acton-sp2300i notes
* This daemon has been tested and designed on a SP-2358 unit. There is a motorized slit on the front side entrance, and the exit mirror is movable. It's primary turret has a mirror and two gratings. The daemon was written with the intent of being usable on all sp23xx systems, but it has not been tested. Feedback and/or bugfixes are appreciated!
* _This daemon is designed for the RS232 port._ sp2300i models can be controlled via their onboard USB or RS232 port, but the USB port has different response behavior (consult the manual) which has not currently been addressed. 
* The identifiers of the gratings occupying each turret are retrieved from the spectrometer memory (`?GRATINGS`).  If gratings are changed, be sure to register changes by changing the on board grating info (see the manual for full instructions).
* The daemon moves to set wavelengths at max speed (i.e. `GOTO` command).  It does not currently support constant speed scanning (i.e. `NM` and `>NM` commands).  

## maintainers

- [Blaise Thompson](https://github.com/untzag)
- [Dan Kohler](https://github.com/ddkohler)

