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

        self.ui = Ui(self.config, self.display)
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

    def lock(self):
        if self.ui is not None:
            self.ui.lock()

    def unlock(self):
        if self.ui is not None:
            self.ui.unlock()
            self._refresh()

    def wake(self):
        if self.ui is not None:
            self.ui.wake()
            self._refresh()

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
