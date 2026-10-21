# StackChan idle face watching (2026-10-21)

Owner decision (relayed 2026-10-21): the robot looks for a face while idle, on by default, and the household can turn it off per
robot with `robot.camera.watch_level` (off, presence, identify). Local only: a frame is decoded and searched in memory and only
"a face was there" and a box are kept. Nothing is stored. The log carries counts, never pictures or boxes.

## What it does

- About twice a second (`LOOK_INTERVAL_S`) `StackChanBehavior.watch_for_faces` takes the unit's latest camera frame, decodes it with
  PyAV and finds faces with the pinned YuNet model on the bundled ONNX Runtime (`vision/jpeg.py`, `vision/yunet.py`).
- A face keeps the rest policy awake (`_last_person_seen`), so the robot no longer drops to drowsy and asleep while someone is in
  the room.
- The head follows the face only when the head gate allows it: on battery, with a known power reading, a calm or lively idle level,
  not resting, under the move cap. Pitch follows a high face upward from level; a face below the middle of the frame is level.
- After the room has been empty for 10 minutes (`GREET_AFTER_ABSENT_S`) the next face gets one gesture greeting: a happy face for a
  moment and a nod when the head may move. Never twice within 30 minutes. `robot.greetings.mode` off turns it off; "spoken" is
  treated as a gesture because spoken greetings follow Home's person and age rules.
- It does nothing during a turn, at night, or when the camera level is off.
- Naming people is a separate decision (it needs the SFace recognizer, consent and the gallery).

## The model

`yunet-2026may`, pinned in the shared spec: 229,738 bytes, sha256 `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`,
MIT (an unmodified redistribution of the OpenCV Zoo YuNet by Wei Wu, Hanyang Peng and Shiqi Yu). It reaches the robot through the
paired hub asset sync. Until it has arrived the detector finds nothing and logs one WARNING every 10 minutes saying what to do.

## Measured on the Mac Studio (2026-10-21, one thread, machine busy)

| Step | Cost |
|---|---|
| JPEG decode, 320x240 | 0.13 ms |
| JPEG decode, 640x480 | 0.44 ms |
| YuNet on a 320x240 frame | 2.6 to 4.5 ms |
| Two looks a second | about 8 ms of CPU a second, under 1 percent of one core |

## What the unit costs

Unmeasured until it runs. Once a minute the host logs one line, for example
`StackChan camera: 612 frames and 9400 KB from the unit in 1.0 min; looked at 120 (a face in 18), mean 3.4 ms, max 9.0 ms`.
The first lines from a real unit give its frame rate and bandwidth.

## Turning toward the speaker, and "can you see me?"

- On a listen start (wake word, tap or follow-up) the head turns toward the last face seen, if it was seen in the last 5 s
  (`TURN_FACE_FRESH_S`), as a response move through the head gate. The turn is held through thinking and speaking (the turn's other
  head cues are skipped so they do not pull it back) and the post-turn settle returns the head to level. No recent face: nothing moves.
  The unit has one microphone, so there is no sound direction; the face is the only cue.
- The yaw follows the camera's field of view (`FOLLOW_YAW_SPAN_DEG`, 60 degrees: a face at the frame edge is 30 degrees away). Pitch is
  level plus up to 20 degrees for a high face.
- `sight.py` answers "can you see me?" from the last-face age and the camera level, and gives the interim picture line for the cue
  phrases ("what do you see", "what am I holding", "look at this", "what's this"). Describing a frame is blocked on Home: its turn
  route accepts pictures only on written chat turns uploaded by a signed-in person, not on a robot's spoken turn. When Home's robot
  vision contract exists, the cue phrases attach one fresh frame in memory and drop it after the turn.
