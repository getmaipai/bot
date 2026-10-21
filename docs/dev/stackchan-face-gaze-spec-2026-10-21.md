# StackChan face and gaze by state (spec, 2026-10-21)

Goal: the robot looks like it is paying attention or thinking, not frozen or staring at the ceiling. Research basis: people look
up and to the side while they think (gaze aversion) and back at the listener to speak; idle faces use blinks, small saccades and
slow drift; eyes and head move separately; a small symbol next to the face (dots) is a common "thinking" sign in assistant faces
(Ruhland et al., "A review of eye gaze in virtual agents, social robotics and HCI"; Disney Research gaze work; NAO gaze-aversion
studies). The numbers below are starting points, UNMEASURED on the unit.

## What the unit can already do (firmware, mint skin)

| Ability | Where | Host control today |
|---|---|---|
| Blink | `BlinkModifier` | none, runs by itself |
| Breathing movement | `BreathModifier` | none |
| Idle eye saccade: both eyes offset up to +/-20 px x, +/-15 px y, mouth wiggle, every 2 to 6 s (70 percent of ticks) | `IdleExpressionModifier` | on/off with the idle level |
| Emotion faces (neutral, happy, sad, angry, sleepy, surprised, doubtful, winking) | `SetEmotion` | `llm` emotion frames |
| Decorators: heart (head pet), dizzy and shy (shake), sweat, angry | `avatar/decorators` | triggered by touch and the IMU, not by the host |
| Eye position, mouth offset, a gaze or look-direction frame, a thinking symbol | `Feature::setPosition` exists | NOT exposed: no MCP tool, no avatar-channel frame |

## Spec by state

| State | Eyes | Head | Symbol |
|---|---|---|---|
| Idle | slow random saccade every 3 to 8 s (the firmware already does 2 to 6 s), blink every 2 to 6 s | level, still | none |
| Listening | centred, eyes slightly larger (the "surprised" size is too much: use a +10 percent scale if the skin allows) | perk +8 degrees up, then still | none |
| Thinking | shift to the upper left or upper right, small (about 8 px x, 8 px y), alternating sides each time, 1.5 to 3 s per side; blink at each switch | yaw 12 degrees to the same side and +10 degrees up, return to centre when the reply starts | optional three dots beside the face, like the heart decorator |
| Speaking | centred, mouth animation by the firmware | level, small speak offset | none |
| Asleep | closed or sleepy face | level | none |

## What needs firmware, in order of value

1. `self.screen.set_gaze(x, y, hold_ms)`: offsets both eyes, pauses the idle saccade for `hold_ms`, then lets it resume. Replaces the
   emotion hack for thinking. A host call per change, at most 2 per second.
2. `self.screen.show_symbol(name, on)`: shows or hides a decorator (`thinking`, `heart`). The thinking dots are a new small decorator.
3. Nothing else: blink, breath and saccade already exist.

## What the host can do now (no firmware)

Gaze aversion with the head only: while thinking, turn the head 12 degrees to alternating sides and 10 degrees up through the same
path as the spoken head commands, return to level when the reply starts. It passes the head gate as a response. Not built yet:
it adds head moves on every turn, so it should wait for the firmware gaze tool and the raised head-move cap (patch 038, 40 a minute).
