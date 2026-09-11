"""The PiSugar reader, against a real Unix socket.

A thread serving a socket rather than a mocked one: the parsing, the timeout
and the connection handling are the whole of this module, and mocking the
socket would test none of them.
"""

import contextlib
import logging
import os
import shutil
import socket
import tempfile
import threading

import pytest

from mopidy_epaper.battery import Battery


class FakeServer:
    """Answers one line per connection, as pisugar-server does.

    Routed by request, because the reader asks two different questions and a
    server that answered both the same way would let a broken parse pass.
    """

    DEFAULTS = {
        b"get battery": "battery: 28.754677",
        b"get battery_power_plugged": "battery_power_plugged: false",
    }

    def __init__(self, directory, reply=None, replies=None, accept=True):
        self.path = f"{directory}/s"
        self.replies = dict(self.DEFAULTS)
        if replies:
            self.replies.update(replies)
        if reply is not None:
            self.replies[b"get battery"] = reply
        self.requests = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(4)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        if accept:
            self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                request = conn.recv(64)
                self.requests.append(request)
                reply = self.replies.get(request.strip())
                if reply is not None:
                    conn.sendall(reply.encode())

    def close(self):
        self._stop.set()
        self._sock.close()
        # Closing the socket leaves the file behind, and the next bind to the
        # same path fails with "Address already in use".
        with contextlib.suppress(OSError):
            os.unlink(self.path)


@pytest.fixture
def sockdir():
    """A short directory, because AF_UNIX paths have a hard length limit.

    Around 104 bytes on macOS, and pytest's tmp_path is comfortably longer
    than that, so binding under it fails with "AF_UNIX path too long".
    """
    directory = tempfile.mkdtemp(prefix="pe", dir="/tmp")
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def server(sockdir):
    fake = FakeServer(sockdir)
    yield fake
    fake.close()


def test_reads_and_rounds_the_charge(server):
    assert Battery(server.path).read().percent == 30


def test_asks_for_the_battery(server):
    Battery(server.path).read()

    assert server.requests[0] == b"get battery\n"


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("battery: 0", 0),
        ("battery: 4.9", 0),
        ("battery: 5.1", 10),
        ("battery: 28.754677", 30),
        ("battery: 100", 100),
        # Out of range readings are clamped rather than drawn off the end of
        # the glyph.
        ("battery: 104", 100),
        ("battery: -3", 0),
    ],
)
def test_rounding_and_clamping(sockdir, reply, expected):
    server = FakeServer(sockdir, reply=reply)
    try:
        assert Battery(server.path).read().percent == expected
    finally:
        server.close()


def test_jitter_does_not_move_the_displayed_value(sockdir):
    """The reason for rounding at all.

    Consecutive real readings seconds apart: 31.35, 29.88, 29.92, 31.08. Each
    one drawn raw would be a separate e-paper refresh showing a different
    number, for a battery that has not meaningfully moved.
    """
    for reading in ("31.354862", "29.881325", "29.924656", "31.07734"):
        server = FakeServer(sockdir, reply=f"battery: {reading}")
        try:
            assert Battery(server.path).read().percent == 30
        finally:
            server.close()


def test_no_socket_configured_is_not_an_error():
    """Most builds are on mains with no PiSugar at all."""
    assert Battery("").read() is None
    assert Battery(None).read() is None


def test_an_unreachable_socket_returns_none(sockdir):
    assert Battery(f"{sockdir}/absent").read() is None


def test_an_unreachable_socket_is_quiet_until_it_has_answered_once(sockdir, caplog):
    """Same rule as the panel poll: do not train the reader to ignore the log.

    A panel with no PiSugar would otherwise warn every few seconds, forever,
    about hardware that was never fitted.
    """
    missing = f"{sockdir}/absent"

    with caplog.at_level(logging.DEBUG, logger="mopidy_epaper.battery"):
        assert Battery(missing).read() is None
    assert [r.levelname for r in caplog.records] == ["DEBUG"]


def test_a_socket_that_stops_answering_does_warn(sockdir, caplog):
    """Once it has worked, a failure is real news."""
    server = FakeServer(sockdir)
    battery = Battery(server.path)
    assert battery.read().percent == 30
    server.close()

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="mopidy_epaper.battery"):
        assert battery.read() is None

    assert any(r.levelname == "WARNING" for r in caplog.records)


@pytest.mark.parametrize("reply", ["", "garbage", "battery: not-a-number", "no-colon 42"])
def test_an_unparseable_reply_returns_none(sockdir, reply):
    server = FakeServer(sockdir, reply=reply)
    try:
        assert Battery(server.path).read() is None
    finally:
        server.close()


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("battery_power_plugged: true", True),
        ("battery_power_plugged: false", False),
        # Anything unreadable is reported as not plugged: a missing bolt is a
        # smaller lie than one stuck on.
        ("battery_power_plugged: maybe", False),
        ("garbage", False),
        ("", False),
    ],
)
def test_plugged_state(sockdir, reply, expected):
    server = FakeServer(sockdir, replies={b"get battery_power_plugged": reply})
    try:
        assert Battery(server.path).read().plugged is expected
    finally:
        server.close()


def test_both_questions_are_asked(sockdir):
    server = FakeServer(sockdir)
    try:
        Battery(server.path).read()
    finally:
        server.close()

    assert server.requests == [b"get battery\n", b"get battery_power_plugged\n"]


def test_an_unreadable_plug_state_does_not_lose_the_charge(sockdir):
    """The charge is the useful half; do not throw it away over the bolt."""
    server = FakeServer(sockdir, replies={b"get battery_power_plugged": "nonsense"})
    try:
        charge = Battery(server.path).read()
    finally:
        server.close()

    assert charge.percent == 30
    assert charge.plugged is False
