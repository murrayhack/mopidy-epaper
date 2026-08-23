#!/usr/bin/env python3
"""Drive the e-paper input API from GPIO buttons.

This is an example, not part of the extension. mopidy-epaper deliberately does
not talk to GPIO: it exposes an HTTP input API, and anything that can make a
request can drive it. Copy this, change the pins, run it alongside Mopidy.

    python3 examples/gpio_buttons.py

Transport controls (play/pause, next, previous, volume) are a solved problem —
use mopidy-raspberry-gpio for those. This is only for driving the panel.

The pins below avoid the ones the e-paper HAT already occupies: RST 17, DC 25,
CS 8, BUSY 24, PWR 18, plus SPI on 10 and 11. A collision there fails in
confusing ways, so check your own wiring against that list before changing them.
"""

import urllib.error
import urllib.request
from signal import pause

from gpiozero import Button

BASE_URL = "http://localhost:6680/epaper/input/"

BUTTONS = {
    5: "toggle_lock",
    6: "back",
    16: "up",
    20: "down",
    21: "select",
}


def send(action):
    request = urllib.request.Request(BASE_URL + action, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            print(f"{action}: {response.status}")
    except urllib.error.HTTPError as exc:
        # 501 means the API knows the action but browsing has not landed yet.
        print(f"{action}: {exc.code} {exc.reason}")
    except OSError as exc:
        print(f"{action}: {exc}")


def main():
    held = []
    for pin, action in BUTTONS.items():
        button = Button(pin, pull_up=True, bounce_time=0.05)
        # Bind the action per iteration rather than closing over the loop variable.
        button.when_pressed = lambda action=action: send(action)
        held.append(button)
        print(f"GPIO {pin} -> {action}")

    print(f"Posting to {BASE_URL}<action>. Ctrl-C to stop.")
    pause()


if __name__ == "__main__":
    main()
