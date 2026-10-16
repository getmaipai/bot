"""SLEEP-AUTO-01: when the body sleeps and when arrival wakes it (UNMEASURED thresholds)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from maipai_body.presence import sleep_auto
from maipai_body.presence.sleep_auto import SleepAutoPolicy, mean_luma

DARK, BRIGHT = 5.0, 120.0
TICK = 5.0


def _run(policy, seconds, *, start=0.0, luma=DARK, speech=lambda t: False, **kwargs):
    edges, t = [], start
    while t < start + seconds:
        t += TICK
        edge = policy.update(t, luma=luma, speech=speech(t), face=False, **kwargs)
        if edge:
            edges.append((t, edge))
    return edges, t


def test_dark_and_quiet_for_ten_minutes_enters_sleep():
    edges, _ = _run(SleepAutoPolicy(), 700)
    assert [e for _, e in edges] == ["sleep"]
    assert 600 <= edges[0][0] <= 610


def test_light_alone_never_sleeps():
    edges, _ = _run(SleepAutoPolicy(), 7200, luma=BRIGHT)
    assert edges == []


def test_sound_alone_never_sleeps():
    # Dark, but someone speaks every five minutes.
    edges, _ = _run(SleepAutoPolicy(), 7200, speech=lambda t: int(t) % 300 == 0)
    assert edges == []


def test_no_luma_reading_means_the_dark_rule_cannot_run():
    edges, _ = _run(SleepAutoPolicy(), 7200, luma=None)
    assert edges == []


def test_the_setting_off_disables_the_dark_rule():
    edges, _ = _run(SleepAutoPolicy(auto_enabled=False), 7200)
    assert edges == []


def test_a_face_wakes_within_one_tick():
    policy = SleepAutoPolicy()
    _, t = _run(policy, 700)
    assert policy.asleep
    assert policy.update(t + 0.5, luma=DARK, speech=False, face=True) == "wake"
    assert not policy.asleep


def test_speech_and_a_knock_wake():
    for kwargs in (
        {"speech": True, "face": False},
        {"speech": False, "face": False, "knock": True},
    ):
        policy = SleepAutoPolicy()
        _, t = _run(policy, 700)
        assert policy.update(t + 0.5, luma=DARK, **kwargs) == "wake"


def test_quiet_hours_sleep_regardless_of_light_and_sound():
    policy = SleepAutoPolicy(auto_enabled=False)
    edge = policy.update(1.0, luma=BRIGHT, speech=False, face=False, quiet_hours=True)
    assert edge == "sleep"


def test_after_a_wake_in_quiet_hours_it_stays_up_until_ten_idle_minutes():
    policy = SleepAutoPolicy()
    policy.update(1.0, luma=BRIGHT, speech=False, face=False, quiet_hours=True)
    assert policy.update(2.0, luma=BRIGHT, speech=False, face=True, quiet_hours=True) == "wake"
    edges, t = _run(policy, 500, start=2.0, luma=BRIGHT, quiet_hours=True)
    assert edges == []
    edges, _ = _run(policy, 200, start=t, luma=BRIGHT, quiet_hours=True)
    assert [e for _, e in edges] == ["sleep"]


def test_mean_luma_keeps_nothing_and_reads_a_frame():
    frame = np.full((4, 4, 3), 60, dtype=np.uint8)
    assert mean_luma(frame) == 60.0


def test_the_policy_never_touches_audio_so_the_wake_word_stays_live():
    tree = ast.parse(Path(sleep_auto.__file__).read_text())
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if "speech" in m or "audio" in m or "kws" in m]


def test_quiet_hours_use_the_registry_defaults_until_the_hub_sends_a_window():
    from datetime import datetime

    from maipai_body.presence.sleep_auto import QuietHours

    clock = {"now": datetime(2026, 10, 16, 22, 0)}
    quiet = QuietHours(now=lambda: clock["now"])
    assert quiet.active() is True, "21:00 to 07:00 by default"
    clock["now"] = datetime(2026, 10, 16, 12, 0)
    assert quiet.active() is False


def test_quiet_hours_cross_midnight_follow_the_settings_frame_and_ignore_garbage():
    from datetime import datetime

    from maipai_body.presence.sleep_auto import QuietHours

    clock = {"now": datetime(2026, 10, 16, 22, 0)}
    quiet = QuietHours(now=lambda: clock["now"])
    quiet.apply({"household.quiet_hours.from": "23:00", "household.quiet_hours.to": "05:00"})
    assert quiet.active() is False
    clock["now"] = datetime(2026, 10, 16, 23, 30)
    assert quiet.active() is True
    clock["now"] = datetime(2026, 10, 16, 3, 0)
    assert quiet.active() is True
    clock["now"] = datetime(2026, 10, 16, 6, 0)
    assert quiet.active() is False
    quiet.apply({"household.quiet_hours.from": "garbage", "other": 1})
    clock["now"] = datetime(2026, 10, 16, 23, 30)
    assert quiet.active() is True, "a malformed value keeps the last good one"
    quiet.apply({"household.quiet_hours.from": "08:00", "household.quiet_hours.to": "08:00"})
    assert quiet.active() is False, "equal bounds mean never"


def test_the_luma_reader_never_reads_the_camera_at_level_off():
    import numpy as np

    from maipai_body.presence.sleep_auto import luma_reader

    class Camera:
        reads = 0

        def get_frame(self):
            Camera.reads += 1
            return np.full((48, 64, 3), 10, dtype=np.uint8)

    level = {"v": "off"}
    read = luma_reader(Camera(), level=lambda: level["v"])
    assert read() is None and Camera.reads == 0
    level["v"] = "presence"
    assert read() == 10.0 and Camera.reads == 1
