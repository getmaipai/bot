# StackChan music detection and the automatic dance (2026-11-13)

Owner request 2026-11-13: the unit hears and recognises music; first one subtle "I like this"; if the music goes on it
dances by itself in a build-up; it must not annoy and must respect the battery. Design: the StackChan dance note of the same
day (parts 2 and 3). The automatic dance is **off by default** (`robot.dance.auto`). Nothing here has run on a unit: the host
layer runs on a fake clock with scripted number streams, and the firmware feature core runs on synthesized signals.

## Parts

| Part | Where | What |
|---|---|---|
| Feature core | firmware patch 100, `hal/maipai_music_core.h` (plain C) | Four band-pass biquads (about 60-250, 250-1000, 1000-3000, 3000-8000 Hz), DC blocker and zero crossings per 20 ms frame; 6 s of onset signal and loudness envelope; once a second: level, band shares, tempo (autocorrelation of the onset signal, 60 to 187 BPM) and confidence, spectral flatness of the bands, zero-crossing rate and spread, share of the loudness variance at 3 to 6 Hz (speech), share of near-silent frames (speech), onset strength. |
| Tap, worker, event | firmware patch 100, `hal/hal_music.cpp`, `hal.cpp`, `hal_mcp.cpp` | `maipai_music_tap` (channel 0 only) in the audio input path queues a small frame every 20 ms; a low-priority worker task (4 KB PSRAM stack, 2.7 KB history in PSRAM) computes the numbers. Event `music_feat` (`lv b0 b1 b2 b3 bpm tc fl zc zs mo ps on`, about 110 bytes of JSON) once a second only while the last second was louder than RMS 400 and 3 s of history exist; serial line `MF ...` per loud second for the first half hour after boot; `music_stats` once a minute. |
| Self-hearing guard | firmware patch 101, `audio_service.cc` | The tap is told "suppress" while the audio processor runs (the unit listens), anything waits to play or played in the last 1.5 s (speech, tones): the front end stands still and the history clears. `maipai_music_set_muted()` is the hook for a hard mute (the unit has none yet); the host also drops a feature with `muted` set. |
| Decision layer | `bodies/stackchan/music_dance.py` | `judge` (a second is "clear music" or not), hysteresis, the stages, gates, caps, logging, the test mode. Pure but for its hooks and the injected clock. |
| Wiring | `music_dance_wiring.py`, `app.py`, `companion.py`, `dance.py` | Events reach the controller through `behavior.music_feat` (from `wake_on_touch`); touch and shake events chain after the dance's own; a half-second ticker lets a session end when the music stops. `dance.py` gained a `Plan` (the runner can play a build-up and dance, trigger `auto`) and the two settings. |

## What it does

1. **Detect.** Clear rhythmic music for 4 s in a row (one missed or doubtful second is forgiven). A second counts as music when
   the tempo is 60 to 187 BPM with enough confidence (low 55, medium 35, high 25), the bands are not flat (flatness under 70),
   the loudness has no strong 3 to 6 Hz rhythm (under 45, 40 or 55) and it is not mostly pauses (pause share under 40 unless
   the beat is very steady, confidence 50 or more: a sparse click track). A running stage uses lower bars (about a quarter) so
   the unit's own servo noise and quiet bars of a song do not end it.
2. **Nod.** Two small slow nods (8 degrees up, 5 head calls in all, well under the 40 a minute the unit allows) with a happy
   face or, one time in three, a wink, for about 3 s. No ring light. Once per music session.
3. **Build-up.** If the music is still clear 20 s after the nod began: the firmware's `happy` sway twice with a wink between and
   a held beat (9.7 s). In the last 3 s the ring starts a slow gold and lime glow at 0.2 brightness (the first lit pixels).
4. **Dance.** Straight on, 20 s of the firmware keyframe dances (`robot`, `happy`) with the little dance's ring show at 0.5.
   The head moves only inside the unit; the host makes no per-beat head calls. The dance is cut at the 20 s cap.
5. **End.** 9 s without clear music, the cap, or any touch, turn, wake word, shake, tilt, picture, low battery, offline or the
   emergency stop (the `DanceRunner` checks). Ring dark, head level, face neutral. Not built: "finish the current sway, one slow
   nod" (the end is immediate); the dance does not follow the tempo (build 3 of the design: beat-timed keyframes need a firmware
   change; the four built-in dances are used).

Rules: off by default; never at night, asleep, in a turn, with the camera or live cue showing, in full quiet or muted, or with the
estop latched; 10 minutes minimum after the last dance (nods too), 2 minutes between nods, 3 dances an hour and 10 a day (a nod
needs room under those caps); the same music never starts a second session (10 s of quiet re-arms). Battery on battery: 40
percent or more for the full dance, 20 to 39 percent the nod only, under 20 or unknown nothing. **While charging there is no
battery gate** (the design note's question 3 recommendation: no battery cost when plugged in); every other rule still applies.
This reads "while charging it follows the same stage rules" as "the same stages and gates, without the percent". Say so if the
owner meant the percent gates to apply on a charger too (`music_dance.py`, `_gate`).

It does not use the ambient head gate (idle level "still", charging): like the asked dance it is an explicit behaviour behind an
explicit setting.

## Settings and the hub command (Home must register them)

- `robot.dance.auto` (boolean, default **false**).
- `robot.dance.auto_sensitivity` (`low`, `medium`, `high`; default `medium`). Low wants a clearer beat; high takes a weaker one.
- Device command `music_test` on the StackChan command channel, answered `{"music_test": "started" | "refused", "why": ...}`,
  with an optional `{"fast": true}` payload (detect after 2 s, build-up 6 s after the nod: the whole chain in about 40 s).

The bot reads the settings from `settings_changed` as soon as the hub sends them (`DanceSettings.apply`). They still have to be
registered in `commons/spec/settings/keys.json` (device scope, honoured by home and bot) and Home's `robotSettingsKeys.json`, and
Home's Settings page needs the toggle, the sensitivity choice and a "Test music dance" button that sends `music_test`: a commons
tag plus a Home pin, not done here.

## What is analysed, what leaves the unit, and the switch

- **Local.** The unit measures the room's sound itself. Only about 110 bytes of integer features (level, four band shares, tempo,
  confidence, flatness and a few more) leave it, about once a second, only while the room is louder than RMS 400, and never audio.
  No sound is kept on the unit either.
- **Off unless the setting is on.** The analysis runs only while `robot.dance.auto` is on and the robot is neither muted nor in
  full quiet. With it off the unit reads no chunk into the features, sends no `music_feat` event and no `music_stats` diagnostic.
- **The switch.** The host calls the unit's tool `self.music.set(enabled)` (`MusicFeatureSwitch` in `music_dance_wiring.py`)
  when the setting turns on or off, when muted or full quiet start or end, on every connect, and retries a failed call every
  15 seconds. The unit keeps the state in RAM and in its own flash (namespace `mp_music`, key `on`, written only when it changes;
  never the websocket namespace), defaults to off when nothing is stored, and logs `music features off` or `music features on`
  at boot and at each change.
- Tests: `test_the_unit_analyses_music_only_while_the_setting_is_on_and_it_is_not_silenced`,
  `test_a_reconnect_states_the_switch_again_and_a_failed_call_is_retried` and the patch check
  `test_the_firmware_patch_keeps_music_analysis_off_until_the_host_turns_it_on`.

## Logging while it is on (`robot.dance.auto`, or a test)

All at INFO in the bot log, logger `maipai_body.bodies.stackchan.music_dance`:

- `StackChan music: detected clear music for 4 s (tempo 120 bpm, confidence 80%)`
- `StackChan music: stage idle -> nod (the nod (face happy, no ring light))`, then `nod -> watch`, `watch -> show`,
  `show -> spent`, `spent -> idle` with the reason in brackets (why a stage did not run: `no nod: it is night`, `no dance:
  battery under 40% ...`).
- Once a minute while features arrive, one compact INFO line (at most 400 characters) gives counts by decision reason and
  min/median/max for `lv`, `b0`-`b3`, `on`, `bpm`, `tc`, `fl`, `zc`, `zs`, `mo` and `ps`. For example:
  `StackChan music minute: n=41 mus=12 false=2 stage=idle why[music:12,weak_beat:29] lv=...`.
- For a rejected window at or above the level gate, at most one INFO line per 5 seconds shows its integer feature values and
  reason, e.g. `StackChan music window rejected: reason=weak_beat lv=... bpm=...`. Quiet windows are not logged per-window;
  these diagnostics contain no audio.
- The unit's own once-a-minute line (`unit music: music_stats seconds=.. loud=.. sent=.. dropped=.. suppressed=..`) says how
  many seconds it analysed, how many were loud enough, and how many chunks it skipped while the unit spoke or listened.
- On the serial console (first half hour after boot): `MF <ms> <level> <bpm> <conf> <flat> <zc> <zcspread> <mod> <pause> <onset>`.

## Test script for the owner

Needs: the firmware with patches 100 and 101 flashed, the bot release with this change, Home registering the two settings and the
`music_test` command. The unit awake, upright, daytime, battery 40 percent or more (or charging).

1. In the robot's settings turn **Dance to music** on (`robot.dance.auto`); leave sensitivity on medium.
2. Check without music first: press **Test music dance** (`music_test`, add `fast` for a 40 s run). You should see the nod,
   then the build-up and the dance with the ring, and the log lines above. This proves the host half and the dance, not the
   hearing.
3. Play a song with a clear beat (pop, dance, rock) at a normal volume from a phone or speaker about 1 m from the unit. The
   room should be clearly loud: the unit sends nothing under RMS 400 (a quiet room measured 80 to 110, music at 30 cm 2,000
   or more).
4. What you should see, counted from the start of the song: after about 5 s, two small nods and a happy or wink face, ring
   dark. If the song goes on, at about 25 s a build-up (about 10 s of swaying; the ring starts a dim glow in the last 3 s),
   then a dance with the ring show of up to 20 s. Stop the music and it ends about 9 s later. A touch, a word to it, a shake
   or a picture ends it at once.
5. It then rests: no new nod for 10 minutes.
6. If it never triggers: look at the minute line and `unit music: music_stats`. `loud=0` means the room was too quiet (turn it
   up or move closer). Loud but `0 music windows` means the numbers did not look like music (try sensitivity high; slow or
   free music such as classical has no steady beat and will not trigger). A nod but no dance means the music was not clear
   for the full 20 s or the battery is under 40 percent. Send me the minute lines and the `MF` lines of a failed song.
7. If it triggers on TV or on talk: set sensitivity to low, or turn the setting off, and send me the minute lines from that
   time. A TV theme tune can score as music for a while: that is the known cost of detecting music from a few numbers.

## What was and was not checked

- Checked with fakes and synthesized signals: the C core against a 120, 90 and 150 BPM click track, a kick, snare, hat and chord
  loop at 120 and 100 BPM, a steady 440 Hz tone, white noise, noise modulated at 4 Hz, a syllable pattern and a quiet room (tempo
  within 2 BPM, music read as music at all three sensitivities and the rest not); the host layer on scripted streams (3 s
  nothing, 4 s the nod, 24 s the build-up and dance, speech-like streams never, gaps, caps, gates, battery tiers, the test
  command); the plan on the real `DanceRunner`; the event wiring through a real `StackChanBehavior`.
- Built with `recipe.sh` (patches apply after 081 and after the timers patches 090 to 094, the build passes, the host egress
  scan passes). The build is 5,584 bytes larger (3,812,368 to 3,817,952), flash code 4,800 bytes, static internal data 192
  bytes, plus about 0.5 KB queue in internal RAM, 2.7 KB history and a 4 KB task stack in PSRAM.
- **Not checked, needs a unit:** every threshold (tempo confidence, flatness, 3 to 6 Hz share, pause share, the 400 level
  gate) is a guess tuned only on synthesized signals; real music, TV, talk, the unit's own servo noise during a dance (the dance
  ends on silence, so servo noise that looks like a beat could keep it going until the 20 s cap), the CPU cost, the audio task's
  stack headroom (about 300 bytes more; 1,760 were free), the PSRAM task stack (a PSRAM stack was once suspected of a stall in
  0.2.24; this task does no flash or NVS work), whether the unit hears its own speech or chimes despite the guard, and whether the
  firmware dances look right (the pitch sign of the built-in dances is still unverified).
- Not built: a nod and settle at the end, beat-timed dances and ring in firmware, harmonicity as a speech cue, the unit's own mute.

Steady-sound path (0.2.70): a second real song never gave a stable tempo, so the beat bar alone rejected it. A window with level 800 or more, modulation under 32, pauses under 20, flatness under 97 and some tempo found counts as music on medium and high.

## On the unit with no hub

The standalone unit can make the same per-second music decision and track its nod and dance session locally with the plain C99 header `body/maipai_body/bodies/stackchan/firmware/assets/maipai_music_judge.h`.

## Cycles for hours (owner 2026-11-13)

A music session is one stretch of music whose gaps stay under 60 s (a song change does not end it). Inside it: the slow start (nod, build-up,
dance), then a dance block of rounds (5 minutes on USB or charging, 2 minutes on battery), then a 90 s break (calm, no dancing), then the next
cycle starts with the build-up again, and so on for as long as the music goes on. The hourly and daily caps are gone; the 2 minute wait
after a session, the interrupts (touch, wake word, turn, mute, quiet, tilt, picture, offline) and the battery rules remain. The unit's own
offline dance (patch 121) still does one block: the same cycles on the unit are the next step.
