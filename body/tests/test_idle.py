"""S-EXPR-04: idle policy rules on a manual clock."""

from __future__ import annotations

import math
import random

import pytest

from maipai_body.expression import idle as i
from maipai_body.expression.idle import IdleOutput, IdlePolicy

DEG = math.pi / 180.0


def _series(policy, seconds, *, present=False, speaking=lambda t: False, start=1.0, step=0.05):
    out = []
    t = start
    while t < start + seconds:
        out.append((t, policy.update(t, person_present=present, user_speaking=speaking(t))))
        t += step
    return out


def test_idle_stays_quiet_until_300_ms_after_the_last_move():
    policy = IdlePolicy(now=0.0)
    policy.notify_move(10.0)
    assert policy.update(10.2, person_present=False, user_speaking=False) is None
    assert policy.update(10.31, person_present=False, user_speaking=False) is not None


def test_breathing_uses_two_incommensurate_periods_at_1p5_degrees():
    assert i.BREATHE_PITCH_PERIOD_S != i.BREATHE_ROLL_PERIOD_S
    policy = IdlePolicy(now=0.0)
    series = [o for _, o in _series(policy, 60.0) if o is not None]
    assert max(abs(o.pitch) for o in series) == pytest.approx(1.5 * DEG, rel=0.02)
    assert max(abs(o.roll) for o in series) == pytest.approx(1.5 * DEG, rel=0.02)


def test_antennas_sway_in_opposition_at_8_degrees_calm():
    policy = IdlePolicy(now=0.0)
    series = [o for _, o in _series(policy, 10.0) if o is not None]
    assert all(o.antenna_left == pytest.approx(-o.antenna_right) for o in series)
    assert max(abs(o.antenna_left) for o in series) == pytest.approx(8 * DEG, rel=0.02)


def test_still_is_breathing_only():
    policy = IdlePolicy(now=0.0, level_provider=lambda: "still")
    series = [o for _, o in _series(policy, 30.0, present=True) if o is not None]
    assert all(o.antenna_left == 0.0 and o.antenna_right == 0.0 and o.yaw == 0.0 for o in series)
    assert any(o.pitch != 0.0 for o in series)


def test_lively_sways_wider_and_poses_twice_as_often():
    calm = IdlePolicy(now=0.0, rng=random.Random(1))
    lively = IdlePolicy(now=0.0, level_provider=lambda: "lively", rng=random.Random(1))

    def distinct_poses(policy):
        seen = []
        for _, o in _series(policy, 120.0, present=True):
            if o is not None and (not seen or o.yaw != seen[-1]):
                seen.append(o.yaw)
        return len(seen)

    wide = max(abs(o.antenna_left) for _, o in _series(lively, 10.0) if isinstance(o, IdleOutput))
    assert wide == pytest.approx(12 * DEG, rel=0.02)
    assert distinct_poses(lively) > 1.6 * distinct_poses(calm)


def test_micro_poses_come_every_three_to_six_seconds_inside_the_bounds():
    policy = IdlePolicy(now=0.0, rng=random.Random(7))
    changes = []
    last = None
    for t, o in _series(policy, 120.0, present=True):
        if o is None:
            continue
        assert abs(o.yaw) <= i.MICRO_YAW_RAD
        assert abs(o.pitch) <= i.MICRO_PITCH_RAD + 1.5 * DEG + 1e-9
        if o.yaw != last:
            changes.append(t)
            last = o.yaw
    gaps = [b - a for a, b in zip(changes[1:], changes[2:], strict=False)]
    assert gaps and all(2.9 <= gap <= 6.2 for gap in gaps)


def test_no_micro_poses_when_nobody_is_present():
    policy = IdlePolicy(now=0.0)
    assert all(o.yaw == 0.0 for _, o in _series(policy, 60.0, present=False) if o is not None)


def test_antennas_freeze_after_150_ms_of_speech_and_release_after_400_ms():
    policy = IdlePolicy(now=0.0)
    speak_from, speak_to = 5.0, 8.0
    rows = _series(policy, 9.0, speaking=lambda t: speak_from <= t < speak_to, step=0.01)
    by_t = {round(t, 2): o for t, o in rows if o is not None}
    # Before the debounce the sway still moves.
    assert by_t[5.10].antenna_left != by_t[5.05].antenna_left
    frozen = by_t[5.2].antenna_left
    assert by_t[5.5].antenna_left == frozen and by_t[7.9].antenna_left == frozen
    # Still frozen 0.3 s after speech ends, moving again after 0.4 s.
    assert by_t[8.3].antenna_left == frozen
    assert by_t[8.5].antenna_left != frozen


def test_a_sound_look_happens_at_most_once_a_minute():
    policy = IdlePolicy(now=0.0)
    assert policy.sound_look(100.0, bearing=0.3) == pytest.approx(0.3)
    assert policy.sound_look(130.0, bearing=-0.3) is None
    assert policy.sound_look(161.0, bearing=-0.3) == pytest.approx(-0.3)


def test_idle_output_has_no_way_to_carry_a_clip_line_or_offer():
    assert set(IdleOutput.__dataclass_fields__) == {
        "pitch",
        "roll",
        "yaw",
        "antenna_left",
        "antenna_right",
    }
