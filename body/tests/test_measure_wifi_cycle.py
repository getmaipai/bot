"""M-R5 on the unit: the real radio is cycled and the time until the hub answers is read.

Clock, sleep, probe and the command runner are injected, so the logic is
proven here without a radio; the unit run is the only place it touches one.
"""

from __future__ import annotations

import pytest

from maipai_body.measure.wifi_cycle import run_wifi_cycle_trial, time_to_reachable


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_time_to_reachable_is_the_wait_until_the_first_successful_probe():
    clock = _Clock()
    answers = iter([False, False, False, True])
    result = time_to_reachable(
        lambda: next(answers), clock=clock, sleep=clock.sleep, interval_s=0.5, timeout_s=10.0
    )
    assert result == pytest.approx(1.5 * 1e3)  # three failed probes, 0.5 s apart


def test_time_to_reachable_is_none_when_the_hub_never_answers_in_time():
    clock = _Clock()
    result = time_to_reachable(
        lambda: False, clock=clock, sleep=clock.sleep, interval_s=0.5, timeout_s=2.0
    )
    assert result is None


def test_a_probe_that_raises_counts_as_unreachable_not_as_a_crash():
    clock = _Clock()
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("network is unreachable")
        return True

    assert time_to_reachable(
        probe, clock=clock, sleep=clock.sleep, interval_s=0.1, timeout_s=5.0
    ) == pytest.approx(200.0)


def test_a_wifi_trial_runs_off_waits_the_outage_runs_on_then_times_the_return():
    clock = _Clock()
    ran: list[tuple[str, float]] = []

    def runner(command: str) -> None:
        ran.append((command, clock.now))

    answers = iter([False, True])
    row = run_wifi_cycle_trial(
        off_command="radio off",
        on_command="radio on",
        outage_s=5.0,
        probe=lambda: next(answers),
        runner=runner,
        clock=clock,
        sleep=clock.sleep,
        interval_s=0.2,
        timeout_s=30.0,
    )
    assert [c for c, _ in ran] == ["radio off", "radio on"]
    assert ran[1][1] - ran[0][1] == pytest.approx(5.0)
    assert row["outage_s"] == 5.0
    assert row["reachable_after_ms"] == pytest.approx(200.0)


def test_a_wifi_trial_still_turns_the_radio_back_on_if_the_wait_is_interrupted():
    clock = _Clock()
    ran: list[str] = []

    def sleeper(seconds: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_wifi_cycle_trial(
            off_command="radio off",
            on_command="radio on",
            outage_s=5.0,
            probe=lambda: True,
            runner=ran.append,
            clock=clock,
            sleep=sleeper,
            interval_s=0.2,
            timeout_s=30.0,
        )
    assert ran == ["radio off", "radio on"]
