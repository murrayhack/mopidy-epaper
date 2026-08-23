"""The remote page is static, so these check its contract with the API.

Serving it needs a running Tornado, but the page referring to an action that
does not exist — or the packaging dropping the file — are both silent failures
worth catching here.
"""

import pathlib
import re

from mopidy_epaper import http, ui


def page():
    return http.REMOTE_PAGE.read_text(encoding="utf-8")


def test_the_page_ships_with_the_package():
    assert http.REMOTE_PAGE.exists()
    assert http.REMOTE_PAGE.parent == pathlib.Path(http.__file__).parent


def test_the_page_is_listed_as_package_data():
    pyproject = (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text()

    assert "webremote.html" in pyproject


def test_every_button_maps_to_a_real_action():
    actions = set(re.findall(r'data-action="([a-z_]+)"', page()))

    assert actions
    assert actions <= ui.ACTIONS


def test_every_button_maps_to_an_implemented_action():
    actions = set(re.findall(r'data-action="([a-z_]+)"', page()))

    assert actions <= ui.IMPLEMENTED_ACTIONS


def test_the_navigation_actions_are_all_reachable():
    actions = set(re.findall(r'data-action="([a-z_]+)"', page()))

    assert {"up", "down", "select", "back", "home"} <= actions


def test_the_page_calls_the_endpoints_relatively():
    # It is served from /epaper/, so relative URLs keep it working if the app
    # is ever mounted somewhere else.
    html = page()

    assert 'fetch("input/" + action' in html
    assert 'fetch("status")' in html
    assert "/epaper/" not in html


def test_the_page_is_self_contained():
    html = page()

    assert "http://" not in html
    assert "https://" not in html
