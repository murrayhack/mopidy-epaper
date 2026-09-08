# Vendored Waveshare e-Paper driver sources. See ../../NOTICE for licensing.
#
# Nothing here may be imported at package import time: epdconfig.py runs
# hardware detection on import and raises on non-Raspberry Pi platforms.
#
# epdconfig.py is also never the module epd2in13_V4.py ends up importing at
# runtime — ../hardware.py stands in for it, so the PWR pin stays configurable.
# See that module for why the substitution has to happen before the import.
