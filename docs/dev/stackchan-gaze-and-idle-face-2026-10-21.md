# StackChan idle face and the gaze answer (2026-10-21)

## The "open mouth, squinting" idle face

Owner report: an idle animation with an open mouth and squinting eyes looks creepy. Candidates checked in the mint skin (`mint.cpp`) and
the host mappings:

| Face | Eyes | Mouth | Host sends it when |
|---|---|---|---|
| `sleepy` | "u" arcs (squint) | small open oval, plus a "Zzz" bubble from `SetEmotion` | the rest policy's drowsy and asleep stages (after 10 quiet minutes, 5 in quiet hours); with no face tracking in the bundle the robot always reached this stage |
| `happy` | "^" arcs (squint) | wide open smile | the listening cue (`perk`) and the speaking cue (`speak`), and happy replies |
| firmware `IdleExpressionModifier` | random offset of both eyes (+/-20, +/-15) | a small wiggle or tilt of the closed smile, no open mouth | every 2 to 6 s on the unit, always |

The match for "open mouth plus squinting eyes" is `sleepy` (the idle one) and `happy` (on every turn cue). Changed on the host: the
rest stages always show the neutral face (the head stays level and, at night, the face is the dark one), and the `perk` and `speak`
cues use the neutral face; `happy` remains for happy replies and the greeting. The firmware's idle eye drift and mouth wiggle are not
an open mouth or a squint; if Jesse also dislikes them, the firmware batch gets `set_idle_expression(enabled, mouth=false)` that stops
the mouth wiggle and keeps blink and breathing. Not done: it needs a flash.

## "What are you looking at?"

`gaze.py` keeps the reason for the last head move (`GazeReason`: track, command, search, sweep, thinking, rest, idle) and its time.
Reasons are set where the head code knows them: following a face (`watch_for_faces`), a spoken look command (`HeadCommander`),
a face it was following that has been missing for four looks (search), and the thinking cue. Resting or night overrides everything; idle
wandering allowed by the power rule reads as a sweep; otherwise it is level and nothing in particular. A reason older than its window
(10 s following a face, 60 s a command, 20 s a search or thinking) is forgotten.

The answers come only from that reason, with two or three variants each, never the same twice in a row, and no surveillance wording or
claim to see anything specific. "What do you see?" and anything about a picture is not matched and goes to the hub.
