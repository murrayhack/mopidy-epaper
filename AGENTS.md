# AGENTS.md

Guidance for coding agents working in this repository. The [README](README.md)
documents the extension for its users — hardware, installation, configuration,
the input API and the menu. This file covers what an agent needs that the README
does not say: the layering rules, the threading model, and how work gets
verified.

## What this is

A [Mopidy](https://mopidy.com/) frontend extension that renders now-playing
information and a library browser on a Waveshare 2.13" V4 e-paper panel
(250×122) attached to a Raspberry Pi Zero. Input arrives over HTTP, not GPIO.

## Where verification happens

**Do not run Python, `pytest`, or virtualenv setup on the development Mac.**
The target is the Pi, and that is where anything gets confirmed. Write the code,
say plainly that it is unrun, and hand it over.

The Pi (`pi0`, user `murray`) runs the extension as a **system-Python editable
install from a git checkout at `/home/murray/mopidy-epaper`**. Merging a PR does
not update it — the running code is whatever that checkout has on disk, so it
needs a `git pull` (or a branch checkout) on the Pi. If Mopidy there reports
`No module named 'mopidy_epaper'`, check `git log -1` on the Pi first; a stale
checkout is the usual cause.

Tests are `pytest tests/`, run on the Pi. `tests/` covers `layout`, `menu`,
`ui` and the HTTP remote — everything that does not need the panel. Fakes
duck-type Mopidy's models (see `FakeTrack`, `_Ref` in `tests/test_ui.py`)
rather than importing them.

## Layering, and the import rules that hold it up

```
frontend.py   pykka actor + MopidyPlayer — the only module that imports mopidy
   ↓
ui.py         screen state machine: which screen, where the cursor is,
              sleep/lock state. Mopidy arrives as an injected `player`.
   ↓
layout.py     now-playing rendering, pure Pillow
menu.py       browser rendering, pure Pillow
   ↓
display.py    owns the panel: full vs partial refresh, power state
   ↓
hardware.py   GPIO and SPI: the pin map, and our stand-in for the
              vendored epdconfig
   ↓
drivers/      vendored Waveshare sources — do not edit (see NOTICE)
```

Four rules, each of which something will break if ignored:

1. **Nothing in `drivers/` may be imported at module import time.**
   `epdconfig.py` runs hardware detection on import and raises on any
   non-Pi platform. `display.py` imports it lazily, inside the
   `epd2in13_v4` branch only — and calls `hardware.install()` first, which
   substitutes our own module for `drivers.epdconfig` in `sys.modules`.
   That ordering is load-bearing: importing the vendored module is what
   claims GPIO 18, and nothing after the fact can undo it.
2. **`layout.py` and `menu.py` import neither Mopidy nor any driver.** That is
   what makes the rendering testable anywhere Pillow is installed. Mopidy
   models are duck-typed: `track` needs `name`, `artists`, `length`; menu rows
   need `name` and `type`.
3. **`ui.py` does not import Mopidy either.** Everything it needs comes through
   the injected `player` — `browse`, `play`, `playlists`, `playlist_tracks`,
   `queue`, `play_queued`, `options`, `set_option`. `frontend.MopidyPlayer` is
   the production implementation; the tests supply their own.
4. **`drivers/` stays verbatim.** The files are vendored unmodified from
   `waveshareteam/e-Paper` with their MIT-style headers intact, because the
   `waveshare-epaper` PyPI package predates the V4 revision. Fix things around
   them, not in them.

## Threading model

Three threads, and the split matters:

- **The pykka actor thread** handles Mopidy events and HTTP-driven input. It
  must never block on the panel — a full refresh costs seconds on a Pi Zero,
  and Mopidy's events queue up behind the SPI bus.
- **`EpaperTicker`** fires every `update_interval` and marks playback dirty. It
  skips entirely while `ui.dormant` (locked, or idle-asleep), since a tick can
  achieve nothing then and playback events wake the panel directly.
- **`EpaperRenderer`** does all reading and drawing. One thread doing both is
  what makes them atomic — there is deliberately no lock. It also coalesces:
  `input_coalesce_ms` of further presses land before it draws, and the several
  events one track change fires collapse into a single read and draw.

Tornado handlers in `http.py` run on Mopidy's IOLoop, so input is fire-and-
forget with a `202`. Only `/status` waits on the actor, with a timeout.

Reading playback state uses `MopidyPlayer.snapshot()`, which sends all seven
proxy calls before waiting on any of them. Do not reintroduce a `.get()` after
each call; they queue on the same core actor regardless, so waiting in between
is pure added latency.

## Refresh discipline

E-paper physics drive most of the design. A full refresh flashes the whole panel
and takes seconds; a partial refresh is quick and silent but accumulates
ghosting. So: full refresh when the content genuinely changed (track change,
wake, menu open), partial for the status strip, and a forced full every
`full_refresh_every` partials to clear ghosting. `layout.STATUS_TOP` marks the
boundary — everything below it is what a partial refresh redraws.

Waking re-initialises the controller and loses the RAM buffers partials diff
against, so the first frame after a wake is always full. `display.py` tracks
this with `_needs_full`; keep that invariant if you touch power handling.

## Making common changes

**A new config option** touches four places: `ext.conf` (the default),
`Extension.get_config_schema` in `__init__.py` (validation), the settings table
in `README.md`, and wherever it is read.

**A new field on the now-playing screen** means `playback.Playback` (the frozen
value object carried through every layer), the drawing code in `layout.py`,
`MopidyPlayer.snapshot()`, and — if it should trigger a redraw —
`ui.content_key` or `ui.status_key`. Those two keys decide what counts as a
change worth a refresh, at the resolution the panel actually shows.

**A new input action** goes in `ui.ACTIONS`, which is the single source of
truth for the API vocabulary; `http.py` and `/epaper/actions` read it. Then
handle it in `Ui.handle_action` and add it to the README's action table. Actions
in `ACTIONS` but not `IMPLEMENTED_ACTIONS` return `501`.

**Playback control** (play/pause, next, volume) is deliberately out of scope —
the README points users at `mopidy-raspberry-gpio` for that. This extension owns
the panel; Mopidy's JSON-RPC API owns playback.

## Style

Comments and docstrings here explain *why*, not what — the existing modules are
the reference for the register to match, and their density is intentional rather
than incidental. When a decision looks arbitrary from the code alone (a lazy
import, a missing lock, a re-`init()` before a full refresh), the reason belongs
next to it.

Python targets 3.9+. No formatter or linter is configured; follow the
surrounding code.

## Documentation to keep current

- **`PROGRESS.md`** — the design log. Every change gets an entry explaining the
  reasoning, dated, and marked **unverified** until it has run on the panel.
  When the user confirms something on hardware, record that against the entry.
  Research findings, rejected options and known limitations live here too.
- **`CHANGELOG.md`** — user-facing changes, grouped by release.
- **`README.md`** — anything a user of the extension can see: config, actions,
  menu behaviour, installation quirks.

## Git

Branches are cut per change as `feature/…`, `refactor/…`, `perf/…`,
`release/…`, and merged to `main` via PR. Commit subjects are imperative and
under 50 characters ("Add playlists to the menu", "Coalesce rapid input into a
single panel refresh"). No `Co-Authored-By` or Claude Code footer in commits or
PR bodies. The `.claude/skills/` directory holds the repo's commit-message and
PR conventions in full.
