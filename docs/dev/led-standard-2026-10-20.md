# Light standard for every MaiPai robot (2026-10-20)

One meaning per colour and style, on every body. A person who learns it on one robot reads any other. The look table in
`body/maipai_body/indicator/looks.py` is the single source (EYES-02: "the only site of a colour or a level"); this note says what the
table means, extends it, and says how each body shows it. Status: DRAFT, pending architect review (new design note).

## Principles

1. **Light tells the truth about the senses.** Whenever sound leaves the robot for the hub, or a picture is taken that the person is
   meant to know about, a cue is lit that no setting, night level or child level can dim below its floor.
2. **Quiet by default.** Local wake-word listening is not a cue: nothing leaves the robot, so the robot shows its ordinary idle look.
   Light is for state changes a person needs, not decoration.
3. **No red, ever.** A red light on a face that watches a child reads as alarm (`Palette`, closed set: white, green, blue, amber,
   cyan, magenta, pink, off; pink is a hue near 330 degrees, a bright pink-white, never red). A fault is steady amber.
4. **One table.** No body, renderer or feature names a colour or a brightness. It asks `resolve()` for a look; each body only
   translates a look into its own hardware. A grep test holds that line, and extends to every body renderer (see Compliance).
5. **Night is dimmer, never silent about privacy.** Night and child levels scale ordinary rows; the live and camera cues keep a 0.5 floor.

## What each state shows

| State (what is true) | Colour | Style | Brightness | Notes |
|---|---|---|---|---|
| Live: audio is being sent to the hub | green | steady | at least 0.5, ignores night and child levels | the only "recording" signal; wake-word scoring is local and is NOT live |
| Camera: a visible capture or stream | pink | `flash`: two quick flashes at capture start, then steady for the capture | at least 0.5, ignores night and child levels | Jesse 2026-10-20: distinct from every other colour, like a shutter flash. Replaces StackChan's red ring and the bot's cyan. Still photo, video stream and live view all use it |
| Silent ambient capture | none | none | none | the ONLY exception: opt-in `robot.ambient_vision` (default off), owner decision 2026-10-20; see below |
| Alarm or timer ringing | amber | blink, one cycle per second at most | bright then dim | `robot.indicator.alarm` can turn the light off, the sound is separate |
| Fault (thermal, motor, hardware) | amber | steady | 0.7 of the day level | never red |
| Microphone muted (software mute) | amber | steady | 0.4 of the day level | labelled "software mute" in settings; a physical cut would be a separate row |
| Held or carried | magenta | steady | 0.5 of the day level | MOVE-CARRY-01 |
| Offer: the robot asked and listens locally for yes or no | blue | steady | 0.6 of the day level | not green: nothing leaves the robot |
| Listening to the person (turn open, local) | blue | steady | day level | |
| Thinking | magenta | slow breathe, 3 s | 0.8 of the day level | NEW style |
| Speaking | white | steady | day level | |
| Idle, awake | white | steady, dim | 0.35 of the day level | |
| Sleep or night idle | blue | steady, very dim, or off (`sleep_eyes`) | 0.3 of the night level | |
| **NEW** Connecting to Wi-Fi or the hub | blue | slow pulse, 2 s | 0.5 | after power on or a Wi-Fi switch; ends in idle or offline |
| **NEW** Offline (hub not reachable, robot still works) | amber | two short pulses every 10 s | 0.3 | local mode; never alarming |
| **NEW** Pairing or setup waiting for a person | cyan | slow pulse, 2 s | 0.6 | cyan is now free of the camera, so it means 'look at me, I need you' |
| **NEW** Charging | green | slow breathe, 4 s, only while on the dock | 0.3 | dark when full; never mistaken for live, because live is steady and at least 0.5 |
| **NEW** Battery low (under 15 percent, not charging) | amber | one pulse every 20 s | 0.3 | spoken line is separate |
| **NEW** Updating firmware | white | fast pulse, 1 s | 0.5 | robot does not move or listen while updating |
| **NEW** Dancing | white | steady | 0.35 | no colour show; the face and head carry the dance, the light stays quiet |
| Off (`robot.indicator.enabled` false) | dark | | | never reaches live, camera or alarm |

Priority, highest first: live, camera, alarm, fault, held, muted, offer, then the connection and power rows, then the funnel
(thinking, speaking, listening), then idle or sleep. Two cues never blend: the higher row wins whole.

Style names are a closed set: `steady`, `breathe` (slow, sine), `pulse` (short on, long off), `blink` (alarm only), `flash` (two quick flashes, camera only). Periods are
UNMEASURED design defaults and stay in the look table.

## The silent-capture exception

Jesse asked for continuous silent vision (2026-10-20). It is allowed under four limits: the setting is opt-in and off by default;
the picture is dropped in the same call and only a short text note is kept; it never runs in quiet hours or with a child present;
and the Settings page and the robot's own screen show plainly that ambient vision is on while it is. Visible capture never uses it.
A robot with a camera and a screen should show a small steady "ambient vision on" glyph on the screen (not the light), so the person
can always tell the mode without a flash on every capture.

## How each body shows it

| Body | Hardware | How it shows a look |
|---|---|---|
| Reachy Mini | two-colour eyes (the Eyes part) | direct: `Look(colour, brightness)`; styles by animating brightness at the Eyes driver |
| StackChan | 12-pixel RGB ring, whole-ring colour calls (`set_led_color`, `set_led_colors`), channel max 168 | every pixel the look's colour at `brightness x 168`; styles are driven by the host timer (no firmware change); the face carries expression, the ring carries state, they never share a job |
| Pi build and future builds | light ring or dial, chest LCD | the look goes to the ring or dial; pictures and text go through the display router (`robot/display.py`), never to a light |

The ring must not show expression colours. StackChan's expression map currently sets per-primitive LED triples
(`BodyAction.led`); those are retired in favour of the look table, so the ring means one thing.

## Defects this note finds (fixed in the same change)

- StackChan lights the whole ring RED for the camera (`_CameraAdapter._light_on`, `_LedAdapter` camera branch). Red is outside the
  palette. Fix: pink with the `flash` style, from `resolve()`, with the 0.5 floor. Reachy's camera look moves from cyan to pink too.
- StackChan has no live (green) cue while audio streams to the hub; Reachy does. Fix: the StackChan service reports the live fact to the director.
- StackChan expression LED triples bypass the look table. Fix: remove, render through `resolve()`.

## Compliance and tests

- A grep test: no colour name, RGB triple or brightness literal in any body adapter or renderer outside the look table and the
  palette-to-RGB map of that body (one map per body, in the profile).
- A body conformance test: for every `LookKey`, the body renderer produces output; live and camera are never below the floor and are
  never produced by a setting.
- A StackChan test: camera capture asks for pink; the emergency stop, quiet hours and `robot.indicator.enabled=false` never change it.
- An inventory test as today: every capture site goes through the tap that raises the cue; the one silent site is the named exception.

## Decided by Jesse 2026-10-20

Camera is pink with a flash style (distinct from all other colours). Wake-word listening shows nothing special. Charging is a slow green
breathe while docked and low battery is an amber pulse. Other proposed rows and all periods are defaults he can change.
EOF

## Status 2026-10-20

Built: the look table rows, styles and periods (`indicator/looks.py`), pink in the palette, `Look.style` and `Look.period_s`, the StackChan ring
renderer (`bodies/stackchan/ring.py`), the camera cue as two pink flashes then steady pink, expression no longer touching the ring,
and `StackChanRingIndicator` (`bodies/stackchan/ring_indicator.py`), an `Indicator` the existing director can drive.

Not built yet, in order: (1) wire the director and `StackChanRingIndicator` into the StackChan service, with a 50 ms `tick()` thread, so
the live (green), connection, offline, charging and low battery rows reach the ring; this needs a "voice is going to the hub" fact from
the xiaozhi uplink and the battery and connection facts from the device client; (2) the light flags for pairing, updating and dancing in
the callers; (3) the Reachy Eyes protocol gaining a pink word; (4) the grep and conformance tests extended to every future body; (5) the
architect review of this note. Silent ambient capture remains the one cue-less capture.

## Wiring status 2026-10-20 (later)

Wired on StackChan: `StackChanLightService` and `LightPoller` (`light_service.py`, `light_wiring.py`) start with the StackChan channels in
`app.py`. The camera cue reaches the service from the camera adapter (`cue_sink`), the live (green) cue from the turn bridge around the
hub speech stream (`live_sink`), and connecting, offline, charging and low battery are polled once a second (battery once a minute). Pairing,
updating and dancing flags have no caller yet. Nothing here has run on a unit.

## Cue sequences on StackChan (owner request 2026-10-20)

| Moment | Screen | Ring | Sound | Owner |
|---|---|---|---|---|
| Power on, joining Wi-Fi | plain "Connecting to Wi-Fi..." text, no face | blue slow pulse | none | firmware (patch 033, planned): the host is not connected yet |
| Wi-Fi needs a person (setup) | the setup instructions | cyan slow pulse | none | firmware (patch 033, planned) |
| Wi-Fi joined, opening the hub session | plain "Connecting to Home..." text, no face | blue slow pulse | none | firmware (patch 033, planned) |
| Ready (hub session open) | the face appears | settles to idle white, dim | one short soft chime (the firmware's success sound) | face and chime: firmware; ring: host (the `connecting` fact clears when the device session opens) |
| Wake word heard or a tap opens a turn | head lifts and the face brightens (`perk`) | blue steady | the firmware's rising pop-up tone | host: ring and `perk`; tone: firmware (already plays) |
| Audio streaming to the hub | listening face | green steady (the live cue outranks blue and is held 0.5 s) | none | host |
| Thinking | `doubt` face, head attends | magenta slow breathe | none | host |
| Speaking | speaking face | white steady | the reply | host |
| Turn over | settle | idle white, dim | none | host |
| Hub unreachable after ready | face stays | amber double pulse, two short pulses every 10 s | none | host |

Notes: the firmware has no wide-eyed emotion (its six are neutral, happy, angry, sad, doubt, sleepy), so "it heard you" is the head lift
with the brighter face, not wider eyes; wide eyes would need a face skin change in the firmware (patch 033 can add one). Wake-word
scoring alone shows nothing; the detected wake word is a state change to listening and does show. `double` joined the closed style set.
