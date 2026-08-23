"""Mopidy frontend actor driving the e-paper display.

Mopidy glue only: it turns playback events and a periodic tick into calls on
:class:`~mopidy_epaper.ui.Ui`, which owns all the screen state.
"""

import logging
import threading

import pykka

from mopidy import core

from .display import EpaperDisplay
from .ui import Ui

logger = logging.getLogger(__name__)


class MopidyPlayer:
    """Everything the UI needs from Mopidy, behind one small surface.

    Injected into :class:`~mopidy_epaper.ui.Ui` rather than imported by it, so
    the screen state machine stays testable without a running Mopidy.
    """

    def __init__(self, core):
        self._core = core

    def browse(self, uri):
        """Library contents. ``None`` is the root."""
        return self._core.library.browse(uri).get()

    def play(self, uris, start_uri):
        """Replace the queue with ``uris`` and start at ``start_uri``."""
        self._core.tracklist.clear().get()
        self._core.tracklist.add(uris=uris).get()
        # Match on URI rather than index: add() silently drops anything it
        # cannot resolve, so positions do not necessarily line up.
        target = self._find_tlid(start_uri)
        if target is not None:
            self._core.playback.play(tlid=target).get()
        else:
            self._core.playback.play().get()

    def _find_tlid(self, uri):
        for tl_track in self._core.tracklist.get_tl_tracks().get():
            if tl_track.track.uri == uri:
                return tl_track.tlid
        return None

    def queue(self):
        return self._core.tracklist.get_tl_tracks().get()

    def play_queued(self, tlid):
        self._core.playback.play(tlid=tlid).get()

    def options(self):
        repeat = self._core.tracklist.get_repeat().get()
        single = self._core.tracklist.get_single().get()
        return {
            "shuffle": self._core.tracklist.get_random().get(),
            # Mopidy spells repeat-one as repeat plus single.
            "repeat": ("one" if single else "all") if repeat else "off",
        }

    def set_option(self, name, value):
        if name == "shuffle":
            self._core.tracklist.set_random(bool(value)).get()
        elif name == "repeat":
            self._core.tracklist.set_repeat(value != "off").get()
            self._core.tracklist.set_single(value == "one").get()


class EpaperFrontend(pykka.ThreadingActor, core.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config["epaper"]
        self.core = core
        self.display = None
        self.ui = None
        self._stop_event = threading.Event()
        self._ticker = None
        # Reading playback state and rendering it must be atomic; see _refresh.
        self._refresh_lock = threading.Lock()

    def on_start(self):
        try:
            self.display = EpaperDisplay(self.config)
        except Exception:
            # A missing panel should disable this frontend, not take Mopidy down.
            logger.exception("Could not initialise the e-paper display; frontend disabled")
            self.stop()
            return

        self.ui = Ui(self.config, self.display, player=MopidyPlayer(self.core))
        self._refresh()
        self._ticker = threading.Thread(
            target=self._tick_loop, name="EpaperTicker", daemon=True
        )
        self._ticker.start()

    def on_stop(self):
        self._stop_event.set()
        if self._ticker is not None:
            self._ticker.join(timeout=5)
        if self.display is not None:
            self.display.close()

    def _tick_loop(self):
        """Tick regardless of playback state.

        The UI needs a heartbeat even while stopped, otherwise nothing drives
        the idle-sleep timer. It skips redundant redraws itself.
        """
        interval = self.config["update_interval"]
        while not self._stop_event.wait(interval):
            try:
                self._refresh()
            except Exception:
                logger.exception("e-paper tick failed")

    def _refresh(self):
        if self.ui is None:
            return

        # Both the actor thread and the ticker call this. Reading state and
        # rendering it has to be one atomic step: otherwise each thread takes
        # its own snapshot and whichever renders second can be carrying the
        # older one, which is enough to wake a panel that was just put to
        # sleep, or to walk the progress bar backwards.
        with self._refresh_lock:
            try:
                track = self.core.playback.get_current_track().get()
                state = self.core.playback.get_state().get()
                # Read the real position every time rather than extrapolating,
                # so the progress bar cannot drift out of sync.
                position = self.core.playback.get_time_position().get()
                volume = self.core.mixer.get_volume().get()
            except Exception:
                logger.exception("Could not read playback state")
                return

            try:
                self.ui.render_playback(track, state, position, volume)
            except Exception:
                logger.exception("Could not update the e-paper display")

    def handle_input(self, action):
        """Apply an input action, from the HTTP API or anywhere else."""
        if self.ui is None:
            return
        try:
            self.ui.handle_action(action)
        except Exception:
            logger.exception("Input action %s failed", action)
            return
        # Locking deliberately leaves the panel asleep, and the browser owns
        # the screen while it is open. Otherwise show the result straight away
        # rather than waiting for the next tick.
        if not self.ui.locked and not self.ui.in_menu:
            self._refresh()

    def input_state(self):
        if self.ui is None or self.display is None:
            return {"locked": False, "asleep": False, "in_menu": False, "running": False}
        return {
            "locked": self.ui.locked,
            "asleep": self.display.asleep,
            "in_menu": self.ui.in_menu,
            "running": True,
        }

    def track_playback_started(self, tl_track):
        self._refresh()

    def track_playback_ended(self, tl_track, time_position):
        self._refresh()

    def track_playback_paused(self, tl_track, time_position):
        self._refresh()

    def track_playback_resumed(self, tl_track, time_position):
        self._refresh()

    def playback_state_changed(self, old_state, new_state):
        self._refresh()

    def volume_changed(self, volume):
        self._refresh()

    def mute_changed(self, mute):
        self._refresh()
