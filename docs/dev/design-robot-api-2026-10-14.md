# Design record: one robot API for every MaiPai Bot body (2026-10-14)

Status: DRAFT, research only. Not reviewed by the architect, not committed, not a plan change.
Serves: the framework paragraph in `AGENTS.md` and `docs/dev/hal-seam.md`, and BODY-STACKCHAN-01.
Evidence: `SURVEY.md` (session scratchpad, 2026-10-14), a source-level survey of 14 robot projects. Anything the survey could not read in source is UNVERIFIED and is not relied on here.

## 1. Why

The bot project is to robots what the Stack is to local AI: a headless service Home pairs with. Home and the layers above the seam must see one clean robot, whatever the body. Two robots are planned now (Reachy Mini, StackChan) and a third, wheeled or legged, will follow. The interface must grow without rewriting what is above it.

Today the seam is a set of separate protocols (`HeadActuator`, `AudioIO`, `Camera`, `Imu`, `FaceTracker`, `StateFeed`, `Teachable`) plus `BodyProfile`. That is a good base. It has no whole-robot verbs (power, sleep, shutdown), no base or limb, no battery, no emergency stop and no control arbitration, and these are the things the survey shows every robot project needs the moment it moves or runs on a battery.

## 2. Decisions in one line each

1. One `Robot` object with named parts. A part exists on a robot or it does not; the profile declares which.
2. Whole-robot lifecycle verbs live on the robot: `connect`, `disconnect`, `wake`, `sleep`, `power_on`, `shutdown`, `emergency_stop`.
3. The API is the union of what all integrated robots can do. Growing it follows one rule (section 7).
4. Units are SI and radians, frame REP-103 (x forward, y left, z up, yaw positive to the left). A profile converts from its robot's native units; no native unit leaks above the seam.
5. Every motion call is clamped by the profile first, returns the value actually applied, and a continuous motion call carries a deadline so a lost link stops the robot.
6. Control of the robot is leased: one controller at a time, with a priority, and an emergency stop that always works.
7. Capabilities are discovered from the profile, never by trial. Calling something absent raises `NotSupported`.
8. The vocabulary (part names, verb names, capability ids) is declared once in the commons spec (principle 4), not in the bot repo.

## 3. What the survey showed, and what we take

Primary shapes, with licenses. Spot's SDK is proprietary: we read its shape only and copy nothing (principle 8). Everything else we use as a reference for naming and shape, never code.

| Pattern | Seen in | Our take |
|---|---|---|
| Top-level robot object with named sub-objects | Vector (`behavior`, `motors`, `screen`, `audio`, `camera`), Spot (typed clients), Reachy (`media`) | Adopt. Matches what Jesse described. |
| Connect and disconnect as context manager | Vector, LeRobot, Spot | Adopt for `connect`/`disconnect`. |
| Power or wake separate from connect, and a safe shutdown | Spot (`power_on`, `safe_power_off`), Reachy (`wake_up`, `goto_sleep`), HA (`turn_on`, `turn_off`), Petoi (`krest`, `d`) | Adopt as `wake/sleep` (soft) and `power_on/shutdown` (hard). A profile maps either to whatever steps the robot needs. |
| Immediate and timed motion | Reachy (`set_target`, `goto_target`) | Adopt as `set` (immediate) and `goto` (timed, interpolated). Already in `HeadActuator`. |
| Velocity command with a deadline | Spot (`end_time_secs`), Create 3 (watchdog, not yet available) | Adopt for `base.drive`. A velocity with no deadline is invalid. |
| Lease or priority for control | Spot lease, Vector control priority, Reachy app lock | Adopt (section 5). Several things drive our robot: the turn engine, expression, teaching, a person with a remote. |
| Emergency stop as a separate, always-available path | Spot, Duckietown, Create 3 reflexes | Adopt. |
| Clamp and report the applied value | LeRobot (`send_action` returns the sent action), already our rule | Adopt; return the clamped value from every motion call. |
| Capability discovery as a list | HA `supported_features`, MCP `tools/list`, LeRobot feature dicts, Spot `list_services` | Adopt as the profile's capability ids. |
| Distinct unsupported error | HA `ServiceNotSupported`, Vector `VectorUnimplementedException`, Spot `UnimplementedError` | Adopt `NotSupported` (already ours). |
| Batch calls to save round trips | stackchan-mcp (`set_leds`, mouth sequences) | Adopt as a `many` form on parts where a body is slow per call. |
| Actions with goal, feedback, result | ROS 2 | Adopt for long moves (drive a distance, dock): the call returns a handle that can be awaited or cancelled. |
| Fire and forget with no reply | Unitree `Move`, Petoi tokens | Reject for motion; allowed only for indicators. |
| Per-robot units and frames | everything | Reject at the seam (decision 4). |

Where the projects conflict and what we chose:

- Angles: degrees (Vector, Misty, Petoi, StackChan) versus radians (Reachy, ROS, Unitree, Spot). Chose radians in the API, degrees allowed in `profile.py` data as long as the unit is named, because the existing profile convention already records source and date per limit.
- Speed: mm/s, m/s, percent, tokens. Chose m/s and rad/s.
- StackChan yaw sign: -128 is the robot's left, opposite to REP-103. The StackChan profile flips it; nothing above sees it.
- Errors: exceptions in most, codes in Unitree and Nav2, strings in the stackchan gateways. Chose typed exceptions (section 6).

## 4. The robot object

Part names are nouns for what a person would point at. A robot has a part only if its profile says so.

```
robot
  .connection        connect(), disconnect(), state, BodyLost on loss
  .power             wake(), sleep(), power_on(), shutdown(), state
  .estop             engage(), release(), engaged     (required if any part can hurt)
  .lease             acquire(priority), release(), holder
  .head              set(pose), goto(pose, duration), hold(), enable(), disable()
  .appendages        antennas, ears or arms: set(name, angle), goto(...)
  .base              drive(vx, vy, wz, deadline), stop(), goto(pose), turn(angle)    (wheels, treads, legs)
  .posture           stand(), sit(), lie()                                          (legged bodies only)
  .dock              seek(), leave(), docked                                        (battery bodies)
  .battery           level, charging, state, low and critical (events)     (see 4b)
  .health            per-part ok/warn/error/stale, summary, readings         (see 4b)
  .pose              position and heading in a frame, moving bodies only      (see 4b)
  .eyes              express(emotion, intensity) -> face, display, LEDs or motion  (see 4a; existing `indicator` is the status light)
  .leds              set(index, rgb), many([...])
  .display           show(frame), brightness
  .audio             speaker(play, volume), mic(stream), direction_of_arrival
  .camera            frame(), stream()
  .imu, .touch, .proximity    readings and streams
  .network           link, signal, ip, mac, rtt, speed, paired peer          (see 4c)
  .system            serial, model, firmware, load, clock; reboot, identify  (see 4c)
  .log               read(since, level, part), tail; bounded retention       (see 4d)
  .diagnostics       list(), run(check), bundle(); counters per part          (see 4d)
  .state             one monotonically stamped feed of every part's state
  .capabilities      the profile's capability ids (read only)
```

Existing protocols map in directly: `HeadActuator` becomes `.head`, `AudioIO` becomes `.audio`, `Camera`, `Imu` keep their names, `StateFeed` becomes `.state`, `Teachable` stays an optional extension of `.head`. `FaceTracker` is a behavior built on `.camera` and `.head`, not a part.

Whole-robot verbs and the translation rule: a verb names the outcome, a profile hides the steps. `shutdown()` is one command on a bot with a power relay, a rest pose then a motor disable on another, and a sequence with a wait for a safe stance on a legged one. A caller cannot tell and must not need to. Each verb documents its postcondition ("motors disabled, safe to carry") and a profile test proves it against the fake.

Where each current and planned robot lands (UNVERIFIED rows are filled in on arrival of the unit):

| Part or verb | Reachy Mini | StackChan | Planned wheeled or legged |
|---|---|---|---|
| `.head` | yes (6-DoF pose) | yes (yaw, pitch) | maybe |
| `.appendages` | yes (antennas) | no | maybe |
| `.base` | no | no | yes |
| `.posture` | no | no | legged only |
| `.dock`, `.battery` | battery UNVERIFIED | battery yes (550 mAh) | yes |
| `.eyes` | via antennas and head | face display | per build |
| `.leds`, `.display` | no | yes | per build |
| `.touch` | no | yes (3-zone) | per build |
| `.audio`, `.camera`, `.imu` | yes | audio yes, camera 0.3 MP, IMU UNVERIFIED | yes |
| `.power` wake/sleep | yes (`wake_up`, `goto_sleep`) | no verbs; the translator ends the session and blanks the face | yes |
| `.estop` | torque disable | torque disable | required, wheels |

## 4a. Emotion and expression

Not `robot.frown()`. A method per emotion is the wrong shape for three reasons: the list never stops growing (every robot invents its own), a frown means a face on StackChan, an antenna and head droop on Reachy Mini and maybe a light color on a tread robot, and a caller should never need to know which. The survey agrees: Vector does emotion through animation names, the stackchan-mcp gateways through face and LED tools, and none of them is portable across robots.

What the bot already has, and what this API keeps:

- The model never emits a face token. The turn produces an expression cue (`expression/cue.py`: `expressed_emotion`, `emotion_intensity`, the phase, whether there is a target). The expression engine maps a cue to a primitive (listen, glance, tilt, nod, perk, attend, settle, breathe, track, speak). A per-body renderer (`expression/renderers.py`, one per profile id, for example `reachy_mini_renderer.py`) turns a primitive into that body's motion, face, light or sound.
- So emotion is data into the expression layer, not a method on the robot. The one public call is `robot.eyes.express(emotion, intensity)`, used by the expression engine and by nothing else (a feature that wants the robot to look happy sends a cue, never calls the body).
- The emotion vocabulary is one shared list in the commons spec (principle 4). A profile declares which emotions it renders in its capabilities and which it folds into a neighbor: a StackChan with eight faces renders happy, sad, angry, sleepy, doubt directly and folds "wry" into "doubt"; a robot with only a light renders mood as color. An emotion with no rendering and no fold raises `NotSupported`; the expression layer treats that as "stay neutral", never as a failed turn.
- Intensity is a small fixed scale (the cue already has `emotion_intensity`), so a profile can render "slightly sad" as a smaller head droop or a dimmer color.
- Safety and age rules sit above this: the output gate and age gates decide what is said and whether an expression is allowed (`react_allowed`, `is_safety_line`); the renderer only draws.

## 4b. Battery, health and location

All three are read-only state with events, in the same stamped `.state` feed as everything else. Shapes come from ROS (`BatteryState`, diagnostics, REP-105 frames), Spot (`robot_state`), Vector (status flags and dock verbs) and Create 3 (dock status); none is copied.

Battery and charging (`.battery`, `.dock`):

- `battery.level` is 0.0 to 1.0, plus `charging` and a state: `full`, `charging`, `discharging`, `low`, `critical`. A time-remaining estimate is optional and marked as an estimate.
- `low` and `critical` are events with thresholds in the profile (one place), so the expression layer can say "I need charging" in the robot's own way, and Home can notify a person.
- One verb for charging, `dock.seek()` (go to the charger and charge), exists only on a body with a `.base`. A body a person plugs in (StackChan, probably Reachy Mini) has no `.dock` and raises `NotSupported`; it still reports battery and the `low` event so the household can be told. A mains-only body has no `.battery` at all.
- A critical battery runs `shutdown()` safely before the power dies; it is the profile's job, tested on the fake.

Health (`.health`):

- A per-part status with a level (`ok`, `warn`, `error`, `stale`), a short code and a plain sentence, as in ROS diagnostics. A whole-robot summary is the worst part.
- Standard readings where the body has them: motor temperature, motor overload, link quality (Wi-Fi signal), uptime, firmware version, free storage, last-seen-sensor age (a camera that stopped delivering frames is `stale`).
- Health feeds the Devices page and the existing body dashboard. Every `warn` and `error` sentence says what went wrong and what to do (STYLE.md, error messages), because a person reads it.
- A part that fails reports `error` and stops accepting motion; the rest of the robot keeps working (a failed tool never fails the answer).

Location (`.pose`, and a hub-owned place):

- Two different things, kept apart. `pose` is where the robot is in a frame (REP-105 `odom`, optionally `map`): position and heading with a confidence, present only on a body that moves (`.base`) or has an IMU heading. `place` is the household's idea of where it is ("kitchen"), and that belongs to Home, not the robot.
- A fixed body (StackChan on a desk, Reachy Mini on a shelf) has no `.pose`. Its place is a setting the household chooses on the Devices page. Direction of a voice or a face relative to the robot is not location; it stays in the state feed.
- A moving body reports pose and, once the hub has a map, a place derived on the hub. The robot never invents room names.
- Privacy: pose and place stay on the home network and in the household record. They are never sent outside the home, and a child's profile never exposes where the robot found them (SAFETY.md, PRIVACY.md).

## 4c. Network and system information

Two read-only parts, `.network` and `.system`, in the same state feed. They are what the Devices page, pairing and support need, and what health (4b) reads from.

Network (`.network`):

- Link: `kind` (wifi, ethernet, usb, ble, serial), `state` (down, connecting, up), `signal` (0.0 to 1.0, plus the raw dBm where the body has it), `ssid` or interface name.
- Addressing: `ip` (a list, v4 and v6), `mac`, and the name the robot is reachable by. The Tailscale name and address appear here when the body is itself a tailnet node; a body that cannot be one (StackChan) reports the LAN address and which paired bot service is its gateway (section 5.2a of the StackChan note).
- Quality: round-trip time to the paired service, packet loss, and `speed` (negotiated link rate and a measured throughput, both optional and marked as such).
- Link events: `up`, `down`, `degraded`, `roamed`. A down link on a connected body becomes `BodyLost` for anything that needs it.
- The paired peer: which hub or bot service this body is paired with, since when, and whether the session is open. Pairing itself is not a robot verb; it goes through the Devices flow.

System (`.system`):

- Identity: `serial`, `model`, `hardware_revision`, `manufacturer`, `body_id` (our stable id, the one in spec records). The vendor serial is the vendor's; `body_id` is ours and is what everything references.
- Software: `firmware_version`, `translator_version` or daemon version, the pinned `spec` version, build date. A test fails if a profile cannot report its firmware version.
- Resources: uptime, CPU and memory load, free storage, temperature, boot reason (power loss, watchdog, user).
- Clock: the body's time and offset from the hub, because every record carries a clock stamp (principle 3). A body whose clock is off by more than a set amount reports `warn`.
- Operations (these are verbs, not state): `reboot()`, `identify()` (a visible and audible "this one"; every body can do it with whatever it has), `factory_reset()` (guarded by the lease and a person's confirmation, never callable by a turn).

Rules that apply to all of it:

- Local only. Network addresses, serial numbers and signal data stay on the home network and in the household record, never leave the home, never reach a log meant to be shared. Docs and fixtures use `192.0.2.x` and made-up serials (PII rules); a recorded fixture is scrubbed before it is committed.
- Read-only by default. Changing network settings (join a Wi-Fi network, set an address) is a pairing and setup flow with a person present, not a runtime call.
- Gaps are honest: a body that cannot report a figure leaves it out and the capability id is absent. It does not invent a value.
- Where the body is only a thin client (StackChan), part of this comes from the gateway, not the device: the translator reports its own link to the device and the device's reported figures, and says which is which.

## 4d. Logs and diagnostics

Two parts, `.log` and `.diagnostics`. Health (4b) is the live summary a person sees; this is the detail behind it, for support and for finding a fault.

Logs (`.log`):

- A body's own log is read through one call: `log.read(since, level, part)` returns stamped entries (time, level, part, code, message). Levels are `debug`, `info`, `warn`, `error`. A live tail is the same entries as a stream.
- The profile maps its robot's native log (ESP32 serial console, the Reachy daemon log, ROS rosout) into that shape. What the body cannot log is absent, not faked.
- Retention is bounded on the body and on the host. Old entries roll off; the cap is in the profile, one place.
- The bot service also keeps its own log of the translator and the profile (connects, drops, clamps, refused calls, lease changes, estops). That log is the first place to look, and it is the same shape.
- Local only. Logs never contain a transcript, an audio frame, a camera image or a face embedding; they hold events and numbers. Addresses and serials are masked in anything exported for sharing (PRIVACY.md). Nothing is sent off the home network.

Diagnostics (`.diagnostics`):

- `run(check)` runs a named self-test and returns a result with a plain sentence for a person: `servo_sweep` (each joint moves through a small safe range and reports torque and error), `audio_loopback`, `camera_frame`, `leds`, `display`, `imu_still`, `link_quality`, `battery_load`. A check a body cannot run raises `NotSupported`.
- A check that moves anything needs the lease and the person present, and cannot run during a turn. A check never runs unprompted.
- `diagnostics.list()` returns the checks this body offers, from its profile.
- A support bundle: `diagnostics.bundle()` collects the recent log, the health report, system and network info and the last check results into one local file, with addresses and serials masked by default and an explicit, local-only unmasked option for the owner. The household decides whether to share it; the bot never uploads it.
- Counters worth keeping, per part: clamps applied, refused calls, restarts, link drops, estops. They show in health as trends ("the pitch servo has hit its limit 40 times today").

How it connects to the rest:

- A failed check or a log `error` raises the matching part to `warn` or `error` in health, with the sentence a person reads (what went wrong, what to do).
- Fixtures: the fake replays recorded logs and check results so the diagnostics suite runs without a unit.
- Order of work: `.log` and `.diagnostics` are read-only first; the checks that move hardware come with the profile that can do them safely.

## 5. Safety shape

The survey's strongest finding is that safety is a layer apart from motion verbs, and every mature project has the same three pieces.

- Limits: only in `profile.py` (existing rule). Every motion call clamps against them first and returns the applied value. The vendor's own clamp is the second line.
- Lease: a controller acquires the robot with a priority (`safety` > `person` > `expression` > `idle`). A lower priority is refused while a higher holds it. Without a lease a motion call raises `NotPermitted`. This lets the turn engine, the expression layer, teaching mode and a person with a remote share a robot without fighting.
- Emergency stop: `estop.engage()` works with or without the lease, from any caller, and stops motion, disables torque or drive, and holds until a person releases it. Required on any body with a `.base` or `.posture`. Head-only bodies implement it as "torque off".
- Deadline: `base.drive` and any continuous velocity call takes a deadline. When it passes, the profile stops the robot. A lost link behaves the same (`BodyLost` also stops motion).

Child and teen protections are not in this layer. Age gates and the output gate sit above the seam and apply whatever the robot can do (SAFETY.md).

## 6. Errors, async, and discovery

- Errors, typed: `BodyLost`, `OutOfEnvelope`, `NotSupported` (existing); add `NotPermitted` (no lease or a lower priority), `EstopEngaged`, `Busy` (a timed move is running that this call may not interrupt). No string codes, no integer codes above the seam.
- Async: the API is async. Long moves return a handle: awaitable, cancellable, with progress. `state` is a stream. A thin sync wrapper may exist for tools and tests. Motion with no reply and no deadline is rejected (section 3).
- Discovery: `robot.capabilities` is a set of ids from the commons body-capability vocabulary, and a part is present only if its capabilities are. A test fails if a profile has a part and no matching capability id, or the reverse.

## 7. How the API grows

When a new body arrives:

1. Record its features in plain words against the existing parts and verbs. Mark each: same, same with a different range, or new.
2. For "same": use the existing verb and write the translation in the profile. Do not add a verb.
3. For "new": add the capability id and the verb in the commons spec first (shared record changes go spec, hub, robot), named for the outcome, never the robot. A one-sided patch is a bug.
4. Write the verb's postcondition and a fake that replays recorded fixtures. The full suite runs against the fake always and the body when present.
5. Bodies that lack the verb gain `NotSupported` automatically; no edit to their profiles.

A feature kept out of the shared API (a vendor-only trick) lives in the profile and is not callable from above the seam.

## 8. What to do with the StackChan and Reachy designs

- The StackChan note's section 5.3 tool list becomes the StackChan profile's translation table: `head.set` to `self.robot.set_head_angles`, `leds.set` to `self.robot.set_led_color`, and so on. The tool names never appear above the profile.
- The Reachy Mini design's HAL mapping stays; `.head`, `.appendages` and `.audio` rename nothing it already does.
- Neither design is edited by this note.

## 9. Order of work (proposal, not a plan change)

1. Architect verdict on this note and the `AGENTS.md` paragraph (the architect gate applies to `docs/design/` and `docs/dev/` changes that carry rules).
2. Spec first: body-capability vocabulary additions for power, estop, lease, base, posture, battery, leds, display, touch (commons).
3. Seam restructure behind the existing protocols: add `Robot`, `.power`, `.estop`, `.lease`, `.battery`; keep the old protocol names working until the Reachy profile moves.
4. Move the Reachy profile onto `Robot`; run the existing suite against the fake to prove nothing above the seam changed.
5. StackChan profile and translator (BODY-STACKCHAN-01) on the new object.
6. `.base`, `.posture`, `.dock` land with the first moving robot, not before. No speculative parts (principle 5 spirit: build what has a user).

## 10. Open items

- UNVERIFIED: NAOqi, EMO, Open Bot (no reachable primary docs), wire-pod internals, Duckietown license, Spot frame details.
- Radians versus degrees at the API edge is a technical choice made here on the evidence (ROS, Reachy and Spot use radians); revisit only if profile data readability suffers.
- Lease priority names and the `Busy` rules need a trial against the real turn engine and expression layer before they are fixed.

## Sources

- `SURVEY.md`, session scratchpad: https://github.com/pollen-robotics/reachy_mini, https://github.com/m5stack/StackChan, https://github.com/kisaragi-mochi/stackchan-mcp, https://github.com/migratorywhale/stackchan-mcp, https://github.com/anki/vector-python-sdk, https://github.com/MistyCommunity/REST-API, https://github.com/PetoiCamp/OpenCat, https://github.com/apirrone/Open_Duck_Mini, https://github.com/ros-infrastructure/rep, https://github.com/ros-navigation/navigation2, https://github.com/boston-dynamics/spot-sdk (proprietary, shape only), https://github.com/unitreerobotics/unitree_sdk2_python, https://github.com/iRobotEducation/create3_docs, https://github.com/huggingface/lerobot, https://github.com/home-assistant/core
- In this repo: `docs/dev/hal-seam.md`, `body/maipai_body/hal/seam.py`, `docs/dev/design-reachy-mini-2026-09-27.md`, `docs/dev/design-stackchan-2026-10-14.md`
