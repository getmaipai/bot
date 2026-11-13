# StackChan mute, vision off and full quiet (2026-11-13)

Built from the owner's final design (2026-11-13): "tap on the mouth to mute and unmute; tap on the eyes to stop vision; and tap
above and between the eyes to basically disable movement, talking and listening; with each of these we have different screens ...
I wouldn't want an X on the eyes though, looks dead." Everything is a touch on the face on the screen, not on the head strip. The
design this builds on is the hard-mute note (mechanics: the microphone chip is powered down and read back; the unit is the
authority). Firmware patches 105 to 108, host `bodies/stackchan/privacy.py`. The recipe intentionally skips patch 109; the next batch begins at 110.

Nothing here has run on a unit. The host side is tested with fakes; the firmware builds with `recipe.sh`. Section 7 lists what only
a flash can show.

## 1. Every touch gesture the unit has today (read from the patched source)

| Gesture | Where | What it does |
|---|---|---|
| Tap on the face | `stackchan_display.cc`, panel click | Starts a listen, or ends one (the old tap). 800 ms debounce. A tap that began in the top 24 px is ignored (a swipe from the top bezel reports a point at y 0 to 16 and then loses it, which LVGL read as a tap). |
| Swipe left / right | `OnGesture`, `LV_DIR_LEFT` / `LV_DIR_RIGHT` | Volume down / up by 10 (toast "Volume N"). |
| Swipe down | `OnGesture`, `LV_DIR_BOTTOM` | Stop: ends speech or a listen, like a tap. |
| Swipe up | `OnGesture`, `LV_DIR_TOP` | Opens the quick-settings panel (volume, brightness, saved Wi-Fi, Done). This is the "drag for settings" gesture. Inside the panel a swipe up or down closes it. |
| Any touch while a timer rings | patch 093, `PRESSED` | Ends the ring. |
| Head touch strip | `hal_head_touch.cpp` | Pets and taps; not the screen, untouched here. |

No gesture on the face opens Home; the unit has no Home screen. The boot cover and the Wi-Fi setup screen take no face touches.
The swipes can start anywhere on the face. They are told apart from taps by LVGL's own gesture limit.

## 2. The hit map (320 by 240, `maipai_touch_core.h`)

Plain C, tested on the host. The regions tile the screen with no overlap:

| Region | Box (x, y) | Acts on |
|---|---|---|
| Edge margins | x under 20 or from 300, y under 28 or from 220 | nothing, ever. Swipes start here. |
| Forehead, above the eyes | x 20 to 299, y 28 to 55 | hold 0.5 s: full quiet |
| Forehead, between the eyes | x 112 to 207, y 56 to 119 | hold 0.5 s: full quiet |
| Left eye | x 20 to 111, y 56 to 149 | tap: vision off or on |
| Right eye | x 208 to 299, y 56 to 149 | tap: vision off or on |
| Mouth | x 112 to 207, y 120 to 219 | hold 0.5 s: mute or unmute |
| The rest (cheeks) | everything else | a tap starts a listen, as today |

The eyes are drawn at x 56 to 108 and 212 to 264, the mouth at y 130 to 190, so each target is bigger than what it toggles.

A touch counts only if all of these hold: the finger stays within 10 px of where it went down; it is released (or still held)
inside the region it began in; it is a tap (400 ms or less) or a hold (500 ms or more). Between 400 and 500 ms it does nothing, so
a slow tap is never a hold. A touch that begins in an edge margin is never a toggle, however still and long. Anything that strays
more than 10 px is a drag and toggles nothing, even if it comes back to where it began.

**Tap or hold (decided):** the eyes toggle on a plain tap. A wrong tap there costs only the camera, and the half-lidded eyes show
it. Mute and full quiet need the 0.5 s hold: a plain tap on the mouth is what a person does to stop a reply or poke the face, and
a mute that nobody notices stops the robot hearing. A hold acts while the finger is still down, so the change shows at once.

The toggle regions and the margins never start a listen. The unit also refuses to start any listen while muted or in full quiet
(section 4), so a tap on the cheek does nothing then except a log line.

## 3. The three states and what each does

All three are independent and combinable, are saved in the unit's own NVS namespace `maipai_priv` (keys `mute`, `vision`, `quiet`,
`local_unmute`; never the websocket namespace) and are restored at boot.

| State | Listening | Speaker | Head | Camera |
|---|---|---|---|---|
| Muted | off: wake word, stop word, voice processing, microphone chip | host says nothing (no turns, no reactions, announcements and timers logged as missed) | normal | normal |
| Vision off | normal | normal | normal | not read: no frame captured, none sent, none analysed, no picture question |
| Full quiet | off, exactly as for mute | silent: the codec drops all output | holds: no move from anyone, a move under way stops | unchanged (chosen: vision is its own switch) |

Full quiet leaves vision as it is on purpose: the owner called it "disable movement, talking and listening" and gave vision its own
switch. The head holds where it is; the servos are not torqued off by this.

The face for each state (existing faces and palettes, no new art, no X on the eyes):

| State | Look |
|---|---|
| Muted | the mouth is one flat closed line, whatever the emotion or the lip sync says (`MintMouth::setSealed`) |
| Vision off | the eyes are calm half discs, a little low so they look down (`MintEye::setLowered`); never an X |
| Full quiet | the sleeping face (patch 073) with a small pause mark (two short bars) above the eyes |
| Combined | the parts combine; in full quiet the eyes are shut so only the mouth and the mark show |

The toggle makes no sound: the eyes blink once (260 ms) and the new look appears. The looks persist: the muted mouth stays through
blinks, replies and the idle look-around; the sleeping face holds against every other emotion; the saved state is drawn once at
boot, before the first tap.

## 4. How mute really cuts the microphone (patches 106 and 107)

1. The guard sits inside the codec class, below the audio task (which reopens the input on its own every read): `EnableInput(true)`
   returns at once while blocked, `Read()` hands back paced silence, and `AudioService::ReadAudioData` reads nothing.
2. `EnableWakeWordDetection(true)`, `EnableVoiceProcessing(true)` and `SetStopWordArmed(true)` refuse; `Application::SetListeningMode`
   (the one way into the listening state: tap, wake word, host start, reconnect) refuses and puts the unit back to idle.
3. The main task stops what is listening, disarms the wake and stop words, closes the input and writes the ES7210 power-down
   registers by hand (0x47 to 0x4C to 0xff, 0x40 to 0xc0, 0x01 to 0x7f, 0x06 to 0x07), then reads them back. `mic_off_verified` is
   true only if 0x47 to 0x4C read 0xff and 0x06 has its low three bits set. The registers read are reported as `mic_regs`.
4. At boot the codec constructor powers the chip down before anything can open it, when the saved state is muted or quiet.
5. Unmute needs nothing special: the audio task opens the microphone on its next read, and the wake word is armed for an idle unit.

Honest limit (unchanged from the design note): this is a register and clock power-down plus a firmware lock, not a cut wire.

## 5. Host behaviour (`bodies/stackchan/privacy.py`, wired in `app.py` `_wire_privacy`)

- `PrivacyState` reads the unit's `privacy` event and its minute `wake_stats` (`muted`, `vision_off`, `quiet`, `mic_off_verified`,
  `mute_source`). Nothing is assumed: until the unit reports, every fact is null. `muted_reason()` is the named hook the announcement,
  repeat and dance code ask: `"muted"`, `"full quiet"` or None (the dance is refused with it; the repeat builder's `RepeatControl(muted=...)`
  takes `privacy.silent`; the announcer's `muted` and `quiet` flags follow the unit's state, whoever changed it).
- No turn: `StackChanTurnBridge.listen` goes idle on a start or detect, and `speak_reaction` returns False, while muted or in full quiet.
- No head move: `_HeadAdapter` returns `{"blocked": "full quiet"}` for any `set` or `goto`; the spoken head command says it holds its head still.
- Vision off: `watch_allowed` is false (no stream ask, no stall ladder), `camera.frame`, `stream_frame` and `stream(enabled=True)` are
  refused, the camera stream is told to stop, a frame that still arrives is dropped before it is kept or analysed and reported as a leak,
  and "can you see me" answers from the same flag. The admin's saved `robot.vision` and `robot.camera.watch_level` are not touched.
- Self-heal: `wake_stats` `muted=1` already skips the wake self-test; a camera that is off is not a stalled camera (the watch level
  gate reads the same flag); a refused rebuild is not a failure.
- **Leak check** (an error event, one ERROR log line a minute per kind, and the existing error look for 30 s): a minute report with
  `muted=1` (or `quiet=1`) showing `armed=1`, `fetches>0`, `detections>0` or `vad_speech>0`; a minute `camera` report with
  `vision_off=1` and `captured>0` or `sent>0`; a camera frame arriving over the avatar socket while vision is off. A state must have
  held 75 s before a minute report counts (its counters began before the change), and 5 s before a late frame counts.
- A mute the unit cannot read back stays "unconfirmed": the hub command answers `{"muted": true, "status": "unconfirmed"}` and a
  WARNING says so after a minute.
- **The host never sends an unmute on connect** and never resets the unit's state. On connect it reads the unit (`self.privacy.get`),
  sends the unmute policy, and retries only what Home asked and the unit never confirmed. Home's first settings dump can only restrict;
  after that a changed value is pushed, an unmute included (the admin confirmed it in Home).
- Remote unmute needs a confirm: the hub `unmute` command without `"confirm": true` answers `{"status": "needs_confirm"}` and changes nothing.
- `robot.mute.local_unmute` (default true). Off: the unit's own face may mute but not unmute or leave full quiet (the unit refuses
  and pushes a `privacy_refused` event); only the hub can.

## 6. What Home needs (a separate task; these are the keys and the contract)

Settings (robot scope, group `robot.hello`):

| Key | Type | Default | Notes |
|---|---|---|---|
| `robot.muted` | boolean | false | already read by the announcer; this build drives the unit's hard mute from it. (The key is `robot.muted`, not `robot.mute`.) |
| `robot.vision_off` | boolean | false | new |
| `robot.quiet` | boolean | false | already read by the announcer; now also drives the unit's full quiet |
| `robot.mute.local_unmute` | boolean | true | new; off means only Home can unmute or leave full quiet |

Device commands (existing spec names): `mute` and `unmute`. The `unmute` payload must carry `"confirm": true` (Home asks an admin to
confirm first); the answer is `{"muted": bool, "status": "confirmed" | "unconfirmed" | "needs_confirm", "mic_off_verified": bool}`. Home
should set `deviceStates.muted` only from `status == "confirmed"`.

Check-in members (always present, null until the unit reports): `muted`, `vision_off`, `quiet`, `mic_off_verified`, `mute_source`
(`face`, `home` or `boot`). Show "Muted" only when `muted` and `mic_off_verified` are both true; while Home's request is out show
"Asking the robot", and if the unit does not confirm, "The robot has not confirmed", never "Muted". When the unit was changed at the
unit (`mute_source` is `face`) accept the unit's state as the truth and show it with the time. Mirror the three states into the
three toggles from the check-in. A spec change is not needed for any of this (new check-in members are additive).

## 7. Verified with fakes only, and what needs a flash

Verified with fakes: the touch classifier on a table of points and durations (tap, hold, dead band, drag, edges, region borders, clock
wrap), 26 host tests of the state, the leak check, the controller, the check-in, the head and camera gates and a dropped frame over a
real avatar socket, the series applying cleanly in `recipe.sh` and building (the patched firmware compiles and links; image size is in
the commit message).

Needs a flash, and cannot be known before: that the ES7210 registers really read back 0xff and the low bits of 0x06 on this unit (if
not, `mic_off_verified` stays 0 and `mic_regs` in the log shows the real values; the mute itself still holds); that LVGL delivers
steady `PRESSING` events while a finger rests still (the hold acts from them); the feel of the 10 px and 0.5 s numbers on a real
finger; the half-lidded eyes and the flat mouth against the owner's eye (a still of each should be approved first, his 2026-11-10 rule);
that the screen rotation (patch 067, upside down) maps the touch regions the same way as the face; the mic-off current drop; and the
real camera sensor, which this build stops reading but does not power down.

## 8. Owner test script (on the unit, after a flash; nothing here needs a command)

1. Hold your finger on the mouth for half a second. The eyes blink once and the mouth becomes a flat line. No sound. The host log
   shows `unit privacy: muted=1 ... source=face` then `StackChan privacy: muted=True ... (microphone chip verified off)`.
2. Say the wake word, and talk for 30 seconds. Nothing happens. The next `unit wake` line shows `muted=1 armed=0 fetches=0 detections=0`.
   Tap a cheek: nothing, and the log says `unit tap: decision=ignored why=muted`.
3. Hold the mouth again. It blinks and the smile returns; the wake word works within a second.
4. Tap the mouth quickly: nothing. Press the mouth slowly and let go at about 0.4 s: nothing.
5. Tap an eye. Both eyes become half discs. The camera log line shows `vision_off=1 vision_skipped=...` and no frames reach the host.
   Tap an eye again; the eyes return.
6. Hold the forehead (between the eyes, or the strip above them) for half a second. The face goes to sleep with a small pause mark. Walk
   in front of it and speak: no head move, no sound, no listening. Hold the forehead again: it wakes.
7. Combine: mute, then vision off. The mouth is flat and the eyes are half discs. Unmute: only the mouth changes back.
8. The drags still work: swipe up for quick settings (then swipe down or up to close it), swipe left or right for volume, swipe down
   to stop a reply. Start a drag on the mouth or on an eye: it toggles nothing. Start one from the very top edge: nothing toggles.
9. Mute, then power-cycle the unit: it comes back muted (the log says `saved state: mute=1` and the microphone is never opened).
10. In Home turn "listening" off and on: Home shows "Muted" only after the unit confirms; an unmute asks for a confirmation.

Boot and log check list: `MAIPAI-PRIVACY: saved state: mute=0 vision_off=0 quiet=0 local_unmute=1` at boot (the serial log; the
host sees the `privacy` event only when a state is on); `MAIPAI-PRIVACY: microphone off, read back verified (47:ff,...)` after a mute;
`face: touch ended kind=... region=... action=...` for every finger; no `StackChan privacy LEAK` line ever.
