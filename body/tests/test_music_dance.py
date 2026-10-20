"""BOT-SC-DANCE-01 (host half): music detection and the dance policy.

Every number here is an UNMEASURED design default (the module docstrings
in ``speech/music.py`` and ``presence/auto_dance.py`` say the same); this
suite pins the *shape* of the behaviour, not the thresholds' tuning, so a
future measurement pass can move the constants without rewriting the
tests. Policy times are kept on a 0.5 s grid where an exact boundary
matters, so no assertion depends on float rounding.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from maipai_body.presence.auto_dance import AutoDancePolicy
from maipai_body.speech.music import MusicDetector

SR = 16000
BLOCK = 512  # one 32 ms frame at 16 kHz, as capture.py's poll_blocks yields


def feed(detector: MusicDetector, signal: npt.NDArray[np.float32], block: int = BLOCK) -> None:
    for i in range(0, len(signal), block):
        detector.accept(signal[i : i + block])


def click_train(
    sr: int = SR,
    duration_s: float = 4.0,
    bpm: float = 120.0,
    freq_hz: float = 440.0,
    burst_s: float = 0.1,
    amplitude: float = 0.5,
) -> npt.NDArray[np.float32]:
    """A tone burst on every beat - the "music" stand-in."""
    n = round(duration_s * sr)
    t = np.arange(n, dtype=np.float64) / sr
    out = np.zeros(n, dtype=np.float64)
    period = 60.0 / bpm
    start = 0.0
    while start < duration_s:
        stop = min(start + burst_s, duration_s)
        mask = (t >= start) & (t < stop)
        out[mask] = amplitude * np.sin(2.0 * np.pi * freq_hz * t[mask])
        start += period
    return out.astype(np.float32)


class TestMusicDetector:
    def test_music_scores_above_threshold(self) -> None:
        det = MusicDetector(sample_rate=SR)
        feed(det, click_train())
        assert det.music_score() > 0.55
        assert det.is_music() is True

    def test_white_noise_scores_below_threshold(self) -> None:
        rng = np.random.default_rng(42)
        noise = (rng.standard_normal(4 * SR) * 0.1).astype(np.float32)
        det = MusicDetector(sample_rate=SR)
        feed(det, noise)
        assert det.music_score() < 0.55
        assert det.is_music() is False

    def test_silence_scores_zero(self) -> None:
        det = MusicDetector(sample_rate=SR)
        feed(det, np.zeros(4 * SR, dtype=np.float32))
        assert det.music_score() == 0.0
        assert det.is_music() is False

    def test_window_under_three_seconds_scores_zero(self) -> None:
        det = MusicDetector(sample_rate=SR)
        feed(det, click_train(duration_s=2.5))
        assert det.music_score() == 0.0

    def test_accepts_a_single_whole_signal(self) -> None:
        det = MusicDetector(sample_rate=SR)
        det.accept(click_train())
        assert det.music_score() > 0.55

    def test_window_never_grows_beyond_four_seconds(self) -> None:
        det = MusicDetector(sample_rate=SR)
        feed(det, click_train(duration_s=8.0))
        # still scoring from the last 4.0 s, i.e. the tail of the music
        assert 0.0 <= det.music_score() <= 1.0
        assert det.is_music() is True

    def test_is_music_respects_custom_threshold(self) -> None:
        det = MusicDetector(sample_rate=SR)
        feed(det, click_train())
        assert det.is_music(threshold=0.0) is True
        assert det.is_music(threshold=1.01) is False


def dance_policy(**kwargs: object) -> AutoDancePolicy:
    kwargs.setdefault("enabled", lambda: True)
    return AutoDancePolicy(**kwargs)  # type: ignore[arg-type]


def run(policy: AutoDancePolicy, updates: list[tuple[float, bool, bool]]) -> None:
    """Drive (now, music, turn_active) updates through the policy."""
    for now, music, turn in updates:
        policy.update(now, music=music, turn_active=turn)


def times_up_to(seconds: float, step: float = 0.1) -> list[float]:
    return [round(t, 6) for t in np.arange(0.0, seconds + step / 2, step)]


class TestAutoDancePolicy:
    def test_disabled_never_starts(self) -> None:
        policy = dance_policy(enabled=lambda: False)
        for t in times_up_to(10.0):
            assert policy.update(t, music=True, turn_active=False) == "none"
        assert policy.dancing is False

    def test_starts_after_three_seconds_of_continuous_music(self) -> None:
        policy = dance_policy()
        for t in times_up_to(2.9):
            assert policy.update(t, music=True, turn_active=False) == "none"
        assert policy.update(3.0, music=True, turn_active=False) == "start"
        assert policy.dancing is True
        # "start" is delivered exactly once
        assert policy.update(4.0, music=True, turn_active=False) == "none"

    def test_gap_under_one_second_does_not_reset_the_run(self) -> None:
        policy = dance_policy()
        for t in times_up_to(2.0):
            assert policy.update(t, music=True, turn_active=False) == "none"
        # a 0.4 s gap (false at 2.2, true again at 2.4) must not reset
        # the run that began at 0.0
        assert policy.update(2.2, music=False, turn_active=False) == "none"
        assert policy.update(2.4, music=True, turn_active=False) == "none"
        assert policy.update(3.0, music=True, turn_active=False) == "start"

    def test_gap_of_one_second_resets_the_run(self) -> None:
        policy = dance_policy()
        for t in times_up_to(2.0):
            policy.update(t, music=True, turn_active=False)
        policy.update(2.2, music=False, turn_active=False)
        # 3.2 is 1.2 s after the last true (2.0): the run resets
        policy.update(3.2, music=False, turn_active=False)
        for t in np.arange(3.5, 6.5, 0.5):
            assert policy.update(round(t, 6), music=True, turn_active=False) == "none"
        # the run restarts at 3.5, so 3.0 s later the dance starts at 6.5
        assert policy.update(6.5, music=True, turn_active=False) == "start"

    def test_turn_active_never_starts(self) -> None:
        policy = dance_policy()
        for t in times_up_to(10.0):
            assert policy.update(t, music=True, turn_active=True) == "none"
        assert policy.dancing is False

    def test_quiet_hours_never_starts(self) -> None:
        policy = dance_policy()
        for t in times_up_to(10.0):
            assert (
                policy.update(t, music=True, turn_active=False, quiet_hours_active=True) == "none"
            )
        assert policy.dancing is False

    def test_stops_exactly_once_after_dance_for_s(self) -> None:
        policy = dance_policy()
        run(policy, [(t, True, False) for t in times_up_to(3.0)])
        assert policy.dancing is True
        for t in np.arange(4.0, 13.0, 0.5):
            assert policy.update(round(t, 6), music=True, turn_active=False) == "none"
        assert policy.update(13.0, music=True, turn_active=False) == "stop"
        assert policy.dancing is False
        # once, never again on its own
        assert policy.update(14.0, music=True, turn_active=False) == "none"

    def test_turn_active_stops_an_active_dance(self) -> None:
        policy = dance_policy()
        run(policy, [(t, True, False) for t in times_up_to(3.0)])
        assert policy.update(5.0, music=True, turn_active=True) == "stop"
        assert policy.dancing is False

    def test_quiet_hours_stops_an_active_dance(self) -> None:
        policy = dance_policy()
        run(policy, [(t, True, False) for t in times_up_to(3.0)])
        assert policy.update(5.0, music=True, turn_active=False, quiet_hours_active=True) == "stop"
        assert policy.dancing is False

    def test_no_restart_under_continuous_music_after_a_dance(self) -> None:
        policy = dance_policy()
        run(policy, [(t, True, False) for t in times_up_to(3.0)])
        run(policy, [(round(t, 6), True, False) for t in np.arange(4.0, 60.0, 0.5)])
        assert policy.dancing is False

    def test_rearms_after_ten_seconds_of_silence(self) -> None:
        policy = dance_policy()
        run(policy, [(t, True, False) for t in times_up_to(3.0)])
        run(policy, [(round(t, 6), True, False) for t in np.arange(4.0, 13.0, 0.5)])
        assert policy.update(13.0, music=True, turn_active=False) == "stop"
        # ten seconds of silence: quiet clock starts at 13.5, re-arms at 23.5
        for t in np.arange(13.5, 23.5, 0.5):
            assert policy.update(round(t, 6), music=False, turn_active=False) == "none"
        assert policy.update(23.5, music=False, turn_active=False) == "none"
        # a fresh run begins at 24.0, so the next dance starts at 27.0
        for t in np.arange(24.0, 27.0, 0.5):
            assert policy.update(round(t, 6), music=True, turn_active=False) == "none"
        assert policy.update(27.0, music=True, turn_active=False) == "start"
        assert policy.dancing is True

    def test_silence_blip_breaks_the_rearm_clock(self) -> None:
        policy = dance_policy()
        run(policy, [(t, True, False) for t in times_up_to(3.0)])
        run(policy, [(round(t, 6), True, False) for t in np.arange(4.0, 13.0, 0.5)])
        policy.update(13.0, music=True, turn_active=False)
        # silence to 21.5 (8.0 s, not enough), a one-tick blip of music,
        # then silence again: the re-arm clock restarts at 22.5 and lands
        # at 32.5, not ~23.5 as it would have without the blip
        for t in np.arange(13.5, 22.0, 0.5):
            policy.update(round(t, 6), music=False, turn_active=False)
        policy.update(22.0, music=True, turn_active=False)
        for t in np.arange(22.5, 32.5, 0.5):
            policy.update(round(t, 6), music=False, turn_active=False)
        policy.update(32.5, music=False, turn_active=False)
        for t in np.arange(33.0, 36.0, 0.5):
            assert policy.update(round(t, 6), music=True, turn_active=False) == "none"
        assert policy.update(36.0, music=True, turn_active=False) == "start"

    def test_custom_timings(self) -> None:
        policy = dance_policy(start_after_s=1.0, dance_for_s=2.0, quiet_before_rearm_s=4.0)
        assert policy.update(0.5, music=True, turn_active=False) == "none"
        assert policy.update(1.0, music=True, turn_active=False) == "none"
        # the run began at the first true tick (0.5), so 1.0 s lands at 1.5
        assert policy.update(1.5, music=True, turn_active=False) == "start"
        assert policy.update(3.0, music=True, turn_active=False) == "none"
        assert policy.update(3.5, music=True, turn_active=False) == "stop"
        for t in np.arange(4.0, 8.0, 0.5):
            assert policy.update(round(t, 6), music=False, turn_active=False) == "none"
        assert policy.update(8.0, music=False, turn_active=False) == "none"  # re-armed here
        for t in np.arange(8.5, 9.5, 0.5):
            assert policy.update(round(t, 6), music=True, turn_active=False) == "none"
        assert policy.update(9.5, music=True, turn_active=False) == "start"
