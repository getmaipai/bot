# StackChan head motion audit (2026-10-20)

Owner report: the unit "was moving around like crazy" and was switched off (servo wear). Cause found in the live log of bot 0.2.6:
the idle settle ran with nothing gating it, and a lost link engaged and released the head stop over and over, each release
followed by another move. Everything below is on `main` after this change; it needs a host-only bot release (no reflash) to take
effect on the unit, and patch 038 (plus 037) on the next flash.

## Every code path that can move the head

| Path | File | Gate | Moves when |
|---|---|---|---|
| Idle settle, face following (`attend`) | `app.py` `render_primitive` | `HeadMotionGate`: refused while power is unknown or stale, charging, night, `robot.idle.level` is still, resting, or over the per-minute cap | only on battery with a known reading and level calm or lively |
| Turn cues (`perk`, `attend`, `speak`) | `app.py` `render_turn_state` | gate with `response=True` (answers a person), still subject to the cap of 12 head moves a minute | a person is mid-turn |
| Settle after a turn | `app.py` `render_turn_state("settle")` | runs only if an earlier move left the head off centre, and passes the same gate | once per turn that moved the head, never after a quiet turn |
| Rest pose (drowsy, asleep) | `app.py` `rest_step` -> `RestRenderer` | sends only when the rest stage changes (a few times per long quiet spell) | stage change |
| Night turn to a speaker | `app.py` night branch | gate plus one turn per night wake | a person speaks |
| Safe stop `head.hold` | `robot/core.py`, `vision_bridge.py` | none by design; it reads the angles and holds them, it does not travel | an e-stop or a lost link |
| Dance tool | `companion.py` `dance` | explicit call by a person's request only; no automatic caller exists | a person asks |
| Look at speaker, auto dance, silent ambient vision | `speaker_gaze.py`, `presence/auto_dance.py`, `ambient_vision.py` | not wired into the app yet; when wired they must call `HeadMotionGate.allow` first | never today |
| Self-test movement check | `selftest/stackchan_wiring.py` | explicit run by a person | on request |

`tests/test_stackchan_head_stillness.py` pins the gate, the default, the settle rule, the cap and the stop backoff, and fails
if a new `head.set(` call site appears outside the audited files.

## Defaults

- A hosted StackChan starts at `robot.idle.level = still`. Until the hub's settings frame says calm or lively, nothing wanders.
  Note: the hub's own default for `robot.idle.level` is still `calm` (`robotSettingsKeys.json`), so a hub that sends its default
  switches wandering on while the unit is on battery. Changing that default is a Home change, listed as a follow-up.
- Unknown or stale power counts as charging: still.
- Firmware: idle motion is off after any boot and the host's choice is saved in NVS (patch 037). Patch 038 refuses more than 20
  `set_head_angles` calls a minute. The servos already release torque at rest (upstream default), so a still head draws no holding current.

## The stop churn

`EstopRecovery` already requires a real answer (a `get_head_angles` read) before it clears a lost-link stop. The log still showed
about 40 engage and release rounds because the next move failed and latched again. Two fixes: a release now restarts the watch from
scratch (before, the old "seen since" time let the next latch clear at once), and every re-latch within 120 s doubles the settle time
(3 s, 6 s, 12 s, up to 120 s). A long quiet spell resets it.
