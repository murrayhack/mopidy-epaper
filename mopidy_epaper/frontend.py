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

    def snapshot(self):
        """Everything the now-playing screen needs, in one round trip.

        Each proxy call returns a future immediately, so every request is sent
        before any is waited on. They queue on the same core actor either way;
        waiting between sends only adds a round trip each time.
        """
        track = self._core.playback.get_current_track()
        state = self._core.playback.get_state()
        # Read the real position every time rather than extrapolating, so the
        # progress bar cannot drift.
        position = self._core.playback.get_time_position()
        volume = self._core.mixer.get_volume()
        muted = self._core.mixer.get_mute()
        index = self._core.tracklist.index()
        total = self._core.tracklist.get_length()

        number = index.get()
        return Playback(
            track=track.get(),
            state=state.get(),
            position_ms=position.get(),
            volume=volume.get(),
            number=None if number is None else number + 1,
            total=total.get(),
            muted=muted.get(),
        )

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
        self._playback_dirty = threading.Event()

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
        the idle-sleep timer. Once the panel is asleep or locked there is
        nothing a tick can do, and playback events wake it, so the tick stops
        costing anything until then.
        """
        interval = self.config["update_interval"]
        while not self._stop_event.wait(interval):
            try:
                if self.ui.dormant:
                    continue
                self._invalidate_playback()
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
            if not self._render_wanted.wait(timeout=5):
                continue
            self._render_wanted.clear()
            if self._stop_event.is_set():
                break
            if coalesce:
                # Let anything already on its way land before drawing, so the
                # refresh shows where things ended up.
                time.sleep(coalesce)
                self._render_wanted.clear()
            try:
                if self._playback_dirty.is_set():
                    self._playback_dirty.clear()
                    self._refresh()
                self.ui.flush()
            except Exception:
                logger.exception("e-paper render failed")

    def _invalidate_playback(self):
        """Ask the render thread to re-read and redraw.

        Reading and drawing happen on that one thread, which keeps them atomic
        without a lock, keeps the panel's seconds-long refreshes off the actor,
        and collapses the several events a single track change fires into one
        read and one draw.
        """
        self._playback_dirty.set()
        self._render_wanted.set()

    def _refresh(self):
        if self.ui is None:
            return
        try:
            playback = self.player.snapshot()
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
            self._invalidate_playback()

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
        self._invalidate_playback()

    def track_playback_ended(self, tl_track, time_position):
        self._invalidate_playback()

    def track_playback_paused(self, tl_track, time_position):
        self._invalidate_playback()

    def track_playback_resumed(self, tl_track, time_position):
        self._invalidate_playback()

    def playback_state_changed(self, old_state, new_state):
        self._invalidate_playback()

    def volume_changed(self, volume):
        self._invalidate_playback()

    def mute_changed(self, mute):
        self._invalidate_playback()
