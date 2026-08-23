"""Mopidy frontend actor driving the e-paper display.

Mopidy glue only: it turns playback events and a periodic tick into calls on
:class:`~mopidy_epaper.ui.Ui`, which owns all the screen state.
"""

import logging
import threading
import time

import pykka

from mopidy import core

from .display import EpaperDisplay
from .playback import Playback
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

    def playlists(self):
        """Saved playlists. Separate from library browsing in Mopidy."""
        return self._core.playlists.as_list().get()

    def playlist_tracks(self, uri):
        playlist = self._core.playlists.lookup(uri).get()
        return list(playlist.tracks) if playlist else []

    def queue(self):
        return self._core.tracklist.get_tl_tracks().get()

    def position(self):
        """Where the current track sits in the queue, as 1-based ``(n, total)``."""
        index = self._core.tracklist.index().get()
        total = self._core.tracklist.get_length().get()
        return (None if index is None else index + 1, total)

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
        self.player = None
        self._stop_event = threading.Event()
        self._ticker = None
        self._renderer = None
        self._render_wanted = threading.Event()
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

        self.player = MopidyPlayer(self.core)
        self.ui = Ui(
            self.config, self.display, player=self.player, on_dirty=self._render_wanted.set
        )
        self._refresh()
        self._ticker = threading.Thread(
            target=self._tick_loop, name="EpaperTicker", daemon=True
        )
        self._ticker.start()
        self._renderer = threading.Thread(
            target=self._render_loop, name="EpaperRenderer", daemon=True
        )
        self._renderer.start()

    def on_stop(self):
        self._stop_event.set()
        self._render_wanted.set()
        for thread in (self._ticker, self._renderer):
            if thread is not None:
                thread.join(timeout=5)
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

    def _render_loop(self):
        """Draw pending menu changes, off the actor thread.

        Two things fall out of this. A burst of presses collapses into one
        refresh instead of the panel stepping through every position; and a
        slow full refresh no longer blocks the actor, so Mopidy's events do not
        queue up behind the SPI bus.
        """
        coalesce = self.config["input_coalesce_ms"] / 1000
        while not self._stop_event.is_set():
            if not self._render_wanted.wait(timeout=1):
                continue
            self._render_wanted.clear()
            if self._stop_event.is_set():
                break
            if coalesce:
                # Let anything already on its way land before drawing, so the
                # refresh shows where the cursor ended up.
                time.sleep(coalesce)
                self._render_wanted.clear()
            try:
                self.ui.flush()
            except Exception:
                logger.exception("e-paper render failed")

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
                number, total = self.player.position()
                playback = Playback(
                    track=self.core.playback.get_current_track().get(),
                    state=self.core.playback.get_state().get(),
                    # Read the real position every time rather than
                    # extrapolating, so the progress bar cannot drift.
                    position_ms=self.core.playback.get_time_position().get(),
                    volume=self.core.mixer.get_volume().get(),
                    number=number,
                    total=total,
                    muted=self.core.mixer.get_mute().get(),
                )
            except Exception:
                logger.exception("Could not read playback state")
                return

            try:
                self.ui.render_playback(playback)
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
