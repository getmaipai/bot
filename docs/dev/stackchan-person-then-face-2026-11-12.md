# StackChan: find the person, then find the face (2026-11-12)

Status: design, waiting for the owner's word. Owner's words (2026-11-12): "you find the person and then you have to find the
face"; "aren't you supposed to use the super fast object detection to determine where people are?"; the detector serves more than
one thing ("StackChan what do you see" answers "I see a table and a person" at once while the full vision runs in parallel).

## What exists (reuse, nothing new invented)

- The detector is decided: YOLOX-nano, Apache-2.0, 3,659,407 bytes, sha256 `c789161e...18a0b7d`, the Stack's Look (LOOK-01,
  `home/docs/design/look-component-2026-10-22.md`; decode in `stack/backend/src/look/look_core.py`: letterbox 416, pad 114, raw BGR
  float32, grid decode, per-class NMS, score 0.35). It is already a shared robot asset, `yolox-nano-0_1_1rc0` in
  `commons/spec/assets/robot-assets.json` (spec-v0.1.208 and later), and the live hub already holds the file in its robot asset
  store and serves it to a paired robot by id, fetched by digest, never vendored. The bot pins spec-v0.1.196, which predates that
  entry, so the bot's pin moves to spec-v0.1.208, the first tag that carries it, and `vision/models.py` adds the pin beside YuNet.
- Measured here (this Mac, onnxruntime 1.30, bot venv, random 320x240 frame, letterbox plus decode): 10.1 ms median at one CPU
  thread, 7.7 ms at two; the process grows by about 72 MB (onnxruntime plus the model). The Look design measured 13.5 ms.
- The 2026-10-22 decision said a StackChan uses the hub's Look because its body runs on the hub host. The owner's 2026-11-12 words
  make the body run the same fast pass itself on the StackChan frames (the robot's own fast pass, same model pin, same `LookResult`
  shape from `spec/schemas/look-result.schema.json`, same 42-class household vocabulary). The profile declares it; nothing else
  changes, and the posted frame to Home and the Stack's detailed vision stay as they are.
- Reused as is: `vision_bridge.track_stream_frame` (one camera read, YuNet, the thumbnail, movement), `follow_pose` (frame x to yaw:
  `(x - 0.5) * FOLLOW_YAW_SPAN_DEG`, left of the picture is negative yaw; pitch only up from level, `CENTRE_PITCH_DEG`),
  `head_search.HeadSearch` (the slow ambient sweep and the spoken find-me sweep), `head_gate` (every move asks), `presence_watch`
  (movement, the learned empty room), `sight.SightAnswers` and `vision_post` (the ask to Home), `_turn_toward_face`.

## The tracker: a small state machine (new module `bodies/stackchan/person_tracker.py`)

Every frame the watch loop already decodes gets both detectors (YuNet first, YOLOX on the same array). The merge: a face wins over
a body. With faces, the largest face is the target and nothing below applies. With no face, the person boxes are the signal: the
largest box (the nearest person) is the one; two boxes within 10 percent in area pick the one nearest the picture's middle; the
choice is kept for the whole attempt unless that box disappears. Who spoke is not known from the picture (no sound direction is
built), so the design says so and does not guess.

| State | What the head does | Leaves when |
|---|---|---|
| idle | nothing; the old presence signals only keep the rest policy awake | a person box with score at least 0.5 in 2 of the last 3 looks and no face for 5 s: to aiming (logged as "person seen"). A face: straight to follow. Awake, no turn, not night, head gate says yes |
| aiming | one eased move per settled look toward the box centre (below) | centred for 2 looks, or 6 s or 4 moves (roughly on the person): to follow. Face seen: to follow ("face found"). Box gone 2 s: to lost |
| follow | keeps the person near the middle: the face when one is in view, the body (its upper part) when not; relative moves, dead zone, smoothing, capped steps, hold when centred (below, "Following") | standing still 1.5 s with no face: to face-search. Nothing in view 2 s: back to aiming (they may reappear); 10 s: to lost, no miss. Still for 90 s: relax (head to rest, idle until they move) |
| face-search | tilt up in 8 degree steps toward above the box top, then one small pan 8 degrees each way at the top; re-aims yaw if the box drifts past the dead zone | face seen: to follow. 5 poses or 6 s with no face: a miss, back to follow on the body (the head comes back down to it) and no face search for 1, 3, then 10 minutes unless they move |
| lost | the slow return to the resting pose (essential move) | at once: to idle, with the back-off below when it was a miss |

Following (owner, 2026-11-12: "follow me as I pace in the room"; "only code what's necessary"). Each fresh look (frame budget below) gives
one target point: the face centre, else the body's upper part (box top plus 15 percent of its height). The target is smoothed a little
(60 percent new, 40 percent old; the smoothing restarts after each move, since the picture shifts with the head). Outside the dead zone
(8 percent of the frame width) the head turns by 80 percent of the error, at most 25 degrees a step, servo speed 120; the pitch follows
a face more gently (50 percent). Inside the dead zone it holds: no twitching. No prediction: the head aims where the person is in the
newest look. A constant-velocity lead from the last two centres is added only if the measured trailing at walking pace loses them or
visibly lags (`follow_report` in the log gives the numbers: moves made and how far off centre the target sat). The camera's rate is the
limit (below). A turn pauses the follow (the camera stops while the unit listens and speaks) and the turn's own head moves are told to
the tracker; a rest or the night ends it. The tracker owns following whenever the Look model is loaded: the bridge's older absolute
follow (`follow_pose` from the centre pose, which oscillates when the head is off centre) stays only for a robot without the model.

Box to yaw and pitch. The box centre x gives the yaw error in degrees the same way as face following: `(cx - 0.5) * 60`. The move
is relative to the pose the body last commanded (the behavior keeps that pose; the unit has no servo read-back), scaled by a gain of
0.7 and capped at 30 degrees a step, servo speed 110 (eased). Lag: the detector and the servo together add 100 to 300 ms, so this is
not a continuous controller: one move, then wait until the move has ended plus 0.4 s, then judge only a look taken after that. A dead
zone of 8 percent of the frame width (about 5 degrees) around the middle counts as centred, so the head never hunts. Pitch in aiming:
when the box top is cut off at the frame edge (top under 5 percent) the head is too low and tilts up one 10 degree step with the yaw
move; otherwise the pitch stays. Face-search then tilts toward where the face must be (above the box top) in steps up to 30 degrees
over level, the profile's clamp applying last.

Back-off and caps. A miss (face-search ended without a face) waits 1, 3 then 10 minutes before the next attempt on the same still
person (`PERSON_BACKOFF_S`, as today); the wait resets when a face is found or when the person box moves by more than 15 percent of
the frame (they changed position, worth another try). At most 3 attempts in 10 minutes. The whole attempt is bounded at 12 s.

## How it fits what is there

- Face following: unchanged; face-lock is its normal work. The tracker never moves while a face is fresher than 1 s.
- Speaker turn (`_turn_toward_face` at listen start): unchanged when a face was seen in the last 60 s. New: with no fresh face but a
  person box seen in the last 15 s, the one brisk move turns toward the box centre instead of the blind glance up; the look after the
  reply then starts at face-search, pointed the right way.
- Spoken find-me (`ask`, `ask_level` sweep): unchanged, except a fresh person box ends the sweep ("found a person") and hands over
  to aiming, so the wide scan stops at the person and the face is looked for there.
- The ambient "person" sweep from the learned empty room or movement runs only while the detector is not loaded (model not synced
  yet). With the detector ready, a person-like picture without a person box starts nothing; the baseline and movement stay as weak
  presence signals for the rest policy. Movement and the baseline are not thrown away.
- Rest, sleep, night, a turn: the tracker moves only awake, outside a turn, not at night, through `head_gate.allow("person", response=True)`
  (the owner's 2026-11-12 "natural, not annoying" ruling made looks for a face responses). The camera pauses while the unit listens
  and speaks, so the tracker freezes in a turn and resumes after; a rest, the night or a turn ends an attempt at once (no miss counted).
- Presence: any person box sets "a person was seen now" (keeps the rest policy awake and stops the empty-room learning), replacing
  "picture differs from the empty room" as the main signal.
- Sight, "what do you see": the fast pass answers at once from the newest look, "I see a person and a laptop" (labels from the
  household vocabulary, counts, "a person" never more), then the normal turn runs and Home's detailed sentence follows as today
  (`vision_ask` posts the picture in parallel). No crop of a person is sent for details, nothing is stored, the spoken line is not logged.

## Constants (one place: the top of `person_tracker.py`)

| Name | Value | Meaning |
|---|---|---|
| PERSON_SCORE | 0.5 | a box below this never moves the head (naming uses the Stack's 0.35) |
| PERSON_LOOKS | 2 of 3 | looks with a box before an attempt starts |
| FACE_GONE_S | 5.0 | no face this long before a body is acted on (as `SEARCH_FACE_GONE_S`) |
| AIM_DEAD_ZONE | 0.08 | of frame width: centred |
| AIM_GAIN, AIM_MAX_STEP_DEG | 0.7, 30 | share of the yaw error moved per step, and its cap |
| AIM_SPEED | 110 | servo speed (profile range 100 to 150) |
| AIM_SETTLE_S | 0.4 | after a move ends before the next look counts |
| AIM_MAX_MOVES, AIM_TIMEOUT_S, CENTRED_LOOKS | 4, 6.0, 2 | aiming bounds |
| BOX_TOP_CUT, AIM_TILT_STEP_DEG | 0.05, 10 | box cut off at the top: tilt up a step while aiming |
| TILT_STEP_DEG, TILT_MAX_DEG | 8, 30 | face-search tilt steps and ceiling over level |
| SEARCH_HOLD_S, SEARCH_PAN_DEG, SEARCH_MAX_POSES, SEARCH_TIMEOUT_S | 0.8, 8, 5, 6.0 | face-search bounds (6 s: five poses at about a second each under the frame budget) |
| PERSON_GONE_S, RELOCK_S | 2.0, 2.0 | box gone: lost; face lost but body there: re-aim |
| BACKOFF_S, RETRY_MOVE, MAX_ATTEMPTS_PER_10MIN, ATTEMPT_CAP_S | (60, 180, 600), 0.15, 3, 12.0 | misses and caps |
| SPEAKER_PERSON_FRESH_S | 15.0 | turn toward a body at listen start if seen this recently |
| YAW_SPAN_DEG, PITCH_SPAN_DEG, CENTRE_PITCH_DEG | from `profile.py` | 60, 40, 5: the camera to head mapping face following uses |

## Frame budget (owner's live trial of 0.2.63, 20:40)

The unit sends about 1.8 frames a second (109 in a minute; the firmware's stream loop captures at most every 350 ms, `hal_ws_avatar.cpp`,
and the capture takes about 30 ms plus 83 ms to encode the JPEG, measured from the serial logs). A pose judged by wall time gets one
frame at best, often taken during the move. So: a pose is judged only by a look whose frame arrived after the move ended plus the settle
time (`AIM_SETTLE_S`), by the frame's arrival stamp (`avatar/server.py` keeps it, the camera driver hands it on), never by the clock.
At this rate a pose costs about a second; aiming is one or two moves (one frame gives the direction), so the person box replaces most
of the blind sweep. When a face is found the head is centred on it (`_point_at_face`, the face box centre) before the attempt ends.

Faster frames while searching: the 350 ms is a firmware constant (`_is_video_mode ? 700 : 350`). A patch could add a "fast" flag to
`StartCameraStream` (for example a 150 ms interval while an aim or a search runs, back to 350 after), about 4 to 5 frames a second;
the encode alone is 83 ms, so 5 is the ceiling at 320x240. Not built here (a firmware build and a flash); an option for the owner.

## What the log carries (INFO, counts and times only, never a label)

One line per stage change: `StackChan person-then-face: aiming -> face-search (2.1 s, 2 moves, box x 0.31 top 0.00)`; one line at
face-lock with the time from person-seen (`face found after 3.4 s`); one at a miss with the wait; the per-minute camera line gains
"a person in N looks, detector mean X ms"; every 5 minutes with no face in the window, the false-person rate (person-box looks over
looks). The "what do you see" fast answer logs its object count and ms, not the words.

## Tests and proof

Unit: the decode against a synthetic output; box to yaw and pitch (left box turns left, cut-off top tilts up, dead zone holds);
the state machine with a fake clock (aiming then face-search then lock; miss and back-off; a turn ends an attempt; face wins over
body; two boxes pick the largest). Live: the owner's few short tests on the unit (sit back, lean so only an arm shows, stand at the
side, leave); the log's stage lines are the evidence. Empty room for 5 minutes: the false-person rate.
