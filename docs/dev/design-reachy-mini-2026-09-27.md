# Design record: Reachy Mini as a MaiPai Bot body (2026-09-27)

The owner ordered a Reachy Mini Wireless (Pollen Robotics, sold through
Hugging Face; lead time up to 90 days) and asked for it to be an
officially supported body, with a design for how the platform uses it,
a decision on which repo its code lives in, and a read of Pollen's app
ecosystem for what MaiPai should learn from it or use. This record
answers all three. It amends the robot design record
([`../dev.md`](../dev.md)) and builds on the research note of the same
morning
([`research-minicpm5-reachy-mini-2026-09-27.md`](research-minicpm5-reachy-mini-2026-09-27.md)),
which said what the robot is; this says what we do with it. Facts come
from Pollen's own docs and repos on the date above and are cited at the
end; anything not verified is marked.

## Why this design exists

Below the platform sits a robot we did not build: a Python daemon that
owns nine servos, a camera, a four-microphone array and a speaker,
serves them over HTTP, WebSocket and WebRTC on port 8000, runs one app
at a time as its own subprocess, installs those apps from Hugging Face
Spaces, updates itself from PyPI, and ships on a customized Raspberry
Pi OS image with a published default SSH password. Above it sit
Home's turn engine, the safety floor, the memory store, the people
model and the expression contract, none of which may learn that a
second kind of robot exists, and none of which may leak a family's
audio, images or records to a store, a relay or a cloud model because
the robot's vendor built for a different default.

The design puts one layer between the two, and only one: a body
profile in `bot`, the same seam the MaiPai build's own hardware sits
behind. The failure it prevents is the one every "supported device"
grows into when the seam is skipped: a fork of the engine with robot
ifs in it, a second expression vocabulary copied from the vendor's
demo, a robot on the household Wi-Fi with its factory password and a
cloud chat app still installed, and a family who cannot tell which
promises the product keeps on which robot.

## Decisions in one line

1. **The code lives in `bot`.** MaiPai Bot is the robot companion on
   any supported body. The repo gains a body layer with one profile
   per body (the MaiPai build, Reachy Mini); nothing else in the org
   changes shape. No new repo (principle 5 fails on all three tests),
   nothing in `home` (Home stays lean), no body driver as a catalog
   package (a real-time loop launched by the vendor's daemon is body
   code, not a package a family installs).
2. **MaiPai runs on the robot as a Reachy Mini app.** The body is a
   Python package with the daemon's `reachy_mini_apps` entry point,
   run by the daemon as its one app, on the Wireless's own compute and
   on the Lite's tethered computer alike. Nothing on the robot's image
   is replaced; the daemon keeps the hardware, the clamps and the media
   path. The prebuilt install mechanism is used as it ships.
3. **Reachy Mini v0.1 is a connected body: the hub runs every turn.**
   The robot wakes, endpoints, expresses, tracks and speaks; Home
   thinks. With the hub unreachable it says so once and keeps wake,
   stop and its idle life alive. Principle 2 (complete without a hub)
   is the MaiPai build's promise; whether a 4 GB Compute Module can
   also carry the household runtime and a small model is a measurement
   (M-R6), never a claim, and the org's product table says which body
   carries which promise.
4. **Speech has two placements per body, chosen by measurement.** The
   `pod` tier (wake, VAD, endpointing and direction of arrival on the
   robot; the endpointed utterance to the hub's `stt`; the hub's `tts`
   streamed back to the robot's speaker) is the v0.1 baseline. The
   `robot` tier (speech to text and synthesis on the robot too, as the
   MaiPai build does) is the measured upgrade (M-R1). Both are on the
   privacy page in words a parent understands.
5. **One expression vocabulary, one more column.** The primitive table
   of `dev.md` section 5 gains a Reachy Mini column: the curious tilt
   is a real roll, the antennas are a channel of their own, body yaw
   extends tracking, and speech-reactive sway is a `speak` refinement.
   The vendor's recorded emotions and dances are content a family asks
   for, played through a catalog package at the plan's `react` slot,
   never a second vocabulary driving the reply path.
6. **The robot is Home's first non-browser client, on the routes the
   PWA already uses.** A device token of kind `robot`, the turn stream
   with `surface: robot`, the `stt` and `tts` routes. The oplog, the
   replica and adoption (`spec/link/`, hub v0.3) are not needed by a
   body with no runtime, so this body ships before the link milestone
   and proves the hub's robot surface for the MaiPai build.
7. **Privacy is set before the robot joins the family's network.** A
   day on an isolated network with traffic captured, the vendor's
   conversation app and store token absent, the default password
   rotated into Home's credentials center, the outbound list on the
   robot's privacy page. The Hugging Face store is a distribution
   channel MaiPai publishes to, never one the body pulls from.
8. **Everything that has no screen or sensor on this body is said
   honestly.** No physical mute, no camera shutter, no battery readout,
   no light ring, no display: the product labels the software mute and
   software camera-off as such, shows "on battery, level unknown", and
   carries every state on the antennas and in Home's shell rather than
   claiming the accessibility invariant is met.
9. **The simulator is the bench until the unit arrives.** Pollen's
   MuJoCo daemon serves the identical API on the dev Mac; the body
   profile, the expression column and the pod-tier speech path are
   built and proven against it, and the unit's first day is a
   measurement, not a bring-up.

## 1. What the robot is, in the terms the design uses

The facts the decisions rest on, each verified in Pollen's docs or
repos on 2026-09-27 unless marked.

| Piece | What Pollen ships | What it means here |
|---|---|---|
| Daemon | Python, FastAPI, pydantic; REST and WebSocket on port 8000; OpenAPI at `/docs` and `/openapi.json`; a control loop at about 50 Hz; a systemd unit `reachy-mini-daemon`; on the Wireless it runs on the CM4 and advertises `reachy-mini.local` | The one owner of the hardware. The body never opens the serial bus and never bypasses the clamps. |
| State and motion | `GET /api/state/full` and `ws://…/api/state/ws/full` (head pose, body yaw, antennas, direction of arrival); `goto_target(head, antennas, body_yaw, duration, method)` with `linear`, `minjerk`, `ease_in_out` and `cartoon` interpolation; `set_target` for high-rate control; `look_at_image`, `look_at_world`; daemon-side face tracking (`start_head_tracking(weight)`, `get_tracked_face`); `enable_gravity_compensation` (limp, teach by hand); `disable_motors` | The actuator surface the expression package drives, and a state feed that stands in for the MaiPai build's encoders. |
| Limits (daemon-clamped) | pitch and roll ±40°, head yaw ±180°, body yaw ±160° (one page says ±180°, conflicting, unverified), head-to-body yaw delta at most 65° | The outer envelope. MaiPai's expression envelope is fractions inside it. |
| Media | GStreamer; local IPC when the client is on the same machine, WebRTC (H.264, Opus) when remote; `media.get_audio_sample()` and `push_audio_sample()` at 16 kHz float32; `get_DoA()` returns the angle and a speech flag; `get_frame()`; `media_backend="no_media"` hands the devices to the app's own pipeline; ALSA names `reachymini_audio_src` and `reachymini_audio_sink` on the Wireless | Audio and frames stay on the robot when the body runs there. The XMOS XVF3800's on-chip echo cancellation is the same family the MaiPai build's ears use, so barge-in transfers. |
| Apps | A class subclassing `ReachyMiniApp` with `run(reachy_mini, stop_event)`, declared under the `reachy_mini_apps` entry-point group; scaffolded by `reachy-mini-app-assistant`; optional web page via `custom_app_url`; installed from a Hugging Face Space (tag `reachy_mini_python_app`) through the dashboard or `POST /api/apps/install`, or offline by `scp` and `pip` into the shared venv at `/venvs/apps_venv/`; run one at a time as a daemon subprocess, stopped with SIGINT, the robot returned to its default pose after | MaiPai's body is exactly one of these. The offline path is our install path; the Space is our listing. |
| Image and access | A pi-gen build of Raspberry Pi OS (`reachy-mini-os`, BSD-3-Clause); SSH as user `pollen` with a published default password and `sudo`; the daemon updates from PyPI through the desktop "Reachy Mini Control" app or the JS SDK; a full reflash is a factory reset over `rpiboot` | Root is ours if we need it; we do not need it beyond the install and the password rotation. |
| Outbound | Hugging Face Hub (the store listing, installs, OAuth, WebRTC signaling for browser apps) and PyPI (the daemon's update); proxies honored through `HTTP_PROXY` set on the unit; no documented telemetry and no documented opt-out; the flagship conversation app calls a hosted realtime backend (Hugging Face's, or OpenAI's per one page: unverified which, possibly version-dependent) | Nothing MaiPai installs calls any of these. What the image itself calls is measured on the isolated network, not assumed. |
| Battery | LiFePO4 2,000 mAh, 6.4 V, 12.8 Wh, with protection; no software readout, a three-color LED only; runtime and run-while-charging unstated (a reseller says two to four hours: unverified) | The product cannot say its level. M-R4 measures runtime by the clock. |
| Simulation | `reachy-mini-daemon --sim` (MuJoCo; `mjpython` on macOS Apple silicon); the identical REST, WebSocket and SDK surface; software echo cancellation in place of the chip's | The bench for everything but the physical numbers. |
| Licences | SDK and daemon Apache-2.0; OS image BSD-3-Clause; hardware files CC BY-SA-NC; the emotions library Apache-2.0 (the dances library's licence is not stated: unverified) | All compatible beside AGPL for software. The hardware licence only bars selling a derived body, which MaiPai does not do. |

Two things the MaiPai build has that this body does not, and that the
design leans on elsewhere: a screen with eyes and a mouth, and the
sensors that make the near-hand freeze and the physical mute possible.
Sections 5, 7 and 8 say what replaces each.

## 2. The repo and the body layer

`bot` is MaiPai Bot: the robot companion runtime on any supported
body. The design record's two-process shape holds unchanged: the
household runtime (Home's own TypeScript on Bun, where a body can carry
it) and the Python body that owns every piece of hardware. What changes
is that the body's hardware layer becomes a set of profiles behind the
one HAL seam that BODY-02 already names:

```
body/
  contract/          IPC-01: the body contract, unchanged
  speech/            VOICE-01: the one speech process, unchanged
  head/controller    the arbitration and limiter, unchanged; drives a profile
  bodies/
    maipai/          the owned build: PCA9685, AS5600, Pico face, UPS HAT, Hailo
    reachy_mini/     the daemon client: the SDK behind the seam, a fake from recorded fixtures
```

A profile declares, once, what the body has: the axes and their
limits, the expressive channels (eyes, mouth, light ring, antennas,
body yaw), the sensors (encoders or a state feed, camera, the array
and its direction of arrival, touch, distance, IMU, battery readout or
none), the physical cuts it can prove (mute, shutter, e-stop) and the
speech placement it runs. That declaration is the spec's business, not
a Python constant: `Device.capabilities` (already a string array on the
hub's device row, with `robot` and `pod` kinds reserved for the link)
takes ids from a body-capability vocabulary declared in
`commons/spec/vocab/`, so the expression package, the settings
renderer, Home's Devices page and the bench all read one list and a
second robot on the same hub is a second row with its own list. Spec
first, then the hub, then the robot, as the org rule says.

Why not the alternatives, briefly. A new repo would need a different
release cadence, committer audience or visibility, and a body ships
with Bot's release to the same people at the same visibility. Putting
the Reachy body in `home` would make the hub carry robot code the day
after the owner asked for Home to stay lean. Making the body driver a
catalog package would put a 50 Hz control loop, the arbitration
priority and the stop path inside a Deno worker with net permissions,
under a manifest whose job is to describe what a family installs on
top of a robot, not the robot.

## 3. Where MaiPai runs: the app

The MaiPai body for this robot is a Python package, `maipai-bot`,
exposing `MaiPaiBody(ReachyMiniApp)` under the `reachy_mini_apps`
entry-point group, scaffolded with Pollen's own assistant so the layout
matches every other app on the store. The daemon launches it, hands it
the connected `ReachyMini` and a stop event, and the body runs the
same processes it runs on the MaiPai build minus the drivers that
profile replaces: capture and playback through the daemon's media
path, wake, VAD, endpointing, direction of arrival, presence and
tracking, the expression package against `goto_target` and
`set_target`, the link client to Home, and the honest software mute.

On the Wireless the app runs on the CM4, media over the daemon's local
IPC, nothing leaving the robot but what section 8 lists. On the Lite
the same app runs on the tethered computer, which for a family is the
hub machine itself; the daemon and the body are then both on the hub
and the robot is a USB peripheral, the cheapest possible proof of the
expression layer on real servos. One package, one profile, two hosts.

Why the app and not the two other placements considered. Replacing the
image (our own OS build with the body as a service) discards a
maintained install and update path for one we would own, on a robot
whose vendor ships fixes to the daemon on their own cadence. Running
the body on the hub against a remote daemon (the robot streaming its
camera and microphones over WebRTC to a body process on the hub) needs
nothing installed on the robot at all, which is attractive, but it
moves the raw audio and video of a family's rooms onto the Wi-Fi
continuously, contradicts plan 7.5 (speech stays on the robot) and
section 9 (raw audio never leaves the body process), and closes the
door on the robot ever standing alone. It stays recorded as the
fallback if M-R1 finds the CM4 cannot carry even the `pod` tier beside
the daemon; then the design is amended, not quietly bent.

What "one app at a time" means for the family: while MaiPai is the
robot's app, no store app runs; a guest app (section 11, GUEST-01)
runs only when the body yields the robot on purpose and takes it back
after. The daemon returning the robot to its default pose on app exit
is the vendor's behaviour and is left alone.

## 4. What the family gets on this body

The capability matrix of `dev.md` section 1 has three modes. On this
body, in v0.1, two of them collapse into one honest line. Cells name
what is there, never a stub.

| Capability | Connected (the hub reachable) | The hub unreachable, or never paired | In v0.1 |
|---|---|---|---|
| Conversation, memory, recall, the guards, the safety floor | the hub's engine and model, in the robot's voice | one line once ("I can't reach home right now"), then wake, stop and idle stay alive; no turn runs | yes |
| Timers, reminders, lists, commands | the hub owns, the robot delivers and speaks | unavailable, said once | yes |
| The Tier 0 and Tier 1 packages, search, integrations | the hub's | unavailable | yes (whatever the hub has) |
| Expression: listen, glance, tilt, nod, perk, attend, settle, breathe, track, stop | the hub's cues over the stream (the `signal` and `cancel` events landed on the hub 2026-09-15; the `plan` event follows ACT-03; the scripted bench before either) | breathe, track and stop from the body's own state | yes |
| Speaker evidence | the voice print in the body (`pod` tier: the hub's `stt` returns the transcript; the embedding is the body's, never sent) | the same | after v0.1-standalone's SPEAK-01, as on the MaiPai build |
| Presence and `present` | the daemon's face tracking plus direction of arrival, as observations | the same | yes (the `present` spec field, as designed) |
| Face identity | on-device matching, opportunistic rate, explicit enrollment at the hub (reversed 2026-09-28, below) | no | after v0.1 (FACE-01) |
| Recorded moves and dances a person asks for | the catalog package, played by the body | unavailable (the package is a hub tool) | after v0.1 (MOVES-01) |
| Media playback on the robot | a player device of the hub (plan 7.5) | unavailable | v0.2 |
| The household runtime on the robot (the paired-unreachable and robot-only modes of the MaiPai build) | | | no; M-R6 decides whether it ever is |

The one line for the unreachable case is the register guard's, once
per outage, and the robot never mentions a hub it has not been paired
with: unpaired, it says the pairing code (section 9) and nothing else.

**Amendment, 2026-09-28 (owner's call): face identity reversed.**
Jesse asked directly for actual identity recognition (which specific
family member, not just "a face is present"), confirmed again live in
conversation the same day, on both this body and the hub - a real
product decision, recorded here per the org's "every feature is
reviewed and rebuilt, a one-line verdict recorded before it is built"
rule. The feasibility and the concrete shape are in
[`docs/dev/face-voice-recognition-design-2026-09-28.md`](face-voice-recognition-design-2026-09-28.md);
this note is the design record's own verdict, not a restatement. The
row's original argument ("the CM4 has no room for it beside speech")
was a hardware-budget concern, not a privacy-policy ban, and it still
holds as a constraint on the shape, not a reason to exclude the
feature: recognition itself runs on-device (a review, 2026-09-28,
caught the original wording here overclaiming "identity inference runs
on-device only" without saying what still crosses the network - fixed
below to say exactly). Concretely, per
`face-voice-recognition-design-2026-09-28.md` section 3's own split:
raw image, video and audio never leave the capturing device; a fresh
embedding extracted for an ongoing recognition is matched locally
against the household's own reference embeddings (synced down from
the hub), so only the match *result* (`{person, basis, level}`, the
existing `SpeakerEvidence` shape) crosses the network for that -
never a fresh embedding. The one embedding that does cross the network
is the reference embedding created once, at enrollment, from a photo
or voice sample captured and processed at the hub itself - a durable
biometric identifier, stored there encrypted at rest
(`lib/secrets.ts`'s existing pattern), synced to paired devices for
their own local matching. All of this runs at an opportunistic, capped
rate driven off the existing presence system (never a continuous
background stream competing with wake-word and audio), and only for a
person explicitly, revocably enrolled by an adult - never inferred
from repeated appearances. `docs/PRIVACY.md`'s
"zero phone-home, no MaiPai-operated service in a user data path"
already constrains this to entirely local models and local storage;
nothing here asks for an exception. Also confirmed live, 2026-09-28:
"the home hub needs this" means the hub consumes recognition results
from whatever surface did the capturing (this body, the PWA's own
browser camera via `getUserMedia`, a future Go client's own camera) -
not that the physical hub server needs a camera or microphone bolted
to it. The hub and Go's own browser/device-camera-driven facial *and
gesture* recognition are `home`/`go` items, out of scope for this
record and this repo. Gesture recognition on this body specifically
is not analyzed here; FACE-01 (below) covers face and voice identity
only.

## 5. Expression on this body

The primitive table stands; this body renders it on more axes and
fewer indicators. Roll exists, so the curious tilt is a real lateral
tilt with a slight yaw, the compromise noted in section 5 retired for
this profile. The antennas are a channel with no analogue on the MaiPai
build and carry what the eyes carry there. Body yaw extends `track` and
`glance` past the 65° head-to-body limit: the head leads, the body
follows slowly, never the reverse, and never a body turn to express
anything on its own. A `speak` refinement comes from the vendor's own
flagship app, whose one durable idea is a small continuous sway under
speech: the `speak` cue's rendering on this body is a low-amplitude
pitch and antenna motion modulated by the outgoing audio's energy,
deterministic, read from the playback ledger, no model.

| Primitive | Head (6 DoF) | Antennas | Body yaw |
|---|---|---|---|
| listen | small yaw toward the direction of arrival, steady | both forward and slightly up | none |
| glance | a short yaw and roll toward the target and back | a flick on the target side | none, unless the target is past the head limit |
| tilt | roll with a slight yaw and a pitch lift | one up, one level | none |
| nod | one compact pitch dip and recovery | none | none |
| perk | a slight pitch rise, quicker | both up, quick, inside the envelope | none |
| attend | minimal orient and hold, slow settle | both soft and low | none |
| settle | small return toward neutral | neutral | return toward the head's yaw over seconds |
| breathe | a very small, smooth pitch and roll oscillation, the 8 s cycle | a slow, tiny sway on a different phase | none |
| track | deadbanded gaze with velocity and acceleration limits | none | follows when the head nears the delta limit |
| speak | the low-amplitude sway on the audio envelope | in phase with the sway | none |
| stop | `set_target` to the current pose, trajectories cancelled, then hold | hold | hold |
| muted (a state, not a cue) | neutral | both fully down and still | none |

The envelope is the daemon's limits scaled by a per-profile fraction
written into the robot's device-scope settings with the date of the run
that set it, exactly as BODY-04 does from a calibration run on the
MaiPai build; here the run reads the daemon's declared limits and
verifies each primitive's amplitude, peak velocity and settling time
against the state feed. `goto_target`'s interpolation is used as it
ships (`minjerk` for the primitives, `cartoon` never, since the
vocabulary forbids caricature), and `set_target` only for `track`,
`breathe`, `speak` and `stop`, where the body owns the trajectory.

What this body cannot show: there is no eye, mouth, ring or screen,
so the invariant "every state a spoken cue carries is on the light ring
and the screen, and every screen state has a sound" is not met by the
robot itself. The states live in Home's shell (the robot's card shows
listening, thinking, speaking, muted, on battery) and on the antennas
(listening and muted have unmistakable poses; thinking is the `attend`
hold), and the robot's user page says so plainly. A deaf household
member relies on the card; a blind one on the sounds, which are the
same sound set the MaiPai build uses. Not claimed as met.

## 6. Vision, presence and tracking

The daemon's own face tracking is prebuilt, runs on the robot, and
drives the head with a blend weight; it is the `track` primitive's
source under the arbitration priority (consented tracking sits below
inhibit, reflex and service, above expression and idle), and its
"a face is tracked" fact is the presence funnel's first observation on
this body, beside the array's direction of arrival and speech flag. No
identity is inferred from *this* signal - tracking stays anonymous
presence, never a lookup (section 4's amendment adds identity as a
separate, explicitly-enrolled inference elsewhere in the pipeline, not
by teaching this observation to recognize anyone). The IMU is read for
the tip and freefall
observations the safety section uses. Frames never leave the body
process; a still image for the hub is the v0.2 host call the design
already names, consented and explicit.

## 7. Safety on this body

The daemon clamps every target and owns the bus, so the envelope of
`dev.md` section 10 shrinks to fractions of published limits rather
than measured mechanical stops, and the calibration gate becomes a
verification run (M-R2). What the MaiPai build gates on and this body
cannot provide is recorded, not waived:

- **No near-hand sensor.** The MaiPai build freezes the head on a
  time-of-flight or touch reading. This body has neither, so the
  expression fractions stay conservative (peak velocity well under the
  daemon's, no full-range excursions), the servos are the low-torque
  XL330 class, and a child's hand on the head is a measurement (M-R2
  records the stall behaviour under a held head) before any fraction
  is raised. Gravity compensation is never enabled during expression.
- **The stop.** `stop` cancels trajectories and holds the pose through
  `set_target`; the physical stop is the power switch. The e-stop
  chain, sense line and rail measurements of the MaiPai build do not
  apply and are not claimed.
- **Tip and freefall.** From the IMU: motors disabled, one line
  spoken, the body reports the event.
- **The link and the daemon.** Loss of the hub mid-turn is `cancel`
  with reason `link_lost`; loss of the daemon's socket is `cancel`
  with reason `body_lost` and nothing further is commanded (the daemon
  holds its own safe state).
- **Power and thermal.** The CM4's temperature and throttle flags are
  read; the battery is not readable, so the power policy has one input
  fewer and the shutdown grace cannot be promised on battery. The
  robot says "on battery" when the charger is absent only if a
  readable fact exists for it; M-R4 finds out whether one does, and
  until then the card says "battery level unknown".

## 8. Privacy on this body

The invariants of `dev.md` section 9, applied and extended:

- **Raw audio and images never leave the body process.** On the
  Wireless the body runs on the robot and the daemon's media path is
  local IPC; the `pod` tier sends the endpointed utterance's audio
  (from the wake word to the end of speech, nothing before it, nothing
  ambient) to the hub's `stt` over the household's Wi-Fi, encrypted by
  the hub's TLS, and receives synthesized speech back. The robot's
  privacy page says this in one sentence a parent can read: after the
  wake word, what you say goes to your Home to be understood, and
  nowhere else.
- **The "what leaves the robot" table** on that page: the hub
  (utterance audio in the `pod` tier or the transcript in the `robot`
  tier, the observations, the cues, the device state), the daemon's
  update check to PyPI (a person's click, never automatic, surfaced on
  Home's Updates page), and nothing else. The Hugging Face Hub appears
  on that table only if the person installs a guest app from it, with
  that app's own declared rows.
- **The vendor's software is measured before it is trusted.** The
  first day of the unit is on an isolated network with every outbound
  connection captured, before and after the MaiPai app is installed,
  and the list goes on the privacy page and in `docs/dev/
  measurements.md`. Proxies are honored by the daemon, which is the
  lever if anything unexpected appears.
- **The store's conversation app is never installed**, and any app
  the unit ships with is removed by the install step; the store token
  (`/api/hf-auth`) is never set, since MaiPai installs offline. A
  guest app (section 11) is the one exception and is declared like any
  package.
- **The default password is rotated by the install** into Home's
  credentials center, per the org's credentials rules; a robot on the
  family's Wi-Fi with a published password is refused by Home's add
  flow until it is.
- **Software mute and software camera-off are labelled so** in the
  settings keys' descriptions, on the card and on the privacy page,
  as the design already does for the MaiPai build until its physical
  cut is wired. This body will never have the cut, so the label is
  permanent.

## 9. Pairing, the Devices page, several robots

Home's device table already has kind `robot` with nothing minting it.
The flow of plan 7.1 (a six-digit code on the robot's screen) has no
screen to show on, so on this body the robot **speaks** the code, and
its own app page (the daemon's `custom_app_url` mechanism, served at a
fixed port) shows the same code for anyone who prefers to read it. Home
finds the robot by its advertised name, the admin types the code, the
device token is returned once and sealed by the body, the hub's
fingerprint pinned. Revoke, "trust this hub again", the link states,
and "two robots on one hub are two device rows" all hold as the plan
wrote them; the rank and the oplog do not apply until this body carries
a runtime.

Several bodies of different kinds on one hub are several rows whose
capability lists differ, and every renderer draws from the list: the
Devices page shows what each robot can do, the expression package
renders on the axes each declares, the bench runs the rows each
supports. Nothing in the hub knows the name of a vendor.

**Amendment (2026-09-28, design-resolver, G4):** speaking the code
needs pre-rendered clips (a `pod`-tier robot has no hub to synthesize
with before it's paired), which is not built yet - until it lands, the
app page above is the only surface for the code, and the offline lines
this same clip mechanism will also carry (the hub-unreachable line,
the freefall line, the reconnect line) stay unsayable too. This is a
named interim state, not a silent gap: see `docs/BACKLOG.md`'s
offline-speech-clips item, which blocks family use and RM-05's own
unreachable-line acceptance until it lands.

## 10. Install, update, and the store listing

Install runs from Home's Devices page: Add a robot, pick the found
unit, enter the code, and Home's installer performs the documented
offline install over SSH (copy the wheel, `pip install` into the
shared venv, register the app, rotate the password, remove the vendor
apps, restart the daemon). The person never opens a terminal and never
signs in to Hugging Face. The `pip` install pulls the wheel's pinned
dependencies from PyPI on the robot, which is the one install-time
outbound connection and is listed.

Update is Home's Updates page, per UPDATES.md: the MaiPai app updates
with Bot's release (the hub pushes the wheel the same way), and the
daemon's own PyPI update, which Pollen's desktop app would offer, is
surfaced as a row with the daemon's version and a person's click,
never applied on its own. The daemon version the robot runs is recorded
in the device row and in every measurement header.

The listing: a Hugging Face Space tagged `reachy_mini_python_app`,
built from Bot's release by a script in `scripts/`, so a Reachy Mini
owner who has never heard of MaiPai finds it in the robot's own store
and installs it with one click; that path then asks for Home's
address and the code like the offline one. The Space mirrors a
release and is never edited by hand; creating the account is the
owner's call (open question 1).

## 11. What Pollen's apps teach, and what MaiPai takes from them

The store had 200-plus free apps from 150-plus creators at launch,
discoverable by a README tag, with no review, no curation and no
certified tier; the stated growth strategy is an agent that writes an
app from a plain-English prompt. Pollen's apps page lists 61. Every
distinct pattern was read (the catalogue is in the sources). The
verdicts, in the review queue's own three words plus "learn":

| What their apps do | Examples | Verdict | MaiPai's answer |
|---|---|---|---|
| A recorded emotion and dance library, played on demand | Emotions (official), reachy-dance-duo, music-quiz, reachy_face_party | Adopt as content | **MOVES-01:** a catalog package (`platforms: [bot]`, category Robot body, requires the `moves.recorded` capability) that fetches the Apache-2.0 emotions library and the dances library on demand at a pinned revision with a checksum, never vendored, and plays a named move through the body at the plan's `react` slot or on a person's ask ("do the happy dance"). Never on sentiment, never in the reply path's cues. |
| Teach it a move by hand, replay it | Marionette (Python and JS) | Adopt as an app | **MOVES-02** (after MOVES-01): gravity compensation on, a child moves the head, the body records the trajectory as a move file in the vendor's JSON shape, names it, replays it. Offline, no model, a family feature. |
| The body as a game controller: antenna taps, the head as a joystick, hand poses to the camera | Simon, Spaceship, rock-paper-scissors, tap_lab, morse-code | Adopt the observations, defer the games | The body contract (IPC-01) gains `antenna_tap`, `head_moved_by_hand` and `hand_pose` observations so a game package can exist; the games themselves are catalog apps after v0.1, each reviewed on its own. |
| Speech-reactive sway under any move, a sleep state, idle placeholders | the conversation app's layered motion | Learn | Section 5's `speak` refinement and the existing `breathe` and `settle`. Their "go to sleep" is the settle at the slow rate; no new primitive. |
| Face tracking and a happy reaction to a wave | Howdy_Friend, reachy-cameraman | Already designed | The daemon's tracking is section 6; a reaction to a wave is a `react` the plan permits, not a separate app. |
| Reacting to what the camera sees in a room: a phone left on the desk, phone use, a crying baby | Reachy Phone Home (the store's most liked), judgy_reachy_no_phone, Baby Companion | Owner's verdict | These are the watching rows of the review queue (absence_check, routine_watch, record) in new clothes: an assumed watch, never opt-in. The lesson kept is the product one, a single clear hook per app; the features wait for the family-use verdicts already owed. |
| Telepresence and teleoperation, including a VR headset | Telepresence (official), reachy-quest-teleop, marionette-js | Owner's verdict | A grandparent calling in through the robot is a real family feature and the daemon's WebRTC makes it cheap; it is also the `message` and `follow` rows' territory and a camera stream off the robot, so it joins the owned verdicts, not v0.1. |
| A fully local voice stack | Hugging Face's reference pipeline (Silero VAD, Parakeet-TDT 0.6B, Qwen3-TTS, Gemma 4 or Qwen3-4B), the Jetson build, the Ollama fork | Learn | Confirms the platform's own shape. Parakeet-TDT joins the Stack's `stt` candidate list beside Moonshine and Qwen3-TTS its `tts` list beside Pocket TTS, as candidates with a readiness bench, never a pin change. Every one of these runs on a laptop or a GPU box beside the robot, none on the CM4, which is the M-R6 finding in advance. |
| Home Assistant through a HACS integration | three community and official integrations | Already designed | LINK-06: the robot serves the ESPHome native API, so HA needs no integration at all. |
| The robot as a web radio and speaker | radio | Already designed | Plan 7.5's player device on the robot, v0.2. |
| A dashboard and a live 3D pose view | reachy-mini-dashboard, the 3D visualizer | Learn | Home's robot card shows live state from the daemon's WebSocket feed; a pose widget is a kit block later, never a second dashboard. |
| Cloud-backed chat: OpenAI, Claude, Perplexity, Gemini | the conversation app's hosted backend, talk_with_claude, talk-with-perplexity | Skip | Not on any MaiPai body. Nothing leaves the house. |
| One click from the store, an agent that writes your app | the app store, the ML Intern toolkit | Learn, and publish | Section 10's listing, and **GUEST-01** below: MaiPai's catalog accepts a wrapped store app with a manifest, so a family launches a reviewed community app from Home's Apps page and the body yields the robot for its duration. |
| Kids' apps with no parental features | Baby Companion, asl-teacher, reachy-tell-me, bedtime stories | Learn | The store has no age gating, no filter, no review. Every MaiPai package on this body inherits the safety invariants and the child profile rules; a story or a lesson is a skill on the hub, and the robot is its voice. |

**GUEST-01 (after v0.1, M).** A store app runs on a MaiPai robot only
as a catalog package of kind `app` whose manifest declares its Space
and pinned revision, its `data_sources` and `permissions` as any
package does, and whose CI review passes the org's supply-chain gate
(the pinned revision's hash, the banned-API scan, no store token, no
cloud model unless declared). Home's Apps page launches it; the body
stops itself, the daemon starts the guest, and when the guest exits or
the family says stop from Home, the daemon's own app control restarts
MaiPai. Wake, stop and the safety floor are unavailable while a guest
holds the robot, and the card says so for the duration.

## 12. Measurements for this body

Bench runs with the header `dev.md` section 11 requires, plus the
daemon version, the OS image release and the profile id; recorded in
`docs/dev/measurements.md`; never a hostname, never a household
recording. The simulator rows are marked `sim`.

- **M-R1: the CM4 budget.** The daemon alone; then with the body in
  the `pod` tier (wake, VAD, endpointing, direction of arrival, the
  link); then with `stt` and `tts` on the robot (the `robot` tier).
  RSS and headroom, CPU per process, temperature and throttle flags
  over an hour, in conversation every two minutes. Decision rule: the
  `robot` tier is adopted only if endpoint-to-transcript p95 is under
  the MaiPai build's M-06 figure plus 500 ms and nothing throttles;
  otherwise the `pod` tier ships.
- **M-R2: cue to motion.** `t_cue_received`, `t_motion_command`, and
  the first state-feed delta above noise as the onset (no encoders on
  this body), p50 and p95 per primitive; the stall behaviour under a
  held head at each fraction; every primitive's amplitude, peak
  velocity and settling time against the declared limits. On the sim
  first, then the unit.
- **M-R3: wake and direction of arrival on this array.** The MaiPai
  wake model on the daemon's 16 kHz path: false accepts per hour and
  recall at the ear gates of section 6; direction of arrival error at
  eight bearings; barge-in through the chip's echo cancellation with
  the hub's synthesized speech playing at conversation level.
- **M-R4: battery.** Runtime idle, in conversation every two minutes,
  and with tracking on, measured by the clock from full to the LED's
  red; whether any readable fact (a voltage, a charger-present flag)
  exists on the unit; whether it runs while charging. Until this row
  exists the card says "battery level unknown".
- **M-R5: the link.** Wi-Fi loss mid-turn and mid-sentence: `cancel`
  raised, the pose settled, the one line spoken on reconnect if a turn
  was lost; reconnection time p50 and p95.
- **M-R6: the household runtime on the CM4 (the standalone
  question).** Bun, the pinned runtime, the embed model and
  MiniCPM5-1B at Q4_K_M (the one candidate that fits, per the research
  note) beside the daemon and the `pod`-tier body, on 4 GB: does it
  boot, what is the first delta p95 with the prefix cached, and do the
  hard rows pass. The decision rule is M-02's. A pass opens a
  paired-unreachable mode for this body as its own design amendment; a
  fail is recorded and the product table's wording stands.

## 13. What "officially supported" means

A body is supported when every row below is true, and the README's
supported-bodies table lists it only then:

1. A profile under `body/bodies/<id>/` behind the HAL seam with a fake
   that passes the same tests as the hardware run.
2. Its capability list in the spec vocabulary, and a device row on the
   hub that carries it.
3. The expression column proven on the bench (M-R2) and the speech
   placement decided by measurement (M-R1).
4. Install and update from Home's pages with no terminal and no
   third-party account.
5. The privacy page's "what leaves the robot" table, from a capture,
   not a reading of docs.
6. The user-tier guide from the box to the first conversation, with
   the body's honest limits on one page.
7. The measurements of section 12 recorded, and the bench's
   deterministic suite green on the profile's fake.
8. A CHANGELOG line and a release note that names the body.

## 14. Order of work

The unit is up to 90 days out and the simulator is free today, so the
order is the sim first and the physical rows the week the box lands.
Items are in `docs/BACKLOG.md` under "Reachy Mini body"; the names
here are theirs.

1. **RM-00** (spec, in `commons`): the body-capability vocabulary and
   the profile declaration shape. Spec first.
2. **RM-01**: the profile and the daemon client behind the HAL seam,
   with the fake recorded from the sim's own responses; `check.sh`
   grows the body block it already anticipates.
3. **RM-02**: the expression column on the sim (EXPR-01's package with
   this profile), M-R2's sim rows.
4. **RM-03**: the app packaging, the offline installer script, the
   Space build script.
5. **RM-04**: the `pod`-tier speech path against the hub's routes.
6. **RM-05**: the hub client: pairing by spoken code, the turn stream,
   the cue stream from the hub's `signal` and `cancel` events (landed
   2026-09-15; the `plan` event after ACT-03), the
   device state.
7. **RM-06**: presence and tracking from the daemon's feed.
8. The unit arrives: **RM-07** (the isolated-network capture and the
   privacy page), M-R1 through M-R5, then **RM-08** (install and update
   from Home's pages) and **RM-09** (the user guide).
9. After v0.1: MOVES-01, MOVES-02, GUEST-01, M-R6.

Three hub items are needed and are listed in the backlog's
hub-dependencies table under this body's name: the Devices page's add
flow that mints a `robot` device token for a found unit and accepts a
code the robot spoke; the turn, `stt` and `tts` routes accepting a
device token with `surface: robot`; and the robot's card with live
state and the daemon's update row. SURFACE-01 and WIRE-01's signal and
cancel halves landed on the hub on 2026-09-15, so the surface and the
stream this body needs already exist.

## 15. Org and doc updates required

- `.github/CLAUDE.md`, the products table: `bot` is the robot
  companion on any supported body, with the standalone promise named
  as the MaiPai build's and the connected promise as every body's.
  Applied with this record.
- `bot/AGENTS.md` and `README.md`: the bodies sentence, and the
  supported-bodies table (the MaiPai build "in build", Reachy Mini "in
  design") once RM-01 lands.
- `dev.md`: decision 11 in "Decisions in one line", the "Bodies"
  section pointing here, and the section 5 note that this body has
  roll. Applied with this record.
- `.github/brand/COPY.md`: no change proposed here. The bot copy
  describes the MaiPai build; a sentence naming supported bodies is
  the owner's wording call once one is supported (open question 3).
- `commons`: RM-00, the vocabulary, filed there.
- `home/docs/BACKLOG.md`: the three hub items, filed by the
  coordinator.

## 16. Open questions (the owner's calls)

1. A Hugging Face account for the org, to publish the Space listing
   (section 10). Without it the offline install is the only path; the
   design does not depend on it.
2. Whether a Lite is bought as well, for the "USB peripheral of the
   hub" placement that proves servo expression on the hub machine
   before the Wireless arrives and stays the bench after. Not
   required; the sim covers the software and the Wireless covers the
   physical rows.
3. The brand copy for supported bodies, when the first one is.
4. The family-use verdicts on telepresence and the camera-triggered
   reactions (section 11), which join the seven watching, messaging
   and following rows already owed.

## Sources

Read on 2026-09-27.

- https://huggingface.co/docs/reachy_mini (core concepts, the Python
  and JavaScript SDKs, media architecture, apps, the REST API,
  installation, troubleshooting, the hardware datasheet, the wireless
  get-started and reflash pages, the simulation get-started)
- https://github.com/pollen-robotics/reachy_mini,
  `reachy_mini_app_example`, `reachy_mini_conversation_app`,
  `reachy-mini-os`, `reachy_mini_dances_library`,
  `reachy_mini_homeassistant`
- https://pypi.org/project/reachy-mini/
- https://pollen-robotics.com/reachy-mini/apps/ (61 apps) and
  https://huggingface.co/spaces?filter=reachy_mini
- https://huggingface.co/blog/reachy-mini,
  https://huggingface.co/blog/clem/reachymini-appstore,
  https://huggingface.co/blog/local-reachy-mini-conversation
- https://store.pollen-robotics.com/products/reachy-mini-wireless-version
- The research note of the same morning, for the hardware table.
