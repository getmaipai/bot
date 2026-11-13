"""The head tap rule of firmware patch 081, replayed on real recordings and on shaped cases.

The rule lives in the unit's firmware (hal_imu.cpp, hal_head_touch.cpp); this is a plain model of
it with the same constants, so a recording from the unit can be replayed here without a flash.
The idle fixture is ten untouched minutes on 2026-11-12 with the strip noisy (148 runs at reading
1): no rule may make a press out of it. Keep the constants equal to the patch when either changes.
"""

from __future__ import annotations

from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "stackchan" / "head_strip_idle_2026-11-12.txt"

# hal_imu.cpp
TAP_JOLT_MIN = 1.0  # m/s^2, the three axes' changes between two samples 10 ms apart, added
TAP_QUIET_MAX = 0.4
TAP_QUIET_SAMPLES = 15
FRONT_TAP_ENABLED = False  # a desk slap beside the unit is the size of a light tap on the shell
FRONT_TAP_JOLT_MIN = 2.0
FRONT_TAP_WAIT_US = 300_000
SERVO_BLANK_US = (
    600_000  # the jerk is at a move's start; 1.5 s swallowed taps during a host head move
)
# hal_head_touch.cpp
PET_PEAK = 2
PET_SAMPLES = 1
RUN_GAP = 2
WEAK_PET_SAMPLES = 32
TAP_BEFORE_MS = 100
TAP_AFTER_MS = 150
TAP_PENDING_MS = TAP_AFTER_MS + 70  # the strip only looks at its own samples, every 62 ms


class JoltDetector:
    """One jolt per sample that moves at least TAP_JOLT_MIN after TAP_QUIET_SAMPLES still ones,
    unless a servo was commanded within SERVO_BLANK_US. A jolt of FRONT_TAP_JOLT_MIN that the strip
    does not claim within FRONT_TAP_WAIT_US is a front tap (strip=0), when that is switched on."""

    def __init__(self) -> None:
        self.quiet_run = 0
        self.jolt_us = 0
        self.jolt = 0.0
        self.servo_cmd_us = -10_000_000
        self.strip_touch_us = -10_000_000
        self.strip_used_jolt_us = 0
        self.front_pending_us = 0
        self.front_pending = 0.0
        self.front_taps: list[dict] = []

    def update(self, now_us: int, adiff: float) -> bool:
        hit = adiff >= TAP_JOLT_MIN and self.quiet_run >= TAP_QUIET_SAMPLES
        if hit and now_us - self.servo_cmd_us < SERVO_BLANK_US:
            hit = False
        if hit:
            self.jolt_us, self.jolt = now_us, adiff
            if FRONT_TAP_ENABLED and adiff >= FRONT_TAP_JOLT_MIN and self.front_pending_us == 0:
                self.front_pending_us, self.front_pending = now_us, adiff
        if self.front_pending_us and now_us - self.front_pending_us >= FRONT_TAP_WAIT_US:
            strip_near = abs(self.strip_touch_us - self.front_pending_us) <= FRONT_TAP_WAIT_US
            if not strip_near and self.strip_used_jolt_us != self.front_pending_us:
                self.front_taps.append(
                    {"at_us": now_us, "strong": 1, "tap": 1, "strip": 0, "gap": 0}
                )
            self.front_pending_us = 0
        self.quiet_run = self.quiet_run + 1 if adiff < TAP_QUIET_MAX else 0
        return hit


class StripRecognizer:
    """Presses from strip samples, as the firmware's GestureRecognizer makes them (one per run)."""

    def __init__(self, jolts: JoltDetector) -> None:
        self.jolts = jolts
        self.pressed = False
        self.run_len = 0
        self.run_peak = 0
        self.gap = 0
        self.run_start_us = 0
        self.used_jolt_us = 0
        self.presses: list[dict] = []

    def _jolt_near(self) -> tuple[bool, int]:
        jolt_us = self.jolts.jolt_us
        if jolt_us == 0 or jolt_us == self.used_jolt_us or self.run_start_us == 0:
            return False, 0
        gap = jolt_us - self.run_start_us
        if gap < -TAP_BEFORE_MS * 1000 or gap > TAP_AFTER_MS * 1000:
            return False, 0
        self.used_jolt_us = jolt_us
        self.jolts.strip_used_jolt_us = jolt_us
        return True, gap // 1000

    def _press(self, now_us: int, strong: bool, tap: bool, gap_ms: int) -> None:
        self.pressed = True
        self.presses.append(
            {
                "at_us": now_us,
                "strong": int(strong or tap),
                "tap": int(tap),
                "strip": 1,
                "gap": gap_ms,
            }
        )

    def update(self, now_us: int, reading: int) -> None:
        touched = reading >= 1
        if touched:
            self.jolts.strip_touch_us = now_us
        pressed_now = False
        if (
            not self.pressed
            and self.run_start_us != 0
            and now_us - self.run_start_us <= TAP_PENDING_MS * 1000
        ):
            near, gap_ms = self._jolt_near()
            if near:
                self._press(now_us, self.run_peak >= PET_PEAK, True, gap_ms)
                pressed_now = True
                if self.run_len == 0:
                    self.pressed = False
        if touched:
            self.gap = 0
            if self.run_len == 0:
                self.run_start_us = now_us
            self.run_len += 1
            self.run_peak = max(self.run_peak, reading)
            if (
                not pressed_now
                and not self.pressed
                and self.run_len >= PET_SAMPLES
                and (self.run_peak >= PET_PEAK or self.run_len >= WEAK_PET_SAMPLES)
            ):
                near, gap_ms = self._jolt_near()
                self._press(now_us, self.run_peak >= PET_PEAK, near, gap_ms)
        elif self.run_len > 0:
            self.gap += 1
            if self.gap >= RUN_GAP:
                self.run_len, self.run_peak, self.gap = 0, 0, 0
                self.pressed = False


def replay(samples: list[tuple[int, str, float | int]]) -> list[dict]:
    """samples: (time_us, "I", adiff) for the motion sensor, (time_us, "T", reading) for the strip,
    (time_us, "S", 0) for a servo command, in time order. Untouched strip samples are (t, "T", 0).
    Returns every head_touch event the unit would send, strip taps and front taps alike."""
    jolts = JoltDetector()
    strip = StripRecognizer(jolts)
    for at_us, kind, value in sorted(samples, key=lambda s: s[0]):
        if kind == "I":
            jolts.update(at_us, float(value))
        elif kind == "S":
            jolts.servo_cmd_us = at_us
        else:
            strip.update(at_us, int(value))
    return sorted(strip.presses + jolts.front_taps, key=lambda p: p["at_us"])


def _load_idle_fixture() -> list[tuple[int, str, float | int]]:
    """The recording keeps touched strip samples and moving IMU samples only; the untouched strip
    samples (every 62 ms) and still IMU samples (every 10 ms, no change) are filled back in."""
    touched: dict[int, int] = {}
    moving: dict[int, float] = {}
    for line in FIXTURE.read_text().splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "T":
            touched[int(parts[1])] = max(int(parts[2]), int(parts[3]), int(parts[4]))
        elif parts[0] == "I":
            moving[int(parts[1])] = int(parts[2]) / 100
    first = min(min(touched), min(moving, default=min(touched)))
    last = max(max(touched), max(moving, default=max(touched)))
    samples: list[tuple[int, str, float | int]] = []
    for ms in range(first, last + 1, 10):
        samples.append((ms * 1000, "I", moving.get(ms, 0.0)))
    strip_times = sorted(touched)
    ms = first
    while ms <= last:
        reading = next((touched[t] for t in strip_times if abs(t - ms) <= 31), 0)
        samples.append((ms * 1000, "T", reading))
        ms += 62
    return samples


def test_ten_noisy_untouched_minutes_make_no_press_and_no_tap():
    presses = replay(_load_idle_fixture())
    assert presses == []


def _rest(start_ms: int, end_ms: int) -> list[tuple[int, str, float | int]]:
    out: list[tuple[int, str, float | int]] = []
    for ms in range(start_ms, end_ms, 10):
        out.append((ms * 1000, "I", 0.05))
    for ms in range(start_ms, end_ms, 62):
        out.append((ms * 1000, "T", 0))
    return out


def _without_strip(samples, lo_ms: int, hi_ms: int):
    return [s for s in samples if not (s[1] == "T" and lo_ms <= s[0] // 1000 <= hi_ms)]


def test_a_light_tap_is_a_press_marked_as_a_tap():
    """Reading 1 for two strip samples, the jolt 58 ms before the first (measured): the rule of
    080 ignored it (weak run under 32 samples); now it is a tap, strong=1 for older hosts."""
    samples = _without_strip(_rest(0, 2000), 990, 1130)
    samples += [(1000 * 1000, "I", 1.6), (1058 * 1000, "T", 1), (1120 * 1000, "T", 1)]
    presses = replay(samples)
    assert len(presses) == 1
    assert presses[0]["tap"] == 1 and presses[0]["strong"] == 1 and presses[0]["gap"] == -58


def test_the_strip_feels_the_finger_before_the_impact_and_the_tap_still_counts():
    """Measured: on the weak-reading light taps the jolt came 70 and 112 ms after the first strip
    sample. 112 ms lands past the next strip sample, so the run keeps waiting one sample beyond
    the window."""
    for after_ms in (70, 112):
        samples = _without_strip(_rest(0, 2000), 990, 1300)
        samples += [(1000 * 1000, "T", 1), (1062 * 1000, "T", 1)]
        samples += [(1124 * 1000, "T", 0), (1186 * 1000, "T", 0), (1248 * 1000, "T", 0)]
        samples += [((1000 + after_ms) * 1000, "I", 2.8)]
        events = replay(samples)
        assert len(events) == 1 and events[0]["tap"] == 1 and events[0]["strip"] == 1
        assert events[0]["gap"] == after_ms


def test_a_slap_on_the_desk_or_typing_with_no_contact_is_nothing():
    """Measured 2026-11-12: typing beside the unit stays under 0.5 m/s^2, a slap on the desk beside
    it is 2.3 to 4.4, the same as a light tap on the shell; so a jolt alone is never a touch and
    the front tap by the motion sensor alone stays off."""
    assert replay(_rest(0, 2000) + [(1000 * 1000, "I", 0.5)]) == []
    assert replay(_rest(0, 2000) + [(1000 * 1000, "I", 4.4)]) == []


def test_a_jolt_just_after_a_servo_command_is_the_units_own_move():
    """A head move of the unit's own can start with a jerk of 3 to 5 m/s^2 (18:09:54 in the
    2026-11-12 capture); it is blanked, with or without noise on the strip."""
    samples = _without_strip(_rest(0, 3000), 990, 1130)
    samples += [(900 * 1000, "S", 0), (1000 * 1000, "I", 4.9)]
    samples += [(1030 * 1000, "T", 1), (1092 * 1000, "T", 1)]
    assert replay(samples) == []


def test_a_move_that_ramps_up_is_never_still_before_so_it_arms_no_jolt():
    """Most servo moves ramp (0.2, 0.85, 0.7 in the first 100 ms): no 150 ms of stillness right
    before the big change, so no jolt, even with noise on the strip meanwhile."""
    samples = [s for s in _rest(0, 3000) if not (s[1] == "I" and 1000 <= s[0] // 1000 < 1800)]
    samples += [(ms * 1000, "I", 0.85 if ms == 1000 else 2.0) for ms in range(1000, 1800, 10)]
    samples += [(1400 * 1000, "T", 1), (1462 * 1000, "T", 1), (1524 * 1000, "T", 1)]  # noise
    assert replay(samples) == []


def test_a_slow_rub_is_a_press_but_not_a_tap_and_a_firm_tap_is_both():
    rub = _without_strip(_rest(0, 5000), 1000, 3199)
    rub += [(ms * 1000, "T", 1) for ms in range(1000, 3200, 62)]
    presses = replay(rub)
    assert len(presses) == 1 and (presses[0]["strong"], presses[0]["tap"]) == (0, 0)
    firm = _without_strip(_rest(0, 2000), 1000, 1099)
    firm += [(1010 * 1000, "I", 3.0), (1030 * 1000, "T", 2)]
    presses = replay(firm)
    assert len(presses) == 1 and presses[0]["tap"] == 1 and presses[0]["strong"] == 1


def test_one_jolt_makes_at_most_one_tap():
    samples = _without_strip(_rest(0, 3000), 990, 1300)
    samples += [(1000 * 1000, "I", 1.6), (1030 * 1000, "T", 1), (1092 * 1000, "T", 0)]
    samples += [(1154 * 1000, "T", 0), (1216 * 1000, "T", 1), (1278 * 1000, "T", 0)]  # noise after
    assert len(replay(samples)) == 1


def test_the_known_residual_a_hard_knock_inside_a_noise_runs_window_counts():
    """Documented, not hidden: a desk knock of 2.3 or more that lands within 100 ms before or
    150 ms after a noise run's first sample is a tap. Measured 2026-11-12: two of five shell taps
    counted this way through noise; with nobody knocking, ten noisy minutes gave nothing."""
    samples = _without_strip(_rest(0, 2000), 990, 1130)
    samples += [(1000 * 1000, "T", 1), (1062 * 1000, "T", 1), (1080 * 1000, "I", 2.3)]
    assert len(replay(samples)) == 1
    samples = _without_strip(_rest(0, 2000), 990, 1130)
    samples += [(1000 * 1000, "T", 1), (1062 * 1000, "T", 1), (1300 * 1000, "I", 2.3)]  # outside
    assert replay(samples) == []
