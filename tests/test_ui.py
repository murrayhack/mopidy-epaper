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


def fake_browse(uri):
    return LIBRARY.get(uri, [])


class PlayRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, uris, start_uri):
        self.calls.append((uris, start_uri))


def make_ui(
    display,
    sleep_after=300,
    idle_screen="keep",
    menu_timeout=20,
    browse=fake_browse,
    play=None,
):
    config = {
        "sleep_after": sleep_after,
        "idle_screen": idle_screen,
        "menu_timeout": menu_timeout,
    }
    return ui.Ui(config, display, browse=browse, play=play)


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


def test_navigation_from_now_playing_opens_the_browser():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    screen.handle_action("down")

    assert screen.in_menu


def test_browser_starts_at_the_library_root():
    display = FakeDisplay()
    screen = make_ui(display)

    screen.handle_action("home")

    assert screen.in_menu
    assert screen._stack[-1]["title"] == ui.ROOT_TITLE
    assert [i.name for i in screen._stack[-1]["items"]] == ["Albums", "Artists"]


def test_selection_moves_and_wraps():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")

    screen.handle_action("down")
    assert screen._stack[-1]["selected"] == 1

    # Only two entries at the root, so this wraps back to the top.
    screen.handle_action("down")
    assert screen._stack[-1]["selected"] == 0

    screen.handle_action("up")
    assert screen._stack[-1]["selected"] == 1


def test_select_descends_into_a_directory():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")

    screen.handle_action("select")

    assert screen._stack[-1]["title"] == "Albums"
    assert len(screen._stack) == 2


def test_back_pops_one_level():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")
    screen.handle_action("select")

    screen.handle_action("back")

    assert screen.in_menu
    assert len(screen._stack) == 1
    assert screen._stack[-1]["title"] == ui.ROOT_TITLE


def test_back_at_the_root_leaves_the_browser():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")

    screen.handle_action("back")

    assert not screen.in_menu


def test_selecting_a_track_queues_its_siblings_and_plays_it():
    display = FakeDisplay()
    play = PlayRecorder()
    screen = make_ui(display, play=play)
    screen.handle_action("home")
    screen.handle_action("select")  # Albums
    screen.handle_action("select")  # An Album
    screen.handle_action("down")  # second track

    screen.handle_action("select")

    assert play.calls == [
        (["local:track:1", "local:track:2", "local:track:3"], "local:track:2")
    ]
    # Picking a track hands the screen back to now-playing.
    assert not screen.in_menu


def test_playback_does_not_paint_over_an_open_browser():
    display = FakeDisplay()
    screen = make_ui(display)
    screen.handle_action("home")
    shows_before = len(display.shows)

    screen.render_playback(FakeTrack(), "playing", 30000, 80)

    assert len(display.shows) == shows_before
    assert screen.in_menu


def test_browser_closes_itself_after_the_timeout(clock):
    display = FakeDisplay()
    screen = make_ui(display, menu_timeout=20)
    screen.handle_action("home")

    clock[0] += 21
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    assert not screen.in_menu
    # And the now-playing screen is redrawn in full over the menu.
    assert display.shows[-1] is True


def test_browser_stays_open_before_the_timeout(clock):
    display = FakeDisplay()
    screen = make_ui(display, menu_timeout=20)
    screen.handle_action("home")

    clock[0] += 10
    screen.render_playback(FakeTrack(), "playing", 0, 80)

    assert screen.in_menu


def test_menu_timeout_zero_keeps_the_browser_open(clock):
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


def test_empty_directory_does_not_raise_on_select():
    display = FakeDisplay()
    screen = make_ui(display, browse=lambda uri: [])

    screen.handle_action("home")
    screen.handle_action("select")
    screen.handle_action("down")

    assert screen.in_menu


def test_browse_failure_leaves_an_empty_menu_rather_than_raising():
    def broken(uri):
        raise RuntimeError("library is unavailable")

    display = FakeDisplay()
    screen = make_ui(display, browse=broken)

    screen.handle_action("home")

    assert screen.in_menu
    assert screen._stack[-1]["items"] == []
