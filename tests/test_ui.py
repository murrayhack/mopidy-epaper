import time

import pytest

from mopidy_epaper import ui


class FakeArtist:
    def __init__(self, name):
        self.name = name


class FakeTrack:
    def __init__(self, uri="fake:track:1", name="A Track", length=240000):
        self.uri = uri
        self.name = name
        self.artists = [FakeArtist("An Artist")]
        self.length = length
        self.album = None


class _Ref:
    """Duck-types mopidy.models.Ref."""

    def __init__(self, uri, name, type="track"):
        self.uri = uri
        self.name = name
        self.type = type


class FakeDisplay:
    """Records what the UI asked of the panel, without any hardware."""

    def __init__(self):
        self.shows = []  # force_full flag per push
        self.sleeps = 0
        self.wakes = 0
        self.asleep = False

    def show(self, image, force_full=False):
        self.asleep = False
        self.shows.append(force_full)

    def sleep(self):
        self.asleep = True
        self.sleeps += 1

    def wake(self):
        self.asleep = False
        self.wakes += 1


LIBRARY = {
    None: [
        _Ref("local:directory?type=album", "Albums", "directory"),
        _Ref("local:directory?type=artist", "Artists", "directory"),
    ],
    "local:directory?type=album": [_Ref("local:album:1", "An Album", "directory")],
    "local:album:1": [
        _Ref("local:track:1", "One"),
        _Ref("local:track:2", "Two"),
        _Ref("local:track:3", "Three"),
    ],
}


class _TlTrack:
    def __init__(self, tlid, name):
        self.tlid = tlid
        self.track = _Ref(f"local:track:{tlid}", name)


class FakePlayer:
    """Stands in for frontend.MopidyPlayer."""

    def __init__(self, library=None, queue=None, browse_error=False):
        self.library = LIBRARY if library is None else library
        self._queue = queue if queue is not None else []
        self._options = {"shuffle": False, "repeat": "off"}
        self.browse_error = browse_error
        self.played = []
        self.played_tlids = []

    def browse(self, uri):
        if self.browse_error:
            raise RuntimeError("library is unavailable")
        return self.library.get(uri, [])

    def play(self, uris, start_uri):
        self.played.append((uris, start_uri))

    def queue(self):
        return self._queue

    def play_queued(self, tlid):
        self.played_tlids.append(tlid)

    def options(self):
        return dict(self._options)

    def set_option(self, name, value):
        self._options[name] = value


def make_ui(display, sleep_after=300, idle_screen="keep", menu_timeout=20, player=None):
    config = {
        "sleep_after": sleep_after,
        "idle_screen": idle_screen,
        "menu_timeout": menu_timeout,
    }
    return ui.Ui(config, display, player=FakePlayer() if player is None else player)


def open_library(screen):
    """home, then select the Library row."""
    screen.handle_action("home")
    screen._stack[-1]["selected"] = 0
    screen.handle_action("select")


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def test_first_render_is_a_full_refresh():
    display = FakeDisplay()
    make_ui(display).render_playback(FakeTrack(), "playing", 0, 80)

    assert display.shows == [True]


def test_progress_advancing_uses_a_partial_refresh():
    display = FakeDisplay()
    screen = make_ui(display)
    track = FakeTrack()

    screen.render_playback(track, "playing", 0, 80)
    screen.render_playback(track, "playing", 5000, 80)

    assert display.shows == [True, False]


def test_identical_state_skips_the_refresh_entirely():
    display = FakeDisplay()
    screen = make_ui(display)
    track = FakeTrack()

    screen.render_playback(track, "playing", 5000, 80)
    screen.render_playback(track, "playing", 5000, 80)

    assert display.shows == [True]


def test_sub_second_progress_change_skips_the_refresh():
    display = FakeDisplay()
    screen = make_ui(display)
    track = FakeTrack()

    screen.render_playback(track, "playing", 5000, 80)
    screen.render_playback(track, "playing", 5400, 80)

    assert display.shows == [True]


def test_track_change_forces_a_full_refresh():
    display = FakeDisplay()
    screen = make_ui(display)

    screen.render_playback(FakeTrack(uri="a", name="One"), "playing", 0, 80)
    screen.render_playback(FakeTrack(uri="b", name="Two"), "playing", 0, 80)

    assert display.shows == [True, True]


def test_volume_change_redraws_the_status_strip():
    display = FakeDisplay()
    screen = make_ui(display)
    track = FakeTrack()

    screen.render_playback(track, "playing", 5000, 80)
    screen.render_playback(track, "playing", 5000, 40)

    assert display.shows == [True, False]


def test_lock_draws_a_final_frame_then_sleeps():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.lock()

    assert screen.locked
    assert display.shows == [True, True]
    assert display.sleeps == 1
    assert display.asleep


def test_locked_panel_ignores_playback_updates():
    display = FakeDisplay()
    screen = make_ui(display)
    track = FakeTrack()
    screen.render_playback(track, "playing", 0, 80)
    screen.lock()
    shows_before = len(display.shows)

    screen.render_playback(track, "playing", 60000, 80)

    assert len(display.shows) == shows_before
    assert display.asleep


def test_unlock_wakes_the_panel():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)
    screen.lock()

    screen.unlock()

    assert not screen.locked
    assert display.wakes == 1


def test_unlocked_panel_redraws_in_full_after_waking():
    display = FakeDisplay()
    screen = make_ui(display)
    track = FakeTrack()
    screen.render_playback(track, "playing", 0, 80)
    screen.lock()
    screen.unlock()

    screen.render_playback(track, "playing", 60000, 80)

    # Nothing survives on the panel to diff against after a wake.
    assert display.shows[-1] is True


def test_lock_is_idempotent():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.lock()
    screen.lock()

    assert display.sleeps == 1


def test_panel_sleeps_once_stopped_for_long_enough(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60)
    track = FakeTrack()

    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)

    assert display.sleeps == 1
    assert display.asleep


def test_panel_stays_awake_before_the_idle_timeout(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60)
    track = FakeTrack()

    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 30
    screen.render_playback(track, "stopped", 0, 80)

    assert display.sleeps == 0


def test_sleep_after_zero_disables_idle_sleep(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=0)
    track = FakeTrack()

    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 100000
    screen.render_playback(track, "stopped", 0, 80)

    assert display.sleeps == 0


def test_idle_panel_is_not_redrawn_while_asleep(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60)
    track = FakeTrack()
    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)
    shows_before = len(display.shows)

    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)

    assert len(display.shows) == shows_before
    assert display.sleeps == 1


def test_playback_wakes_an_idle_panel(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60)
    track = FakeTrack()
    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)

    screen.render_playback(track, "playing", 0, 80)

    assert display.wakes == 1
    assert not display.asleep
    assert display.shows[-1] is True


def test_blank_idle_screen_clears_the_panel_before_sleeping(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60, idle_screen="blank")
    track = FakeTrack()

    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)

    assert display.shows[-1] is True
    assert display.sleeps == 1


def test_content_key_distinguishes_tracks():
    assert ui.content_key(None) is None
    assert ui.content_key(FakeTrack(uri="a")) != ui.content_key(FakeTrack(uri="b"))
    # A URI whose metadata arrives later must still count as a change.
    assert ui.content_key(FakeTrack(uri="a", name="?")) != ui.content_key(
        FakeTrack(uri="a", name="Real Title")
    )


def test_unlocking_an_idle_asleep_panel_resumes_drawing(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60)
    track = FakeTrack()
    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)
    assert display.asleep

    screen.lock()
    screen.unlock()
    shows_before = len(display.shows)
    screen.render_playback(track, "stopped", 0, 80)

    # Still stopped, but the idle timer restarted, so it must draw rather than
    # stay stuck behind the asleep flag.
    assert len(display.shows) == shows_before + 1


def test_toggle_lock_locks_an_unlocked_panel():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.handle_action("toggle_lock")

    assert screen.locked
    assert display.asleep


def test_toggle_lock_unlocks_a_locked_panel():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)
    screen.handle_action("toggle_lock")

    screen.handle_action("toggle_lock")

    assert not screen.locked
    assert display.wakes == 1


def test_lock_and_unlock_actions_dispatch():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.handle_action("lock")
    assert screen.locked

    screen.handle_action("unlock")
    assert not screen.locked


def test_wake_action_wakes_an_idle_panel(clock):
    display = FakeDisplay()
    screen = make_ui(display, sleep_after=60)
    track = FakeTrack()
    screen.render_playback(track, "stopped", 0, 80)
    clock[0] += 61
    screen.render_playback(track, "stopped", 0, 80)
    assert display.asleep

    screen.handle_action("wake")

    assert display.wakes == 1
    assert not display.asleep


def test_wake_action_does_nothing_while_locked():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)
    screen.handle_action("lock")

    screen.handle_action("wake")

    assert display.asleep
    assert display.wakes == 0


def test_implemented_actions_are_a_subset_of_the_vocabulary():
    assert ui.IMPLEMENTED_ACTIONS <= ui.ACTIONS


def test_back_from_now_playing_does_nothing():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)
    shows_before = len(display.shows)

    screen.handle_action("back")

    assert not screen.in_menu
    assert len(display.shows) == shows_before


def test_navigation_from_now_playing_opens_the_menu():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.handle_action("down")

    assert screen.in_menu


def test_root_menu_has_a_fixed_shape():
    display = FakeDisplay()
    screen = make_ui(display)

    screen.handle_action("home")

    assert screen._stack[-1]["title"] == ui.ROOT_TITLE
    assert [i.name for i in screen._stack[-1]["items"]] == [
        "Library",
        "Queue",
        "Shuffle",
        "Repeat",
    ]


def test_cursor_starts_on_library_when_idle():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "stopped", 0, 80)

    screen.handle_action("home")

    assert screen._stack[-1]["selected"] == 0


def test_cursor_starts_on_queue_while_playing():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.handle_action("home")

    assert screen._stack[-1]["selected"] == 1


def test_root_menu_shape_is_the_same_either_way():
    playing = make_ui(FakeDisplay())
    playing.render_playback(FakeTrack(), "playing", 0, 80)
    playing.handle_action("home")

    idle = make_ui(FakeDisplay())
    idle.render_playback(FakeTrack(), "stopped", 0, 80)
    idle.handle_action("home")

    assert [i.name for i in playing._stack[-1]["items"]] == [
        i.name for i in idle._stack[-1]["items"]
    ]


def test_selecting_library_opens_the_library():
    display = FakeDisplay()
    screen = make_ui(display)

    open_library(screen)

    assert screen._stack[-1]["title"] == ui.LIBRARY_TITLE
    assert [i.name for i in screen._stack[-1]["items"]] == ["Albums", "Artists"]


def test_selection_moves_and_wraps():
    display = FakeDisplay()
    screen = make_ui(display)
    open_library(screen)

    screen.handle_action("down")
    assert screen._stack[-1]["selected"] == 1

    # Only two entries here, so this wraps back to the top.
    screen.handle_action("down")
    assert screen._stack[-1]["selected"] == 0

    screen.handle_action("up")
    assert screen._stack[-1]["selected"] == 1


def test_select_descends_into_a_directory():
    display = FakeDisplay()
    screen = make_ui(display)
    open_library(screen)

    screen.handle_action("select")

    assert screen._stack[-1]["title"] == "Albums"


def test_back_pops_one_level():
    display = FakeDisplay()
    screen = make_ui(display)
    open_library(screen)
    screen.handle_action("select")

    screen.handle_action("back")

    assert screen._stack[-1]["title"] == ui.LIBRARY_TITLE


def test_back_from_the_library_returns_to_the_root():
    display = FakeDisplay()
    screen = make_ui(display)
    open_library(screen)

    screen.handle_action("back")

    assert screen._stack[-1]["title"] == ui.ROOT_TITLE


def test_back_at_the_root_leaves_the_menu():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")

    screen.handle_action("back")

    assert not screen.in_menu


def test_selecting_a_track_queues_its_siblings_and_plays_it():
    display = FakeDisplay()
    player = FakePlayer()
    screen = make_ui(display, player=player)
    open_library(screen)
    screen.handle_action("select")  # Albums
    screen.handle_action("select")  # An Album
    screen.handle_action("down")  # second track

    screen.handle_action("select")

    assert player.played == [
        (["local:track:1", "local:track:2", "local:track:3"], "local:track:2")
    ]
    assert not screen.in_menu


def test_queue_view_lists_the_tracklist():
    display = FakeDisplay()
    player = FakePlayer(queue=[_TlTrack(1, "First"), _TlTrack(2, "Second")])
    screen = make_ui(display, player=player)
    screen.handle_action("home")
    screen._stack[-1]["selected"] = 1

    screen.handle_action("select")

    assert screen._stack[-1]["title"] == ui.QUEUE_TITLE
    assert [i.name for i in screen._stack[-1]["items"]] == ["First", "Second"]


def test_selecting_a_queued_track_plays_it():
    display = FakeDisplay()
    player = FakePlayer(queue=[_TlTrack(7, "First"), _TlTrack(9, "Second")])
    screen = make_ui(display, player=player)
    screen.handle_action("home")
    screen._stack[-1]["selected"] = 1
    screen.handle_action("select")  # into the queue
    screen.handle_action("down")

    screen.handle_action("select")

    assert player.played_tlids == [9]
    assert not screen.in_menu


def test_shuffle_row_shows_and_toggles_its_value():
    display = FakeDisplay()
    player = FakePlayer()
    screen = make_ui(display, player=player)
    screen.handle_action("home")
    screen._stack[-1]["selected"] = 2
    assert screen._stack[-1]["items"][2].value == "Off"

    screen.handle_action("select")

    assert player.options()["shuffle"] is True
    # The row is rebuilt in place rather than navigating anywhere.
    assert screen._stack[-1]["items"][2].value == "On"
    assert screen._stack[-1]["title"] == ui.ROOT_TITLE


def test_repeat_cycles_through_three_states():
    display = FakeDisplay()
    player = FakePlayer()
    screen = make_ui(display, player=player)
    screen.handle_action("home")
    screen._stack[-1]["selected"] = 3

    screen.handle_action("select")
    assert player.options()["repeat"] == "all"

    screen.handle_action("select")
    assert player.options()["repeat"] == "one"

    screen.handle_action("select")
    assert player.options()["repeat"] == "off"


def test_toggle_shuffle_action_works_outside_the_menu():
    display = FakeDisplay()
    player = FakePlayer()
    screen = make_ui(display, player=player)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.handle_action("toggle_shuffle")

    assert player.options()["shuffle"] is True
    assert not screen.in_menu


def test_toggle_repeat_action_works_outside_the_menu():
    display = FakeDisplay()
    player = FakePlayer()
    screen = make_ui(display, player=player)

    screen.handle_action("toggle_repeat")

    assert player.options()["repeat"] == "all"


def test_returning_to_the_root_refreshes_its_values():
    display = FakeDisplay()
    player = FakePlayer()
    screen = make_ui(display, player=player)
    open_library(screen)
    player.set_option("shuffle", True)

    screen.handle_action("back")

    assert screen._stack[-1]["items"][2].value == "On"


def test_playback_does_not_paint_over_an_open_menu():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")
    shows_before = len(display.shows)

    screen.render_playback(FakeTrack(), "playing", 30000, 80)

    assert len(display.shows) == shows_before
    assert screen.in_menu


def test_menu_closes_itself_after_the_timeout(clock):
    display = FakeDisplay()
    screen = make_ui(display, menu_timeout=20)
    screen.handle_action("home")

    clock[0] += 21
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    assert not screen.in_menu
    # And the now-playing screen is redrawn in full over the menu.
    assert display.shows[-1] is True


def test_menu_stays_open_before_the_timeout(clock):
    display = FakeDisplay()
    screen = make_ui(display, menu_timeout=20)
    screen.handle_action("home")

    clock[0] += 10
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    assert screen.in_menu


def test_menu_timeout_zero_keeps_the_menu_open(clock):
    display = FakeDisplay()
    screen = make_ui(display, menu_timeout=0)
    screen.handle_action("home")

    clock[0] += 100000
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    assert screen.in_menu


def test_locked_panel_ignores_navigation():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)
    screen.handle_action("lock")

    screen.handle_action("home")

    assert not screen.in_menu
    assert display.asleep


def test_empty_listing_does_not_raise_on_select():
    display = FakeDisplay()
    screen = make_ui(display, player=FakePlayer(library={}))

    open_library(screen)
    screen.handle_action("select")
    screen.handle_action("down")

    assert screen.in_menu


def test_browse_failure_leaves_an_empty_listing_rather_than_raising():
    display = FakeDisplay()
    screen = make_ui(display, player=FakePlayer(browse_error=True))

    open_library(screen)

    assert screen.in_menu
    assert screen._stack[-1]["items"] == []
