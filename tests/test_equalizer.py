"""The ALSA equalizer control, with amixer stubbed.

The parser is tested against output captured verbatim from a Pi running
alsaequal, rather than against what the documentation claims the format is.
"""

import subprocess

import pytest

from mopidy_epaper import equalizer
from mopidy_epaper.equalizer import Equalizer, in_output_path, parse_bands

# Captured from `amixer -D equal scontents` on the target hardware.
REAL_OUTPUT = """Simple mixer control '00. 31 Hz',0
  Capabilities: pvolume
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 100
  Mono:
  Front Left: Playback 66 [66%]
  Front Right: Playback 66 [66%]
Simple mixer control '01. 63 Hz',0
  Capabilities: pvolume
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 100
  Mono:
  Front Left: Playback 80 [80%]
  Front Right: Playback 80 [80%]
Simple mixer control '09. 16 kHz',0
  Capabilities: pvolume
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 100
  Mono:
  Front Left: Playback 40 [40%]
  Front Right: Playback 40 [40%]
"""


def test_parses_real_amixer_output():
    assert parse_bands(REAL_OUTPUT) == [
        ("00. 31 Hz", 66),
        ("01. 63 Hz", 80),
        ("09. 16 kHz", 40),
    ]


def test_a_control_without_a_playback_level_is_skipped():
    """A switch has no level, and must not be reported as a band at zero."""
    output = REAL_OUTPUT + """Simple mixer control 'Some Switch',0
  Capabilities: pswitch
  Playback channels: Front Left - Front Right
  Mono:
  Front Left: Playback [on]
"""

    assert [name for name, _ in parse_bands(output)] == [
        "00. 31 Hz",
        "01. 63 Hz",
        "09. 16 kHz",
    ]


def test_nonsense_output_yields_no_bands():
    assert parse_bands("") == []
    assert parse_bands("amixer: Mixer attach equal error") == []


class FakeRun:
    """Stands in for subprocess.run, recording the argv it was handed."""

    def __init__(self, stdout=REAL_OUTPUT, raises=None):
        self.stdout = stdout
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")


@pytest.fixture
def run(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(equalizer.subprocess, "run", fake)
    return fake


def test_no_device_means_no_equalizer(run):
    eq = Equalizer("")

    assert eq.enabled is False
    assert eq.bands() == []
    assert run.calls == []  # and nothing is executed


def test_bands_are_read_from_the_configured_device(run):
    assert Equalizer("equal").bands()[0] == ("00. 31 Hz", 66)

    assert run.calls == [["amixer", "-D", "equal", "scontents"]]


def test_setting_a_band(run):
    Equalizer("equal").set_band("00. 31 Hz", 80)

    assert run.calls == [["amixer", "-D", "equal", "set", "00. 31 Hz", "80%"]]


@pytest.mark.parametrize(
    "asked,applied",
    [(150, 100), (-20, 0), (0, 0), (100, 100), (66, 66)],
)
def test_levels_are_clamped(run, asked, applied):
    """The menu adds a step at a time and would otherwise walk off the end."""
    assert Equalizer("equal").set_band("00. 31 Hz", asked) == applied

    assert run.calls[0][-1] == f"{applied}%"


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("amixer"),
        subprocess.TimeoutExpired("amixer", 2.0),
        subprocess.CalledProcessError(1, "amixer"),
    ],
)
def test_a_failing_amixer_is_not_fatal(monkeypatch, failure):
    """A broken equalizer must not take the menu down with it."""
    monkeypatch.setattr(equalizer.subprocess, "run", FakeRun(raises=failure))

    assert Equalizer("equal").bands() == []
    assert Equalizer("equal").set_band("00. 31 Hz", 80) == 80


def test_flat_is_not_the_midpoint():
    """66, not 50. The scale is asymmetric, with more cut than boost.

    Pinned because centring a band looks like the obvious way to reset it and
    would quietly cut instead.
    """
    assert equalizer.FLAT == 66


def test_reset_flattens_every_band(run):
    assert Equalizer("equal").reset() == 3

    sets = [call for call in run.calls if "set" in call]
    assert [call[-2:] for call in sets] == [
        ["00. 31 Hz", "66%"],
        ["01. 63 Hz", "66%"],
        ["09. 16 kHz", "66%"],
    ]


def test_reset_with_no_device_does_nothing(run):
    assert Equalizer("").reset() == 0
    assert run.calls == []


@pytest.mark.parametrize(
    "output,routed",
    [
        ("alsasink device=equal", True),
        ("volume volume=0.25 ! alsasink device=equal", True),
        ('alsasink device="equal"', True),
        ("alsasink device=plug:equal", True),
        # The plain sink: an equalizer is configured but nothing goes through it.
        ("alsasink device=sysdefault:CARD=sndrpihifiberry", False),
        # A GStreamer element, not an ALSA device. The word boundary is what
        # keeps this from counting as routing.
        ("audioconvert ! equalizer-10bands band0=4.0 ! alsasink", False),
        ("", False),
    ],
)
def test_whether_the_device_is_in_the_output_path(output, routed):
    assert in_output_path("equal", output) is routed


def test_no_device_is_never_routed():
    """Nothing configured, nothing to check -- the caller skips the warning."""
    assert in_output_path("", "alsasink device=equal") is False
    assert in_output_path(None, "alsasink device=equal") is False
