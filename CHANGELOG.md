# Changelog

All notable changes to MaiPai Bot. Format follows
[Keep a Changelog](https://keepachangelog.com); versions follow semver.
Everything stays `0.x` until the product passes its battle-tested
checklist (`docs/dev.md`).

## [Unreleased]

### Added

- The robot's state frame now carries `app_version`, the installed
  `maipai-bot` version, in every frame (`daemon_version` is still the
  vendor SDK's), so the hub can compare a robot to a Bot release.

## [0.1.0] - 2026-09-28

The first release since the platform rebuild's fresh start
(`docs/dev.md`): Reachy Mini as a supported body, with real motion,
audio, and the beginning of a conversational voice loop. Not yet a
complete conversational robot; see `docs/BACKLOG.md` for what's still
missing (G3 onward).

### Added

- Reachy Mini as a supported body behind the HAL seam: a real daemon
  client, a fixture-driven fake for tests, and a profile carrying the
  unit's own measured axis limits.
- Expression and presence: procedural motion primitives (nod, listen,
  settle, and more) rendered through one arbitrated engine, plus
  presence detection and face tracking with a priority system so
  nothing fights over the body at once.
- Audio capture and playback through the daemon's own media path, the
  foundation the voice loop builds on.
- Wake-word detection: the robot listens for "hey maipai" against
  MaiPai's own trained model (attached to this release as
  `trained_hey_maipai_v2.onnx`), catches the direction the phrase came
  from, and goes back to sleep without re-waking itself on the words
  that just woke it.
- Packaging and an install script for a real unit, including removing
  any app the unit ships with by default.

### Fixed

- A cached Hugging Face login on a dev machine could silently break
  local audio entirely, not just add an unwanted outbound connection
  (`docs/dev.md`).
- `reachy-mini`'s own pinned dependency version was silently producing
  wrong wake-word scores with no error; the install now forces the
  version verified to score correctly, on both the dev bench and a
  real unit.
