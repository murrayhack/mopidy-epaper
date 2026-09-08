"""Our own stand-in for the vendored ``drivers.epdconfig``.

The vendored module hardcodes ``PWR_PIN = 18``, claims it with gpiozero, and
drives it high on every ``module_init``. GPIO 18 is also I2S BCLK, and that is
fixed in the SoC's pinmux — it cannot be moved to another pin. So a Pi with an
I2S DAC and the stock epdconfig cannot coexist, and the failure is silent
rather than loud: claiming the pin pulls it out of ALT0, which breaks audio
instead of raising.

Patching after the fact is too late. ``epdconfig`` builds its gpiozero objects
at module scope, so *importing* it is what takes the pin, and closing the pin
afterwards does not hand the pinmux back to the I2S driver. :func:`install`
therefore puts this module in its place in ``sys.modules`` before the driver is
imported, so the stock one never runs at all. The vendored sources stay
verbatim — see ../NOTICE.

Panels wired directly rather than through a HAT have no power gate for PWR to
open, so ``pwr_pin`` may be left unset to keep this off GPIO entirely.
"""

import logging
import sys
import time
import types

logger = logging.getLogger(__name__)

#: Where the vendored driver looks for its hardware interface.
MODULE_NAME = "mopidy_epaper.drivers.epdconfig"

#: Everything ``epd2in13_V4`` reads off the interface. Checked against the
#: driver source in the tests, so a vendored update that reaches for something
#: new fails there rather than at runtime on the Pi.
REQUIRED_NAMES = (
    "RST_PIN",
    "DC_PIN",
    "CS_PIN",
    "BUSY_PIN",
    "digital_write",
    "digital_read",
    "delay_ms",
    "spi_writebyte",
    "spi_writebyte2",
    "module_init",
    "module_exit",
)

#: Provided as well, though this driver revision never reads them.
OPTIONAL_NAMES = ("PWR_PIN",)

# The panel's wiring. Only PWR is configurable: CS has to be GPIO 8 to be
# spidev0.0's chip select, MOSI and SCLK are fixed by ALT0, and there is no
# reason to move RST, DC or BUSY.
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8
BUSY_PIN = 24
PWR_PIN = 18

SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 4000000

_INTERFACE_ATTR = "_mopidy_epaper_interface"


class PinInterface:
    """GPIO and SPI for the panel.

    Mirrors the vendored ``epdconfig.RaspberryPi`` behaviour, with two
    departures: PWR is optional, and SPI is opened once rather than on every
    ``module_init``.
    """

    def __init__(self, pwr_pin=PWR_PIN):
        import gpiozero
        import spidev

        self.RST_PIN = RST_PIN
        self.DC_PIN = DC_PIN
        self.CS_PIN = CS_PIN
        self.BUSY_PIN = BUSY_PIN
        self.PWR_PIN = pwr_pin

        self._spi = spidev.SpiDev()
        self._spi_open = False

        self._outputs = {
            RST_PIN: gpiozero.LED(RST_PIN),
            DC_PIN: gpiozero.LED(DC_PIN),
        }
        if pwr_pin is None:
            logger.info("e-paper PWR pin disabled; no GPIO claimed for it")
        else:
            self._outputs[pwr_pin] = gpiozero.LED(pwr_pin)

        # pull_up=False matches the vendored module: BUSY reads high while the
        # panel is working. It also means a disconnected BUSY reads "idle",
        # which is why an absent panel produces no error anywhere.
        self._busy = gpiozero.Button(BUSY_PIN, pull_up=False)

    def digital_write(self, pin, value):
        # CS is deliberately not in _outputs. The kernel drives the chip select
        # as part of each SPI transfer, so the driver's CS writes have to stay
        # no-ops — the vendored module comments them out for the same reason,
        # and claiming GPIO 8 here would fight the SPI driver for it.
        device = self._outputs.get(pin)
        if device is None:
            return
        if value:
            device.on()
        else:
            device.off()

    def digital_read(self, pin):
        # BUSY is the only pin the driver reads.
        if pin == self.BUSY_PIN:
            return self._busy.value
        return 0

    def delay_ms(self, milliseconds):
        time.sleep(milliseconds / 1000.0)

    def spi_writebyte(self, data):
        self._spi.writebytes(data)

    def spi_writebyte2(self, data):
        self._spi.writebytes2(data)

    def module_init(self, cleanup=False):
        """Power the panel and open SPI. Returns 0, as the driver expects.

        ``cleanup`` exists for signature compatibility; the vendored module
        uses it to select a bundled C library we do not ship.
        """
        pwr = self._outputs.get(self.PWR_PIN)
        if pwr is not None:
            pwr.on()

        # The driver re-inits before every full refresh. spidev's open() does
        # not close the descriptor it replaces, so opening unconditionally —
        # as the vendored module does — leaks one per full refresh.
        if not self._spi_open:
            self._spi.open(SPI_BUS, SPI_DEVICE)
            self._spi_open = True
        self._spi.max_speed_hz = SPI_SPEED_HZ
        self._spi.mode = 0b00
        return 0

    def module_exit(self, cleanup=False):
        if self._spi_open:
            self._spi.close()
            self._spi_open = False

        for device in self._outputs.values():
            device.off()

        if cleanup:
            for device in self._outputs.values():
                device.close()
            self._busy.close()


def install(pwr_pin=PWR_PIN, interface=None):
    """Put our interface where the vendored driver will find it.

    Call this *before* importing ``drivers.epd2in13_V4``: that module does
    ``from . import epdconfig`` at its top, and importing the stock epdconfig
    is what claims GPIO 18.

    ``interface`` is for the tests, which have no GPIO to claim.
    """
    from . import drivers

    existing = sys.modules.get(MODULE_NAME)
    if existing is not None and hasattr(existing, _INTERFACE_ATTR):
        # Importing the stock epdconfig twice is a no-op, because sys.modules
        # caches it. Keep that property, so a restarted frontend does not try
        # to claim pins gpiozero is still holding.
        return existing
    if existing is not None:
        logger.warning(
            "%s was imported before we could stand in for it; GPIO %d is "
            "probably already claimed",
            MODULE_NAME,
            PWR_PIN,
        )

    if interface is None:
        interface = PinInterface(pwr_pin=pwr_pin)

    shim = types.ModuleType(MODULE_NAME)
    for name in REQUIRED_NAMES:
        setattr(shim, name, getattr(interface, name))
    for name in OPTIONAL_NAMES:
        setattr(shim, name, getattr(interface, name, None))
    setattr(shim, _INTERFACE_ATTR, interface)

    sys.modules[MODULE_NAME] = shim
    # ``from . import epdconfig`` reads the attribute off the parent package,
    # so set it rather than leaning on the import system's sys.modules
    # fallback.
    drivers.epdconfig = shim
    return shim
