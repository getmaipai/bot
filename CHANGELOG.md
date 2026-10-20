# Changelog

All notable changes to MaiPai Bot. Format follows
[Keep a Changelog](https://keepachangelog.com); versions follow semver.
Everything stays `0.x` until the product passes its battle-tested
checklist (`docs/dev.md`).

## [Unreleased]

## [0.2.6] - 2026-10-20

### Fixed

- Silence, a timeout and an empty transcript end a StackChan turn quietly, with no spoken line, and the host sends a `system idle` command so the device leaves Listening instead of re-opening the microphone in a loop. A listen the device re-opens within 2 seconds of a turn end gets an 8 second follow-up window; an early "no speech" inside the 6 second patience opens a fresh recognition stream instead of ending the turn; the first 0.3 seconds after a listen start (the pop-up tone) is not sent to recognition; the apology needs at least 0.5 seconds of speech detected by the hub.
- A loop breaker for the canned error and offline lines: at most once per 60 seconds, never twice in a row, never within 3 seconds of other speech, and silent after more than 3 requests in 2 minutes until the next real transcript.
- The face is reset in order with speech: `llm neutral` goes out right before every speech stop, the speaking cue is neutral, a face watchdog resends the idle face after 5 quiet seconds and every 30 seconds after (skipped while resting or at night), and an abnormal end while speaking sends a speech stop. The thinking ring light is violet.

### Added

- Volume by voice on the robot: "louder", "quieter", "turn it up", "turn it down", "volume to N", "maximum volume" and "mute", handled before the hub in steps of 15 (minimum 20, mute is 0), answered with "Volume N."
- A plain per-voice pitch offset (`speech/pitch.py`, -12 to 12 semitones; 0 returns the audio untouched) shared by the robot and Home.
- StackChan firmware patch 034: a `system idle` command that returns the device to Idle from Listening or Speaking. Patches to flash since 0.2.2: 030, 032, 033, 034.

## [0.2.5] - 2026-10-20

### Fixed

- A built-in answer (the time, a timer) arrives only in the final message as `value.reply.text`, with no streamed text pieces; the turn client read replies from the pieces alone, so those answers came back empty and the robot said nothing. The final message now wins when it carries the text.
- The hub command channel gets `(url, cookie)` in the order it unpacks them; it used the cookie as the URL and reconnected every 30 seconds with a ValueError.
- The face is set over the voice socket when the avatar channel is not connected (the avatar channel never starts in AI-agent mode), and the per-turn connection errors are gone.
- A short voiced burst, such as the listening tone, no longer ends the turn: when the hub answers no speech inside the 6 second wake patience and the device has not stopped, a fresh stream keeps listening before the error line is spoken.
- The first 180 ms of an utterance is no longer dropped, and the listen frame's mode and echo-cancel flag are forwarded.

### Added

- StackChan firmware patch 033: a plain "Connecting" screen with the blue slow pulse until the robot is ready, the face hidden until it is, and the ring settling to idle white.

## [0.2.4] - 2026-10-20

### Fixed

- The reply plays: after each sentence the turn stopped playback on the server's event loop, and sending the audio needed that same loop, so every reply deadlocked for exactly 30 seconds and failed with a timeout. Playback now stops on a worker thread (a test asserts it never runs on the loop thread).
- The turn request leaves out `speaker_evidence` and `present` when they are empty instead of sending null, so older hubs accept it.
- The voice session logs the speech out: each sentence started, synthesized and sent with timings, and when the reply finished playing; a failed turn logs the exception text.
- The StackChan avatar channel logs every connection, each refusal with its reason, and the connected state; the hub command channel logs the exception and a traceback when it reconnects.

### Added

- The turn funnel drives the ring: blue the moment a turn opens, green while audio streams to the hub, magenta slow breathe while thinking, white while speaking.

## [0.2.3] - 2026-10-20

### Fixed

- A voice turn no longer freezes: the face and ring updates ran inline on the server's event loop and each device call blocked it for up to 5 seconds, which caused the slow turn start, the late first audio frame, the device call timeouts and the early "no speech" result. They now run on one worker thread, in order, and a slow device cannot delay the turn.
- The StackChan stays still when it cannot tell: an unknown or stale (3 minutes) power state counts as plugged in, idle motion is turned off before any battery reading and retried every 5 seconds, `robot.idle.level` is read from the settings frame (Still turns idle motion off), and idle settling and face following are skipped while still.
- The ring no longer sticks on the camera pink: local watching (face tracking, the night light read) shows no cue and follows `robot.camera.watch_level`, while a visible camera stream or photo still lights pink and clears.
- Battery and head reads retry once.

### Added

- The StackChan sleeps when nothing happens: the presence loop runs the rest policy, so after quiet minutes it rests.

## [0.2.2] - 2026-10-20

### Fixed

- StackChan firmware patch 032: with the always-open websocket from patch 003, a detected wake word took the "channel already opened" branch and returned without leaving Idle, so "Hi, StackChan" was heard but never started listening. The device now enters Connecting first in both wake word paths (BOT-STACKCHAN-WAKE-01).
- The hosted Bot app configures logging when it runs under the hub (INFO, timestamped, to stderr), so the voice session lines reach the hub's log.
- The light poller reads the offline rungs that own the state machine instead of the link lifecycle, which had no such attribute and crashed on every poll; the "connecting" cue is a blue pulse.
- A failed StackChan tool call logs its real exception type and message once a minute per tool.
- The idle settle head move is skipped while the robot is on USB power.

### Added

- Per-part self-test (BOT-SELF-TEST-01): `python -m maipai_body.selftest --list` and `--only led,movement,camera,hearing,wakeword,speech,reply` run plain pass, fail or skip checks with a fix line against the live StackChan service, on loopback only; the voice bridge keeps frame, byte, peak level and wake counts, never audio or words.

## [0.2.1] - 2026-10-20

### Fixed

- StackChan firmware patch 030 loads the assets already on the flash (the wake word model, fonts and emoji) without any vendor download; patch 002 had skipped the only call that does it, so "Hi, StackChan" could not trigger and the boot log showed `MODEL_LOADER: Can not find model in partition table` (BOT-STACKCHAN-WAKE-01).
- A hosted body never sets the host computer's clock or runs `sudo` (523 failed `date -s` attempts on a live hub), and the night light read uses the camera driver's `stream_frame`.
- A stop caused by a lost StackChan link is released about 3 seconds after the device answers again; a stop a person pressed is never released by itself.
- Health-check connections that send no bytes log nothing, and a face detector that cannot import in the hub bundle is one quiet log line, not a traceback.
- `XiaozhiDeviceClient.set_led_colors` exists for the per-pixel LED tool.

### Added

- The StackChan voice session logs every stage at INFO with counts only, never audio or words: listen start, first audio frame, turn start and end, speech-to-text result length, chat result length, and a warning when the hosted bot has no hub session.
- StackChan stays still while charging or on USB power: the battery poll feeds a power rule that switches the firmware idle motion off, and the configured level returns on battery.
- StackChan firmware patches 020 (dance tools), 021 (touch and shake event queue) and 023 (saved Wi-Fi tools); the camera cue is two pink flashes then steady pink; a light service drives the ring (live, offline, charging and low-battery looks).

## [0.2.0] - 2026-10-20

### Changed

- StackChan firmware patches 018 and 019 take the long-lived token from the hub's hello, save it to NVS, and have the avatar channel read its token and address from NVS (BOT-STACKCHAN-ENROLL-01, firmware half).
- StackChan provisioning sets `boot_ai` and `is_configed` so the robot boots straight into the AI Agent without the Welcome screen.
- Pin the body checks and release asset lookup to the robot API vocabulary in `spec-v0.1.141`.

### Added

- `scripts/cut-release.sh` stages the three hub bundles and signed StackChan firmware asset, signs the complete `SHA256SUMS`, and prints the owner's publish command without uploading (BOT-RELEASE-FLASH-01).
- StackChan releases take the signing key from the macOS Keychain (`--signing-key keychain:<item>`), `scripts/sign-release-sums.sh` signs `SHA256SUMS` into `SHA256SUMS.sig.json`, and `verify.sh --public-key` checks the flash manifest signature (BOT-RELEASE-FLASH-01).
- StackChan firmware releases can be staged as `stackchan-firmware-<version>.tar.gz`, containing the signed flash manifest and its parts and listed in the release `SHA256SUMS` (BOT-RELEASE-FLASH-01, asset half).
- StackChan releases now ship bootloader and partition table binaries with a signed flash manifest generated from ESP-IDF flash offsets (BOT-RELEASE-FLASH-01, release half).

- StackChan face color and night mode in the Bot app (BOT-FACE-NIGHT-01): `robot.face.color` and `robot.night.mode` arrive on the existing command channel; the night rule (quiet hours, light hysteresis, camera fallback unless watch is off) dims the screen, drops the voice to 40%, turns LEDs and idle motion off, and never lowers an alarm. Thresholds pending measurement on the unit; nothing flashed.

- StackChan firmware patch 017 (BOT-FACE-NIGHT-01): MCP tools `self.screen.set_face_background` (seven palettes and a night face, palette kept in NVS), `self.robot.set_idle_motion` and `self.screen.get_ambient_light` (LTR-553). Built, not flashed.

- EYES-02, the Eyes director (Reachy Mini): one look table (`indicator/looks.py`,
  no red), a director that reads only the funnel's shown state and the
  live-capture facts, and `LiveCaptureTap`, which wraps the mic and camera so
  the green cue shows whenever the voice is being sent to the hub and cannot be
  bypassed or turned off. Seven robot-only settings (`robot.indicator.*`), and
  the profile declares `eyes` only while the Eyes are connected. Not run on a
  unit.

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
