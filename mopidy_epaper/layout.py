"""Rendering of the now-playing screen.

Pure Pillow: this module imports neither Mopidy nor any hardware driver, so it
can be exercised on any machine. ``track`` is duck-typed against
:class:`mopidy.models.Track` (``name``, ``artists``, ``length``).
"""

import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Native landscape size of the Waveshare 2.13" V4 panel. EPD.getbuffer()
# rotates this into the panel's portrait framebuffer for us.
WIDTH = 250
HEIGHT = 122

WHITE = 255
BLACK = 0

# Everything below this line is redrawn on a partial refresh; everything above
# it only changes when the track changes, which forces a full refresh anyway.
STATUS_TOP = 86

MARGIN = 6

VOLUME_GLYPH_WIDTH = 10

_BOLD_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

_font_cache = {}


def _load_font(bold, size):
    key = (bold, size)
    if key not in _font_cache:
        _font_cache[key] = _find_font(_BOLD_FONTS if bold else _REGULAR_FONTS, size)
    return _font_cache[key]


def _find_font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    logger.debug("No TrueType font found, falling back to the bitmap default")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10.1 has no sized default font.
        return ImageFont.load_default()


def blank():
    """An empty panel-sized image."""
    return Image.new("1", (WIDTH, HEIGHT), WHITE)


def _format_ms(milliseconds):
    """Format a duration as ``m:ss`` (or ``h:mm:ss`` past an hour)."""
    if milliseconds is None:
        return "--:--"
    seconds = max(0, int(milliseconds)) // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _truncate(draw, text, font, max_width):
    """Shorten ``text`` with an ellipsis until it fits within ``max_width``."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + ellipsis


def _artist_names(track):
    artists = getattr(track, "artists", None) or []
    names = [a.name for a in artists if getattr(a, "name", None)]
    return ", ".join(names)


def _state_name(state):
    """Normalise Mopidy's PlaybackState to a plain string.

    Mopidy has shipped this as both bare string constants and an enum; unwrap
    ``.value`` so the comparisons below hold either way.
    """
    return getattr(state, "value", state)


def render(
    track,
    state,
    position_ms,
    volume,
    elapsed_only=False,
    base=None,
    locked=False,
    number=None,
    total=None,
    muted=False,
):
    """Render the now-playing screen.

    With ``elapsed_only`` the status strip is redrawn onto ``base`` in place and
    that same image is returned, which is what feeds a partial refresh.
    Otherwise a fresh full-screen image is returned.
    """
    if elapsed_only and base is not None:
        draw = ImageDraw.Draw(base)
        draw.rectangle((0, STATUS_TOP, WIDTH, HEIGHT), fill=WHITE)
        _draw_status(draw, track, state, position_ms, volume, number, total, muted)
        return base

    image = blank()
    draw = ImageDraw.Draw(image)
    _draw_track(draw, track, reserve_right=locked)
    if locked:
        _draw_lock_glyph(draw, WIDTH - MARGIN - 11, 8)
    _draw_status(draw, track, state, position_ms, volume, number, total, muted)
    return image


def _draw_track(draw, track, reserve_right=False):
    if track is None:
        font = _load_font(bold=True, size=18)
        text = "Nothing playing"
        width = draw.textlength(text, font=font)
        draw.text(((WIDTH - width) / 2, 34), text, font=font, fill=BLACK)
        return

    usable = WIDTH - 2 * MARGIN
    # Keep the title clear of the padlock rather than letting them overlap.
    title_usable = usable - 18 if reserve_right else usable

    title_font = _load_font(bold=True, size=19)
    title = getattr(track, "name", None) or "Unknown track"
    draw.text(
        (MARGIN, 8), _truncate(draw, title, title_font, title_usable), font=title_font, fill=BLACK
    )

    artist_font = _load_font(bold=False, size=15)
    artist = _artist_names(track) or "Unknown artist"
    draw.text(
        (MARGIN, 36), _truncate(draw, artist, artist_font, usable), font=artist_font, fill=BLACK
    )

    album = getattr(getattr(track, "album", None), "name", None)
    if album:
        album_font = _load_font(bold=False, size=12)
        draw.text(
            (MARGIN, 58),
            _truncate(draw, album, album_font, usable),
            font=album_font,
            fill=BLACK,
        )


def _draw_status(draw, track, state, position_ms, volume, number=None, total=None, muted=False):
    length_ms = getattr(track, "length", None)

    bar_top = STATUS_TOP + 2
    bar_bottom = bar_top + 8
    bar_left = MARGIN
    bar_right = WIDTH - MARGIN
    draw.rectangle((bar_left, bar_top, bar_right, bar_bottom), outline=BLACK, fill=WHITE)

    if length_ms and position_ms is not None and length_ms > 0:
        fraction = min(1.0, max(0.0, position_ms / length_ms))
        filled = int((bar_right - bar_left - 2) * fraction)
        if filled > 0:
            draw.rectangle(
                (bar_left + 1, bar_top + 1, bar_left + 1 + filled, bar_bottom - 1), fill=BLACK
            )

    text_font = _load_font(bold=False, size=13)
    text_y = bar_bottom + 5

    _draw_state_glyph(draw, MARGIN, text_y + 2, state)

    times = f"{_format_ms(position_ms)} / {_format_ms(length_ms)}"
    draw.text((MARGIN + 16, text_y), times, font=text_font, fill=BLACK)

    right_edge = WIDTH - MARGIN
    if volume is not None:
        vol_text = str(volume)
        vol_width = draw.textlength(vol_text, font=text_font)
        draw.text((right_edge - vol_width, text_y), vol_text, font=text_font, fill=BLACK)
        glyph_x = right_edge - vol_width - 4 - VOLUME_GLYPH_WIDTH
        _draw_volume_glyph(draw, glyph_x, text_y + 2, muted=muted)
        right_edge = glyph_x - 10

    if number and total:
        # Where you are in the queue. Placed left of the volume rather than
        # centred, because a long elapsed/total pair reaches past the middle of
        # the panel and would collide with it.
        counter = f"{number}/{total}"
        counter_width = draw.textlength(counter, font=text_font)
        draw.text((right_edge - counter_width, text_y), counter, font=text_font, fill=BLACK)


def _draw_state_glyph(draw, x, y, state, size=9):
    """Draw play/pause/stop as primitives, so no font glyph coverage is needed."""
    state = _state_name(state)
    if state == "playing":
        draw.polygon([(x, y), (x, y + size), (x + size, y + size / 2)], fill=BLACK)
    elif state == "paused":
        bar = max(2, size // 3)
        draw.rectangle((x, y, x + bar, y + size), fill=BLACK)
        draw.rectangle((x + size - bar, y, x + size, y + size), fill=BLACK)
    else:
        draw.rectangle((x, y, x + size, y + size), fill=BLACK)


def _draw_volume_glyph(draw, x, y, size=VOLUME_GLYPH_WIDTH, muted=False):
    """A speaker, drawn as primitives like the other glyphs.

    Muting is shown as a slash through it rather than by hiding the level, so
    you can still see what the volume will return to.
    """
    step = size / 3
    # Body, then the cone flaring out to the right.
    draw.rectangle((x, y + step, x + step, y + 2 * step), fill=BLACK)
    draw.polygon(
        [(x + step, y + step), (x + size, y), (x + size, y + size), (x + step, y + 2 * step)],
        fill=BLACK,
    )
    if muted:
        draw.line((x - 1, y + size + 1, x + size + 1, y - 1), fill=BLACK, width=1)


def _draw_lock_glyph(draw, x, y, width=11, height=15):
    """A padlock, drawn as primitives for the same reason as the state glyph."""
    body_top = y + height // 2
    draw.rectangle((x, body_top, x + width, y + height), fill=BLACK)
    shackle_inset = 2
    draw.arc(
        (x + shackle_inset, y, x + width - shackle_inset, body_top + 3),
        start=180,
        end=360,
        fill=BLACK,
    )
