"""Rendering of the library browser screen.

Pure Pillow, like :mod:`~mopidy_epaper.layout`: no Mopidy import, so it stays
testable anywhere. Items are duck-typed against :class:`mopidy.models.Ref` —
they need a ``name`` and a ``type``.
"""

from PIL import ImageDraw

from .layout import (
    BLACK,
    HEIGHT,
    MARGIN,
    WHITE,
    WIDTH,
    _load_font,
    _truncate,
    blank,
)

HEADER_HEIGHT = 22
ROW_HEIGHT = 19
ROWS = (HEIGHT - HEADER_HEIGHT) // ROW_HEIGHT


#: Row types that are acted on in place rather than descended into.
LEAF_TYPES = ("track", "toggle")


def is_directory(item):
    """Whether a row leads somewhere rather than doing something."""
    return getattr(item, "type", None) not in LEAF_TYPES


def scroll_offset(count, selected, previous=0, rows=ROWS):
    """The first visible row that keeps ``selected`` on screen.

    Pure function so the scrolling can be tested without rendering anything.
    """
    if count <= rows:
        return 0
    offset = max(0, min(previous, count - rows))
    if selected < offset:
        offset = selected
    elif selected >= offset + rows:
        offset = selected - rows + 1
    return max(0, min(offset, count - rows))


def render(title, items, selected=0, offset=0):
    image = blank()
    draw = ImageDraw.Draw(image)

    _draw_header(draw, title, items, selected)

    if not items:
        font = _load_font(bold=False, size=14)
        text = "Empty"
        width = draw.textlength(text, font=font)
        draw.text(((WIDTH - width) / 2, HEADER_HEIGHT + 20), text, font=font, fill=BLACK)
        return image

    row_font = _load_font(bold=False, size=14)
    for row in range(ROWS):
        index = offset + row
        if index >= len(items):
            break
        _draw_row(draw, row_font, items[index], row, selected=index == selected)

    return image


def _draw_header(draw, title, items, selected):
    font = _load_font(bold=True, size=13)
    counter = f"{selected + 1}/{len(items)}" if items else ""
    counter_width = draw.textlength(counter, font=font) if counter else 0

    available = WIDTH - 2 * MARGIN - counter_width - 6
    draw.text((MARGIN, 3), _truncate(draw, title, font, available), font=font, fill=BLACK)
    if counter:
        draw.text((WIDTH - MARGIN - counter_width, 3), counter, font=font, fill=BLACK)

    draw.line((0, HEADER_HEIGHT - 3, WIDTH, HEADER_HEIGHT - 3), fill=BLACK)


def _draw_row(draw, font, item, row, selected):
    top = HEADER_HEIGHT + row * ROW_HEIGHT
    if selected:
        draw.rectangle((0, top, WIDTH, top + ROW_HEIGHT - 1), fill=BLACK)
    ink = WHITE if selected else BLACK

    # A row shows either a value (a setting) or an arrow (somewhere to go).
    value = getattr(item, "value", None)
    if value:
        value_width = draw.textlength(value, font=font)
        draw.text((WIDTH - MARGIN - value_width, top + 2), value, font=font, fill=ink)
        reserved = value_width + 8
    elif is_directory(item):
        _draw_arrow(draw, WIDTH - MARGIN - 6, top + ROW_HEIGHT // 2, ink)
        reserved = 12
    else:
        reserved = 0

    label = getattr(item, "name", None) or "?"
    label = _truncate(draw, label, font, WIDTH - 2 * MARGIN - reserved)
    draw.text((MARGIN, top + 2), label, font=font, fill=ink)


def _draw_arrow(draw, x, y, ink, size=5):
    """A right-pointing triangle, drawn rather than typed so the fallback
    bitmap font's glyph coverage never matters."""
    draw.polygon([(x, y - size), (x, y + size), (x + size, y)], fill=ink)
