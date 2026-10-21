# StackChan touch, shake and the heart (2026-10-21)

Owner requests: petting the head does nothing; a shake should get a spoken line and a face; the loving heart face should be rare and
earned. Everything below was read from the firmware source (pinned build with patches 001 to 039) and the host code. The unit was not
touched, and its serial logs cannot show strokes (see "What cannot be seen").

## How touch works on the unit

| Step | Where | Behavior |
|---|---|---|
| Sensor | `hal_head_touch.cpp`, Si12T, three zones, sensitivity level 3 | read every 50 ms; any intensity of 1 or more counts as touched |
| Gesture | `GestureRecognizer` | Press on first contact; SwipeForward or SwipeBackward when the touch position moves more than 40 percent across the zones; Release when contact ends |
| Reaction on the unit | `HeadPetModifier` (`head_pet.h`) | reacts ONLY to a swipe: happy face, the heart and shy decorators for 1.5 to 2.5 s, a small head motion. A tap, a hold or a pat in one place (Press with no swipe) does nothing visible |
| Event queue | patch 021 (`self.robot.get_events`) | `head_touch` on Press, `head_swipe_forward` and `head_swipe_back` on swipes, `shake` on a shake; a ring of 16, read and cleared by the host |

So the answer to "does the unit raise a pet event": yes, a `head_touch` event on every contact and a swipe event on a stroke, but its
own reaction needs a stroke across zones, which is why a plain pat looks like nothing. Before this change the host read the queue only to
wake a sleeping robot, so nothing on the host reacted either.

## Shake

`hal_imu.cpp`: BMI270 started ("BMI270 init ok" in the boot log), shake threshold 16.0, a `shake` event every time it trips.
`ImuEventModifier` shows the dizzy and shy decorators and wiggles the mouth for 4 s. Picking the robot up or a bump that is not a shake
is not detected: the pick-up check in `hal_imu.cpp` is commented out. That needs firmware (below).

## What the host does now (`reactions.py`, `StackChanBehavior.wake_on_touch`)

- The host reads the events every 2 s while the robot is awake (every 5 s while drowsy or asleep), never during a turn; the first look
  after a pause only empties the queue.
- A shake: a surprised face, and one of three lines (three short startled lines that vary), never the same line twice
  in a row, at most once every 20 s, never during a turn or a reply, and in quiet hours only the face. The line is spoken by the same
  voice as a reply, through the hub's text-to-speech; the chat model is not asked.
- A pet (`head_touch`): the heart, at most once a minute (below).

## The heart: where it comes from

Searched every place: the host never sends a heart. The face names the host can send are the firmware's emotion list (neutral, happy,
laughing, angry, sad, crying, sleepy, doubtful, surprised, shocked, winking), none of them a heart; ordinary happy replies map to
`happy`, the smile; an unknown reply mood maps to neutral. The firmware's idle expression modifier only offsets the eyes and the mouth.
The heart on the unit comes from exactly one place: `HeadPetModifier` adds the `HeartDecorator` on every swipe gesture. So hearts the
owner did not ask for are swipe gestures from the touch sensor: a real stroke by anyone, or noise (contact threshold 1 at sensitivity
level 3 is very sensitive, and the CoreS3 head touch is known for phantom pets; this is a likely cause, not measured).

The host now owns the rule: the heart is shown for a pet, for kind words from a short list ("you're so helpful", "thank you so much",
"I love you", "you're the best", "good robot", "you're adorable", "you're so cute"), or when the reply mood from the cue is love,
affection or adoration (a very cute picture), and never twice within 60 s. It asks the unit for `self.screen.show_symbol` with
`{"name": "heart", "ms": 2500}`. That tool does not exist yet; until it does the host shows the smile instead and does not ask again for
10 minutes. The unit's own heart on a stroke stays until the firmware change below.

## What cannot be seen

The touch update task has its log lines commented out, so a serial capture shows "init" and "start update task" and nothing when the
head is touched. The first real answer comes from the host's INFO lines ("StackChan was petted", "StackChan was shaken") and the
event kinds in "StackChan woke up on touch".

## Firmware batch list (in this order)

1. `self.screen.show_symbol(name, ms)` with `heart` and `thinking_dots` decorators, and `HeadPetModifier` stops adding the heart and
   shy decorators itself (it keeps the happy face and queues the events). Then the host alone decides when a heart appears.
2. Debounce touch: require several consecutive samples, a minimum stroke length and time, a higher contact threshold, and ignore touches
   while the IMU says the unit is moving. Count a hold of 300 ms or more as a pet so a pat is not ignored.
3. Enable the pick-up event (`isPickUpDetected` in `hal_imu.cpp`) and queue `pickup` so a lift gets the same reaction as a shake.
4. A rate-limited INFO log line per touch and per shake, so the next serial capture shows them.
5. A `loud_sound` event for waking on sound.
