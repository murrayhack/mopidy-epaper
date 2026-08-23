"""Screen state machine: decides what to draw, and when the panel sleeps.

Sits between the Mopidy frontend and the panel. It owns everything stateful
about the display — which screen is showing, where the menu selection is,
whether the content changed enough to warrant a full refresh, whether the panel
is locked, and how long playback has been stopped.

It never imports Mopidy. Library access arrives as two injected callables, so
the whole state machine is testable without a running Mopidy.
"""

import logging
import threading
import time

from . import layout, menu

logger = logging.getLogger(__name__)

# The full input vocabulary. This is the API contract, so it is declared in one
# place and stays stable.
ACTIONS = frozenset(
    {
        "up",
        "down",
        "select",
        "back",
        "home",
        "lock",
        "unlock",
        "toggle_lock",
        "wake",
        "toggle_shuffle",
        "toggle_repeat",
    }
)
IMPLEMENTED_ACTIONS = ACTIONS

_PANEL_ACTIONS = frozenset({"lock", "unlock", "toggle_lock", "wake"})
_OPTION_ACTIONS = frozenset({"toggle_shuffle", "toggle_repeat"})
# Pressing any of these from the now-playing screen opens the menu.
_OPENS_MENU = frozenset({"up", "down", "select", "home"})

ROOT_TITLE = "Menu"
LIBRARY_TITLE = "Library"
QUEUE_TITLE = "Queue"

#: Repeat cycles through these in order.
REPEAT_STATES = ("off", "all", "one")

_ROOT_LIBRARY = 0
_ROOT_QUEUE = 1


class Entry:
    """A menu row that is not a library ``Ref``.

    Duck-types the same attributes ``menu.render`` reads from a ``Ref``, plus
    ``value`` for settings rows and ``action`` for what selecting it does.
    """

    def __init__(self, name, type, action, value=None, uri=None, tlid=None):
        self.name = name
        self.type = type
        self.action = action
        self.value = value
        self.uri = uri
        self.tlid = tlid


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
    def __init__(self, config, display, player=None):
        """``player`` supplies everything that needs Mopidy.

        It is injected rather than imported so this whole state machine stays
        testable without a running Mopidy. See ``frontend.MopidyPlayer`` for
        the expected surface: ``browse``, ``play``, ``queue``, ``play_queued``,
        ``options`` and ``set_option``.
        """
        self._display = display
        self._sleep_after = config["sleep_after"]
        self._idle_screen = config["idle_screen"]
        self._menu_timeout = config.get("menu_timeout", 20)
        self._player = player

        self._lock = threading.RLock()
        self._locked = False
        self._idle_asleep = False
        self._stopped_since = None

        self._base_image = None
        self._last_content = None
        self._last_status = None
        self._last_playback = None

        self._stack = []
        self._last_input = 0.0

    @property
    def locked(self):
        with self._lock:
            return self._locked

    @property
    def in_menu(self):
        with self._lock:
            return bool(self._stack)

    def render_playback(self, track, state, position_ms, volume):
        """Draw the current playback state, or sleep if it has been idle."""
        with self._lock:
            self._last_playback = (track, state, position_ms, volume)

            if self._locked:
                return

            if self._stack:
                if not self._menu_timed_out():
                    # The browser owns the screen; playback ticks must not
                    # paint over it.
                    return
                self._leave_menu()

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

    def handle_action(self, action):
        """Apply an input action. Unknown ones are rejected before they reach here."""
        with self._lock:
            if self._locked and action not in ("unlock", "toggle_lock"):
                logger.debug("Panel is locked, ignoring %s", action)
                return

            self._last_input = time.monotonic()

            if action in _PANEL_ACTIONS:
                self._handle_panel_action(action)
                return

            if action in _OPTION_ACTIONS:
                self._toggle_option(action)
                return

            if not self._stack:
                if action in _OPENS_MENU:
                    self._enter_menu()
                # "back" from the now-playing screen has nowhere to go.
                return

            if action == "up":
                self._move(-1)
            elif action == "down":
                self._move(1)
            elif action == "select":
                self._select()
            elif action == "back":
                self._back()
            elif action == "home":
                self._leave_menu()

    def _handle_panel_action(self, action):
        if action == "lock":
            self.lock()
        elif action == "unlock":
            self.unlock()
        elif action == "toggle_lock":
            self.unlock() if self._locked else self.lock()
        elif action == "wake":
            self.wake()

    def lock(self):
        """Freeze the panel on its current frame and power the controller down.

        E-paper holds its image with no power, so the last frame drawn *is* the
        lock screen.
        """
        with self._lock:
            if self._locked:
                return
            self._locked = True
            if self._stack:
                frame = self._stack[-1]
                image = menu.render(
                    frame["title"], frame["items"], frame["selected"], frame["offset"]
                )
                self._display.show(image, force_full=True)
            elif self._last_playback is not None:
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
            self._last_input = time.monotonic()
            self._display.wake()
            self._base_image = None
            if self._stack:
                self._draw_menu()
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

    # -- browsing ---------------------------------------------------------

    def _menu_timed_out(self):
        if not self._menu_timeout:
            return False
        return time.monotonic() - self._last_input >= self._menu_timeout

    def _enter_menu(self):
        self._stack = []
        self._open_root()
        logger.debug("Entered the menu")

    def _leave_menu(self):
        if not self._stack:
            return
        self._stack = []
        # The menu screen is not a valid base for a partial refresh of the
        # now-playing screen, so force a full redraw of it.
        self._base_image = None
        logger.debug("Left the menu")

    # -- root -------------------------------------------------------------

    def _open_root(self):
        # The menu is always the same shape; only the cursor moves. It lands on
        # the queue while something is playing and the library otherwise, which
        # is usually what was wanted without making the button unpredictable.
        selected = _ROOT_QUEUE if self._is_playing() else _ROOT_LIBRARY
        self._push("root", ROOT_TITLE, self._root_items(), selected=selected)

    def _root_items(self):
        options = self._options()
        repeat = str(options.get("repeat", "off")).capitalize()
        return [
            Entry(LIBRARY_TITLE, "directory", "library"),
            Entry(QUEUE_TITLE, "directory", "queue"),
            Entry("Shuffle", "toggle", "shuffle", value="On" if options.get("shuffle") else "Off"),
            Entry("Repeat", "toggle", "repeat", value=repeat),
        ]

    def _is_playing(self):
        if self._last_playback is None:
            return False
        return layout._state_name(self._last_playback[1]) == "playing"

    def _options(self):
        if self._player is None:
            return {"shuffle": False, "repeat": "off"}
        try:
            return self._player.options()
        except Exception:
            logger.exception("Could not read playback options")
            return {"shuffle": False, "repeat": "off"}

    def _set_option(self, name, value):
        if self._player is not None:
            try:
                self._player.set_option(name, value)
            except Exception:
                logger.exception("Could not set %s to %r", name, value)
                return
        # The row displays the value, so it has to be rebuilt where it shows.
        if self._stack and self._stack[-1]["kind"] == "root":
            self._stack[-1]["items"] = self._root_items()
            self._draw_menu()

    def _toggle_option(self, action):
        options = self._options()
        if action == "toggle_shuffle":
            self._set_option("shuffle", not options.get("shuffle", False))
            return
        current = options.get("repeat", "off")
        index = REPEAT_STATES.index(current) if current in REPEAT_STATES else 0
        self._set_option("repeat", REPEAT_STATES[(index + 1) % len(REPEAT_STATES)])

    # -- library and queue ------------------------------------------------

    def _open_library(self, uri, title):
        self._push("library", title, self._browse_items(uri), uri=uri)

    def _browse_items(self, uri):
        if self._player is None:
            return []
        try:
            return list(self._player.browse(uri))
        except Exception:
            logger.exception("Could not browse %s", uri)
            return []

    def _open_queue(self):
        self._push("queue", QUEUE_TITLE, self._queue_items())

    def _queue_items(self):
        if self._player is None:
            return []
        try:
            queued = self._player.queue()
        except Exception:
            logger.exception("Could not read the queue")
            return []
        entries = []
        for tl_track in queued:
            track = getattr(tl_track, "track", None)
            entries.append(
                Entry(
                    getattr(track, "name", None) or "?",
                    "track",
                    "queued",
                    tlid=getattr(tl_track, "tlid", None),
                )
            )
        return entries

    # -- navigation -------------------------------------------------------

    def _push(self, kind, title, items, uri=None, selected=0):
        self._stack.append(
            {
                "kind": kind,
                "title": title,
                "items": items,
                "uri": uri,
                "selected": selected,
                "offset": menu.scroll_offset(len(items), selected, 0),
            }
        )
        self._draw_menu()

    def _back(self):
        if len(self._stack) > 1:
            self._stack.pop()
            self._reload_frame()
            self._draw_menu()
        else:
            self._leave_menu()

    def _reload_frame(self):
        """Re-read a frame that may have gone stale while we were deeper in."""
        frame = self._stack[-1]
        if frame["kind"] == "root":
            frame["items"] = self._root_items()
        elif frame["kind"] == "queue":
            frame["items"] = self._queue_items()
        count = len(frame["items"])
        frame["selected"] = min(frame["selected"], max(0, count - 1))
        frame["offset"] = menu.scroll_offset(count, frame["selected"], frame["offset"])

    def _move(self, delta):
        frame = self._stack[-1]
        count = len(frame["items"])
        if not count:
            return
        # Wrapping matters when there are only a couple of buttons to press.
        frame["selected"] = (frame["selected"] + delta) % count
        frame["offset"] = menu.scroll_offset(count, frame["selected"], frame["offset"])
        self._draw_menu()

    def _select(self):
        frame = self._stack[-1]
        items = frame["items"]
        if not items:
            return
        item = items[frame["selected"]]

        if frame["kind"] == "root":
            self._select_root(item)
        elif frame["kind"] == "queue":
            self._select_queued(item)
        else:
            self._select_library(item, items)

    def _select_root(self, item):
        if item.action == "library":
            self._open_library(None, LIBRARY_TITLE)
        elif item.action == "queue":
            self._open_queue()
        elif item.action == "shuffle":
            self._toggle_option("toggle_shuffle")
        elif item.action == "repeat":
            self._toggle_option("toggle_repeat")

    def _select_queued(self, item):
        if self._player is None or item.tlid is None:
            return
        try:
            self._player.play_queued(item.tlid)
        except Exception:
            logger.exception("Could not play queued track %s", item.tlid)
            return
        self._leave_menu()

    def _select_library(self, item, items):
        if menu.is_directory(item):
            self._open_library(item.uri, getattr(item, "name", None) or LIBRARY_TITLE)
            return
        if self._player is None:
            return
        # Queue every track alongside it, so picking one song out of an album
        # plays the album rather than stopping at the end of that track.
        uris = [i.uri for i in items if not menu.is_directory(i)]
        try:
            self._player.play(uris, item.uri)
        except Exception:
            logger.exception("Could not play %s", item.uri)
            return
        self._leave_menu()

    def _draw_menu(self):
        frame = self._stack[-1]
        image = menu.render(frame["title"], frame["items"], frame["selected"], frame["offset"])
        self._base_image = None
        self._display.show(image)

    # -- now playing ------------------------------------------------------

    def _go_idle(self):
        if self._idle_screen == "blank":
            self._display.show(layout.blank(), force_full=True)
        self._display.sleep()
        self._idle_asleep = True
        self._base_image = None
        logger.info("Panel idle for %ss, sleeping", self._sleep_after)

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
