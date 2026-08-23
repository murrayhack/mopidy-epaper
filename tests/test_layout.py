from PIL import Image, ImageDraw

from mopidy_epaper import layout


class FakeArtist:
    def __init__(self, name):
        self.name = name


class FakeAlbum:
    def __init__(self, name):
        self.name = name


class FakeTrack:
    """Duck-types mopidy.models.Track, so the tests need no running Mopidy."""

    def __init__(self, name="A Track", artists=("An Artist",), length=240000, album=None):
        self.uri = "fake:track:1"
        self.name = name
        self.artists = [FakeArtist(a) for a in artists]
        self.length = length
        self.album = FakeAlbum(album) if album else None


def test_render_returns_panel_sized_1bit_image():
    image = layout.render(FakeTrack(), "playing", 30000, 80)

    assert image.size == (layout.WIDTH, layout.HEIGHT)
    assert image.mode == "1"


def test_render_without_track_does_not_raise():
    image = layout.render(None, "stopped", 0, None)

    assert image.size == (layout.WIDTH, layout.HEIGHT)


def test_render_with_album_does_not_raise():
    image = layout.render(FakeTrack(album="An Album"), "paused", 1000, 50)

    assert image.mode == "1"


def test_elapsed_only_mutates_base_in_place():
    base = layout.render(FakeTrack(), "playing", 0, 80)

    result = layout.render(FakeTrack(), "playing", 120000, 80, elapsed_only=True, base=base)

    assert result is base


def test_elapsed_only_leaves_track_area_untouched():
    track = FakeTrack(name="Distinctive Title")
    base = layout.render(track, "playing", 0, 80)
    before = base.crop((0, 0, layout.WIDTH, layout.STATUS_TOP)).tobytes()

    layout.render(track, "playing", 120000, 80, elapsed_only=True, base=base)
    after = base.crop((0, 0, layout.WIDTH, layout.STATUS_TOP)).tobytes()

    assert before == after


def test_elapsed_only_redraws_status_strip():
    track = FakeTrack()
    base = layout.render(track, "playing", 0, 80)
    before = base.crop((0, layout.STATUS_TOP, layout.WIDTH, layout.HEIGHT)).tobytes()

    layout.render(track, "playing", 120000, 80, elapsed_only=True, base=base)
    after = base.crop((0, layout.STATUS_TOP, layout.WIDTH, layout.HEIGHT)).tobytes()

    assert before != after


def test_state_name_unwraps_enum_like_values():
    class EnumLike:
        value = "playing"

    assert layout._state_name("playing") == "playing"
    assert layout._state_name(EnumLike()) == "playing"


def test_enum_like_state_renders_same_glyph_as_plain_string():
    class EnumLike:
        value = "playing"

    track = FakeTrack()
    from_string = layout.render(track, "playing", 1000, 50)
    from_enum = layout.render(track, EnumLike(), 1000, 50)

    assert from_string.tobytes() == from_enum.tobytes()


def test_format_ms():
    assert layout._format_ms(None) == "--:--"
    assert layout._format_ms(0) == "0:00"
    assert layout._format_ms(-500) == "0:00"
    assert layout._format_ms(9000) == "0:09"
    assert layout._format_ms(65000) == "1:05"
    assert layout._format_ms(3725000) == "1:02:05"


def test_truncate_leaves_short_text_alone():
    draw = ImageDraw.Draw(Image.new("1", (layout.WIDTH, layout.HEIGHT), layout.WHITE))
    font = layout._load_font(bold=False, size=13)

    assert layout._truncate(draw, "short", font, 200) == "short"


def test_truncate_ellipsizes_long_text():
    draw = ImageDraw.Draw(Image.new("1", (layout.WIDTH, layout.HEIGHT), layout.WHITE))
    font = layout._load_font(bold=False, size=13)
    text = "An extremely long track title that will never fit on this panel"

    result = layout._truncate(draw, text, font, 100)

    assert result.endswith("…")
    assert len(result) < len(text)
    assert draw.textlength(result, font=font) <= 100


def test_locked_render_differs_from_unlocked():
    track = FakeTrack()
    unlocked = layout.render(track, "playing", 1000, 50)
    locked = layout.render(track, "playing", 1000, 50, locked=True)

    assert unlocked.tobytes() != locked.tobytes()


def test_locked_render_is_panel_sized():
    image = layout.render(FakeTrack(), "playing", 1000, 50, locked=True)

    assert image.size == (layout.WIDTH, layout.HEIGHT)
    assert image.mode == "1"


def test_locked_render_without_track_does_not_raise():
    image = layout.render(None, "stopped", 0, None, locked=True)

    assert image.size == (layout.WIDTH, layout.HEIGHT)


def test_blank_is_an_empty_panel_sized_image():
    image = layout.blank()

    assert image.size == (layout.WIDTH, layout.HEIGHT)
    assert image.mode == "1"
    assert set(image.getdata()) == {layout.WHITE}


def test_queue_position_renders():
    image = layout.render(FakeTrack(), "playing", 1000, 50, number=3, total=12)

    assert image.size == (layout.WIDTH, layout.HEIGHT)
    assert image.mode == "1"


def test_queue_position_changes_the_status_strip():
    without = layout.render(FakeTrack(), "playing", 1000, 50)
    with_counter = layout.render(FakeTrack(), "playing", 1000, 50, number=3, total=12)

    assert without.tobytes() != with_counter.tobytes()


def test_queue_position_renders_without_a_volume():
    image = layout.render(FakeTrack(), "playing", 1000, None, number=3, total=12)

    assert image.mode == "1"


def test_queue_position_is_skipped_when_unknown():
    plain = layout.render(FakeTrack(), "playing", 1000, 50)
    no_number = layout.render(FakeTrack(), "playing", 1000, 50, number=None, total=12)

    assert plain.tobytes() == no_number.tobytes()


def test_long_duration_and_queue_position_do_not_overlap():
    # A track over an hour gives the longest possible elapsed/total pair; the
    # counter sits right of it and must still fit.
    long_track = FakeTrack(length=4500000)
    image = layout.render(long_track, "playing", 3725000, 100, number=12, total=34)

    assert image.size == (layout.WIDTH, layout.HEIGHT)
