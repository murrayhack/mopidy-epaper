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
