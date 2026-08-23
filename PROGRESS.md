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

**Verified on hardware 2026-08-23.** Both unknowns resolved: Mopidy mounts
the routes at `/epaper/`, and `pykka.ActorRegistry.get_by_class()` does
resolve the frontend from the Tornado thread.

- `GET /epaper/` lists the vocabulary.
- `toggle_lock` draws the padlock on the panel and sleeps it; toggling
  again wakes it.
- `POST /epaper/input/up` returns `501`.
- `GET /epaper/status` returned `{"locked": false, "asleep": true,
  "running": true}` after an unlock followed by an idle timeout — the
  phase 1 sleep logic and the phase 2 API agreeing.

This also closes the one loose end from phase 1: no spurious wake was
observed after the panel slept, so the read-then-render race fix holds.

## Phase 3 — library browsing (written 2026-08-23, unverified)

The navigation actions declared in phase 2 now do something.

- `menu.py` renders a scrollable list — header with a position counter,
  five rows, selected row inverted, a drawn arrow marking directories. No
  Mopidy import, same discipline as `layout.py`.
- `ui.py` holds a stack of browse frames over `core.library.browse()`.
  Library access is injected into `Ui` as two callables rather than
  imported, so the whole state machine is testable without Mopidy.
- Selecting a track queues its siblings and starts at the chosen one, so
  picking a song from an album plays the album.
- The browser closes itself after `menu_timeout` seconds and hands the
  screen back to now-playing. Playback ticks do not paint over it while
  it is open.
- Scrolling uses partial refreshes, so it does not flash.

**Verified on hardware 2026-08-23.** Browsing the library on the panel,
descending several levels, selecting a track and having it play all work.

- Five rows at font size 14 is readable on the 2.13" panel. No change
  needed.
- The root `browse(None)` gives `Files` and `Local media`, which is a
  reasonable starting point, so the browser opens there rather than at
  some curated menu.
- Ghosting while scrolling looked fine on a first pass, but has not been
  pushed hard. **Revisit** — scroll quickly through a long list and see
  whether text smears before the periodic full refresh clears it.

Note for future diagnosis: empty categories under `Local media` mean an
empty mopidy-local library, not a display fault. `mopidy local scan` has
to have actually indexed something. The browser renders "Empty" perfectly
correctly in that case, which reads like a bug and is not one.

## Player menu, queue view and playback options (2026-08-23, unverified)

`home` now opens a fixed root menu — Library, Queue, Shuffle, Repeat —
rather than dropping straight into the library.

The design question was whether `home` should be context-sensitive:
a player screen while playing, the library when idle. It is not. The same
button leading somewhere different depending on state breaks muscle
memory, which matters when there are five buttons and no preview of what
a press will do. Instead the menu always has the same shape and only the
**cursor** moves: Queue while playing, Library otherwise. Same
convenience, no unpredictability.

- Queue view lists the tracklist; selecting a row jumps to it.
- Shuffle and Repeat flip in place rather than navigating. Repeat cycles
  off/all/one, which is Mopidy's `repeat` plus `single`.
- `toggle_shuffle` and `toggle_repeat` were added to the input API too, so
  a dedicated button need not go through the menu.
- Everything Mopidy-shaped now sits behind `frontend.MopidyPlayer`, one
  injected adapter, instead of loose callables passed to `Ui`. The state
  machine still imports no Mopidy.

**Verified on hardware 2026-08-23.** The toggles work from the menu and
the right-aligned values read well at font size 14. No redraw problem was
reported when flipping a setting.

## Queue position and volume icon (2026-08-23)

The now-playing status strip gained an `n/total` queue counter and a
drawn speaker glyph in place of the words "vol".

Placement of the counter was decided by collisions: not in the header,
because the title line already truncates and taking width from it makes
that worse; and right-aligned rather than centred, because a long
elapsed/total pair such as `1:02:05 / 1:15:30` reaches past the middle of
the panel. There are tests for both.

Muting was a silent no-op before this. `mute_changed` triggered a
refresh, but `get_volume()` still reports the level while muted, so the
screen redrew identically. The speaker glyph now carries a slash, and
`muted` joined `status_key` so the redraw actually happens. The level
stays visible so you can see what unmuting will return to.

**Verified on hardware 2026-08-23.** The speaker glyph is legible at
10px and mute/unmute both show correctly.

**Done:** the playback-state value object landed as
`mopidy_epaper/playback.py`. See below.

## Playback value object (2026-08-23)

Pure refactor, no behaviour change. `track`, `state`, `position_ms`,
`volume`, `number`, `total` and `muted` were seven loose arguments
threaded through the frontend, the UI and the layout. They are now one
frozen dataclass, `playback.Playback`.

`layout.render` went from ten parameters to four, and `render_playback`
from seven to one. Adding a field is now three edits — the dataclass,
wherever it is drawn, and where it is read in `frontend._refresh` — where
`muted` took ten.

It also removes a latent trap. `_last_playback` was a tuple unpacked
positionally inside `lock()`. If the tuple grew and that unpack was not
updated, it would raise only when someone locked the panel, not on any
ordinary render.

The tests keep loose arguments through small helpers, since
`render(track, "playing", 5000, 80)` reads better in a test than building
a dataclass on every line.

## Playlists (2026-08-23, unverified)

The menu gained a Playlists row. Mopidy keeps playlists behind
`core.playlists`, entirely separate from `core.library.browse()`, so they
were unreachable from the panel before this — nothing in the extension
had ever called that API.

One trap worth recording: `core.playlists.lookup()` returns `Track`
models, which carry no `type` attribute. `menu.is_directory()` reads
`type` and treats anything that is not a known leaf as navigable, so
unwrapped playlist tracks would have drawn arrows and tried to descend
into themselves. They are wrapped in `Entry` objects with an explicit
`type="track"`, the same way queue rows are.

Playlist tracks open as a `library` frame rather than a kind of their
own, so selecting one queues its siblings exactly as it does elsewhere.

**Verified on hardware 2026-08-23.** Playlists list, open, and selecting
a track queues the playlist. The tracks render without directory arrows,
confirming the `Entry` wrapping holds.

Note on where playlists live: `[m3u] playlists_dir` is a Mopidy setting,
unset by default, so playlists land in the extension's data dir rather
than beside the music. Pointing it at the media directory works, with
`base_dir` set alongside it so relative paths inside the files resolve.
Doing so makes mopidy-local try to scan the m3u file as audio and log a
harmless warning; `[local] excluded_file_extensions` silences it, but
that setting replaces the default list rather than extending it.

## Web remote (2026-08-23, unverified)

`/epaper/` now serves a small HTML remote instead of a JSON blob: the
five navigation buttons plus lock, wake, shuffle and repeat, with badges
for locked/asleep/in-menu. Toggled by `web_remote` in `mopidy.conf`;
`false` restores the JSON listing there. `GET /epaper/actions` always
returns the vocabulary regardless, so nothing was lost.

The point of it is evaluating the browsing UX. Tapping through a menu at
real speed is a completely different experience from sending one `curl`
at a time, and it needs no hardware.

The page is static, self-contained, and uses relative URLs so it does not
care where the app is mounted. `tests/test_webremote.py` checks that
every button maps to an implemented action and that the file is listed as
package data — both silent failures otherwise.

**Reaching it from a phone is a Mopidy-wide decision.** Mopidy binds to
127.0.0.1 by default, so this is localhost-only until `[http] hostname`
changes, which exposes all of Mopidy's API rather than just this page.

## Backlog

Discussed and worth doing, not yet built:

- **Alphabet jump.** With five buttons, reaching a track deep in a long
  list means pressing `down` a hundred times. A first-letter jump strip
  is what stops the panel falling apart past a few hundred albums. Not
  painful at the current library size.
- **Append vs replace.** Selecting a track calls `tracklist.clear()`
  first, so there is no way to add to a queue that is already playing. An
  `enqueue` action alongside `select` would fix it.
- **Seek and volume actions.** `seek_forward` / `seek_back` by 30s, and
  `volume_up` / `volume_down`. The API currently carries shuffle and
  repeat but not volume, which is a little inconsistent — transport was
  deferred to mopidy-raspberry-gpio.

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
