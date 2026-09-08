#!/usr/bin/env python3
"""Drive the e-paper input API from GPIO buttons.

This is an example, not part of the extension. mopidy-epaper deliberately does
not talk to GPIO: it exposes an HTTP input API, and anything that can make a
request can drive it. Copy this, change the pins, run it alongside Mopidy.

    python3 examples/gpio_buttons.py

It is meant to stay this small — enough to show what the API expects. For a
whole player, with volume, transport, mode-aware buttons and a systemd unit,
see the paperpod repository, which drives this API from the outside.

Transport controls (play/pause, next, previous, volume) are a solved problem —
use mopidy-raspberry-gpio for those, or Mopidy's JSON-RPC API directly. This is
only for driving the panel.

The pins below avoid the ones the e-paper HAT already occupies: RST 17, DC 25,
CS 8, BUSY 24, plus SPI on 10 and 11, and PWR 18 unless `pwr_pin =` has freed
it. They also avoid I2S — 18, 19, 20 and 21 — which an I2S DAC needs. A
collision with any of those is quiet rather than loud: gpiozero takes the pin,
the other device stops working, and nothing raises. Check your own wiring
against that list before changing them.
"""

import urllib.error
import urllib.request
from signal import pause

from gpiozero import Button

BASE_URL = "http://localhost:6680/epaper/input/"

BUTTONS = {
    5: "up",
    6: "down",
    13: "select",
    16: "back",
    26: "home",
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
