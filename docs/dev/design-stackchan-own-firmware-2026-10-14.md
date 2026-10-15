# StackChan: our own firmware (2026-10-14)

Status: DRAFT, design only. The unit has not arrived; nothing is built or flashed. Everything about the hardware below is read from
source and other people's measurements, so each hardware claim is UNVERIFIED until the unit confirms it.
Supersedes `design-stackchan-firmware-build-2026-10-14.md` as the recommended path; that recipe stays as the fallback if this
cannot reach parity (section 8). Raised by Jesse: "can't you just make us a 100% custom".

## 1. Verdict

Yes, and it is the better design on merit. The patch route inherits three things we do not want: the xiaozhi cloud-shaped flow
(OTA check, activation, hello), M5's second protocol and hosts, and a version-drift problem against two moving upstreams. A firmware
of our own is a thin client of the bot service, speaks one protocol we define, and has no vendor code path to remove. It also matches
org principle 8 (review and rebuild, never carry) and the bot repo's role as the robot framework.

What we do not rewrite from scratch: hardware drivers and the speech front end. Those are MIT or Apache in M5 and Espressif repos
and are what make the board work (power chip, camera, audio codecs, servo bus, touch, NFC, display). We use them as libraries or copy
them with the notice kept.

## 2. What the firmware does

A thin body: it senses and acts, the bot service thinks. Roles:

| Area | Firmware does | Server does |
|---|---|---|
| Audio in | Capture both mic channels plus the speaker reference, optional on-device AEC, send frames | Wake word (option), speech to text, speaker identity |
| Audio out | Play frames from the server | Text to speech, pacing |
| Camera | Capture JPEG at a requested rate and size | Face tracking, vision |
| Head | Move servos to targets with speed, enforce hard limits, report position and stalls | Gaze, gestures, choreography |
| Face and LEDs | Render the avatar from expression cues; set LEDs; light the camera indicator in firmware, not on request | Choose cues |
| Sensors | Touch, IMU, NFC, light and proximity, battery, charging, clock as events and polls | Interpretation |
| Safety | Local limits that hold with the network down (servo torque and stall cutoff, e-stop, volume cap, camera indicator) | Policy, consent |
| System | Config, pairing, logs, OTA from our service | Everything else |

The camera indicator and servo protection live on the device on purpose: they must work if the server is down or wrong.

## 3. Protocol: one, ours

Design it from the robot API (`design-robot-api-2026-10-14.md`), so the wire shape and the robot object match, instead of from
xiaozhi or M5. Shape, informed by what works in the field (the i41 "embody" design is the closest prior art):

- One WebSocket, device dials out to the service on the home network; `ws://` on the LAN first, `wss://` later with our CA (gap D).
- JSON text frames for commands, events and config; binary frames with a one-byte type for audio, JPEG and sensor streams.
- Audio: Opus for bandwidth, with the speaker reference channel carried so the server can do echo cancellation. Raw PCM is the
  simpler fallback; the i41 fork ships raw 24 kHz and measured the camera at about 5 fps, so bandwidth is not tight on a LAN.
- Every command carries an id and gets an applied-value reply (clamped value returned), matching the robot API's rules; motion
  carries a deadline so a lost link stops it.
- Hello advertises capabilities and firmware version; the service answers with config. This is how the robot API's capability
  list is filled for this body.
- Pairing: per-device token issued by an admin approval, the same flow as before.

This is the "Embody path" (gap Q). Because the protocol is ours, the translator in the bot repo becomes a thin adapter rather than
two protocol implementations, and the fake body for tests speaks the same frames.

## 4. Firmware stack

- ESP-IDF 5.5.4 on the ESP32-S3 (the version M5 and the i41 fork build with; 6.x is known to break the M5 tree), C++.
- Libraries reused: Espressif's audio front end (AFE/AEC, WakeNet if we want an on-device wake word), M5's BSP and drivers
  (AXP2101, GC0308, ES7210 and the output codec, servo bus, touch, NFC, RTC), LVGL for the face, `esp_websocket_client`,
  `esp_https_ota` for updates. All permissive; the licence check runs on the final list.
- Our code: protocol client, the state machine (provisioning, connected, degraded, e-stop), the face renderer and cue mapping,
  safety limits, config in NVS.
- Where M5 code is copied, keep its MIT notice in the file; where it is rewritten from reading, that is fine too.

## 5. Order of work (hardware-free first)

1. Protocol spec in the bot repo plus the fake device and a test server: drives the translator before any firmware exists.
2. A host-side harness: run the firmware's protocol and state-machine code on the PC against the test server.
3. Board bring-up on the unit: display, touch, LEDs, servos with limits, then audio, camera, sensors, one driver at a time, each
   with a measurement recorded (servo limits, camera fps, AEC quality, battery behaviour including the PMIC read crash seen in the field).
4. Pairing, OTA, logs and diagnostics as the robot API's `system`, `log` and `diagnostics` parts.
5. Proof of "no third party": static host search plus a captured trace, as in the recipe note section 7. This is easy now because the
   firmware contains no vendor hostnames to begin with.

Steps 1 and 2 need no hardware and are the real start. Step 3 starts when the unit arrives.

## 6. What we give up

- Time. Patching reaches a working unit sooner than a rewrite; the drivers and AEC tuning are the slow part.
- M5's polish: avatar animations, the apps, the Android/iOS app, the dance and call features. Those are not requirements.
- Stock restore stays available through M5Burner, so a bad flash is recoverable.

## 7. Risks

- Audio quality and echo cancellation are the hard part; M5's build and the field reports may hide tuning we have to redo. Measure
  early and keep server-side AEC (speaker reference on the wire) as the backup.
- Internal RAM is tight (about 35 KB free in one field build); display, camera, AEC and TLS compete. Budget memory per subsystem from the start.
- PMIC/I2C reads can abort the firmware in field reports; every bus read returns errors rather than aborting.
- Driver details (servo bus protocol, touch IC, codec setup) must be taken from M5's source; copying with notice is allowed.

## 8. Fallback and the decision rule

Per the rule that the best design is found on merit first: this note is the best design. The patch recipe is the fallback if step 3
shows we cannot reach parity on audio, or if time matters more than independence. Switching is cheap until step 3 begins, because
steps 1 and 2 are shared with either path (the protocol work is wasted on the patch path only if we keep xiaozhi's protocol).

## Sources

`design-stackchan-pieces-and-gaps-2026-10-14.md` (sections 3, 4, 8); `design-stackchan-firmware-build-2026-10-14.md`; m5stack/StackChan
(firmware and server MIT); i41-eu/i41eu-StackChan (embody design and measurements); andymai/stackchan-kai (clean-slate Rust, LAN-only);
ESP-IDF 5.5.4 documentation.
