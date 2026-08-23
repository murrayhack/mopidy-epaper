"""Owns the panel: pushes images to it and manages its power state.

This module knows nothing about tracks or screens. Callers decide *what* to
draw and whether the content changed; this decides *how* to push it — full or
partial refresh — and keeps the panel's sleep state straight.
"""

import logging
import threading

logger = logging.getLogger(__name__)

DEFAULT_DUMMY_PATH = "/tmp/mopidy-epaper.png"


class EpaperDisplay:
    """Pushes images to the e-paper panel.

    A full refresh is slow and flashes the whole panel; a partial one is quick
    and silent but accumulates ghosting. Callers ask for a full refresh when
    the content genuinely changed, and one is forced anyway every
    ``full_refresh_every`` partials to clear that ghosting.
    """

    def __init__(self, config):
        self._driver_name = config["driver"]
        self._full_refresh_every = config["full_refresh_every"]
        self._lock = threading.Lock()
        self._partials = 0
        self._epd = None
        self._dummy_path = None
        self._asleep = False
        # The first push has nothing on screen to diff against.
        self._needs_full = True

        if self._driver_name == "dummy":
            self._dummy_path = config.get("dummy_output_path") or DEFAULT_DUMMY_PATH
            logger.info("e-paper dummy driver rendering to %s", self._dummy_path)
        elif self._driver_name == "epd2in13_v4":
            # Imported lazily: epdconfig runs hardware detection at import time
            # and raises on anything that is not a Raspberry Pi.
            from .drivers import epd2in13_V4

            self._epd = epd2in13_V4.EPD()
            # No Clear() here: the first show() does a full refresh that
            # overwrites the whole panel anyway, and a full refresh costs
            # seconds of flashing on a Pi Zero.
            self._epd.init()
            logger.info('Initialised Waveshare 2.13" V4 e-paper display')
        else:
            raise ValueError(f"Unknown e-paper driver: {self._driver_name!r}")

    @property
    def asleep(self):
        with self._lock:
            return self._asleep

    def show(self, image, force_full=False):
        """Push ``image`` to the panel, waking it first if it was asleep."""
        with self._lock:
            self._wake_locked()

            if force_full or self._needs_full or self._partials >= self._full_refresh_every:
                self._partials = 0
                self._needs_full = False
                self._show_full(image)
            else:
                self._partials += 1
                self._show_partial(image)

    def sleep(self):
        """Power down the controller. The last frame stays on the panel."""
        with self._lock:
            if self._asleep:
                return
            self._asleep = True
            # Waking re-initialises the controller, which loses the RAM buffers
            # partial refreshes diff against.
            self._needs_full = True
            if self._epd is None:
                logger.info("Dummy panel asleep")
                return
            try:
                self._epd.sleep()
                logger.info("Panel asleep")
            except Exception:
                logger.exception("Failed to put the e-paper display to sleep")

    def wake(self):
        with self._lock:
            self._wake_locked()

    def _wake_locked(self):
        if not self._asleep:
            return
        self._asleep = False
        self._needs_full = True
        if self._epd is None:
            return
        # init() re-runs module_init(), which reopens SPI. epdconfig's
        # module_exit() leaves the gpiozero pin objects open, so they survive
        # the round trip.
        self._epd.init()
        logger.info("Panel awake")

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
                self._asleep = True
            except Exception:
                logger.exception("Failed to shut down the e-paper display cleanly")
