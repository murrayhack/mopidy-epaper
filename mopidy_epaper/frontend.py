"""Mopidy frontend actor driving the e-paper display."""

import logging
import threading

import pykka

from mopidy import core

from .display import EpaperDisplay

logger = logging.getLogger(__name__)


class EpaperFrontend(pykka.ThreadingActor, core.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config["epaper"]
        self.core = core
        self.display = None
        self._stop_event = threading.Event()
        self._ticker = None

    def on_start(self):
        try:
            self.display = EpaperDisplay(self.config)
        except Exception:
            # A missing panel should disable this frontend, not take Mopidy down.
            logger.exception("Could not initialise the e-paper display; frontend disabled")
            self.stop()
            return

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
        """Refresh the progress bar periodically while playing."""
        interval = self.config["update_interval"]
        while not self._stop_event.wait(interval):
            try:
                if self.core.playback.get_state().get() == core.PlaybackState.PLAYING:
                    self._refresh()
            except Exception:
                logger.exception("e-paper tick failed")

    def _refresh(self):
        if self.display is None:
            return

        try:
            track = self.core.playback.get_current_track().get()
            state = self.core.playback.get_state().get()
            # Read the real position every time rather than extrapolating, so
            # the progress bar cannot drift out of sync.
            position = self.core.playback.get_time_position().get()
            volume = self.core.mixer.get_volume().get()
        except Exception:
            logger.exception("Could not read playback state")
            return

        try:
            self.display.update(track, state, position, volume)
        except Exception:
            logger.exception("Could not update the e-paper display")

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
