# The HAL seam: one platform, many bodies

A reference for the modular architecture `body/` is built on: one typed
seam, one profile per supported body behind it, and how the expression
and presence layers plug into that seam generically rather than knowing
a vendor's name. `docs/dev.md` and
`docs/dev/design-reachy-mini-2026-09-27.md` are the design record (the
why and the history); this page is the how, kept current as bodies land.

## The promise

Nothing above the seam may learn a vendor's name. A body is a profile
under `body/bodies/<id>/` that declares what it has (axes, channels,
sensors, speech placement) and implements a small set of typed
protocols; everything else in the platform - the expression package,
the presence funnel, eventually the household runtime - talks to
whichever body is installed through those protocols alone. Swapping
bodies, or adding a second one, never means editing the layers above
the seam.

## The seam itself

Declared once, in `body/maipai_body/hal/seam.py`:

- **`BodyProfile`**: id, capability ids (from the body-capability
  vocabulary), axes (each with its own limit, unit, source and date -
  see "Where limits live" below), channels, sensors, physical cuts, and
  speech placement.
- **`HeadActuator`**: `goto`, `set_target`, `hold`, `enable`, `disable`.
  Every implementation clamps a target against the profile's axes
  before it reaches any hardware or daemon; a vendor's own clamp, where
  one exists, is the second line, never the first.
- **`StateFeed`**: an iterator of typed, monotonically stamped frames
  (head pose, antennas, body yaw, direction of arrival).
- **`AudioIO`**, **`Camera`**, **`Imu`**, **`FaceTracker`**: the sensor
  and speaker surfaces a body may implement, each a thin typed wrapper
  around whatever the real hardware or daemon actually exposes.

Two things cross the seam and nothing else: the typed protocol calls
above, and three errors (`body/maipai_body/hal/errors.py`):
`BodyLost` (the connection is gone; every further call is refused until
a fresh client is built), `OutOfEnvelope` (a target failed the
profile's own clamp), `NotSupported` (the profile declares no such
capability).

## A body profile

Everything under `body/bodies/<id>/` for one body:

- **`profile.py`**: the *one* place this body's numeric limits and
  capability ids are declared. A test greps the package and fails if a
  limit appears anywhere else.
- **`client.py`**: the real implementation, wrapping whatever SDK or
  daemon this body actually uses. The only file that imports a vendor's
  own library.
- **`fake.py`**: replays fixtures recorded from the real hardware
  (`fixtures/`, made by `scripts/record_fixtures.py`) through the exact
  same seam, so the whole test suite runs twice - against the fake
  always, against the real thing when it's reachable
  (`MAIPAI_BODY_LIVE=1`) - and never fails when there's no unit plugged
  in, only skips with a reason.

## Where limits live

A body's physical limits (joint ranges, the head-to-body yaw delta, an
antenna's range) live in exactly one place: that body's own
`profile.py`, each with its source and the date it was recorded or
verified. Nothing else in the package is allowed to hardcode a number
that looks like a limit - `tests/test_profile.py`'s own grep test is
what enforces this, not convention. Add a second body and its limits
live in *its* `profile.py`, never a shared constant.

## Rendering the same vocabulary on a different body

`body/maipai_body/expression/` is the primitive vocabulary (listen,
glance, tilt, nod, perk, attend, settle, breathe, track, speak, stop) -
declared once, decided once (the cue-to-primitive mapping and the
suppression table are body-agnostic Python, no vendor import anywhere
in `cue.py` or `suppression.py`). *Rendering* a primitive - what motion
it actually is - is real per body, because the hardware is real
different: Reachy Mini has antennas and a roll axis and no eyes; the
MaiPai build (once it exists) has eyes, a mouth and a light ring and no
roll. So each body gets its own render column, and `renderers.py` is a
small registry keyed by profile id:

```python
from maipai_body.expression.renderers import register_renderer
register_renderer("reachy_mini", render)  # reachy_mini_renderer.py's own render()
```

`ExpressionEngine` looks its renderer up by `profile.id` - never a
hardcoded import - so adding the MaiPai build's own column is a second
`register_renderer` call in a new `maipai_build_renderer.py`, not an
edit to the engine, the cue mapper, or the suppression table.

`body/maipai_body/presence/` follows the same split: `arbitration.py`
(the priority order: inhibit/reflex, then service, then consented
tracking, then expression, then idle) and the presence-observation
shape are body-agnostic; a body's own `client.py` is what actually
answers `get_face_target()`/`get_doa()`/`read()` for the IMU.

## Supported bodies

| Body | Status | Where |
|---|---|---|
| Reachy Mini (Pollen Robotics) | Profile, daemon client, fake, expression column and presence inputs landed against the simulator (RM-01, RM-03, EXPR-01/RM-02, RM-06); live-verified against `reachy-mini-daemon` 1.11.0. The muted pose (antennas down, 0.30 of range) renders edge-triggered from `set_muted()`, gated by arbitration, not from cue suppression. `AudioIO` is fully implemented and live-verified (G1): recording/playback lifecycle and sample-rate calls pass through to `self._reachy.media.*`, with `body/maipai_body/speech/` (`AudioCapture`/`AudioPlayback`) built on top for the voice loop. Not yet: full trajectory blending, body yaw following past the head delta limit, anything needing the physical unit. | `body/bodies/reachy_mini/` |
| The MaiPai build (the owned hardware) | Not started. Needs BODY-02 (the HAL drivers: PCA9685, AS5600, the Pico face controller, the Hailo pipelines) and BODY-04 (the physical calibration run that produces this body's own axis limits) before a `profile.py` can be written at all - a body's limits have to come from a real measurement, not a placeholder. | `body/bodies/maipai/` (not created yet) |
| A third body | Whatever the next owned or purchased robot turns out to be. The seam doesn't change; a new `body/bodies/<id>/` and a registered expression renderer are the whole addition. | - |

## What's deliberately not built yet

- **A web dashboard to see and drive a body without hardware.**
  Pollen's own simulator ships a native 3D viewer
  (`reachy-mini-daemon --sim`, `mjpython` on macOS); nothing in this
  repo yet renders a body's state in a browser or lets someone drive it
  from one. Backlogged as `EXPR-05` in `docs/BACKLOG.md`: a small,
  body-agnostic page built against the seam alone (the state feed for
  telemetry, the expression engine for triggering primitives), so it
  works identically against the fake, the Reachy Mini simulator, and
  the MaiPai build once it exists.
- **The arbitration/blending limiter itself** (EXPR-01's own remaining
  gap): today each primitive issues its commands independently: nothing
  yet stops two from firing back to back or blends two small compatible
  trajectories into one.
