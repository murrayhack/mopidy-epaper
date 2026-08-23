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


def make_ui(display, sleep_after=300, idle_screen="keep"):
    return ui.Ui({"sleep_after": sleep_after, "idle_screen": idle_screen}, display)


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
