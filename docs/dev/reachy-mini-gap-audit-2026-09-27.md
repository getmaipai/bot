# Reachy Mini gap audit (2026-09-27)

An audit of where the platform stands against "Reachy Mini is a real
conversational, seeing robot" (the owner's floor: wake word, STT, TTS,
vision), and a review of the two commits that landed the same evening,
`bot` `3333b68` (RM-03 vendor-app removal, EXPR-01/RM-02's muted pose
and render lock) and `home` `159e3ee8` (ROBOT-DEVICE-01's "refuses to
finish until rotated"). Every claim below was checked in the code named,
not in a commit message. Line numbers are as of `bot` `3333b68` and
`home` `159e3ee8`; the installed vendor SDK is `reachy-mini` 1.11.0 in
`body/.venv`.

The design record this audits against is
[`design-reachy-mini-2026-09-27.md`](design-reachy-mini-2026-09-27.md)
(cited by section). The backlogs are `bot/docs/BACKLOG.md` (RM-*,
EXPR-*, VOICE-*) and `home/docs/BACKLOG.md` (ROBOT-DEVICE-01,
ROBOT-ROUTES-01, ROBOT-CARD-01).

Part 1 is the commit review: real defects with a mechanism and a
failure scenario, each with a file:line pointer. Part 2 is the gap
ladder, ordered so that reading order is build order; each item names
what exists, what is missing, and an acceptance check a Sonnet-tier
session can implement without further research.

## Part 1: defects and gaps in the two audited commits

### 1.1 `bot` 3333b68: the muted pose is re-rendered on every suppressed cue, ignores arbitration, and contradicts the package's own contract

**Where.** `body/maipai_body/expression/engine.py:80-95`;
`body/maipai_body/expression/primitives.py:23-26`;
`body/maipai_body/presence/arbitration.py:52-63`.

**What the code does.** `ExpressionEngine.handle()` has no state. Every
cue whose primitive is suppressed with reason `"muted"` (that is every
`listen` and every `breathe` cue while muted, per `suppression.py:42-45`
and `68-79`) renders the muted pose again: a fresh `goto` to
`HeadPose()` with the antennas at minus 0.30 of range over 0.5 s, taken
under `_render_lock`.

**Why it is a defect, with the mechanism.**

1. `breathe` is a continuous idle primitive (the design record section
   5's table, the 8 s cycle; EXPR-04's loop is what emits it). Once that
   loop exists, every breathe tick while muted becomes a blocking 0.5 s
   `goto` to the identical pose: the real client's `goto()` blocks the
   thread until the daemon's task completes (`reachy_mini.py:722`,
   `wait_for_task_completion(timeout=duration + 1.0)`), so the idle
   loop is throttled to about 2 Hz, the daemon receives a continuous
   stream of goto tasks for a pose it is already in, and every other
   render (a turn's `nod`, a `stop` from another thread; see 1.2)
   queues behind them under the lock.
2. The muted render commands the head to neutral (`HeadPose()`,
   `reachy_mini_renderer.py:185-192`) without consulting
   `presence/arbitration.py`, whose `expression_may_drive()` says
   tracking outranks expression. A muted robot with face tracking
   enabled has its head yanked to neutral on every breathe tick while
   the daemon's tracker pulls it back. (The engine ignoring arbitration
   predates this commit; the muted pose is the first render that fires
   repeatedly with no cue from a turn, so it is the first place it
   bites.)
3. `primitives.py:23-26` says, in the same package: "`muted` is a
   state, not a cue-driven primitive; it is rendered directly by the
   mute contract, never by `map_cue_to_primitive`." The commit renders
   it from cue suppression, which is the opposite. Neither the comment
   nor the design table ("muted (a state, not a cue)", section 5) was
   reconciled.
4. There is no unmute transition. When `muted` flips back to false,
   nothing returns the antennas from the muted pose; they stay down
   until the next `settle` (a `DONE` cue) happens to arrive.

**Failure scenario.** Mute the robot from Home while it is tracking a
face and idling. Head snaps to neutral every breathe tick, antennas
re-goto to the same position twice a second, and a `stop` cue from the
turn thread waits up to 0.5 s behind whichever muted render is in
flight. Unmute: nothing moves until the next conversation ends.

**Fix shape.** Make `muted` an edge-triggered state on the engine (a
`set_muted(bool)` that renders the muted pose once on the rising edge
and `settle` once on the falling edge, both gated by
`expression_may_drive()`), and keep suppression as "rendered=False"
exactly as the generic table says. Update `primitives.py`'s comment,
`docs/dev/hal-seam.md:106` and `docs/dev.md:1396` in the same commit
(both still say "there is no muted pose"; see 1.4).

**Acceptance.** A test that handles ten `breathe` cues while muted and
asserts exactly one command reached the fake; a test that flips muted
false and asserts one `settle`-shaped goto; a test that, with
`ArbitrationState(tracking_active=True)`, the muted edge renders nothing
to the head.

### 1.2 `bot` 3333b68: the render lock makes `stop` wait, and `hold()` never cancels the daemon's in-flight trajectory

**Where.** `body/maipai_body/expression/engine.py:103-104` (the lock
around every render, `stop` included);
`body/maipai_body/bodies/reachy_mini/client.py:136-157` (`hold()`);
the vendor daemon's `reachy_mini/daemon/backend/abstract.py:841`
(every goto loop polls the global stop flag flipped by `StopMoveCmd`)
and `reachy_mini/io/protocol.py:862-872` (`StopMoveCmd`: "Stop whatever
move is currently playing (recorded move, uploaded move, goto)").

**What the code does.** `stop` (a `CANCEL` cue) is "never suppressed"
(`suppression.py:39-40`) and the design says it "cancels trajectories
and holds the pose" (section 5 table, section 7). Two things stop that
from being true:

1. The new `threading.Lock` is taken for `stop` like any other
   primitive. If thread A is inside a `goto` (blocking for the whole
   duration, up to `settle`'s 0.8 s plus the SDK's extra second of
   timeout), a `stop` handled on thread B waits for A's goto to return
   before its `hold()` is even issued. Before the lock, B's `hold()`
   went out immediately; the lock was added precisely for the two-thread
   case, and in that case it inverts the one priority the design makes
   absolute.
2. `hold()` reads the present pose over HTTP and re-issues it with
   `set_target`. It never sends `StopMoveCmd`. The daemon's goto task
   keeps writing interpolated targets until its duration ends
   (`abstract.py:841`), so "stop" during a goto is a fight between the
   held target and the task, which the task wins until it finishes.
   The SDK exposes the command path (`client.send_command(cmd)`,
   `reachy_mini/io/ws_client.py:145`), and its own `cancel_move()`
   (`reachy_mini.py:1105-1113`) only covers uploaded moves, not gotos.

**Failure scenario.** A child says "stop" mid-sentence while the idle
thread is finishing a 0.8 s `settle`: the head keeps settling for up to
0.8 s, and even when `hold()` runs the daemon's task still owns the
head until the goto's duration elapses. The M-R2 sim row for `stop`
(`docs/dev/measurements.md`, "stop | n/a") did not exercise this because
nothing was in flight when it ran.

**Fix shape.** `stop` bypasses the render lock (or the lock becomes a
priority gate that a stop may preempt), and `hold()` sends
`StopMoveCmd()` before `set_target`. Note that on a single thread this
cannot be fixed by locking at all: a blocking `goto` on the turn thread
means the `CANCEL` cue cannot be handled until the goto returns, which
is an argument for the renderer issuing gotos from a worker and the
engine never blocking the cue thread (the same shape EXPR-04's loop
needs).

**Acceptance.** With `_SlowGotoClient` (already in
`tests/test_expression_engine.py:16-36`), thread A renders `settle`,
thread B handles a `CANCEL` cue 50 ms later: assert the `hold` command
is recorded before A's goto returns. Live against the simulator: issue a
2 s goto, call `hold()` at 0.5 s, and assert the state feed stops moving
within one control tick, not at 2 s.

### 1.3 `bot` 3333b68: vendor-app removal trusts the daemon's job status, which can report "done" without removing anything

**Where.** `scripts/install-reachy.sh:57-99`; the vendor daemon's
`reachy_mini/apps/sources/local_common_venv.py:733-800`
(`uninstall_package`) and `239-300` (`_list_apps_from_separate_venvs`).

**What the code does.** The script lists installed apps (entry-point
names in the shared `apps_venv`, `local_common_venv.py:262-266`), then
for each name other than `maipai_bot` posts `remove/{name}` and polls
`job-status` until `done`. The daemon's removal is
`uv pip uninstall --python <apps_venv python> <entry-point name>` (or
`pip uninstall -y <name>`; `local_common_venv.py:754-768`). That
uninstalls a *distribution* named after the *entry point*. Both `pip`
and `uv` exit 0 with a "Skipping X as it is not installed" warning when
no such distribution exists, so the job reports `done` and the script
prints `removed X` while the app is still installed.

**Why it matters here.** The removal exists for a privacy promise
(section 8: "any app the unit ships with is removed by the install
step"; section 11 skips the cloud-backed conversation app). Store apps
scaffolded by Pollen's assistant do name the distribution after the
entry point, so the common case works; anything preinstalled on the
image that does not follow that convention silently survives. The
script has no post-condition.

**Also found.** Our own app breaks the same convention: entry point
`maipai_bot`, distribution `maipai-body` (`body/pyproject.toml:2` and
`:29`). The daemon's own dashboard "remove" and "update" for
`maipai_bot` therefore do nothing (or fail), and RM-08's "the hub pushes
the wheel the same way" will have to know that. Rename one of them
before the unit arrives (the distribution to `maipai-bot` is the smaller
change; the design's section 3 already calls the package `maipai-bot`).

**Failure scenario.** A unit ships with an app whose entry point is
`conversation` and whose distribution is `reachy_mini_conversation_app`.
The script prints `removed conversation`, restarts the daemon, and RM-07's
capture on the isolated network shows the hosted realtime backend still
being called from the robot the moment someone launches it from the
dashboard.

**Fix shape.** After the loop, `GET list-available/installed` again and
fail (exit 1) if any name other than `$APP_NAME` remains; print
`job["logs"]` joined with newlines rather than as a Python list.

**Smaller notes on the same step.** A failed or timed-out removal (30
polls at 1 s) exits after the startup app was registered and before the
daemon restart and the `/tmp` wheel cleanup, leaving the unit with
`startup_app = maipai_bot` recorded but the vendor app still running
until the next reboot; the script does not say so. Re-running is safe.
The daemon's `remove_app` (`reachy_mini/apps/manager.py:472`) does not
refuse to remove the currently running app, so removing before the
restart is fine.

**Acceptance.** The stand-in HTTP server the commit already used gains
a case where `remove` returns `done` but the installed list is unchanged;
the script must exit 1 with a message naming the app that survived.

### 1.4 `bot` 3333b68: docs left describing the pre-commit state

`docs/dev/hal-seam.md:106` ("Not yet: ... the muted pose (no mute
mechanism on this body yet)") and `docs/dev.md:1396` ("there is no
`muted` pose") both still say the pose does not exist; the commit
touched only `docs/BACKLOG.md`. The org rule is docs in the same commit.
The BACKLOG's RM-02 addition also says "antennas fully down", which is
the design table's wording, not what renders (0.30 of the antenna's
range, 0.94 rad of pi, deliberately reduced for safety); say "the muted
pose, 0.30 of range".

### 1.5 `bot` 3333b68: the muted step is outside the envelope test, and the antenna sign is unverified

`tests/test_expression_renderer.py:26-40` parametrizes the clamp check
over `PRIMITIVE_NAMES`, which excludes `"muted"` on purpose
(`primitives.py:9-26`), so the new step is never clamp-checked. It
passes today (0.94 rad inside plus or minus pi), but a later fraction
change would not be caught. Add `MUTED_STATE` to that test's parameter
list. Separately, `muted` and `attend` both assume a negative antenna
angle means "down"; nothing in the repo verifies the daemon's joint
direction (the profile's antenna limits come from the URDF but not the
sign convention). This is an M-R2 row on the unit, not a code change,
and is recorded here so the run includes it.

### 1.6 `home` 159e3ee8: the add flow has no way out when the robot never claims the approval

**Where.** `frontend/src/apps/settings/AddRobotSection.tsx:54`
(`awaitingRobot`), `:148-200` (the form is unmounted while
`awaitingRobot`), `:71-104` (`handleSubmit` is the only thing that resets
`priorRobotIds`).

**Mechanism.** After a successful approve, `priorRobotIds` is set and the
pairing form is unmounted. The only code path that clears
`priorRobotIds` is the form's own submit handler, which is no longer
rendered. The robot side of pairing (RM-05) does not exist yet, so today
every real approval ends in "Approved. Waiting for the robot to finish
pairing on its own end..." forever; the same happens whenever the Quick
Connect request expires (5 minutes, `backend/src/lib/quickConnect.ts:38`)
before the robot polls, or the robot reboots mid-pairing. Only a page
reload recovers. The retry button covers a failed poll, not a poll that
succeeds with no new robot.

**Fix shape.** A "Start over" action that clears `priorRobotIds`, and a
timeout aligned to the code's TTL that says the code expired and offers
to request a new one.

**Acceptance.** A test: approve succeeds, `/api/devices/robots` keeps
returning `[]`, assert the six-digit input is reachable again after the
action (and after the TTL with fake timers).

### 1.7 `home` 159e3ee8: "refuses to finish" is enforced only in one component's local state; the server hands out a working token before rotation

**Where.** `backend/src/routes/quickConnect.ts:81-104` (`/poll` mints
the device token and a session on consume);
`backend/src/lib/deviceTokens.ts:52-76`;
`backend/src/routes/deviceAuth.ts:47-65` (redeem, no rotation check);
`frontend/src/apps/settings/AddRobotSection.tsx:51` (`rotationDone` is
React state).

**Mechanism.** The design says a robot with the published password "is
refused by Home's add flow until it is [rotated]" (section 8). What
landed: the moment the robot's poll consumes the approval, it holds a
365-day device token that redeems for a session on every route; nothing
server-side records that the device's pairing is incomplete, and the
only "refusal" is that one admin's browser tab hides the pairing form.
Close the tab, or have a second admin look, and the robot is a fully
paired device with the vendor's password, visible only as a red badge
in `RobotPasswordSection` if someone scrolls to it.

**Failure scenario.** An admin approves the code on their phone in the
kitchen and pockets it. The robot is paired, on the household Wi-Fi,
with `pollen`'s published password, holding a year-long token, and Home
shows no Repair, no notification, nothing on the card.

**Fix shape.** A server-side gate: a `robot` device with no
`robot_credentials` row is refused at `POST /api/auth/devices/redeem`
(or at the turn, stt and tts routes) with a catalogue error such as
`robot_password_unrotated`, the robot speaks "finish adding me in
Home", and the pairing page derives its state from
`GET /api/devices/{id}/robot-password-status` rather than local
`rotationDone`. A Repair row for "a robot still has its vendor password"
is the same fact on the Repairs page.

**Acceptance.** A backend test: a `robot` device token without a
credential row is refused at redeem and accepted after
`storeRobotCredential()`; a frontend test that a reload mid-flow lands
back on the rotation step, not the pairing form.

### 1.8 `home` 159e3ee8: re-pairing an already-rotated robot cannot complete, and "Rotate again" cannot work

**Where.** `backend/src/lib/deviceTokens.ts:60` (every pairing calls
`createDevice`, a new row); `backend/src/lib/robotCredentials.ts`
(keyed by `deviceId`; `getRobotCredential()` at `:29` has no caller in
`backend/src` outside tests); `backend/src/routes/devices.ts:156-183`
(rotation always connects with the caller-supplied `currentPassword`);
`frontend/src/apps/settings/RobotPasswordSection.tsx:83` (the field is
"Current (default) password") and `:99-101` ("Rotate again").

**Mechanism.** The rotated password is stored under the device row that
existed at rotation time and is never surfaced or reused. Any second
pairing of the same unit (a revoked device, an expired 365-day token, a
token file the body finds corrupt and treats as unpaired per section 9,
a hub restore that lost the row) mints a *new* device row, whose status
is "Vendor default", and the add flow (1.7's gate) then demands the
vendor default, which no longer opens the robot. The admin cannot finish
adding a robot they already own. "Rotate again" on the standing list has
the same shape: it asks for a current password nobody knows.

**Failure scenario.** September: pair and rotate. December: the token is
revoked by mistake from the Profile page. The robot requests a new code,
the admin approves, and the rotation step refuses every password they
try. The only recovery is a factory reflash over `rpiboot` (section 1),
which is the one thing the design says a family should never need.

**Fix shape.** Key the credential by the unit, not the pairing (the
mDNS TXT `unit_id` from `lib/robotDiscovery.ts:46`, absent in
simulation, or the SSH host key, see 1.9), let `rotate-robot-password`
try the stored credential when one exists for that host before asking
for a default, and make "Rotate again" use the stored password
server-side as `currentPassword`.

**Acceptance.** A test: rotate device A for host H, revoke A, pair B for
host H, rotation of B succeeds with no password typed; a test that
"Rotate again" on A succeeds against the fake sshd with the stored
password.

### 1.9 `home` 159e3ee8: two assumptions in the rotation path only a unit can settle

Not defects in the diff; recorded so RM-07's first day checks them.

- `backend/src/lib/robotSsh.ts:70` runs `sudo chpasswd` with the new
  password on stdin. That requires `pollen` to have passwordless sudo on
  the image. Section 1 says the user has `sudo`; whether it is
  `NOPASSWD` is unverified. If not, `sudo` fails with "a terminal is
  required" and rotation never works on hardware.
- `robotSsh.ts:78-84` connects with no `hostVerifier`, so the first
  connection trusts any host key. The stored credential will later be
  sent by RM-08's install and update pushes to whatever answers at that
  address. Record the host key at rotation (trust on first use) and
  verify it on every later connection.

### 1.10 `home` 159e3ee8 (and the earlier ROBOT-DEVICE-01 landing): the device row never gets the robot's capability list

ROBOT-DEVICE-01's acceptance says the robot "appears as a device row
with its capability list from the spec vocabulary". `createDevice()`
writes `capabilities: "[]"` (`backend/src/lib/devices.ts:58`) and Quick
Connect's `/code` accepts only `label` and `kind`
(`routes/quickConnect.ts:28-31`). The capability list the profile
declares (`body/maipai_body/bodies/reachy_mini/profile.py:36-49`) has no
way to reach the hub. The item is checked off in `home/docs/BACKLOG.md`
with this acceptance unmet, which matters because ROBOT-CARD-01 and the
Devices page are designed to render from that list (section 9). Track it
with G4 and G5 below; the cleanest carrier is a `capabilities` field on
the `/code` request, validated against `commons`'s vocabulary once RM-00
lands.

## Part 2: the gap ladder to a minimally conversational, seeing robot

### 2.0 What exists today, in one table

| Piece | State | Where |
|---|---|---|
| HAL seam: `HeadActuator`, `StateFeed`, `AudioIO`, `Camera`, `Imu`, `FaceTracker` | Built, live-verified on the simulator | `body/maipai_body/hal/seam.py` |
| Reachy Mini client and fake | Built; `AudioIO` and `Camera` are typed `object` and the fake returns `None` for both | `body/maipai_body/bodies/reachy_mini/{client,fake}.py` |
| Expression: cue mapping, suppression, the Reachy Mini render column, the engine | Built for scripted cues; no blending; ignores arbitration; 1.1 and 1.2 above | `body/maipai_body/expression/` |
| Presence inputs: face target, direction of arrival, IMU tip and freefall; the arbitration priority | Built; nothing calls `read_presence()` or `enable_tracking()` at runtime | `body/maipai_body/presence/` |
| The app the daemon runs | A scaffold: goes neutral, holds, waits for stop. No audio, no link, no page | `body/maipai_body/app.py` |
| Wake word, VAD, endpointing, capture | Nothing. No `body/maipai_body/speech/` exists | (VOICE-01, RM-04) |
| Hub client, pairing, the turn stream, TTS playback | Nothing | (RM-05, RM-04) |
| Hub: discovery, Quick Connect for kind `robot`, device tokens, redeem | Built (with 1.6 to 1.10 open) | `home/backend/src/{lib,routes}/{robotDiscovery,quickConnect,deviceTokens,deviceAuth,devices}.ts` |
| Hub: turn stream with `surface: robot`, `signal` and cancel, stt transcribe, tts stream | Built for a session cookie; identity and scoping are the gap (G5) | `home/backend/src/routes/{turn,stt,tts}.ts` |
| Hub: device state route, the robot card, the update row | Nothing | (ROBOT-CARD-01) |
| Still image to the hub, any vision on a robot frame | Nothing on either side; v0.2 by design | (G11) |

Build order below: G1 to G3 are body-only and need no hub; G4 and G5
unblock everything after; G6 to G9 are the conversation; G10 and G11
are after the floor.

### G1. Audio capture and playback through the daemon's media path (bot, S-M)

**Depends on:** nothing. **Blocks:** G2, G3, G7.

**What exists.** The seam's `AudioIO` protocol
(`hal/seam.py:187-201`) and the client's pass-throughs
(`bodies/reachy_mini/client.py:173-189`), typed `object`, with no
consumer. The fake returns `None` (`fake.py:156-170`).

**Verified vendor facts (read in the installed 1.11.0 package).**
`reachy.media.start_recording()` must be called first
(`reachy_mini/media/media_manager.py:280-285`); `get_audio_sample()`
then returns a float32 array of shape `(n, 2)` (stereo) at 16 kHz or
`None` when nothing is queued
(`media/audio_gstreamer.py:174-190`, `media/audio_base.py:116`).
Playback: `start_playing()` then `push_audio_sample(float32)` mono
`(n,)` or `(n, ch)`, at 16 kHz output, mono duplicated to the device's
channels by the manager (`media_manager.py:334-378`); `stop_playing()`
flushes. `get_DoA()` returns `(angle_rad, speech_detected)` or `None`
(`audio_gstreamer.py:601-609`). The app's `ReachyMini` is built by the
daemon with `media_backend="default"` and a local connection when the
daemon is on localhost (`reachy_mini/apps/app.py:45-49, 138-150`), which
is the Wireless's own IPC path.

**Missing.** A `body/maipai_body/speech/` package with: a capture thread
that pulls samples, downmixes to mono (channel 0, or the mean), and
yields 32 ms blocks (512 samples at 16 kHz) into a ring buffer that
keeps 0.3 s of pre-roll; a playback writer that accepts 16 kHz mono
float32 chunks, calls `start_playing()` once, pushes, and records a
ledger of what was pushed and when (monotonic clock); typed `AudioIO`
(replace `object` with `numpy.typing.NDArray[np.float32]`); a fake that
plays a WAV fixture as its microphone and records pushed audio.

**Acceptance.** Deterministic: the fake fed a 3 s 16 kHz WAV yields
about 94 blocks of 512 mono samples, and the pre-roll ring holds the last
0.3 s. Live (`MAIPAI_BODY_LIVE=1` against `reachy-mini-daemon --sim`): a
5 s capture writes a 16 kHz WAV, and a pushed 1 kHz tone appears in the
sim's playback path without underrun warnings in the daemon log. If the
simulator has no audio device, the recorded finding is "sim audio
unavailable", not a skipped item.

### G2. Wake word on the robot (bot, M)

**Depends on:** G1. **Blocks:** G3, G8.

**What exists.** Nothing in `bot`. The hub's own wake-word assets are
the stock `hey_jarvis_v0.1.onnx` plus the openWakeWord front-end
(`home/backend/src/lib/wakewordAssets.ts:37-51`), and `dev.md:365` says
the stock phrase never ships on the robot (non-commercial). The trained
`hey_maipai.onnx` (openWakeWord format, v2 calibrated at 0.8, "0.00
false accepts/hr at 85 percent recall" claimed in-source, recording set
to be re-verified) lives only in the legacy mirrors:
`legacy-backups/home-legacy.git:backend/assets/wakewords/trained_hey_maipai_v2.onnx`
with `trained-manifest.json` beside it, and the legacy robot installed
it as `wakeword/hey_maipai.onnx`
(`legacy-backups/bot-legacy.git:robot/robot/packs/manifest.py:146-157`).
The scorer and the wake state machine to port are
`legacy-backups/bot-legacy.git:robot/robot/hal/drivers/voice.py`
(`OpenWakeWord` at lines 178-217, `OnnxRecognizer` at 306-427; the
constants at 40-67: `WAKE_THRESHOLD = 0.8`, `WAKE_PATIENCE_S = 6.0`,
`PRE_ROLL_S = 0.3`, `TRAILING_SILENCE_S = 0.7`, `MAX_UTTERANCE_S = 12.0`).
Read it with `git -C legacy-backups/bot-legacy.git show HEAD:robot/robot/hal/drivers/voice.py`.

**Missing.** (a) The artifact shipped the org's way: a Bot release asset
(or a wakeword catalog package) fetched on demand at a pinned URL with a
checksum, never tracked; the front-end models' (melspectrogram,
embedding) license verified and recorded in `docs/dev.md` before v0.1,
as `dev.md:365` already requires. (b) `onnxruntime` for aarch64 in a
real-hardware dependency group (see G12). (c) A `WakeScorer` over G1's
blocks with the front-end the trainer used, the threshold from the
manifest, and a reset after each utterance so a phrase left in the
buffer cannot re-wake (legacy `voice.py:207-217`). (d) Direction of
arrival captured at the wake instant from `get_DoA()` for the `listen`
cue.

**Acceptance.** Deterministic, offline: a recorded "hey maipai" fixture
wakes exactly once and a near-miss fixture ("hey my bike") never does;
the wake stamp lands within 200 ms of the phrase's end in the fixture.
M-R3 on the unit records the real numbers later; the fixture rows are
the gate for now.

### G3. VAD and endpointing: the utterance that leaves the robot (bot, S-M)

**Depends on:** G1, G2. **Blocks:** G6.

**What exists.** Nothing. The hub side runs Silero and Moonshine
through `sherpa-onnx` (`home/backend/src/lib/stt.ts:40`, 16 kHz
features), which fixes the input contract: 16 kHz mono.

**Missing.** Silero VAD on G1's blocks (onnxruntime directly as the
legacy `SileroVad` did, `voice.py:219-257`, or `sherpa-onnx`'s VAD;
either is prebuilt, pick the one already in the dependency set from
G2); the endpointer with the legacy rules: keep 0.3 s of pre-roll before
the first speech block, not from the wake word; wait `WAKE_PATIENCE_S`
for speech before sleeping; end on 0.7 s of trailing silence or at 12 s;
emit an `Utterance` (float32 mono 16 kHz, start and end monotonic
stamps, the DoA at wake). The semantic endpointer the legacy added
("Smart Turn", `voice.py:50-58`) is out of scope for the floor.

**Acceptance.** The RM-04 privacy test in the backlog's own words: with
a fixture of 2 s of room noise, the wake phrase, 1 s pause, a question,
2 s silence, the emitted span begins at most 0.3 s before the question's
first speech block and ends within 0.7 s of its last; the noise before
the wake is not in it (assert on sample counts). A "woken but silent"
fixture returns to sleep at 6 s with nothing emitted.

### G4. The hub client on the robot: discovery, pairing, the sealed token (bot, M; RM-05's first half)

**Depends on:** G1 for the spoken code only (see the open point).
**Blocks:** G6, G7, G8, G10.

**What exists on the hub (all verified).**

- Home advertises itself as `_maipai._tcp` (`home/backend/src/lib/mdns.ts`).
- `POST /api/auth/quick-connect/code` with `{label, kind: "robot"}`
  returns `{code, poll_token}`; the code is 6 characters from the
  alphabet at `lib/quickConnect.ts:43` (no 0/O/1/I), good for 5 minutes
  (`routes/quickConnect.ts:19-56`).
- `GET /api/auth/quick-connect/poll?poll_token=...` returns `pending`,
  then `approved` exactly once with `device_token` and `expires_at`
  (365 days), and also sets a `session` cookie for the polling address
  (`routes/quickConnect.ts:81-104`).
- `POST /api/auth/devices/redeem` with `{token}` sets a fresh `session`
  cookie (`routes/deviceAuth.ts:34-65`). Sessions last 7 days
  (`lib/session.ts:20`), so the client re-redeems before expiry or on
  any 401. The cookie is `Secure` when the hub is reached over https
  (`lib/session.ts:54-61`): the robot talks to the hub over https using
  the household CA from `GET /api/setup/ca`, or over the hub's plain
  http LAN address; pick one and pin the fingerprint either way.
- The CSRF check passes a request with no `Origin` header
  (`middleware/auth.ts:121-122`), so a Python client needs no browser
  headers.
- Nothing carries the robot's capability list (1.10).

**What exists in `bot`.** Nothing. `app.py:81` sets
`custom_app_url = None`, so the daemon starts no settings page for the
app (the SDK starts a FastAPI settings server only when `custom_app_url`
is set, `reachy_mini/apps/app.py:52-60`). The legacy token store to port
is `legacy-backups/bot-legacy.git:robot/robot/hublink/pairing.py`
(`HubPairingStore`: sealed with the device key, 0o600, atomic replace,
a corrupt file means unpaired) and the legacy client shape is
`robot/robot/hublink/client.py` (`HubClient.establish_session`).

**Missing.** A `body/maipai_body/link/` package: browse `_maipai._tcp`
(the `zeroconf` package, already the vendor's own discovery dependency),
request a code as kind `robot` with the unit's name as the label, poll
until approved, seal the token, redeem for a session, pin the hub's TLS
fingerprint, and re-redeem on 401 or before the 7-day session ends. The
app's own page (`custom_app_url`, served by the SDK's settings server)
shows the code and the link state. The robot never mentions a hub it was
not paired with (section 4).

**Open design point the implementer must not guess.** Section 9 says the
robot *speaks* the code, but in the `pod` tier synthesis lives on the
hub, which an unpaired robot cannot call. Two honest resolutions: ship
pre-rendered clips for the 32 code characters and a short prompt as a
Bot asset (a few hundred kilobytes, rendered once from a MaiPai voice
at release time), or make the app page the only surface for the code
until the `robot` tier exists. Dispatch `design-resolver` on this
before G4 is coded; do not ship a third option.

**Acceptance.** A pytest stand-in for the hub (a small HTTP server in
the test, the same pattern RM-03's commit used) runs code, approve,
poll, redeem; the token file is 0o600 and survives a restart; a hub
presenting a different fingerprint is refused; a corrupt token file
reads as unpaired. Live: against a dev hub, the Devices page's add flow
completes end to end, which also closes 1.6's "waits forever" for the
happy path.

### G5. Hub: the robot's identity and scoping on the turn, stt and tts routes (home, S-M; ROBOT-ROUTES-01)

**Depends on:** nothing in `bot`; G4 to exercise live. **Blocks:** G6,
G7 being correct rather than merely working.

**What already works with a session cookie from redeem.**
`POST /api/turn/stream` accepts `surface: "robot"`, `spoken: true`,
`speaker_evidence` and `present` (honored only on the robot surface,
`routes/turn.ts:678-810`), emits newline-delimited JSON events
`turn_meta`, `signal` (WIRE-01's `TurnSignal`, `wire.ts:377`), `delta`,
`status`, `spoken_cue`, `done`, and `error` with
`code: "turn_cancelled"` on cancel (`turn.ts:631`).
`POST /api/turn/{turn_id}/cancel` works when the caller is the turn's
owner (`turn.ts:103-126`). `POST /api/stt/transcribe` takes a raw
`audio/wav` body and returns `{text}` (`routes/stt.ts:79-113`); the
decoder accepts 16-bit mono PCM only (`lib/sttSession.ts:393-394`).
`POST /api/tts` with `{text}` streams `audio/wav` in the caller's
`tts.voice_id` voice (`routes/tts.ts:10-58`).

**What is missing, precisely.** The device token resolves to the
*approving admin* (`lib/deviceTokens.ts:52-76`,
`redeemDeviceToken` returns that `personId`). So every utterance from
anyone in the house runs as the admin: the conversation is the admin's,
memories written are the admin's, the reply voice is the admin's
`tts.voice_id`, and the cancel route's owner check is the admin. The
safety floor still holds because `effectiveBand()` drops an unnamed or
unmatched speaker to the child band on the robot surface
(`lib/turnContext.ts:44-47`) and `sensitiveAllowed()` withholds
sensitive records unless the body confirms the speaker is alone
(`:54-60`). What the design asks for (section 6; ROBOT-ROUTES-01's own
words) is a turn "scoped to that device's own conversation and the
person its evidence names". That needs: a device principal (the token's
`deviceId` on the request context), the acting person chosen from
`speaker_evidence` when it names a confirmed household person and a
per-device household voice otherwise, the conversation keyed by device
id, and a test that a robot token cannot read or cancel another
device's conversation. No new route is needed.

**Acceptance.** ROBOT-ROUTES-01's own: the bot fake completes a
three-turn conversation through these routes; a robot token cannot read
another conversation; tests in those words. Add: a turn with
`speaker_evidence.person = <child>` at `confirmed` writes its turn row
under the child, not the admin.

### G6. The turn round trip from the robot (bot, M; RM-04 and RM-05 together)

**Depends on:** G3, G4, G5. **Blocks:** G7 in practice (nothing to
speak until a reply exists), G9.

**Missing.** Encode G3's utterance as 16-bit mono WAV (the only shape
the hub decodes, G5) and `POST /api/stt/transcribe`; then
`POST /api/turn/stream` with `surface: "robot"`, `spoken: true`,
`speaker_evidence: null` and `present: null` until SPEAK-01 exists
(unknown speaker is the honest value, and the hub treats it as a child);
read the event stream and translate to expression cues: `turn_meta`
then `signal` becomes `Cue(phase=SIGNAL, ...)` mapped through
`cue.py:50-99` from the `TurnSignal`'s `primary_act`,
`expressed_emotion` and `emotion_intensity` fields (EXPR-03's job, but
the floor needs at least `HEARD`, `SIGNAL`, `SPEAK`, `DONE`, `CANCEL`);
`done` becomes `DONE`; `error` with `turn_cancelled` becomes `CANCEL`.
Hold the `turn_id` for the cancel route. On any connection failure
mid-turn, `cancel` with reason `link_lost` (section 7) and say the one
register-guard line once per outage (section 4).

**Acceptance.** A stand-in hub in the test returns a scripted transcript
and a scripted event stream; the body records cues in the order HEARD,
SIGNAL, SPEAK, DONE against the fake and the STT upload's bytes equal the
endpointed span (G3's test extended across the wire). The link-lost
fixture (the stand-in closes mid-stream) produces exactly one CANCEL cue
and one spoken line.

### G7. The reply on the robot's speaker: streamed TTS playback (bot, S-M; RM-04)

**Depends on:** G1, G4, G5. **Blocks:** G8.

**What exists.** The hub streams WAV from `POST /api/tts` (G5). The
browser's chunk handling to mirror is
`home/frontend/src/lib/streamingWavPlayer.ts`: parse only the 44-byte
header for `sampleRate`, `numChannels`, `bitsPerSample`; never trust the
header's data-chunk size (Pocket TTS writes a placeholder,
`streamingWavPlayer.ts:9-14`); start playing at the first 4 KB and end
when the stream ends.

**Missing.** A player in `body/maipai_body/speech/` that reads the
stream, decodes 16-bit PCM to float32, resamples from the voice's rate
to the daemon's 16 kHz output (`audio_base.py:116`; a maintained
resampler such as `soxr` or `scipy.signal.resample_poly`, never a
hand-rolled one), pushes through G1's writer, and stops on cancel.
Emit the `SPEAK` cue at the first pushed chunk (the design's onset
ordering: expression before the first audio sample) and `DONE` when the
stream ends. Note the vendor ships its own speech-reactive head sway
(`HeadWobbler`, enabled through `media.enable_wobbling()`,
`audio_gstreamer.py:611-629`); section 5 designs `speak` as our own
primitive from the playback ledger. Principle 6 (prebuilt over
hand-built) argues for evaluating the vendor's wobbler; the design's
envelope and arbitration argue against a motion source outside the
seam. Record the choice in the design record before wiring either; do
not enable both.

**Acceptance.** A stand-in server streams a 24 kHz 16-bit mono WAV
fixture in 1 KB chunks; the fake records 16 kHz mono float32 pushes
whose total duration matches the fixture within one block, the ledger
holds the pushed prefix when the stream is stopped at 40 percent, and
the SPEAK cue's stamp precedes the first push. Live on the sim: a
sentence from a dev hub is audible through the sim's output path.

### G8. Barge-in, the stop, and the honest software mute (bot, S-M; RM-04 with VOICE-02 and BODY-07's wording)

**Depends on:** G2, G6, G7, and 1.2's fix. **Blocks:** the RM-04
acceptance ("stop over playback is heard").

**Missing.** Wake and VAD keep running during playback (the unit's XMOS
echo cancellation is what makes that possible; the sim's software AEC
stands in). "Stop" heard during playback cuts playback locally within
one block (`stop_playing()`), posts `POST /api/turn/{id}/cancel`, and
handles a `CANCEL` cue (whose `stop` render must actually cancel the
daemon's trajectory, 1.2). The software mute is a state: capture
continues but zero blocks reach the wake scorer and the endpointer, the
label is "software mute" wherever the product names it (`dev.md:685-699`,
BODY-07, section 8: this body will never have the physical cut), the
muted pose renders once on the edge (1.1), and the state is in the
device frame (G10).

**Acceptance.** Fixture: a reply playing, "stop" in the capture stream
at 1.5 s; playback stops within 32 ms of the wake stamp, one cancel
request is sent, the CANCEL cue's `hold` reaches the fake before any
further push. Muted: a full wake-plus-question fixture yields zero
utterances and zero STT uploads, and the words "physical mute" appear
nowhere in `body/` (a grep test, SETUP-04's shape).

### G9. The run loop: one state machine driving audio, cues, tracking and the head (bot, M; BODY-05's funnel on this body, EXPR-04's loop, RM-05's second half)

**Depends on:** G6, G7, G8. **Blocks:** G10.

**What exists.** `app.py:52-75` (`run_body`: goto neutral, hold, wait).
`ExpressionEngine.handle()` for discrete cues. `presence/arbitration.py`
(the priority) and `presence/observations.py` (`read_presence()`), both
unused at runtime. `FaceTracker.enable_tracking(weight)` toggles the
daemon's own tracker, which then drives the head itself
(`client.py:219-231`).

**Missing.** Replace `run_body`'s idle wait with the loop: a presence
tick (`read_presence()` at a few hertz) feeding an `ArbitrationState`;
the funnel's states `idle`, `listening`, `thinking`, `speaking` derived
from G6's events and G8's mute; expression rendered only when
`expression_may_drive()`; tracking enabled when a face is present and
no turn is speaking, disabled under `stop` and service; the `breathe`
idle policy with its suppressions (EXPR-04). One conflict to settle in
code, not by default: `track`'s renderer issues `set_target(yaw=doa)`
(`reachy_mini_renderer.py:57-60`) while the daemon's tracker, once
enabled, also moves the head; on this body `track` should mean "the
daemon's tracker owns the head at weight w", not a second target. Body
yaw following past the 65 degree delta (the RM-02 gap) belongs here.

**Acceptance.** RM-05's own: a three-turn conversation on the simulator
with cues rendered before the first audio sample on eligible rows;
M-R5's link-loss rows behave as section 7 says. Deterministic: the
funnel's state trace for a scripted turn has no state shorter than the
0.5 s settle gate (BODY-05's legacy flash test).

### G10. The device state frame and the robot's card (home and bot, S each; ROBOT-CARD-01)

**Depends on:** G4, G5, G9.

**What exists.** Nothing on either side: no route under
`home/backend/src/routes/` accepts a device's state, and the Devices
page has no card. `DeviceSchema` (`routes/devices.ts:17-24`) carries no
state.

**Missing.** A hub route (`POST /api/devices/{id}/state`, authenticated
by the device's own session, additive) or a state frame on the turn
stream's connection; the body posting `{activity, muted, tracking,
on_battery: "unknown", daemon_version}` on every change and at a slow
heartbeat; the card from the dashboard template's widget with "battery
level unknown" as designed (section 8, M-R4); the daemon's version and
its PyPI update as a row on the Updates page, applied only on a click.

**Acceptance.** ROBOT-CARD-01's own: the fake's frames render on the
card at 1440 and 390; the update row does nothing until clicked;
captures opened and judged.

### G11. Vision: what "seeing" means on the floor, and the still image that is not built (bot and home)

**Depends on:** G9 for presence; the still image waits on a design
decision.

**What exists.** The floor of "seeing" on this body is presence: the
daemon's face tracking (enable, disable, `get_face_target()`,
`client.py:219-247`; a 1 s wait that returns `detected=False` on
timeout) and the array's direction of arrival and speech flag, folded
into `PresenceObservation` (`observations.py:22-50`), with tip and
freefall from the IMU (`safety.py`). Live against the simulator the
mechanism was proven and every value was honestly absent (no face, no
IMU, no DoA in the sim scene; RM-06's note). The seam's `Camera`
(`seam.py:204-210`) and the client's `get_frame()` (`client.py:193-195`,
the SDK returns a `uint8` frame or `None`) exist with no caller anywhere
in the repo.

**Not built, on either side, and v0.2 by design (sections 4 and 6).**
"A still image for the hub is the v0.2 host call the design already
names, consented and explicit." On the hub, a turn accepts
`document_attachments` (`routes/turn.ts:699-719`), whose image types
reach only OCR (`lib/documentExtraction.ts:209`); the Stack declares a
`vision` role id (`wire.ts:722`) but no route feeds a device's image to
it. On the body, nothing captures a frame for anything. Face identity
is explicitly out (section 4: the CM4 has no room beside speech).

**What to do for the floor.** Nothing beyond G9: wire presence and
tracking into the run loop so the robot turns to a face and toward a
speaker. Record the still-image call as its own design item (the
consent prompt, the one-shot capture, the hub route, the vision role)
before any code; the floor does not need it and the owner named vision
as presence-and-tracking-level "seeing" in the v0.1 table.

**Acceptance for the floor.** In G9's live run on the simulator with a
face injected into the sim scene (or on the unit), tracking engages
within one presence tick of `detected=True`, the head follows, and a
`stop` overrides it (the arbitration test, live).

### G12. Packaging for the unit (bot, S)

**Depends on:** nothing; must land before the unit's first install.

- `body/pyproject.toml:7` pins `reachy-mini[mujoco]`, pulling the
  simulator onto the robot (`scripts/install-reachy.sh:18-22` already
  records this). Split a `[sim]` group for the bench from the runtime
  dependencies, and add `onnxruntime` (aarch64 wheels exist) and the
  resampler from G7 to the runtime set.
- The entry-point and distribution name mismatch (1.3): rename the
  distribution to `maipai-bot` so the daemon's own remove and update
  paths, and RM-08's push, address the app by one name.
- `tool.uv.environments = ["sys_platform == 'darwin'"]`
  (`pyproject.toml:35-46`) means the lockfile never resolves the robot's
  Linux set; the wheel's pinned dependencies are what `pip` resolves on
  the robot at install time (section 10's one listed install-time
  outbound connection). Either lock for both platforms or record the
  Linux resolution in the release's measurement header.

**Acceptance.** `uv build --wheel` from a clean clone on the dev Mac,
then `pip install` of that wheel in a fresh Linux aarch64 venv (a
container is enough) pulls no `mujoco` and imports `maipai_body.app`.

## Hub items this ladder needs, restated

| Hub item | State | What the ladder needs from it |
|---|---|---|
| ROBOT-DEVICE-01 | Checked off; 1.6 to 1.10 open | The server-side "not finished until rotated" gate, unit-keyed credentials, the capability list on the row |
| ROBOT-ROUTES-01 | Open | G5: the device principal and the evidence-named person; the scoping test |
| ROBOT-CARD-01 | Open | G10: a state route and the card |
| RM-00 (commons BODY-VOCAB-01) | Open | The capability ids the row carries (1.10, G4) |

## What this audit did not do

No code was changed and nothing was run against a live daemon; every
"verified" above is a read of the installed package or the repo at the
commits named. The two "only a unit can settle" items (1.5's antenna
sign, 1.9's sudo and host key) are listed for RM-07's first day rather
than guessed.
