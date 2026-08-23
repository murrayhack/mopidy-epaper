from mopidy_epaper import menu


class _Ref:
    def __init__(self, uri, name, type="track"):
        self.uri = uri
        self.name = name
        self.type = type


def tracks(count):
    return [_Ref(f"t:{i}", f"Track {i}") for i in range(count)]


def test_render_returns_panel_sized_1bit_image():
    image = menu.render("Library", tracks(3), selected=1)

    assert image.size == (menu.WIDTH, menu.HEIGHT)
    assert image.mode == "1"


def test_render_handles_an_empty_listing():
    image = menu.render("Library", [])

    assert image.size == (menu.WIDTH, menu.HEIGHT)


def test_render_handles_more_items_than_fit():
    image = menu.render("Library", tracks(50), selected=40, offset=38)

    assert image.mode == "1"


def test_selection_changes_the_rendering():
    items = tracks(3)

    first = menu.render("Library", items, selected=0)
    second = menu.render("Library", items, selected=1)

    assert first.tobytes() != second.tobytes()


def test_directories_render_differently_from_tracks():
    as_track = menu.render("Library", [_Ref("a", "Thing", "track")])
    as_directory = menu.render("Library", [_Ref("a", "Thing", "directory")])

    assert as_track.tobytes() != as_directory.tobytes()


def test_is_directory():
    assert menu.is_directory(_Ref("a", "A", "directory"))
    assert menu.is_directory(_Ref("a", "A", "album"))
    assert menu.is_directory(_Ref("a", "A", "artist"))
    assert not menu.is_directory(_Ref("a", "A", "track"))


def test_scroll_offset_stays_zero_when_everything_fits():
    assert menu.scroll_offset(count=3, selected=2, previous=0) == 0


def test_scroll_offset_follows_the_selection_downward():
    rows = menu.ROWS
    assert menu.scroll_offset(count=20, selected=rows, previous=0) == 1


def test_scroll_offset_follows_the_selection_upward():
    assert menu.scroll_offset(count=20, selected=2, previous=5) == 2


def test_scroll_offset_holds_still_while_the_selection_is_visible():
    assert menu.scroll_offset(count=20, selected=6, previous=5) == 5


def test_scroll_offset_never_runs_past_the_end():
    offset = menu.scroll_offset(count=20, selected=19, previous=19)

    assert offset == 20 - menu.ROWS
    assert offset + menu.ROWS == 20


def test_scroll_offset_clamps_a_stale_previous_value():
    assert menu.scroll_offset(count=6, selected=0, previous=99) == 0
