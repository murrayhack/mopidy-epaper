# Mopidy-Epaper

A [Mopidy](https://mopidy.com/) frontend extension that shows now-playing
information — title, artist, album, progress, queue position and volume — on a
Waveshare 2.13" V4 e-paper display attached to a Raspberry Pi Zero.

The status strip carries the progress bar, elapsed and total time, play state,
where the track sits in the queue, and the volume. Muting slashes through the
speaker rather than hiding the level, so you can see what unmuting will return
to.

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
menu_timeout = 20
dummy_output_path =
```

| Setting | Description |
| --- | --- |
| `driver` | `epd2in13_v4` for the real panel, or `dummy` to render PNG frames to disk instead. |
| `update_interval` | Seconds between progress-bar refreshes while playing. |
| `full_refresh_every` | Partial refreshes allowed before forcing a full refresh to clear ghosting. |
| `sleep_after` | Seconds of stopped playback before the panel is put to sleep. `0` disables it. |
| `idle_screen` | `keep` leaves the last frame on the panel when it sleeps, `blank` clears it first. |
| `menu_timeout` | Seconds without input before the library browser closes itself. `0` keeps it open. |
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

Lock is not bound to any particular button — it is exposed through the input
API below.

## Input API

This extension deliberately does not talk to GPIO. It exposes an HTTP input
API instead, so anything that can make a request can drive the panel: a button
script, a phone, `curl`. Buttons never become a dependency, and screen
behaviour can be built and tested before any hardware exists.

It rides on the web server Mopidy already runs, and is separate from Mopidy's
own JSON-RPC API at `/mopidy/rpc`. The split follows what each one owns:
playback, the tracklist and the mixer belong to Mopidy, so they go through
JSON-RPC; the panel belongs to this extension, so locking, waking and menu
navigation come here. Mopidy offers extensions no way to add JSON-RPC methods
in any case, and a plain `POST` is far easier to call from a button script than
a JSON-RPC envelope.

```sh
curl -X POST http://localhost:6680/epaper/input/toggle_lock
curl -X POST http://localhost:6680/epaper/input/lock
curl -X POST http://localhost:6680/epaper/input/unlock
curl -X POST http://localhost:6680/epaper/input/wake

curl http://localhost:6680/epaper/status
```

| Action | Effect |
| --- | --- |
| `up`, `down` | Move the selection, wrapping at either end |
| `select` | Descend, play a track, or flip a setting |
| `back` | Up one level, or leave the menu at the root |
| `home` | Open the menu, or close it |
| `toggle_shuffle`, `toggle_repeat` | Change playback options without opening the menu |
| `lock`, `unlock`, `toggle_lock` | Freeze the panel and sleep it |
| `wake` | Wake an idle panel |

From the now-playing screen, any of `up`, `down`, `select` or `home` opens the
menu. Unknown actions return `400`, and `GET /epaper/` lists the vocabulary.

Accepted actions return `202` immediately: a full refresh takes seconds on a Pi
Zero, and the request must not hold up Mopidy's web server while it happens.

## The menu

`home` — or any navigation action — opens the menu:

```
Menu                  3/5
-------------------------
  Library            >
  Playlists          >
 [Queue              >]
  Shuffle:         Off
  Repeat:          Off
```

The menu always has this shape. Only the cursor moves: it starts on **Queue**
while something is playing and on **Library** otherwise, so the common case is
one press away without the same button leading somewhere different each time.

**Library** browses the tree `core.library.browse()` exposes, so whatever
backends are enabled show up in it. Selecting a track queues every track listed
alongside it and starts at the one picked, so choosing a song from an album
plays the album rather than stopping after one track.

**Playlists** lists saved playlists. In Mopidy these live behind a separate API
from library browsing, so they do not appear anywhere under **Library** — an
empty list here means no playlists are saved, not that anything is broken.

Where Mopidy looks for them is its own setting, not this extension's:
`[m3u] playlists_dir` is unset by default, so playlists live in that
extension's data directory. Pointing it at your media directory keeps
playlists beside the music; set `base_dir` too so relative paths inside the
files resolve. Use the `.m3u8` extension for anything with non-ASCII track
names, since plain `.m3u` is read as latin-1.

**Queue** lists the current tracklist; selecting a row jumps straight to it.

**Shuffle** and **Repeat** flip in place rather than navigating anywhere.
Repeat cycles `Off` → `All` → `One`, which is Mopidy's `repeat` and `single`
options underneath.

The menu closes itself after `menu_timeout` seconds without input and hands the
screen back to now-playing. Set it to `0` to keep it open until dismissed.

Scrolling uses partial refreshes, so it does not flash — the periodic full
refresh that clears ghosting still applies.

If a library category shows **Empty**, that is not a display fault: it means
mopidy-local has nothing indexed. Run `mopidy local scan`.

### Buttons

`examples/gpio_buttons.py` is a working example that maps GPIO pins to these
actions with `gpiozero`. It is a starting point to copy, not part of the
package.

For playback control — play/pause, next, previous, volume — use
[mopidy-raspberry-gpio](https://github.com/pimoroni/mopidy-raspberry-gpio)
rather than anything here. It maps pins to transport actions entirely through
`mopidy.conf` and is a solved problem.

Whatever you wire up, avoid the pins the e-paper HAT already occupies: **RST
17, DC 25, CS 8, BUSY 24, PWR 18**, plus SPI on **10** and **11**. A collision
there fails confusingly.

## Driving it by hand

Mopidy's JSON-RPC API over HTTP is the quickest way to exercise the display
without a web client. Queue the first file in `~/music` and play it:

```sh
F=$(python3 -c "import pathlib; print(sorted((pathlib.Path.home()/'music').iterdir())[0].as_uri())")

curl -s -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"core.tracklist.add\",\"params\":{\"uris\":[\"$F\"]}}" \
  -H 'Content-Type: application/json' http://localhost:6680/mopidy/rpc

curl -s -d '{"jsonrpc":"2.0","id":1,"method":"core.playback.play"}' \
  -H 'Content-Type: application/json' http://localhost:6680/mopidy/rpc
```

Deriving the URI through `pathlib` matters: filenames with spaces need
percent-encoding, and a raw `file://$F` will silently resolve to nothing and
return an empty `result`.

Stop, and clear the queue between runs:

```sh
curl -s -d '{"jsonrpc":"2.0","id":1,"method":"core.playback.stop"}' \
  -H 'Content-Type: application/json' http://localhost:6680/mopidy/rpc

curl -s -d '{"jsonrpc":"2.0","id":1,"method":"core.tracklist.clear"}' \
  -H 'Content-Type: application/json' http://localhost:6680/mopidy/rpc
```

### Testing sleep and wake

Set `sleep_after = 20` so you are not waiting five minutes, then play, stop,
and wait. Mopidy logs each transition at info level — `Panel idle for 20s,
sleeping`, then `Panel awake` when playback resumes.

If it does not flash on wake, the log tells you which of two things happened;
so does the panel. If the display carries on updating, it simply never slept.
If it stays frozen, it slept and the SPI re-init failed.

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
