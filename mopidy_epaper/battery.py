"""Charge from a PiSugar power manager, when one is fitted.

Optional by design. The panel runs on mains with no battery at all, so an
unreachable socket is a quiet no-op rather than an error.

Read over the power manager's Unix socket rather than the I2C registers
directly. That keeps the register layout of a particular PiSugar model out of
this extension, and leaves the kernel's RTC driver as the only thing touching
that bus — a second writer the kernel does not know about is how you get an
occasional wrong clock and no error anywhere.
"""

import logging
import socket

logger = logging.getLogger(__name__)

#: A local socket, so a slow reply means something is wrong rather than busy.
TIMEOUT = 0.5

#: Readings jitter by a point or two, because the estimate comes from battery
#: voltage, which sags under load and recovers. Rounding makes the displayed
#: value stable — which matters more here than on a screen that redraws
#: cheaply, since every change costs an e-paper refresh.
BUCKET = 10


class Battery:
    """Charge from a PiSugar server, rounded so it does not flicker."""

    def __init__(self, socket_path, bucket=BUCKET):
        self._socket_path = socket_path
        self._bucket = bucket
        self._seen = False

    def percent(self):
        """Charge 0-100 rounded to ``bucket``, or None if it cannot be read."""
        if not self._socket_path:
            return None

        try:
            reply = self._ask("get battery")
        except OSError as exc:
            # Quiet until it has answered once. A panel with no PiSugar has no
            # socket to reach, and warning every few seconds about hardware
            # that was never fitted trains the reader to ignore the log.
            log = logger.warning if self._seen else logger.debug
            log("Could not read battery: %s", exc)
            return None

        value = _parse(reply)
        if value is None:
            logger.debug("Unexpected battery reply: %r", reply)
            return None

        self._seen = True
        value = max(0.0, min(100.0, value))
        return int(round(value / self._bucket) * self._bucket)

    def _ask(self, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT)
            sock.connect(self._socket_path)
            sock.sendall(f"{command}\n".encode())
            return sock.recv(64).decode("utf-8", "replace")


def _parse(reply):
    """``"battery: 28.754677"`` to ``28.754677``."""
    _, separator, value = reply.partition(":")
    if not separator:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None
