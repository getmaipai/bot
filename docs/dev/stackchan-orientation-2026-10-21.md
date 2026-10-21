# Orientation reactions (0.2.36)

Host side is `bodies/stackchan/orientation.py`; wiring is `_wire_orientation` in `app.py`.

- Input: the unit's `orientation` diagnostic event, extras `axis` (`+x`, `-x`, `+y`, `-y`, `+z`, `-z`) and `gx`, `gy`, `gz` in milli-g.
  `AXIS_POSES` maps an axis to a pose; it is a first guess, fixed from the owner's calibration test (hold each pose for 3 s, read the
  "unit orientation" log) with no firmware change.
- Poses: upright, left_side, right_side, upside_down, face_down, on_back. Faces come from the unit's fixed emotion set (the eight
  `FIRMWARE_EMOTIONS`); a literal squish or lean needs the unit's face layer and is a separate item.
- Held pose: the pose face is re-sent every 5 s and the idle-face watchdog is paused while the pose holds. Idle motion and gaze stop
  (`PowerIdle.set_orientation_hold`) and resume when upright. Motor torque is never changed.
- Screen: `self.screen.set_rotation {degrees: 180}` when upside down, `0` otherwise; also `0` on every connect and whenever the unit
  is gone, so the screen cannot stay flipped. Until the firmware tool exists the call fails quietly (one warning a minute).
- Speech: one line per change from a small original pool, never twice in a row, at most one per 120 s, not at night, asleep, in quiet
  hours or during a turn.
- Check-in: `orientation` (a pose name or null) joins the robot check-in payload.
