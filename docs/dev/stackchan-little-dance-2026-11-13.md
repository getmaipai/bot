# StackChan little dance (2026-11-13)

Owner approval 2026-11-13. Build 1 of the dance design (stage "the little dance"): on request only, host side, no firmware
change. Music hearing and the automatic dance come later, after measurements. Nothing here has run on a unit: the tests
drive a fake clock and a recording fake robot.

Code: `bodies/stackchan/dance.py` (the routine, gates, ring show), `dance_wiring.py` (hooks it to the live
service), tests in `body/tests/test_stackchan_dance.py`.

## What it plays

About 11.7 s (`TOTAL_S`): firmware dance `happy` (4.2 s), a 0.3 s gap with the face `wink`, `robot` (2.7 s), a 0.3 s gap with
`surprised`, `happy` (4.2 s), then `stop_dance`, one move back to level, face `neutral`, ring dark. The head moves only
inside the firmware keyframe dances (patch 020, one tool call each). The firmware refuses more than 40 `set_head_angles` calls
a minute (patch 038), so the host makes exactly one head call per dance (the return to level). The host sends one face frame
per gap and about four ring frames a second (`self.robot.leds.many`, per pixel, patch 012), which are not head calls.

## Triggers

| Trigger | Where | Notes |
|---|---|---|
| Spoken ask | `head_commands.parse_head_command` returns `HeadCommand("dance")` for "dance", "do a dance", "can you dance", "dance for me", "show me a dance", "let's dance", "a little dance". `dance` left `_UNSUPPORTED`. | Handled before the hub is asked, and before the question and "show" checks. The line is "Let's dance." by day, nothing at night, "Not right now." when refused. `turn.py` ends the turn after it (like "turn to me") so the dance starts once the turn is over; a spoken ask waits up to 10 s for its own turn to end. |
| Hub command | device command `dance` on the StackChan command channel (`behavior.dance_command`) | The Settings page's Dance button sends `{"type": "device-command", "kind": "dance"}`; the ack state is `{"dance": "started" or "refused", "why": ...}`. A sleeping unit is woken first. The Home button itself is not built yet. |

## Gates (`DanceRunner._refusal`)

Setting `robot.dance.enabled` off; full quiet or muted (hook `full_quiet_reason` in `wire_dance`, returns None until the
settings registry has such a flag); emergency stop; offline or not connected; not upright; camera or live cue showing; during a
turn (not for the spoken ask, which waits); asleep (only the hub command wakes the unit); battery 20
percent or lower when not charging, or unknown (a plugged-in unit may dance at any level); under 60 s since the last dance
ended. One dance at a time.

At night an asked dance (voice, hub) runs head and face only: no ring, no spoken line. Charging does not block it (owner choice).

## Early ends (checked every 0.25 s and on events)

A touch or swipe, a shake (both ignored for the first second: the dance's own motion), the wake word or any turn or the live
cue, a tilt, a camera cue, low battery (the light service's flag, or 20 percent or lower on battery), offline, the emergency
stop, going to sleep, muting, the setting turned off. The unit's dance is stopped first, the ring is given back
(`StackChanLightService.give_ring_back`: dark, then the normal rules repaint), and the head goes back to level and the face to
neutral unless someone else is drawing (a turn, a touch reaction, a tilt, the estop, offline).

## The ring show (the lights rule's one decorative exception)

Colours outside the status meanings: gold, lime, mint and a warm sparkle (`SHOW_COLOURS`; a test checks distance from every status
colour and no red). Three patterns (chase, beat pulse, sparkle), every frame has at least two lit colours and differs from
the one before. Brightness 0.5 (`RING_BRIGHTNESS`). While it runs `StackChanLightService.take_ring` stops the service painting;
writes go through the adapter, so the camera pink still wins, and a live or camera cue ends the dance. `robot.dance.show_ring`
off keeps the head and face dance and no lights.

## Settings

`robot.dance.enabled` (default true) and `robot.dance.show_ring` (default true) are read from `settings_changed`
(`DanceSettings.apply`), so they work as soon as the hub sends them. They still have to be registered in
`commons/spec/settings/keys.json` (device scope, honoured by home and bot) and Home's `robotSettingsKeys.json`; that is a
commons tag plus a Home pin, not done here.

## Not verified (no unit)

The unit's dance durations (added up from `dance.h`), the pitch sign in the built-in dances, whether the dance's own motion
fires `shake` or `head_touch` events (the one-second grace only covers the start), whether a host face frame between dances
fights the firmware's own eyes, whether `charging` is false on a full USB unit (it would then count as on battery above 20
percent, which is fine), and how long the unit's `get_battery_status` takes during a dance (read at most every 5 s).

Removed 2026-11-13 (owner): the three-tap trigger and its 10-a-day cap. A dance starts by voice, the hub or Settings command and, later, music only. The head tap reaction (the smile) is unchanged.
