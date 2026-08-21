"""Screen state machine: decides what to draw, and when the panel sleeps.

Sits between the Mopidy frontend and the panel. It owns everything stateful
about the display — what is currently on screen, whether the content changed
enough to warrant a full refresh, whether the panel is locked, and how long
playback has been stopped.
"""

import logging
import threading
import time

from . import layout

logger = logging.getLogger(__name__)


def content_key(track):
    """Identify what the non-status part of the screen shows.

    Keyed on more than the URI so that a track whose metadata is filled in
    after playback starts still triggers the full refresh needed to redraw the
    title area.
    """
    if track is None:
        return None
    return (getattr(track, "uri", None), getattr(track, "name", None))


def status_key(state, position_ms, volume):
    """Identify what the status strip shows, at the resolution it displays."""
    seconds = None if position_ms is None else int(position_ms) // 1000
    return (layout._state_name(state), seconds, volume)


class Ui:
    def __init__(self, config, display):
        self._display = display
        self._sleep_after = config["sleep_after"]
        self._idle_screen = config["idle_screen"]

        self._lock = threading.RLock()
        self._locked = False
        self._idle_asleep = False
        self._stopped_since = None

        self._base_image = None
        self._last_content = None
        self._last_status = None
        self._last_playback = None

    @property
    def locked(self):
        with self._lock:
            return self._locked

    def render_playback(self, track, state, position_ms, volume):
        """Draw the current playback state, or sleep if it has been idle."""
        with self._lock:
            self._last_playback = (track, state, position_ms, volume)

            if self._locked:
                return

            playing = layout._state_name(state) == "playing"
            now = time.monotonic()

            if playing:
                self._stopped_since = None
                if self._idle_asleep:
                    self._idle_asleep = False
                    self._display.wake()
                    # Nothing on the panel to diff against after a wake.
                    self._base_image = None
            else:
                if self._idle_asleep:
                    return
                if self._stopped_since is None:
                    self._stopped_since = now
                elif self._sleep_after and now - self._stopped_since >= self._sleep_after:
                    self._go_idle()
                    return

            self._draw_playback(track, state, position_ms, volume)

    def lock(self):
        """Freeze the panel on its current frame and power the controller down.

        E-paper holds its image with no power, so the last frame drawn *is* the
        lock screen.
        """
        with self._lock:
            if self._locked:
                return
            self._locked = True
            if self._last_playback is not None:
                track, state, position_ms, volume = self._last_playback
                image = layout.render(track, state, position_ms, volume, locked=True)
                self._base_image = image
                self._display.show(image, force_full=True)
            self._display.sleep()
            logger.info("Panel locked")

    def unlock(self):
        with self._lock:
            if not self._locked:
                return
            self._locked = False
            # Unlocking restarts the idle timer from scratch: without this, a
            # panel that was already idle-asleep when it got locked would stay
            # flagged asleep and never redraw.
            self._idle_asleep = False
            self._stopped_since = None
            self._display.wake()
            self._base_image = None
            logger.info("Panel unlocked")

    def wake(self):
        """Wake the panel without changing lock state."""
        with self._lock:
            if self._locked:
                return
            self._idle_asleep = False
            self._stopped_since = time.monotonic()
            self._display.wake()
            self._base_image = None

    def _go_idle(self):
        if self._idle_screen == "blank":
            self._display.show(layout.blank(), force_full=True)
        self._display.sleep()
        self._idle_asleep = True
        self._base_image = None
        logger.debug("Panel asleep after %ss stopped", self._sleep_after)

    def _draw_playback(self, track, state, position_ms, volume):
        content = content_key(track)
        status = status_key(state, position_ms, volume)

        if self._base_image is None or content != self._last_content:
            image = layout.render(track, state, position_ms, volume, locked=self._locked)
            self._base_image = image
            self._last_content = content
            self._last_status = status
            self._display.show(image, force_full=True)
            return

        if status == self._last_status:
            # Nothing visible changed. Skip the refresh entirely rather than
            # burning a partial update — and its ghosting budget — on an
            # identical frame, which is what every tick while paused would do.
            return

        image = layout.render(
            track,
            state,
            position_ms,
            volume,
            elapsed_only=True,
            base=self._base_image,
            locked=self._locked,
        )
        self._last_status = status
        self._display.show(image)
