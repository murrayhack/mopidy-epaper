# Changelog

## v1.0.0 — 2026-08-24

First release. Every feature below has been exercised on the target
hardware: a Raspberry Pi Zero running Raspberry Pi OS Trixie with Mopidy
3.4.2 and a Waveshare 2.13" V4 panel.

### Now playing

- Title, artist and album, with ellipsised truncation for long values.
- Progress bar, elapsed and total time, play state, queue position and
  volume, with mute shown as a slash through the speaker.
- The screen is fully redrawn only when the track changes. The progress
  bar ticks via partial refreshes, so it does not flash. A full refresh is
  forced every `full_refresh_every` partials to clear the ghosting that
  partial updates accumulate.
- Playback position is re-read every tick rather than extrapolated, so
  the progress bar cannot drift.

### Menu

- Library browsing over `core.library.browse()`, so every enabled backend
  is reachable.
- Playlists, which Mopidy keeps behind a separate API from library
  browsing and which were otherwise unreachable.
- A queue view; selecting a row jumps to that track.
- Shuffle, and repeat cycling off, all and one.
- The menu always has the same shape; only the cursor moves, starting on
  Queue while playing and Library otherwise.
- Selecting a track queues the tracks listed alongside it, so picking a
  song from an album plays the album.

### Panel power

- Sleeps after `sleep_after` seconds of stopped playback and wakes on
  playback. E-paper holds its image without power, so the last frame
  stays visible.
- A lock state modelled on an MP3 player's hold switch: the panel draws a
  padlock, sleeps, and ignores everything until unlocked. The frozen
  frame is the lock screen, which costs nothing to display.

### Control

- An HTTP input API, so this extension never talks to GPIO and buttons
  never become a dependency. Anything that can make a request can drive
  the panel.
- A web remote at `/epaper/`, toggled by `web_remote`.
- `examples/gpio_buttons.py` as a starting point for physical buttons.
- Rapid presses are gathered for `input_coalesce_ms` and drawn once, so
  scrolling moves the cursor rather than stepping the panel through every
  position.

### Notes

- The Waveshare driver for this panel revision is vendored, because the
  `waveshare-epaper` package on PyPI predates the V4 revision. See NOTICE.
- Rendering, the menu and the screen state machine import no Mopidy and
  no hardware, which is what keeps 125 tests runnable anywhere.
