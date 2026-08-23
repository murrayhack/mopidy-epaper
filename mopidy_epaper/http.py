"""HTTP input API.

This is what keeps physical buttons out of this extension. Anything that can
make an HTTP request can drive the panel — a GPIO script, a phone, ``curl`` —
so browsing can be built and tested long before any button exists, and buttons
never become a dependency.

Rides on the web server Mopidy already runs; routes are mounted under
``/epaper/``.
"""

import logging
import pathlib

import pykka
import tornado.web

from . import ui
from .frontend import EpaperFrontend

logger = logging.getLogger(__name__)

# How long to wait on the actor for a status read. A refresh in flight can hold
# the actor for a second or two on a Pi Zero.
STATUS_TIMEOUT = 3

REMOTE_PAGE = pathlib.Path(__file__).parent / "webremote.html"


def factory(config, core):
    return [
        (r"/input/([a-zA-Z_]+)", InputHandler),
        (r"/status", StatusHandler),
        (r"/actions", ActionsHandler),
        (r"/", IndexHandler, {"web_remote": config["epaper"]["web_remote"]}),
    ]


class _FrontendHandler(tornado.web.RequestHandler):
    def frontend(self):
        """The running frontend actor, or None if it failed to start."""
        refs = pykka.ActorRegistry.get_by_class(EpaperFrontend)
        return refs[0].proxy() if refs else None

    def unavailable(self):
        self.set_status(503)
        self.finish({"error": "the e-paper frontend is not running"})


class InputHandler(_FrontendHandler):
    def post(self, action):
        action = action.lower()

        if action not in ui.ACTIONS:
            self.set_status(400)
            self.finish({"error": f"unknown action: {action}", "actions": sorted(ui.ACTIONS)})
            return

        if action not in ui.IMPLEMENTED_ACTIONS:
            self.set_status(501)
            self.finish({"error": f"{action} is accepted by the API but does nothing yet"})
            return

        frontend = self.frontend()
        if frontend is None:
            self.unavailable()
            return

        # Fire and forget. A full refresh takes seconds on a Pi Zero, and this
        # runs on Mopidy's Tornado IOLoop, which must not block.
        frontend.handle_input(action)
        self.set_status(202)
        self.finish({"accepted": action})


class StatusHandler(_FrontendHandler):
    def get(self):
        frontend = self.frontend()
        if frontend is None:
            self.unavailable()
            return
        try:
            self.finish(frontend.input_state().get(timeout=STATUS_TIMEOUT))
        except pykka.Timeout:
            self.set_status(504)
            self.finish({"error": "the e-paper frontend did not respond in time"})


class ActionsHandler(tornado.web.RequestHandler):
    """The vocabulary, always available regardless of the remote setting."""

    def get(self):
        self.finish(
            {
                "actions": sorted(ui.ACTIONS),
                "implemented": sorted(ui.IMPLEMENTED_ACTIONS),
                "usage": "POST /epaper/input/<action>, GET /epaper/status",
            }
        )


class IndexHandler(ActionsHandler):
    """The remote page, or the vocabulary when the remote is switched off."""

    def initialize(self, web_remote=True):
        self._web_remote = web_remote

    def get(self):
        if not self._web_remote:
            super().get()
            return
        try:
            page = REMOTE_PAGE.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Could not read %s", REMOTE_PAGE)
            self.set_status(500)
            self.finish({"error": "the remote page is missing"})
            return
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.finish(page)
