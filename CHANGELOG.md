# Changelog

All notable changes to MaiPai Bot. Format follows
[Keep a Changelog](https://keepachangelog.com); versions follow semver.
Everything stays `0.x` until the product passes its battle-tested
checklist (`docs/dev.md`).

## [Unreleased]

### Added

- BODY-05, the presence funnel's settle gate (Reachy Mini): the existing G9
  funnel in `run_loop.py` now holds every state it shows for at least 0.5 s
  (`SETTLE_GATE_S`, the legacy 45 ms flash test). Readers get the settled
  state through `RunLoopState.shown`, `ConversationLoop.subscribe_funnel()`
  and the reported `activity`; the loop itself still acts on the raw state at
  once. No second state machine: `presence/funnel.py` is only the filter.

- EYES-01, the indicator seam (Reachy Mini): `Indicator`, `Look`,
  `IndicatorSpec` and `NullIndicator` in the HAL seam, and a recording
  `FakeEyes`. The palette has no red, `blink` and `ack` are the only
  pulses, and an absent device returns at once without raising. Nothing
  drives real eyes yet.

- EYES-06 (Reachy Mini): `pyserial` is a direct dependency, and the install
  step can write the udev rule (mode 0660, group dialout) and add the daemon
  unit's service user to dialout for the Eyes serial port, idempotently. The
  rule is limited to the design's USB ids, 2e8a:10fc.

- EYES-03 (Reachy Mini): a clean-room serial client for the Reachy Eyes
  (`eyes_client.py`) with one writer thread, an exclusive port, a 50 ms write
  timeout, latest-look-wins, capped reconnect and a reply drain. Its wire
  lines are one unverified table, documented in
  `docs/dev/eyes-wire-protocol.md`, and `scripts/probe_eyes.py` shows what
  the real unit answers on arrival. Nothing is wired into the app yet.

- RM-07 egress tooling (`maipai_body/measure/netcapture.py`,
  `body/scripts/measure_rm07_egress.py`): reads a packet capture, groups the
  robot's own connections by destination and port, labels each against the
  design's allowed list and fails on an unlisted endpoint. The Reachy Mini
  privacy page's "what leaves the robot" rows are now generated from that
  list. The capture on the unit is still to do.

- G4b clips wired (Reachy Mini): the pairing code is spoken from the offline
  clips before pairing, the reconnect clip replaces the text prefix when the
  bundle can say it, and the freefall line is said once per fall. Silent
  until the clips are rendered and released.
- MOVES-01's `react` entry point: `ConversationLoop` can call a hook after the
  reply with the move a plan named, behind the `MAIPAI_BOT_REACT_MOVES` flag
  (off by default; dormant until the hub's turn stream carries a move name).
- LINK-STATE-01, the offline ladder's first rungs (Reachy Mini): a
  `connected`, `reconnecting`, `sleeping` state machine in `link/` driven by
  `LinkLifecycle` and the funnel, an address walk (LAN, then a marked
  tailnet seam for ROBOT-TAILSCALE-01), rung 0 body cues, a closed list of
  rung 1 local commands behind a recognizer interface (no real recognizer
  yet), a rung 2 status text on the app page, and `reconnecting` and
  `sleeping` published as `robot.state.activity`. What needs the unit is in
  `docs/dev/offline-ladder-unit-checks.md`.
- LINK-STATE-01 review fixes (Reachy Mini): a wake during an outage walks
  the addresses at once and runs the turn if the hub answers, else plays the
  acknowledgement and the status line instead of nothing; a body with a
  stored pairing starts the ladder at power-on with the hub away; only a LAN
  answer overwrites the stored pairing address.
- S-KWS-RUNG1 (Reachy Mini): the sherpa-onnx keyword spotter behind rung 1's
  recognizer interface for the closed command list, in `speech/kws.py`, behind
  a new optional `kws` extra and not wired into the app. The model is fetched
  and checksummed, never vendored. Fixtures are synthesized speech;
  `scripts/measure_kws.py` measures accuracy, false accepts and CPU on the unit.
  The Compute Module CPU and false-accept row is UNVERIFIED
  (`docs/dev/measurements.md`).
- The robot's state frame now carries `app_version`, the installed
  `maipai-bot` version, in every frame (`daemon_version` is still the
  vendor SDK's), so the hub can compare a robot to a Bot release.
- Measurement tooling for the design's section 12 rows (`maipai_body/measure/`,
  `body/scripts/measure_mr*.py`, `docs/dev/measure-runbook.md`): M-R2 cue to
  motion with p50 and p95 and a stall probe, M-R5 link loss on a stand-in
  hub, and hardware-only scripts for M-R1 (the Compute Module budget), M-R3
  (wake and direction of arrival) and M-R4 (battery), with unit-only checks
  gated on `MAIPAI_UNIT=1`.

### Changed

- The spec pin text moves to `spec-v0.1.73` (`reconnecting` and `sleeping`
  in `robot.state.activity`). `LinkLifecycle` now retries a stored pairing
  while the hub is away instead of asking for a new code.
- A link lost mid-sentence or while listening (the stt stream) now raises
  one `cancel` and settles the head, where mid-sentence loss used to render
  a finished reply's `settle` and a lost stt stream left the head in its
  listen pose; a turn stream that ends without `done` or `error` is a lost
  turn, not an empty one; and a lost turn is announced once, on the next
  reply that reaches the hub.

## [0.1.0] - 2026-09-28

The first release since the platform rebuild's fresh start
(`docs/dev.md`): Reachy Mini as a supported body, with real motion,
audio, and the beginning of a conversational voice loop. Not yet a
complete conversational robot; see `docs/BACKLOG.md` for what's still
missing (G3 onward).

### Added

- MOVES-01's `react` entry point: `ConversationLoop` can call a hook after the
  reply with the move a plan named, behind the `MAIPAI_BOT_REACT_MOVES` flag
  (off by default; dormant until the hub's turn stream carries a move name).
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
