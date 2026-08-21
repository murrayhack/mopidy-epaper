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

> **Written with [Claude Code](https://claude.com/claude-code).** The research,
> design, implementation and documentation in this repository were produced
> with Anthropic's CLI for Claude. Every code path has since been exercised on
> real hardware — see [PROGRESS.md](PROGRESS.md) for what was verified and what
> is still an untuned guess.

## Hardware

- Raspberry Pi (developed against a Pi Zero)
- Waveshare 2.13" e-Paper HAT, **V4** revision (250×122)
- SPI enabled: `sudo raspi-config` → Interface Options → SPI

The Waveshare driver for this panel revision is vendored into
`mopidy_epaper/drivers/` — see [NOTICE](NOTICE). The `waveshare-epaper` package
on PyPI predates the V4 revision and does not include it.

## Installation

### Raspberry Pi OS (Trixie / Debian 13)

Mopidy from apt lives in the system Python, so the extension has to be
installed there too — otherwise Mopidy will not discover its entry point. A
virtualenv does not work for this.

Let apt supply the dependencies and give pip nothing to resolve:

```sh
sudo apt install -y python3-pil python3-pykka python3-spidev python3-gpiozero \
    python3-pytest fonts-dejavu-core
sudo pip install --break-system-packages --no-deps -e .
```

`--no-deps` matters on a Pi Zero: without it pip may decide the apt-installed
Pillow does not satisfy the version pin and rebuild it from source, which takes
a very long time and shadows the apt version in `/usr/local`.

`fonts-dejavu-core` is optional — text falls back to a bitmap font without it.

### Other platforms

The `hardware` extra pulls in `spidev` and `gpiozero`, which only build on
Linux:

```sh
pip install -e '.[hardware]'
```

To work on the rendering without the panel attached, skip that extra and use
`driver = dummy`:

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
sleep_after = 300
idle_screen = keep
dummy_output_path =
```

| Setting | Description |
| --- | --- |
| `driver` | `epd2in13_v4` for the real panel, or `dummy` to render PNG frames to disk instead. |
| `update_interval` | Seconds between progress-bar refreshes while playing. |
| `full_refresh_every` | Partial refreshes allowed before forcing a full refresh to clear ghosting. |
| `sleep_after` | Seconds of stopped playback before the panel is put to sleep. `0` disables it. |
| `idle_screen` | `keep` leaves the last frame on the panel when it sleeps, `blank` clears it first. |
| `dummy_output_path` | Where the `dummy` driver writes its PNG. Defaults to `/tmp/mopidy-epaper.png`. |

Confirm the extension is loaded with `mopidy deps list`.

## Sleep and lock

E-paper holds its image with no power at all, which shapes how this works.

When playback has been stopped for `sleep_after` seconds the panel controller
is powered down, leaving whatever was last drawn still visible. Playback wakes
it again. Waking re-initialises the controller, so the first frame after a wake
is always a full refresh.

The panel can also be locked, like the hold switch on an old MP3 player. A
locked panel draws a padlock, sleeps, and ignores everything until it is
unlocked — the frozen frame *is* the lock screen, costing nothing to display.

Lock is exposed to callers rather than bound to any particular button; see the
input API below once it lands.

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

- Written with [Claude Code](https://claude.com/claude-code).
- Panel driver by [Waveshare](https://github.com/waveshareteam/e-Paper).
- [ePiPod](https://github.com/delhatch/PiPod_ePaper)
  ([writeup](https://hackaday.io/project/196631-epipod)) — a standalone Pi Zero
  2 W music player using the same panel; used as a hardware reference.

## License

MIT — see [LICENSE](LICENSE).
