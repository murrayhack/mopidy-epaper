# Mopidy-Epaper

A [Mopidy](https://mopidy.com/) frontend extension that shows now-playing
information — title, artist, album, progress bar, elapsed/total time, play
state and volume — on a Waveshare 2.13" V4 e-paper display attached to a
Raspberry Pi Zero.

E-paper is slow to refresh, so the extension splits updates in two: the whole
screen is redrawn (a full, flashing refresh) only when the track changes, while
the progress bar ticks along via partial refreshes of the bottom strip. A full
refresh is forced every `full_refresh_every` partials to clear the ghosting
that partial updates accumulate.

## Hardware

- Raspberry Pi (developed against a Pi Zero)
- Waveshare 2.13" e-Paper HAT, **V4** revision (250×122)
- SPI enabled: `sudo raspi-config` → Interface Options → SPI

The Waveshare driver for this panel revision is vendored into
`mopidy_epaper/drivers/` — see [NOTICE](NOTICE). The `waveshare-epaper` package
on PyPI predates the V4 revision and does not include it.

## Installation

On the Pi:

```sh
pip install -e '.[hardware]'
sudo apt install fonts-dejavu-core   # nicer text; falls back to a bitmap font
```

The `hardware` extra pulls in `spidev` and `gpiozero`, which only build on
Linux. For development on a machine without the panel, install without it and
use `driver = dummy`:

```sh
pip install -e '.[test]'
```

## Configuration

Add to your `mopidy.conf`:

```ini
[epaper]
enabled = true
driver = epd2in13_v4
update_interval = 5
full_refresh_every = 60
dummy_output_path =
```

| Setting | Description |
| --- | --- |
| `driver` | `epd2in13_v4` for the real panel, or `dummy` to render PNG frames to disk instead. |
| `update_interval` | Seconds between progress-bar refreshes while playing. |
| `full_refresh_every` | Partial refreshes allowed before forcing a full refresh to clear ghosting. |
| `dummy_output_path` | Where the `dummy` driver writes its PNG. Defaults to `/tmp/mopidy-epaper.png`. |

Confirm the extension is loaded with `mopidy deps list`.

## Development

`mopidy_epaper/layout.py` holds all the rendering and imports neither Mopidy
nor any hardware driver, so it can be exercised anywhere Pillow is installed:

```sh
pytest tests/
```

Nothing in `mopidy_epaper/drivers/` may be imported at module import time —
`epdconfig.py` runs hardware detection on import and raises on non-Pi
platforms. `display.py` imports it lazily, inside the `epd2in13_v4` branch
only.

## Credits

- Panel driver by [Waveshare](https://github.com/waveshareteam/e-Paper).
- [ePiPod](https://github.com/delhatch/PiPod_ePaper)
  ([writeup](https://hackaday.io/project/196631-epipod)) — a standalone Pi Zero
  2 W music player using the same panel; used as a hardware reference.

## License

MIT — see [LICENSE](LICENSE).
