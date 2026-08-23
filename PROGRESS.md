# mopidy-epaper — progress log

Goal: a Mopidy frontend extension that shows now-playing info (artist,
track, progress, volume) on a Waveshare 2.13" V4 e-paper HAT, running on
a Raspberry Pi Zero.

## Research findings

- **No existing well-baked solution.** `mopidy-pidi` (Pimoroni's plugin-host
  frontend) only ships LCD/framebuffer display plugins
  (`pidi-display-pil`, `-st7735`, `-st7789`, `-tk`) — no e-paper/Inky
  backend exists in `pimoroni/pidi-plugins`, and `pidi-display-inky` does
  not exist on PyPI (an earlier web-search summary claimed otherwise;
  verified false by reading the actual repo contents).
- **ePiPod** (`github.com/delhatch/PiPod_ePaper`, see also
  [hackaday.io/project/196631-epipod](https://hackaday.io/project/196631-epipod))
  is a real, similar build: Pi Zero 2 W + Waveshare 2.13" 250×122 e-paper,
  VLC-based player. Kept as a reference source, but it's a standalone
  player (not a Mopidy frontend), so it's useful for hardware/driver
  patterns only, not code reuse. Its docs note the "Playing" screen
  updates every 5s — informed our default `update_interval`.
- The Waveshare `epd2in13_V4` driver is **not** in the `waveshare-epaper`
  PyPI package (that package predates the V4 revision). Standard practice
  (confirmed via ePiPod and Waveshare's own examples) is to vendor the
  driver source directly from `waveshareteam/e-Paper` rather than depend
  on a package.
- Read the vendored driver source directly to confirm its refresh API:
  `init()` / `init_fast()`, `display()` (full), `display_fast()`,
  `displayPartial()` + `displayPartBaseImage()` (partial-refresh pair).
  Waveshare's own example pattern — full `init()` + `displayPartBaseImage()`
  once to seed both RAM buffers, then repeated `displayPartial()` calls,
  with an occasional full refresh to clear ghosting — is what we're
  following.

## Decisions made

| Decision | Choice | Why |
|---|---|---|
| Display hardware | Waveshare 2.13" V4 (250×122) | User has this panel |
| Driver strategy | Vendor `epd2in13_V4.py` + `epdconfig.py` verbatim (MIT header intact) | No usable PyPI package covers V4 |
| Hardware deps (`spidev`, `gpiozero`) | Optional extra (`pip install mopidy-epaper[hardware]`) | These only build on Linux/Pi; must not block install/dev on macOS |
| Local dev without a Pi | `driver = dummy` config option, renders to a PNG on disk instead of SPI | The dev machine is a Mac; needed a way to iterate without hardware |
| Refresh strategy | Full refresh on track change or every N partials (`full_refresh_every`); partial refresh (progress bar/time only) on a periodic tick while playing | Avoids full-panel flicker on every 5s tick; avoids ghosting build-up from too many partials |
| Progress-bar ticking | Driven by the frontend's own timer thread re-querying `core.playback` on an interval, not estimated/extrapolated in the display layer | Avoids position drift; always shows real position |
| Import safety | Never import the vendored `drivers.epd2in13_V4` module at package top-level | `epdconfig.py` executes hardware-detection code at import time and raises on non-Pi platforms (confirmed by reading it) — must stay a lazy import inside the `epd2in13_v4` driver branch only |

## Done so far

- [x] Vendored `mopidy_epaper/drivers/epd2in13_V4.py` and `epdconfig.py`
      from `waveshareteam/e-Paper` (unmodified, MIT-style header retained).
- [x] Packaging: `pyproject.toml` (entry point `mopidy.ext` →
      `mopidy_epaper:Extension`, `hardware`/`test` extras), `LICENSE`,
      `NOTICE`, `.gitignore`, `README.md`.
- [x] `mopidy_epaper/__init__.py` — `Extension` + config schema.
- [x] `mopidy_epaper/ext.conf` — defaults.
- [x] `mopidy_epaper/layout.py` — all rendering, pure Pillow.
- [x] `mopidy_epaper/display.py` — `EpaperDisplay`, full/partial refresh
      scheduling, lazy hardware import, `dummy` PNG driver.
- [x] `mopidy_epaper/frontend.py` — `EpaperFrontend` pykka actor +
      ticker thread.
- [x] `tests/test_layout.py` — unit tests for the rendering layer.

## Verified on hardware (2026-08-21)

Raspberry Pi Zero, Raspberry Pi OS Trixie (Python 3.13), Mopidy 3.4.2
from apt, real Waveshare 2.13" V4 panel.

- [x] `pytest tests/` — 11/11 pass.
- [x] Extension discovered by Mopidy; `mopidy config` shows the `[epaper]`
      schema.
- [x] `EpaperFrontend` starts; lazy driver import and `epd.init()` work.
- [x] Full refresh renders correctly, and **text orientation is upright** —
      no rotation fix needed for `getbuffer()`'s counter-clockwise
      rotation as mounted.
- [x] Partial refresh confirmed: the progress bar advances every 5s with
      **no panel flash**, which was the main design risk.
- [x] Clean shutdown. The ~4s pause on "Stopping Mopidy frontends" is
      `close()` plus the driver's own 2s pre-sleep delay, not a hang.
- [x] Track-change full refresh works.
- [x] Title / artist / album lines render as intended on a properly
      tagged file. A first test file that turned up truncated had artist
      and title both in the title tag and no artist tag — `_truncate()`
      behaving correctly on bad metadata, not a layout bug.
- [x] Anti-ghosting full refresh at `full_refresh_every` fires as
      expected after ~5 minutes of continuous playback.

Install note: Mopidy from apt lives in system Python, so the extension
must too (`sudo pip install --break-system-packages --no-deps -e .` with
deps from apt). A virtualenv does not work — the entry point is never
discovered. Recorded in the README.

## Environment note

Local execution is off the table on this Mac by preference — verification
happens on the Pi. (For the record: an attempt to create a local `.venv`
under Homebrew Python 3.14 failed at the `ensurepip` step.)

## Phase 1 — panel power and lock (written 2026-08-22, unverified)

Implements the first phase of the roadmap. **Not yet run on hardware.**

Refactor: `display.py` no longer knows about tracks. It is panel I/O only —
`show(image, force_full)`, `sleep()`, `wake()` — and the new `ui.py` owns
all screen state, including the content-key logic that used to live in
`display.py`. This is what makes the refresh machinery reusable by a menu
screen in phase 3.

New behaviour:

- Panel sleeps after `sleep_after` seconds of stopped playback and wakes
  on playback. `idle_screen` chooses whether the last frame stays visible
  (`keep`) or is cleared first (`blank`).
- Lock state: draws a padlock, sleeps, and ignores playback updates until
  unlocked. No way to trigger it yet — that arrives with the input API in
  phase 2.
- Redundant redraws are now skipped entirely. Previously every tick while
  paused burned a partial refresh, and its ghosting budget, on an
  identical frame.

**Verified on hardware 2026-08-23:** the panel sleeps after the configured
idle period and wakes cleanly on playback. `epd.init()` does reopen SPI
after `module_exit()` closed it, which was the main risk in this phase.

One bug found in that first run: the panel slept and then woke itself
57ms later, from the other thread. `frontend._refresh()` read playback
state and rendered it as two separate steps, so the ticker and the actor
each took their own snapshot and whichever rendered second could be
carrying the older one — enough to wake a panel that had just gone to
sleep, and enough to walk the progress bar backwards. Reading and
rendering are now atomic under a lock.

Note the Pi has no working audio sink (`GStreamer warning: Failed to
connect: Connection refused`), so playback state during testing is not
entirely representative. Audio output is out of scope for this repo, but
it makes the sleep/wake test noisier than it should be.

## Phase 2 — input API (written 2026-08-23, unverified)

`http.py` registers a Mopidy `http:app`, putting the input API on the web
server Mopidy already runs:

- `POST /epaper/input/<action>` — `202` accepted, `501` for actions that
  exist in the vocabulary but have no behaviour yet, `400` for unknown
  ones, `503` if the frontend never started.
- `GET /epaper/status` — `{"locked", "asleep", "running"}`.
- `GET /epaper/` — lists the vocabulary.

Requests are fire-and-forget onto the actor. A full refresh takes seconds
on a Pi Zero and this runs on Mopidy's Tornado IOLoop, which must not
block; the status read is the one exception and it carries a timeout.

The full action vocabulary is declared in `ui.ACTIONS` even though only
lock/unlock/toggle_lock/wake do anything, so the contract stays stable
when browsing lands. `examples/gpio_buttons.py` shows the intended
consumer.

**Not yet run on hardware.** The specific unknowns are whether Mopidy
mounts the routes where expected, and whether
`pykka.ActorRegistry.get_by_class()` resolves the frontend from the
Tornado thread.

## Known limitations / deferred

- **Radio stream titles don't update.** For a stream, the track URI and
  name stay constant while `core.playback.get_stream_title()` changes.
  Nothing reads that, so the title area would go stale. Irrelevant for
  the mopidy-local use case; needs plumbing `get_stream_title()` through
  `frontend._refresh()` → `layout.render()` → `display._content_key()`
  if radio is ever wanted.
- **Panel rotation is unverified.** `EPD.getbuffer()` rotates our 250×122
  landscape image counter-clockwise into the panel's 122×250
  framebuffer. Whether text ends up upright depends on how the HAT is
  physically mounted — if it's upside down, rotate 180° in `layout.render`.
- No album art (1-bit, small panel), no button input.

## Next steps

Every code path is now exercised on hardware.

1. Tune `full_refresh_every` once there is more listening time behind it:
   too rare and ghosting builds up, too often and the panel flashes for
   no reason. Currently 60 partials, i.e. ~5 minutes at the default
   5-second interval.
2. Decide whether badly tagged files deserve special handling, e.g.
   splitting a `"Artist - Title"` title tag when no artist tag exists, or
   dropping the album line to give the title two lines.
