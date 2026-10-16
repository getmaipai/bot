"""THERMAL-01: the warm Compute Module slows, says so, never crashes."""

from __future__ import annotations

import pytest

from maipai_body.presence.thermal import (
    HYSTERESIS_C,
    ThermalGovernor,
    ThermalMonitor,
    ThermalSampler,
)


def _ramp(governor: ThermalGovernor, temps):
    return [governor.update(t) for t in temps]


def test_a_scripted_ramp_changes_the_rates_in_order_and_back_with_3_c_hysteresis():
    assert HYSTERESIS_C == 3.0
    g = ThermalGovernor()
    up = _ramp(g, [60, 69.9, 70, 74.9, 75, 77.9, 78, 80])
    assert [(s.vision_hz, s.gestures_suspended, s.idle_still) for s in up] == [
        (5.0, False, False),
        (5.0, False, False),
        (2.0, False, False),  # 70 C: vision drops to 2 Hz
        (2.0, False, False),
        (2.0, True, False),  # 75 C: gestures suspended
        (2.0, True, False),
        (2.0, True, True),  # 78 C: idle drops to still
        (2.0, True, True),
    ]
    down = _ramp(g, [77.0, 75.1, 74.9, 72.1, 71.9, 69.0, 67.1, 66.9])
    assert [(s.vision_hz, s.gestures_suspended, s.idle_still) for s in down] == [
        (2.0, True, True),  # 77 is not 3 C under 78... 78 - 3 = 75, 77 stays
        (2.0, True, True),  # 75.1 still above 75
        (2.0, True, False),  # under 75: idle un-stills
        (2.0, True, False),  # 72.1 is above 72 (75 - 3)
        (2.0, False, False),  # under 72: gestures resume
        (2.0, False, False),  # 69.0 is above 67 (70 - 3)
        (2.0, False, False),
        (5.0, False, False),  # under 67: vision back to 5 Hz
    ]


def test_a_reading_that_wobbles_around_a_threshold_does_not_flap():
    g = ThermalGovernor()
    levels = [g.update(t).level for t in [70.1, 69.8, 70.2, 69.9, 70.1, 68.0]]
    assert levels == [1, 1, 1, 1, 1, 1]


def test_the_line_plays_once_per_episode():
    g = ThermalGovernor()
    g.update(65)
    assert g.take_line() is False
    g.update(71)
    assert g.take_line() is True
    assert g.take_line() is False
    for t in (76, 79, 74, 71, 68):  # the episode goes on, the line does not repeat
        g.update(t)
        assert g.take_line() is False
    g.update(60)  # fully cooled: the episode ends
    g.update(71)  # a new one
    assert g.take_line() is True


def test_the_line_stays_owed_until_it_is_taken():
    g = ThermalGovernor()
    g.update(72)
    g.update(73)
    assert g.take_line() is True


def test_the_error_look_is_only_for_a_real_fault():
    g = ThermalGovernor()
    for t in (70, 75, 78, 83):
        assert g.update(t).fault is False, f"{t} C is slowing down, not a fault"
    assert g.update(85).fault is True
    assert g.update(83).fault is True, "a fault clears with hysteresis"
    assert g.update(81.9).fault is False
    assert g.update(60, throttled_now=True).fault is True
    assert g.update(60, throttled_now=False).fault is False


def test_an_unreadable_temperature_changes_nothing():
    g = ThermalGovernor()
    hot = g.update(79)
    assert g.update(None) == hot
    assert g.update(None, throttled_now=None) == hot


def test_the_state_frame_value_is_plain_json():
    g = ThermalGovernor()
    frame = g.update(76).as_frame()
    assert frame == {
        "level": "gestures_suspended",
        "temp_c": 76.0,
        "vision_hz": 2.0,
        "fault": False,
    }


class _Files:
    def __init__(self, temp="71500\n", throttled="throttled=0x0\n"):
        self.temp, self.throttled = temp, throttled

    def read_text(self, path):
        if isinstance(self.temp, Exception):
            raise self.temp
        return self.temp

    def run(self, cmd):
        if isinstance(self.throttled, Exception):
            raise self.throttled
        return self.throttled


def test_the_sampler_reads_the_thermal_zone_and_the_firmware_flags():
    files = _Files()
    assert ThermalSampler(read_text=files.read_text, run=files.run).read() == (71.5, False)
    files.throttled = "throttled=0x4\n"
    assert ThermalSampler(read_text=files.read_text, run=files.run).read() == (71.5, True)
    files.throttled = "throttled=0x50000\n"  # occurred earlier, not now
    assert ThermalSampler(read_text=files.read_text, run=files.run).read() == (71.5, False)


@pytest.mark.parametrize("bad", [OSError("no zone"), "garbage"])
def test_an_unreadable_sampler_answers_none_and_never_raises(bad):
    files = _Files(temp=bad, throttled=OSError("no vcgencmd"))
    assert ThermalSampler(read_text=files.read_text, run=files.run).read() == (None, None)


def test_the_monitor_samples_on_an_interval_and_survives_a_failing_sampler():
    reads = []

    class Sampler:
        def read(self):
            reads.append(1)
            if len(reads) == 2:
                raise RuntimeError("boom")
            return 71.0, False

    now = {"t": 0.0}
    monitor = ThermalMonitor(Sampler(), clock=lambda: now["t"], interval_s=5.0)
    assert monitor.poll().level == 1
    now["t"] = 1.0
    monitor.poll()
    assert len(reads) == 1, "not again inside the interval"
    now["t"] = 6.0
    assert monitor.poll().level == 1, "a raising sampler keeps the last state"
    now["t"] = 12.0
    assert monitor.poll().level == 1 and len(reads) == 3
