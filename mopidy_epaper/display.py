"""Owns the panel and decides between full and partial refreshes."""

import logging
import threading

from . import layout

logger = logging.getLogger(__name__)

DEFAULT_DUMMY_PATH = "/tmp/mopidy-epaper.png"


def _content_key(track):
    """Identify what the non-status part of the screen shows.

    Keyed on more than the URI so that a track whose metadata is filled in
    after playback starts still triggers the full refresh needed to redraw the
    title area.
    """
    if track is None:
        return None
    return (getattr(track, "uri", None), getattr(track, "name", None))


class EpaperDisplay:
    """Drives the e-paper panel from playback state.

    A full refresh (slow, flashes the whole panel) happens on the first render,
    on every track change, and once every ``full_refresh_every`` partials to
    clear accumulated ghosting. Everything in between is a partial refresh of
    the status strip only.
    """

    def __init__(self, config):
        self._driver_name = config["driver"]
        self._full_refresh_every = config["full_refresh_every"]
        self._lock = threading.Lock()
        self._base_image = None
        self._last_key = None
        self._partials = 0
        self._epd = None
        self._dummy_path = None

        if self._driver_name == "dummy":
            self._dummy_path = config.get("dummy_output_path") or DEFAULT_DUMMY_PATH
            logger.info("e-paper dummy driver rendering to %s", self._dummy_path)
        elif self._driver_name == "epd2in13_v4":
            # Imported lazily: epdconfig runs hardware detection at import time
            # and raises on anything that is not a Raspberry Pi.
            from .drivers import epd2in13_V4

            self._epd = epd2in13_V4.EPD()
            # No Clear() here: the first update() does a full refresh that
            # overwrites the whole panel anyway, and a full refresh costs
            # seconds of flashing on a Pi Zero.
            self._epd.init()
            logger.info("Initialised Waveshare 2.13\" V4 e-paper display")
        else:
            raise ValueError(f"Unknown e-paper driver: {self._driver_name!r}")

    def update(self, track, state, position_ms, volume):
        """Render the current playback state to the panel."""
        with self._lock:
            key = _content_key(track)
            needs_full = (
                self._base_image is None
                or key != self._last_key
                or self._partials >= self._full_refresh_every
            )

            if needs_full:
                image = layout.render(track, state, position_ms, volume)
                self._base_image = image
                self._last_key = key
                self._partials = 0
                self._show_full(image)
            else:
                image = layout.render(
                    track, state, position_ms, volume, elapsed_only=True, base=self._base_image
                )
                self._partials += 1
                self._show_partial(image)

    def _show_full(self, image):
        if self._epd is None:
            self._save_dummy(image, "full")
            return
        # Re-init to restore the full-refresh waveform: displayPartial leaves
        # the controller configured for partial updates.
        self._epd.init()
        # Seeds both the current and previous RAM buffers, so the partial
        # refreshes that follow diff against what is actually on screen.
        self._epd.displayPartBaseImage(self._epd.getbuffer(image))

    def _show_partial(self, image):
        if self._epd is None:
            self._save_dummy(image, "partial")
            return
        self._epd.displayPartial(self._epd.getbuffer(image))

    def _save_dummy(self, image, refresh_type):
        try:
            image.save(self._dummy_path)
            logger.debug("Wrote %s refresh to %s", refresh_type, self._dummy_path)
        except OSError:
            logger.exception("Could not write dummy output to %s", self._dummy_path)

    def close(self):
        """Blank the panel and put it to sleep. Never raises."""
        with self._lock:
            if self._epd is None:
                return
            try:
                self._epd.init()
                self._epd.Clear(0xFF)
                self._epd.sleep()
            except Exception:
                logger.exception("Failed to shut down the e-paper display cleanly")
