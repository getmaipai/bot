# Changelog

All notable changes to MaiPai Bot. Format follows
[Keep a Changelog](https://keepachangelog.com); versions follow semver.
Everything stays `0.x` until the product passes its battle-tested
checklist (`docs/dev.md`).

## [Unreleased]

## [0.2.53] - 2026-10-23

### Fixed
- Pose reactions (host only). A different pose now gets its joke after a 15 s floor; the same pose repeated is held to 2 minutes. Returning upright says a relief line. The line is spoken on its own thread, so a joke no longer blocks touch and orientation events for its whole length, and events are read every 0.5 s instead of every 1 s. The pose face is held while the pose holds: it is sent again after every speech or turn end, the rest renderer and ambient head moves leave it alone, and a reconnect re-applies the current pose instead of resetting it to upright.
- Face detection after a hub restart: the asset manifest fetch retries once with fresh credentials on a 401, and a failed face model load is retried after 10 s, 30 s, 60 s, then every 5 minutes.

## [0.2.52] - 2026-10-23

### Added
- Idle sleep (host only, no firmware change). After 2 minutes with no touch, person or turn the StackChan shows the sleepy face; after 5 minutes it sleeps: eyes fully closed, screen dimmed to 5, ring dark, head level and still. A touch, shake, person or turn wakes it with one short blink, then the neutral face; the screen returns to the owner or night level and the ring to its normal look. Night mode halves both times.

## [0.2.51] - 2026-10-22

### Changed
- Firmware patch 072: a tilt shows up faster. The orientation tracker filters at 0.5 instead of 0.3 and holds a new axis for 5 samples instead of 10, so a pose is reported in under a second instead of about 1.5 seconds. The pull, total-gravity and margin guards are unchanged. Parked for the next flash.

## [0.2.50] - 2026-10-22

### Fixed
- Firmware patch 071: the unit reported its first pose change and then nothing, not even the once-a-minute repeat (pose test, 2026-10-22). The tracker of patch 067 required a new axis to beat the absolute pull along the current one, which turning from one ear to the other can never do. It now compares against the signed pull in the current pose's direction.
- The light sensor and camera are also ignored for 30 seconds after the unit is upright again, so a sensor that was just covered cannot start night mode.

## [0.2.49] - 2026-10-22

### Fixed
- The robot stayed in night mode in a lit room, so its spoken lines were skipped: the light sensor behind the screen glass reads 0 to 4 lux whatever the room (a lit afternoon read 3 to 10, a unit tilted for a pose test 0 to 2). Night now starts only when the sensor and the camera frame both say dark, ends as soon as either says light, and the sensors are ignored while the unit is not upright.
- Orientation sides are named by the robot's own left and right (its right ear down is `right_side`, measured 2026-10-22), and a skipped orientation line says why (night mode, asleep).

## [0.2.48] - 2026-10-22

### Added
- Firmware patch 070: when a reply ends the unit reports its playback numbers (`playback` event, host log "unit playback"): frames that arrived, frames still waiting to be decoded and played, playback gaps (the speaker ran dry) and the longest gap in ms. It separates a decoder that cannot keep up from a network that delivers late, for the stutter that the host's own clean pacing numbers cannot explain.

## [0.2.47] - 2026-10-22

### Fixed
- The robot kept re-opening a turn out of nothing: after a silent turn the host tells the unit to go idle, but audio already in flight made the "audio with no listen start" rule (0.2.41) start another turn, so the unit cycled listen, no speech, idle for about 25 seconds and ignored questions asked in the gaps. Audio that follows a silent turn no longer starts a turn; a real listen start or a wake clears that. The follow-up listening window is 5 seconds instead of 8.
- The face started talking about a second before the voice: it was told at synthesis time. It now starts when the first reply frames go to the unit.

## [0.2.46] - 2026-10-22

### Changed
- "Can you see me", "what do you see" and "is the light on" now depend on how long the camera has been streaming. In its first minute the robot says the camera is just starting up and to ask again in a few seconds. Once it has run a while and nothing can describe the room, it says plainly that the camera is on, whether the room looks bright, dim or dark from the frame, and that it cannot describe the room yet, with no promise to retry. A face seen a moment ago still gets a yes.

## [0.2.45] - 2026-10-22

### Changed
- No camera picture goes to Home for a model caption (owner, 2026-10-22: the proper design, "Look", comes first). The poster of 0.2.44 stays in the code, tested, behind `PICTURE_POSTS_ENABLED = False`. Everything else of 0.2.44 stands: the frame type fix, the start retries, light questions answered from the frame brightness, and "my camera is warming up" instead of "face finding is not ready"; sight questions are answered by the host from a face seen a moment ago or the brightness.

## [0.2.44] - 2026-10-22

### Added
- The robot describes what it sees. The body posts a camera picture to Home (`POST /api/devices/me/vision`, the robot's session cookie) so Home's chat model can keep one plain sentence about the room for 90 seconds, which the robot's turns then know: each picture costs Home a model call, so the default is slow: one a minute while idle, only if the scene differs from the last one posted (a tiny gray thumbnail compare, nothing kept), at once (but never within 10 s) when the brightness bucket changes, and at least every five minutes even if nothing changed; never during a turn, at night, or when camera watching is off; stopped by `robot.vision` none or on demand (the `settings_changed` value is read); after a 429 or 503 the intervals double up to ten times and reset on a success. The picture is held in memory only until it is posted, and only counts and codes are logged.
- "Can you see me" and "what are you looking at" first ask Home to describe a picture and then go to the normal turn, so the hub answers from that description. "Is the light on" never costs a model call: the host answers from the frame's brightness (the unit's light sensor only when there is no frame). When Home cannot describe one, the host answers from what it knows: a face seen a moment ago, or how bright the frame is ("it looks dark in here, so the lights are probably off"). It no longer says that its face finding is not ready; it says the camera is warming up.

## [0.2.43] - 2026-10-22

### Added
- A once-a-minute "StackChan frame check" log line while the face detector finds nobody: the frame size, the average JPEG size, and the detector's best score for the frame as it is and rotated, mirrored, flipped or colour-swapped (a rotated or mirrored frame defeats the detector). Nothing is stored; only the scores are kept.
- The orientation reaction logs what it did with its spoken line (said, or why it was skipped: quiet, a conversation on, one said under two minutes ago, or the voice could not start it).

### Changed
- The unit's events (touch, swipe, shake, orientation) are read every second instead of every two, so a tilt reaches the robot sooner.
- The "speech-to-text ended" log line now says how long after the last loud sound it came (the wait for the end of speech), so a slow answer can be split into hearing, thinking and speaking.

## [0.2.42] - 2026-10-22

### Added
- Firmware patch 069, to find and avoid the freeze (every tool call times out while the socket stays open, no reboot): a stall watch in the IMU task writes the state of the known tasks to flash when the main loop stops for 8 seconds, and the next "boot" event carries it as `stall`; the camera sends no frames while the unit listens, speaks or connects (`paused` in the "unit camera" line); the screen-flip code is compiled out of the firmware.

### Changed
- "Can you see me" in the first minute after boot says the face finding is still starting up and to ask again, instead of that it is not ready.

## [0.2.41] - 2026-10-22

### Fixed
- The robot answered one question and then stopped responding. Two causes: after a reply the unit can listen without telling the host (no "listen start" arrives, so the audio is ignored), and the unit's own state guard counted its time against a clock that resets on every state change, so a unit that had just begun listening was sent back to idle two seconds in. The host now starts the turn from audio that arrives with no listen start (six frames in a row within two minutes of the last turn), and firmware patch 068 fixes the guard arithmetic, drops its Listening limit to 20 seconds, and sends the listen start again when a reply ends while the unit is already listening.
- Face watching that cannot load now logs one line with the cause instead of a traceback.

## [0.2.40] - 2026-10-22

### Fixed
- The face was drawn upside down: the first guess of the orientation table was inverted. The accelerometer reads +1 g along the axis that points up, and the unit standing normally reads axis +y, so +y is now upright and -y upside down.
- The camera showed "looked at 0" with frames arriving: the installed bot could not load face watching (`No module named 'huggingface_hub'`, then the Reachy SDK, which the hub bundle does not have) because the camera bridge imported the face-recognition module at load. It is now imported only when someone is recognised, and a test loads the bridge with those packages missing.
- The unit stopped answering screen-locked tool calls (LEDs, head, events) soon after the screen was flipped, with the face frozen and listening stuck. The flip of the screen is switched off on the host until the firmware does it safely; pose faces and lines still work.

## [0.2.39] - 2026-10-21

### Added
- Firmware patch 067: the unit reports which way gravity points (an `orientation` event on every change and once a minute, with the dominant axis and the filtered vector in milli-g) and has a `self.screen.set_rotation` tool (0 or 180) that flips the screen when it is upside down. A 180 lasts 150 seconds unless sent again, so the screen cannot stay flipped if the host goes away; the host re-sends it every minute while upside down. With this the orientation reactions of 0.2.36 and 0.2.37 become live: pose faces, spoken lines, the held head and the check-in `orientation` field. The axis-to-pose table is a first guess, fixed from the owner's calibration test without a flash.

## [0.2.38] - 2026-10-21

### Fixed
- Camera frames were never counted: the host read the unit's camera frames as type 0x01, but the unit sends a JPEG as type 0x02 (0x01 is Opus audio), so every frame was ignored, the log said "0 frames" and the start retry never stopped. The host now reads type 0x02.

## [0.2.37] - 2026-10-21

### Changed
- Orientation lines are now a large, funny written pool per pose (about ten each, with laugh cues such as "Ha ha" and "Hehe"), and no line repeats within the last ten spoken, across poses. The rate limit (one per two minutes) and the quiet rules are unchanged. Lines generated by the chat model are a separate Home item.

## [0.2.36] - 2026-10-21

### Fixed
- The camera did not start after a fresh boot: the body's one start came before the unit's avatar socket existed, and the start on connect was skipped because local watching still read "off" until the household's settings had loaded. The avatar server now asks the unit to stream every 5 seconds until its first frame arrives, logs the tries ("asked the unit to start its camera stream (try N)"), and says once when it is waiting for local watching to turn on.

### Added
- Orientation reactions (host side; the unit's `orientation` event and `self.screen.set_rotation` tool come in a later firmware patch): the body turns the unit's gravity axis into a pose (upright, on a side, upside down, face-down, lying back), shows a held pose face, flips the screen 180 degrees when upside down and back to 0 on upright, on every connect and when the unit goes away, stops idle motion and gaze while not upright, says one short original line per change (never the same twice in a row, at most one per two minutes, silent at night, asleep, or during a turn), logs "unit orientation", and adds `orientation` to the robot check-in.

## [0.2.35] - 2026-10-21

### Added
- Firmware patch 066: the minute "unit camera" line also reports encode failures apart from capture failures, how many binary messages the avatar socket received and the type of the last one (5 = the start command arrived), and the avatar task's smallest free stack joins "unit memory". It tells apart a start that never arrived, a failing capture, a failing JPEG encode and a too-small task stack.

## [0.2.34] - 2026-10-21

### Added
- Firmware patch 065: a per-minute `barge_stats` event (host log "unit barge") with the echo-cancelled microphone level while the robot speaks (chunks, voice-detector hits, average and peak level, a level histogram), to decide whether talking over a reply can work. The ambient-light tool also returns the raw LTR-553 channel counts, logged as `ch0` and `ch1` in the minute light line.

## [0.2.33] - 2026-10-21

### Fixed
- The camera never streamed: the body's start command used the 0xAA55 envelope, but the unit's avatar socket reads `[type][4-byte length][payload]`, so it ignored the command. The body now sends the unit's own form (start 0x05, stop 0x06), and asks the unit to start the stream whenever its avatar socket connects while local watching is allowed (the one start at boot came before the socket existed).

### Added
- Firmware patch 064: once a minute the unit reports its camera counts (`camera` event, logged as "unit camera"): start commands received, frames captured, frames sent, failures.

## [0.2.32] - 2026-10-21

### Fixed
- Firmware patch 063: the unit's avatar socket now sends its MAC as Device-Id and its UUID as Client-Id (the empty build-time ids Kconfig defaults to were sent instead, so the hub still logged "device missing"), which lets the camera channel connect.
- Firmware patch 063: a wake word heard while the robot speaks now also drops the reply frames queued on the unit, like a tap, before it starts listening.

## [0.2.31] - 2026-10-21

### Added
- Robot check-in: the body tells the hub which StackChan is connected and what it runs, with `PUT /api/devices/me/checkin` on connect, on a reboot or firmware report, and every minute: `device_id`, `board`, `online`, `last_seen`, `connected_since`, `ip`, `firmware_version`, `bot_version`, `rssi`, `signal`, `free_heap_internal`, `free_heap_min`, `psram_free`, `boot_reason`, `crash_resets`, `battery_level`, `charging`. A hub without the route (404) is asked again in ten minutes.
- Firmware patch 062: the unit reports its release version and Wi-Fi RSSI once a minute (a `fw` event, shown in the host log as "unit firmware"); the release scripts pass the version to the build. `firmware_version` is null until a unit with this patch is flashed.

## [0.2.30] - 2026-10-21

### Fixed

- A tap while the robot is speaking now drops the frames already queued on the unit and goes idle at once (firmware patch 061). The host streams a whole reply faster than the unit plays it, so telling the host to abort was not enough.
- The touch path and the wake word's hearing are measured once a minute (`unit touch: touch_path polls poll_fail poll_gap_max_ms reads read_gap_max_ms`, and `vad_speech` in `unit wake: wake_stats`), because taps and the wake word did nothing while it spoke and the log could not say why.
- The hub refused the unit's avatar (camera) socket as "not authorized (token missing, device missing)". Firmware patch 060 sends the same credentials as the voice socket: the saved token as a Bearer token, the unit's MAC as Device-Id and its UUID as Client-Id. The hub still accepts only a paired unit.

## [0.2.29] - 2026-10-21

### Fixed

- Taps at rest did not start listening because firmware patch 047 landed in the wrong place in the real build: its insertion had no context lines, `git apply --unidiff-zero` placed it by line number, and the recipe's tree differs from the one it was written against by a few lines. In every build from 0.2.20 to 0.2.28 a tap at rest called "start listening" and then, in the same handler, an abort and a switch to idle (the host saw two `listen abort` lines and no `listen start`). Patches 046 to 059 now carry three lines of context in every hunk, so the apply check verifies where they go, and a test fails if a later patch has a hunk without context. Taps start, and stop, listening again.

## [0.2.28] - 2026-10-21

### Fixed

- Pets register (firmware patch 056). The head strip reads 1 on 60 to 90 samples a minute with nobody there, in runs up to 23 samples, so reading 1 is noise however long it lasts; real pats and rubs reach 2 or 3. A pet is now a run whose peak reading is at least 2 and that lasts at least 2 samples, every such run is one press, and there is no lockout (the old lockout locked out real pets). The once-a-minute `head_touch_stats` line reports weak and strong samples and runs apart.
- The host reacts to a pet while the robot only listens (a face for about 3 seconds that does not interrupt listening), and reads the unit's events during a turn too. A pet while it is thinking or speaking is ignored.
- A shake is easier to trigger (patch 057: threshold 9 instead of 16 m/s^2) and reports its strongest peak; the unit reports the strongest sample-to-sample change once a minute so the threshold can be tuned. A pick-up event is not added yet.
- The unit tells the host what it decides (patch 059): every tap (`unit tap: decision=start|stop|ignored state=N`), every wake word detection (`unit wake: state=N`), and once a minute the wake-word task's heartbeat and the state the unit believes it is in (`unit wake: wake_stats armed fetches detections state`). A state guard returns a unit stuck in Connecting (8 s) or Listening (45 s) to idle, since it cannot hear the wake word or a tap from there. The swipe-down gesture no longer leaves a listening unit listening after the host drops the turn.
- The unit's boot report carries a count of panic and watchdog restarts kept in NVS (`crash_resets`).

### Changed

- About 11 KB of internal RAM back without a PSRAM stack (patch 058): smaller audio and websocket stacks that keep at least 1.7 KB of margin over the measured peak, and a smaller LVGL draw buffer. The opus codec stack goes to PSRAM again with the stop word still off (patch 055) to settle whether the stalls of 0.2.24 came from that stack or from the stop word; if the unit stalls, remove that one line from the recipe. When about 32 KB of internal RAM is free, patch 054 opens the camera and avatar socket.

## [0.2.27] - 2026-10-21

### Fixed

- The camera had never worked in the voice-agent firmware: the avatar websocket (camera frames) is created only by an app the firmware skips at boot. Firmware patch 054 opens it from a plain task once the voice agent is ready, and turns the stored `http://` avatar address into `ws://`. It starts only when 32 KB of internal RAM is free, so it stays off in this build until RAM is freed (experiment patch 055, not in the recipe). See `docs/dev/stackchan-vision-channel-2026-10-21.md`.
- Faces are always set over the voice socket, so they keep working once the avatar socket is up (it carries the camera only).
- The host logs one line for every head or shake event it reads and one when a conversation suppresses a touch reaction, so a pet that does nothing can be traced.

## [0.2.26] - 2026-10-21

### Changed

- The petted reaction has no cooldown. A pet shows the heart (or a smile) for about 3 seconds and goes back to neutral, and the next real pet reacts again as soon as that animation ends; nothing waits 10 or 60 seconds. A swipe across the head counts as a pet too. The phantom filter and the firmware's sustained-contact recogniser keep false pets out.
- The host logs the light sensor reading every minute (`StackChan light sensor: lux=...`) instead of every 10 minutes, to calibrate night mode from data. The unit's numbers are about 1 to 2 percent of true lux because the sensor sits behind the screen glass.

## [0.2.25] - 2026-10-21

### Fixed

- A stable build after 0.2.24, which stalled the unit for 30 to 45 seconds and reset it. Firmware patch 053 puts the opus codec task and the audio detection task back on internal stacks (a task with a PSRAM stack cannot run while a flash write, such as a volume change saving to NVS, has the cache disabled), and turns the stop word off in the build. The rub detection (052) stays. The unit now reports why it last restarted (`unit boot: boot reason=N`), so a reset shows in the host log.
- Night mode no longer starts at midday. The light sensor read 4.6 to 7.5 lux in the afternoon against a start threshold of 8, so night begins only below 1.5 lux and ends above 3 until a real night reading is logged (the 10-minute light sensor line). Night volume is half the owner's volume, not 40%.

## [0.2.24] - 2026-10-21

### Added

- Firmware patch 051: frees 24 KB of internal RAM by moving the opus codec task's stack to PSRAM, makes the stop word's internal-RAM budget explicit (model at most 12 KB, at least 34 KB free after it, 20 KB free to arm), and reports memory and task-stack headroom once a minute (`unit memory: ...`). The host also logs the light sensor reading every 10 minutes.

### Fixed

- Firmware patch 052: a rub on the head registers. The head strip reads only 1 for a rub, so contact is now told apart by how long and how dense it is: 6 touched samples out of the last 8, at least 400 ms old. An isolated blip or a short tap is ignored, three isolated blips still lock the strip out for 10 seconds, and a rub's dropouts no longer count as blips. The once-a-minute `head_touch_stats` line gains `run_max` and `long_runs` so the host log shows what a rub looks like.

## [0.2.23] - 2026-10-21

### Fixed

- Firmware patch 050: the LED ring goes dark with the screen. On the unit's power-save sleep and before its idle-shutdown power off the ring is blanked, and the host's last look returns on wake. Holding the power button for a hardware shutdown is not covered: the PMIC cuts power with no warning, and clearing the ring in time needs the AXP2101 power-key interrupt, which is left for a check on the unit.

### Changed

- The ring is dark when the robot is awake and idle. Owner ruling: no lights for idle. The status lights stay for real states (blue listening, green live, magenta thinking, white speaking, pink camera flash, amber fault or offline, green charging breathe). The light standard and its tests are updated; `robot.indicator.enabled` still turns every status light off.

## [0.2.22] - 2026-10-21

### Fixed

- Head touch: a press needs a pad reading of 2 held for 400 ms, three short blips in 10 seconds lock the sensor out for 10 seconds, and the unit's stock stroke face, heart and head motion are off, so the host drives every reaction. Press and swipe events carry the held time. Once a minute the unit reports head touch statistics to the host log. This stops the false pets that made the robot show a heart and an open-mouth grin on its own.
- A tap that begins in the top 24 pixels of the screen is ignored, so a swipe from the top edge no longer starts listening, and a tap while it listens or speaks now stops it.

### Added

- A spoken stop word while the robot is speaking: "stop", "stackchan stop", "be quiet", "quiet", "that's enough", "never mind" and "cancel" end its reply, using a small on-unit command-word model that runs on the wake word's echo-cancelled audio. It is armed only while the robot speaks, checks free internal memory before it arms, and turns itself off if it costs too much. The host log records each hit and near-miss as a command name and a score, never audio or words.
- The firmware assets are pruned (unused launcher icons and artwork) to make room for the model in the 4 MB assets partition. Patches to flash since 0.2.13: 038, 046, 047, 048, 049 (plus 037, 039, 044 already flashed).

### Added

- Firmware patch 049 (not flashed): a stop word that works while the robot is talking. A small command-word model on the unit (stop, stackchan stop, be quiet, quiet, that's enough, never mind, cancel) listens only while it speaks; a clear hit aborts the reply and the host ends the turn silently. The host log shows every hit and near-miss as `unit stop word: heard 'stop', score 91 ...` (command name and score only). The model drops itself if it would use more than 6 KB of internal RAM, and the build prunes unused launcher icons so the assets still fit the 4 MB partition.

### Fixed

- Firmware patch 048 (not flashed): the head touch strip no longer invents pets. A press needs contact that starts at a pad reading of 2 and is held for 400 ms; three short blips in 10 seconds lock the strip out for 10 seconds; the unit's own stroke face, heart and head motion are off (the host decides what a pet looks like); and a once-a-minute `head_touch_stats` line in the host log shows the strip's resting noise.

## [0.2.21] - 2026-10-21

### Fixed

- Phantom head touches no longer pet the robot. The head sensor fires a lone touch about every 10 seconds with nobody there; each woke the robot and one in four earned a heart. A lone head touch is now ignored unless the unit reports it held for 400 ms or more, a second one follows within about 3 seconds, or several arrive together. One INFO line a minute counts the ones ignored.

### Added

- Every transcript checked against the stop list writes one INFO line (`stop check 'stop' -> yes`); a matched stop phrase is named and anything else logs only its word count, since the log never holds what a person said.
- The host logs the head sensor's per-minute statistics from firmware that sends them (`unit touch: head_touch_stats ...`).

## [0.2.20] - 2026-10-21

### Added

- A spoken "stop" while listening ends the turn on the robot: "stop", "StackChan stop", "be quiet", "quiet", "never mind", "cancel", "that's enough", "stop talking", "stop listening". The device goes idle, nothing is said, and the hub is not asked. "Stop the music in the kitchen" and other longer sentences still go to the hub.
- Firmware patch 047 (taps): a tap that begins within 24 px of the top edge is ignored, so a swipe from the bezel no longer starts listening; a tap while listening now ends the turn (the persistent websocket made the stock close a no-op); the tap debounce is 0.8 s.

### Fixed

- After a stroke, shake or heart the neutral face comes back after 3 seconds, so the unit's open-mouthed happy face no longer lingers.

## [0.2.19] - 2026-10-21

### Added

- Firmware patch 046, the only firmware change besides the already-pinned head-move cap of 40 a minute: the screen's touch path is reported both on the serial port and to the host, which logs each event as `unit touch: ...` (finger down with x and y, finger up, face pressed, face clicked, swipe direction, and a swipe ignored with why; counts and coordinates only, at most 20 a minute). Swipes and taps did nothing on the unit; one flash and 30 seconds of tapping and swiping says whether the controller reports nothing, the face is not the object touched, or the swipe is not recognised. The control-panel patch 045 stays parked, out of the build, until swipes work.
- Spoken screen brightness, like the volume: "set brightness to 50 percent", "brighter", "dimmer", "it's too bright", "dim your screen", "full brightness". The robot says "Brightness 50." The screen never goes below 10 (a request to turn it off is answered with how to dim it). By day the level is kept as the owner level; at night only the temporary night level changes and the day edge restores the day level exactly.
- The robot reads `robot.volume` and `robot.brightness` from the hub as its default owner levels. A default applies when it changes, by day, and never overwrites the night level or a level the person set later with an unchanged default.
- Levels set on the unit's own panel (the `level_changed` event) are kept as the owner levels, or the night levels at night, once the firmware sends them.

## [0.2.18] - 2026-10-21

### Added

- Turning toward the speaker: on a wake word, tap or follow-up the head turns to the face seen in the last 5 seconds, holds through the reply and returns to level. "Can you see me?" is answered from what the camera last saw (it says it can see you, or that the camera is off, or that nobody is in view). "What are you looking at?" is answered from why the head last moved. "What do you see?" answers "I can look, but I can't describe pictures yet." until Home's vision contract lands.
- Shake reaction: a shaken or abruptly moved robot makes a surprised face and says a short varied line (20 second cooldown, face only in quiet hours, never mid-reply). The host reads touch events while awake.

### Fixed

- The idle face is calm. The sleepy face (open mouth, squinted eyes) is no longer sent at rest; listening and speaking cues are neutral. Happy stays for happy replies and greetings.
- The heart is earned: only on a pet, kind words, or a loving reply mood, at most once a minute.
- Firmware is unchanged from 0.2.17.

### Added

- The robot turns toward the person who starts talking to it: on a wake word, a tap or a follow-up it turns to the face it saw in the last 5 seconds, holds the turn while it listens and answers, and returns to level after. With no recent face it does nothing. Following a face now uses the camera's whole field of view (it turned only 10 degrees at the edge before).
- "Can you see me?" is answered from what the robot really knows: a face in the last 10 seconds gets a yes ("I can see you right there"), a camera that is off says so, nobody in view says it cannot spot anyone but the camera is on; never a flat "I can't see". "What do you see?", "what am I holding?", "look at this" and "what's this" get "I can look, but I can't describe pictures yet." until Home can describe a picture. No frame leaves the host.
- "What are you looking at?", "what are you looking for?" and "why are you looking over there?" are answered by the robot from why its head last moved (following a face, a spoken look command, a lost face, thinking, resting, or nothing in particular), with a few honest, friendly variants per case and no claims about anything it did not detect. "What do you see?" still goes to the hub.

### Fixed

- The idle face is always the calm neutral one. After ten quiet minutes the robot used to show the firmware's sleepy face (u-shaped eyes, a small open mouth, a Zzz bubble), which looked creepy; the listening and speaking cues no longer switch to the open-mouth happy face either. Drowsy and asleep now show as a level head and, at night, the dark face.

## [0.2.17] - 2026-10-21

### Fixed

- The robot no longer wanders. The day and night code only ever switches the unit's idle motion off; it never turns it on. The power rule alone writes the idle-motion value, and every connect re-asserts it (off when the power state is unknown or the idle level is still). The hub's default idle level "calm" counts as "still"; only "lively" wanders.
- A touch, swipe or shake wakes a drowsy or sleeping robot (polled every 5 seconds only while it is drowsy or asleep, 30 second cooldown).

### Added

- Face watching: the bundled build decodes the unit's pictures with PyAV (it has no cv2) and runs the YuNet face detector (MIT, pinned model) on onnxruntime, in memory, about 3 ms a frame. Only boxes and counts are kept; nothing is stored. It is on by default behind `robot.camera.watch_level`, local only, and logs one camera line a minute (frames and bytes). Firmware is unchanged from 0.2.16.

## [0.2.16] - 2026-10-21

### Fixed

- The robot no longer wanders on its own after a reconnect or at day. The night rule used to switch the unit's idle motion ON whenever night ended or the unit reconnected; it now only ever switches it off, and the power rule alone decides when it may wander. Home's default idle level "calm" is treated as "still" (it cannot be told from a choice); "lively" is honoured.

- The robot's head rests level. Centre pitch is now the lowest angle (5 degrees); before, the host treated 45 degrees as centre and the drowsy and asleep poses raised the head to 66 and 85 degrees, so it always looked up. Nods and perks are small upward offsets from level. One constant, `CENTRE_PITCH_DEG` in `bodies/stackchan/profile.py`, sets the level.
- Night and day: every connect now applies the current face, brightness, idle motion, lights and volume once, so a host restart or a unit reboot cannot leave the face dark in the morning. Unreadable light ends night after 10 minutes. There is one log line per night start and end with its reason, and no calls or retry spam while no unit is connected.
- Volume: the default is 70 and brightness 100, both remembered in `owner_levels.json` in the Bot data directory. A voice change by day updates the stored level; at night it changes only the night level; day restores the stored value exactly.
- Firmware patch 038's head-move cap is 40 a minute (it was 20) and the firmware asset includes that change. Patches to flash since 0.2.2: 030, 032, 033, 034, 037, 038, 039, 044.

## [0.2.15] - 2026-10-21

### Added

- Idle face watching, on by default behind `robot.camera.watch_level`: about twice a second the robot looks for a face in the unit's camera frame (local only, nothing stored). A face keeps it from drifting to sleep, the head follows it when the head gate allows, and a person returning after 10 minutes of an empty room gets one gesture greeting. The host logs one line a minute with the unit's camera frames and bytes. See `docs/dev/stackchan-face-watching-2026-10-21.md`.
- Shaking the robot gets a surprised face and a short spoken line from a small set (three short startled lines that vary), at most once every 20 seconds, never during a reply, and only the face in quiet hours. A head touch is read by the host too. The loving heart is now rare: for a pet, kind words from a short list, or a loving reply mood, and never twice within a minute (the host asks the unit for a heart symbol; until the firmware has that tool it smiles). See `docs/dev/stackchan-touch-and-hearts-2026-10-21.md` for what the unit does with touch and what the firmware needs.

- Face detection that works in the hub bundle: camera frames are decoded with the bundled PyAV (no OpenCV) and faces are found by the pinned YuNet model on the bundled ONNX Runtime (no Reachy SDK). Measured on the Mac Studio: JPEG decode 0.13 ms (320x240) and 0.44 ms (640x480), detection about 3 ms per frame on one thread. Frames stay in memory; only boxes are kept. The model arrives from Home like every other pinned model.

- A touch, swipe or shake on a drowsy or sleeping robot wakes it (the unit already queues these; the host now looks every 5 seconds, only while the robot is drowsy or asleep, and at most one wake every 30 seconds). Waking on a loud sound needs a small firmware event and is on the firmware list.

- Spoken head movement on the robot: "look left/right/up/down" (with "a little" or "all the way"), "turn left/right", "look straight", "look at me", "look around", "nod", "shake your head" and "stay". Left and right are the robot's own left and right. Requests it cannot do (spin, dance, turn around) get "I can look left, right, up or down.", and "I can't move right now." when it is charging, stopped, or the move fails. The head returns to centre after 5 seconds unless asked to stay.

### Fixed

- Night and day are reapplied every time the robot connects, so a host restart or a unit reboot can no longer leave the face dark in the morning (or bright at night); night ends after 10 minutes if the light cannot be read; each night start and end is logged with its reason. The owner volume (default 70, brightness 100) is remembered in `owner_levels.json` across host restarts and flashes and restored exactly when day returns; a voice volume change by day changes it, one at night only changes that night.

- The robot's head no longer rests looking at the ceiling. Its up-and-down servo only travels up from level (about 3 to 87 degrees), but the host treated the middle of its range (45 degrees) as straight ahead, and the rest layer raised it to 66 and 85 degrees when drowsy or asleep. Level is now 5 degrees (`CENTRE_PITCH_DEG` in `bodies/stackchan/profile.py`, change it if 5 does not look level), rest stages stay at level, and the nod, perk and look-up moves are small upward offsets. "Look down" means level.

- The camera stream start ran on the host's event loop at every start and reconnect, freezing the host for about 5 seconds and causing a failed first connection after a host restart. It now runs in a worker thread, and the loop guard also covers avatar frames and notifications.
- The head-move cap no longer blocks a return to centre (settle and hold are always allowed) and is 30 moves a minute; a watchdog logs and reboots a unit that answers no commands for 120 seconds while connected.
- Firmware is unchanged from 0.2.13.

### Added

- Spoken head movement on the robot, answered before the hub: "look left / right / up / down" (with "a little" or "all the way"), "turn left", "look straight", "look at me", "look around", "nod", "say yes", "shake your head", "say no" and "stay". It says one short line ("Looking left."), then returns to centre after 5 seconds unless told to stay. If the unit is charging or the stop is latched it says "I can't move right now." Requests like "turn around", "spin" or "dance" get "I can look left, right, up or down." and never reach the hub. See `docs/dev/design-stackchan-head-commands-2026-10-21.md`.

### Fixed

- Starting the robot service no longer freezes the event loop for 5 seconds: the presence start runs in a worker thread, and a device call made on the loop fails at once instead of waiting.
- A return to centre is never refused by the head-move cap; only real head moves count, and the cap is 30 a minute.
- A StackChan that stays connected but stops answering tool calls is logged after 60 seconds (with the age of its last audio frame and last message) and asked to restart itself after 120 seconds.

## [0.2.14] - 2026-10-21

### Fixed

- Spoken volume on the robot understands natural phrases: "set your volume to 100%", number words ("one hundred", "sixty five"), "half", "raise/lower your volume", "I can't hear you", "you're too loud", "too quiet". A bare "volume" asks "Louder or quieter?", and any other remark that mentions volume gets "Say louder, quieter, or a number." instead of reaching the hub. Short loudness remarks without the word volume get the same hint.
- When no robot is connected the e-stop safe stop repeats at most every 30 seconds instead of about 8 times a second, and the ring light skips writes while no unit is connected.
- Firmware is unchanged from 0.2.13 (patches 030, 032, 033, 034, 037, 038, 039, 044); the 0.2.14 firmware asset is the same build, so a unit on 0.2.13 does not need a reflash.

## [0.2.13] - 2026-10-20

### Fixed

- StackChan joins the strongest Wi-Fi access point instead of the first one it scans. Firmware patch 044 turns on the stored `remember_bssid` setting at boot, so a unit that scanned a weak access point on channel 1 before the strong one on channel 6 no longer joins it, which caused connection errors, handshake timeouts and a dropped voice link every 20 seconds. If only one access point exists it is still joined.
- Firmware patches 040, 041 and 043 (decoder priority, update-task sleep, cached head angles) are removed again until each can be booted on the unit by itself. Patches to flash since 0.2.2: 030, 032, 033, 034, 037, 038, 039, 044.

## [0.2.12] - 2026-10-20

### Fixed

- StackChan no longer reboots on the wake word. Patch 042 (uplink Opus voice mode, complexity 3) overflowed the 24 KB stack of the wake-word encode task, which shares the encoder configuration; the patch is removed and the encoder is back to complexity 0. Patches to flash since 0.2.2: 030, 032, 033, 034, 037 to 041, 043.

## [0.2.11] - 2026-10-20

### Fixed

- Smoother speech: a reply is one paced stream with no gap between sentences, a stall is caught up at the normal cadence instead of re-based, and the speaking state lasts until the unit has finished playing.
- Hearing and reliability: one `uplink level peak, rms` line per turn (and an opt-in debug recording of the uplink with `MAIPAI_STACKCHAN_DEBUG_WAV_DIR`); the capture closes when recognition ends and its queue is bounded; `get_head_angles` is no longer retried; the ring light has its own worker; presence-loop warnings are rate limited; `take_photo` no longer passes an unsupported device id.
- StackChan firmware patches 040 to 043: the decoder task runs at priority 5 with a 4-slot playback queue, the update task sleeps before taking the display lock, the uplink Opus uses voice mode at complexity 3 with no DTX at 24 kbps, and `get_head_angles` answers from the animation value without a servo bus read. Patches to flash since 0.2.2: 030, 032, 033, 034, 037 to 043.

## [0.2.10] - 2026-10-20

### Fixed

- A quiet listen no longer waits out the 12 second final wait: the host gives up after 1.5 seconds when the hub sent no voice-activity message, and keeps the long wait only when speech was heard. Home answers a quiet end with no speech at once.
- Every robot connect no longer freezes the host for 5 seconds: session listeners run on their own thread, a device call made on the event loop fails at once with a plain message, and the idle-motion flag is written by the one second tick instead of at connect.

## [0.2.9] - 2026-10-20

### Fixed

- Hearing: a follow-up listen no longer drops its first 0.3 seconds, a dropped speech-to-text connection reconnects up to twice instead of ending the turn with an apology, the give-up deadline has a 0.6 second grace, and the wait for the final transcript is 12 seconds.

### Added

- StackChan firmware patch 039: a log-only timing line when an MCP call, its reply or the audio send takes 100 ms or more (at most one line a second). Patches to flash since 0.2.2: 030, 032, 033, 034, 037, 038, 039.

## [0.2.8] - 2026-10-20

### Fixed

- Smoother, faster StackChan speech: a 14-frame playback lead, a streamed sender, bounded catch-up that logs a warning, per-sentence lateness logging, uplink decoding off the event loop, and a 30 ms settle before speech.
- The thinking, doubt, wry, glance, tilt and attend looks now send the neutral face instead of a confused one. No reflash needed.

## [0.2.7] - 2026-10-20

### Fixed

- StackChan holds still: the idle level defaults to still, the post-turn settle runs only when an earlier move left the head off centre, every head move is capped at 12 a minute on the host, and stop recovery backs off when it re-latches within 120 seconds.
- StackChan firmware patch 038 refuses more than 20 `set_head_angles` calls in 60 seconds. Patches to flash since 0.2.2: 030, 032, 033, 034, 037, 038.

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
