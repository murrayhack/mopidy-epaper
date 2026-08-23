"""HTTP input API.

This is what keeps physical buttons out of this extension. Anything that can
make an HTTP request can drive the panel — a GPIO script, a phone, ``curl`` —
so browsing can be built and tested long before any button exists, and buttons
never become a dependency.

Rides on the web server Mopidy already runs; routes are mounted under
``/epaper/``.
"""

import logging

import pykka
import tornado.web

from . import ui
from .frontend import EpaperFrontend

logger = logging.getLogger(__name__)

# How long to wait on the actor for a status read. A refresh in flight can hold
# the actor for a second or two on a Pi Zero.
STATUS_TIMEOUT = 3


def factory(config, core):
    return [
        (r"/input/([a-zA-Z_]+)", InputHandler),
        (r"/status", StatusHandler),
        (r"/", IndexHandler),
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


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.finish(
            {
                "actions": sorted(ui.ACTIONS),
                "implemented": sorted(ui.IMPLEMENTED_ACTIONS),
                "usage": "POST /epaper/input/<action>, GET /epaper/status",
            }
        )
