"""A ten-band EQ through ALSA, when one is configured.

Optional, like the battery: most builds have no equalizer and the menu simply
does not offer one.

Driven with ``amixer`` rather than a binding, so the dependency list does not
grow for a feature that shells out twice per adjustment. It also means this
works against anything exposing ALSA mixer controls, not only alsaequal.

Nothing here knows about Mopidy or GStreamer. The EQ sits below Mopidy in the
ALSA chain: Mopidy plays into the equalizer device and neither knows nor cares
that it is there, which is what keeps this free of Mopidy's internals — there
is no API to its running pipeline.
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

#: amixer against a local device. Slow means wrong, not busy.
TIMEOUT = 2.0

#: alsaequal's controls run 0-100 with **66** as flat, not 50: the scale is
#: asymmetric, with more cut available than boost. Resetting a band to "no
#: effect" means 66, and centring it would quietly cut.
FLAT = 66

#: Points per press. 100 across the range would be 100 presses a band; this
#: gives 20, which is about as coarse as is still useful.
STEP = 5

_CONTROL = re.compile(r"^Simple mixer control '([^']+)'")
_LEVEL = re.compile(r"Playback \d+ \[(\d+)%\]")


class Equalizer:
    """The bands of an ALSA mixer device, read and written with ``amixer``."""

    def __init__(self, device, timeout=TIMEOUT):
        self._device = device
        self._timeout = timeout

    @property
    def enabled(self):
        return bool(self._device)

    def bands(self):
        """``[(name, level)]`` in the order the device lists them.

        Empty if there is no device or it cannot be read, which the menu reads
        as "offer no equalizer" rather than as an error.
        """
        if not self._device:
            return []
        output = self._run("scontents")
        return [] if output is None else parse_bands(output)

    def set_band(self, name, level):
        """Clamp and apply ``level``. Returns what was actually set."""
        level = max(0, min(100, int(level)))
        self._run("set", name, f"{level}%")
        return level

    def _run(self, *args):
        try:
            completed = subprocess.run(
                ["amixer", "-D", self._device, *args],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("amixer -D %s %s failed: %s", self._device, args[0], exc)
            return None
        return completed.stdout


def parse_bands(output):
    """Pull ``[(name, level)]`` out of ``amixer scontents``.

    A control's name and its level are on different lines, so the name is held
    until a level turns up. Anything without a playback level — a switch, say —
    is skipped rather than reported at zero.
    """
    bands = []
    name = None
    for line in output.splitlines():
        control = _CONTROL.match(line)
        if control:
            name = control.group(1)
            continue
        if name is None:
            continue
        level = _LEVEL.search(line)
        if level:
            bands.append((name, int(level.group(1))))
            name = None
    return bands
