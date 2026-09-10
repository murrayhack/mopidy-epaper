"""Tests for the epdconfig stand-in.

Nothing here touches GPIO: ``install`` takes an interface, so the tests supply
their own. They must also never let the real ``drivers.epdconfig`` load — that
is the whole point of the module under test — so the fixture restores
``sys.modules`` rather than reaching for the vendored file.
"""

import importlib
import pathlib
import re
import sys
import types

import pytest

from mopidy_epaper import drivers, hardware


class FakeInterface:
    """Duck-types PinInterface, recording what the driver would have done."""

    def __init__(self, pwr_pin=hardware.PWR_PIN):
        self.RST_PIN = hardware.RST_PIN
        self.DC_PIN = hardware.DC_PIN
        self.CS_PIN = hardware.CS_PIN
        self.BUSY_PIN = hardware.BUSY_PIN
        self.PWR_PIN = pwr_pin
        self.writes = []
        self.inits = 0
        self.exits = 0

    def digital_write(self, pin, value):
        self.writes.append((pin, value))

    def digital_read(self, pin):
        return 0

    def delay_ms(self, milliseconds):
        pass

    def spi_writebyte(self, data):
        pass

    def spi_writebyte2(self, data):
        pass

    def module_init(self, cleanup=False):
        self.inits += 1
        return 0

    def module_exit(self, cleanup=False):
        self.exits += 1


@pytest.fixture
def clean_modules():
    """Leave sys.modules and the drivers package as they were found."""
    saved_module = sys.modules.pop(hardware.MODULE_NAME, None)
    saved_attr = getattr(drivers, "epdconfig", None)
    yield
    sys.modules.pop(hardware.MODULE_NAME, None)
    if saved_module is not None:
        sys.modules[hardware.MODULE_NAME] = saved_module
    if saved_attr is None:
        if hasattr(drivers, "epdconfig"):
            del drivers.epdconfig
    else:
        drivers.epdconfig = saved_attr


def test_provides_everything_the_driver_reads(clean_modules):
    shim = hardware.install(interface=FakeInterface())

    for name in hardware.REQUIRED_NAMES:
        assert hasattr(shim, name), name


def test_required_names_cover_the_vendored_driver():
    """Guards against a vendored driver update reaching for something new.

    Read as text rather than imported: importing it would pull in the real
    epdconfig, which claims GPIO on a Pi and raises anywhere else.
    """
    source = (
        pathlib.Path(drivers.__file__).parent / "epd2in13_V4.py"
    ).read_text(encoding="utf-8")
    referenced = set(re.findall(r"epdconfig\.(\w+)", source))

    assert referenced
    assert referenced <= set(hardware.REQUIRED_NAMES) | set(hardware.OPTIONAL_NAMES)


def test_stands_in_for_the_vendored_module(clean_modules):
    shim = hardware.install(interface=FakeInterface())

    # Both routes the driver's `from . import epdconfig` can take.
    assert importlib.import_module(hardware.MODULE_NAME) is shim
    assert drivers.epdconfig is shim


def test_install_is_idempotent(clean_modules):
    """A restarted frontend must not try to claim pins twice."""
    first = hardware.install(interface=FakeInterface())
    second = hardware.install(interface=FakeInterface())

    assert first is second


def test_pwr_pin_defaults_to_eighteen(clean_modules):
    shim = hardware.install(interface=FakeInterface())

    assert shim.PWR_PIN == 18


def test_pwr_pin_can_be_disabled(clean_modules):
    shim = hardware.install(interface=FakeInterface(pwr_pin=None))

    assert shim.PWR_PIN is None


class FakeOutput:
    def __init__(self):
        self.states = []

    def on(self):
        self.states.append(1)

    def off(self):
        self.states.append(0)


def _interface_without_gpio(outputs):
    """A PinInterface with its constructor's gpiozero calls skipped."""
    interface = hardware.PinInterface.__new__(hardware.PinInterface)
    interface.BUSY_PIN = hardware.BUSY_PIN
    interface.PWR_PIN = hardware.PWR_PIN
    interface._outputs = outputs
    return interface


def test_cs_writes_are_ignored():
    """CS belongs to the kernel's SPI driver, not to us.

    The vendored epdconfig comments its CS branch out; if ours grew one it
    would fight spidev for GPIO 8, and nothing would reach the panel.
    """
    rst = FakeOutput()
    interface = _interface_without_gpio({hardware.RST_PIN: rst})

    interface.digital_write(hardware.CS_PIN, 0)
    interface.digital_write(hardware.CS_PIN, 1)
    assert rst.states == []

    interface.digital_write(hardware.RST_PIN, 1)
    interface.digital_write(hardware.RST_PIN, 0)
    assert rst.states == [1, 0]


def test_writes_to_a_disabled_pwr_pin_do_nothing():
    interface = _interface_without_gpio({hardware.RST_PIN: FakeOutput()})
    interface.PWR_PIN = None

    # digital_write is dispatched by pin number, so None must not match.
    interface.digital_write(None, 1)
    interface.digital_write(hardware.PWR_PIN, 1)


def test_busy_is_claimed_without_edge_detection(monkeypatch):
    """BUSY must not be a Button, however harmless that looks.

    ``digital_read`` samples its level and nothing subscribes to edges, but
    Button sets edge detection up regardless, which starts lgpio's alert
    thread: a ppoll loop at roughly 1540 wakes a second. Measured at 4.70% of
    a core against 0.15% for InputDevice, permanently, for a pin read a few
    times per refresh. Nothing would fail if this regressed -- it would just
    quietly cost 4.7% again -- so it is pinned here.
    """
    claimed = []

    class Recorder:
        def __init__(self, pin, **kwargs):
            claimed.append((type(self).__name__, pin))

        def close(self):
            pass

    fake_gpiozero = types.ModuleType("gpiozero")
    for name in ("LED", "InputDevice", "Button"):
        setattr(fake_gpiozero, name, type(name, (Recorder,), {}))
    monkeypatch.setitem(sys.modules, "gpiozero", fake_gpiozero)

    fake_spidev = types.ModuleType("spidev")
    fake_spidev.SpiDev = lambda: types.SimpleNamespace(
        open=lambda *a: None, close=lambda: None
    )
    monkeypatch.setitem(sys.modules, "spidev", fake_spidev)

    hardware.PinInterface(pwr_pin=None)

    by_pin = {pin: name for name, pin in claimed}
    assert by_pin[hardware.BUSY_PIN] == "InputDevice"
    assert "Button" not in {name for name, _ in claimed}
