"""StackChan self-healing on the host: the restart guard's state, the wake engine self-test
schedule (rung (c)) and the camera stall ladder (rung (d)). Fake clocks, no sockets."""

from __future__ import annotations

import asyncio
import logging
import threading

from maipai_body.bodies.stackchan.self_heal import (
    CameraStallWatch,
    SelfHealState,
    WakeSelfTest,
)


def _tester(state=None, *, idle=True, connected=True):
    now = [1000.0]
    state = state or SelfHealState()
    flags = {"idle": idle, "connected": connected}
    test = WakeSelfTest(
        state,
        clock=lambda: now[0],
        is_idle=lambda: flags["idle"],
        is_connected=lambda: flags["connected"],
    )
    return test, now, state, flags


# ---- the unit's restart guard and level facts ------------------------------------------------


def test_the_hold_a_unit_reports_stops_the_host_asking_and_lights_the_error_look():
    seen = []
    state = SelfHealState(on_hold=seen.append)
    assert state.hold is False
    state.observe("wake_stats", {"heal_n": 3, "heal_hold": 1, "state": 3})
    assert state.hold is True and state.restarts == 3
    assert seen == [True]
    state.observe("wake_stats", {"heal_n": 0, "heal_hold": 0})
    assert state.hold is False and seen == [True, False]


def test_a_boot_report_carries_the_hold_and_why_the_last_restart_happened(caplog):
    state = SelfHealState()
    with caplog.at_level(logging.INFO):
        state.observe("boot", {"heal_n": 1, "heal_hold": 0, "heal_why": "stall"})
    assert state.restarts == 1
    lines = [r.getMessage() for r in caplog.records if "self-heal" in r.getMessage()]
    assert any("stall" in line for line in lines)


def test_the_unit_logging_a_refused_restart_is_one_info_line(caplog):
    state = SelfHealState()
    with caplog.at_level(logging.INFO):
        state.observe("heal", {"action": "refused", "why": "host", "n": 3})
    (line,) = [r.getMessage() for r in caplog.records if "self-heal" in r.getMessage()]
    assert "refused" in line and "3" in line


def test_a_muted_unit_and_the_microphone_level_are_remembered():
    state = SelfHealState()
    state.observe("wake_stats", {"muted": 1, "mic_rms_max": 40})
    assert state.muted is True and state.mic_rms_max == 40
    state.observe("wake_stats", {"muted": 0, "mic_rms_max": 900})
    assert state.muted is False and state.mic_rms_max == 900


# ---- the wake engine self-test schedule ------------------------------------------------------


def test_the_test_runs_sixty_seconds_after_a_turn_ends():
    test, now, _, _ = _tester()
    test.note_turn_end()
    now[0] += 59
    assert test.tick() == []
    now[0] += 2
    assert test.tick() == ["wake_selftest"]


def test_never_while_the_unit_is_busy_muted_held_or_gone():
    test, now, state, flags = _tester()
    test.note_turn_end()
    now[0] += 70
    flags["idle"] = False
    assert test.tick() == []
    flags["idle"] = True
    flags["connected"] = False
    assert test.tick() == []
    flags["connected"] = True
    state.observe("wake_stats", {"muted": 1})
    assert test.tick() == []  # a muted unit is not deaf
    state.observe("wake_stats", {"muted": 0, "heal_hold": 1})
    assert test.tick() == []  # while the restart hold lasts the host leaves it alone
    state.observe("wake_stats", {"heal_hold": 0})
    assert test.tick() == ["wake_selftest"]


def test_a_hit_means_the_next_test_is_an_hour_away_and_idle_hours_repeat(caplog):
    test, now, _, _ = _tester()
    test.note_turn_end()
    now[0] += 61
    assert test.tick() == ["wake_selftest"]
    test.on_event("wake_selftest", {"result": "hit", "hits": 1})
    now[0] += 3500
    assert test.tick() == []
    now[0] += 101
    assert test.tick() == ["wake_selftest"]


def test_a_miss_rebuilds_the_engine_and_tests_again_and_a_second_miss_restarts(caplog):
    test, now, _, _ = _tester()
    test.note_turn_end()
    now[0] += 61
    assert test.tick() == ["wake_selftest"]
    with caplog.at_level(logging.INFO):
        test.on_event("wake_selftest", {"result": "miss", "hits": 0})
        assert test.tick() == ["wake_rebuild"]
        now[0] += 6
        assert test.tick() == ["wake_selftest"]
        test.on_event("wake_selftest", {"result": "miss", "hits": 0})
        assert test.tick() == ["reboot"]
    assert any("self-heal" in r.getMessage() for r in caplog.records)
    # after the restart request it waits before testing again
    now[0] += 6
    assert test.tick() == []


def test_a_pass_after_a_rebuild_is_logged_as_a_recovery(caplog):
    test, now, _, _ = _tester()
    test.note_turn_end()
    now[0] += 61
    test.tick()
    test.on_event("wake_selftest", {"result": "miss"})
    test.tick()
    now[0] += 6
    test.tick()
    with caplog.at_level(logging.INFO):
        test.on_event("wake_selftest", {"result": "hit", "hits": 1})
    assert any("recovered" in r.getMessage() for r in caplog.records)


def test_a_skipped_or_unanswered_test_is_tried_again_in_a_minute_and_never_counts_as_deaf():
    test, now, _, _ = _tester()
    test.note_turn_end()
    now[0] += 61
    assert test.tick() == ["wake_selftest"]
    test.on_event("wake_selftest", {"result": "skipped", "why": "busy"})
    now[0] += 30
    assert test.tick() == []
    now[0] += 31
    assert test.tick() == ["wake_selftest"]
    now[0] += 30  # no event came back at all
    assert test.tick() == []
    now[0] += 31
    assert test.tick() == ["wake_selftest"]


# ---- the camera stall ladder -----------------------------------------------------------------


def test_a_camera_that_never_streamed_is_left_to_the_connect_retry():
    watch = CameraStallWatch()
    assert watch.step(0.0, watching=True, idle=True) is None
    assert watch.step(500.0, watching=True, idle=True) is None


def test_the_ladder_is_three_reasks_then_a_reconnect_then_a_restart():
    watch = CameraStallWatch()
    watch.note_frame(0.0)
    assert watch.step(59.0, watching=True, idle=True) is None
    assert [watch.step(t, watching=True, idle=True) for t in (61.0, 122.0, 183.0)] == ["reask"] * 3
    assert watch.step(244.0, watching=True, idle=True) == "reconnect"
    assert watch.step(250.0, watching=True, idle=True) is None
    assert watch.step(305.0, watching=True, idle=True) == "restart"


def test_a_frame_ends_the_ladder_and_vision_off_or_a_busy_unit_pauses_it():
    watch = CameraStallWatch()
    watch.note_frame(0.0)
    assert watch.step(61.0, watching=True, idle=True) == "reask"
    watch.note_frame(70.0)
    assert watch.step(120.0, watching=True, idle=True) is None
    assert watch.step(131.0, watching=True, idle=True) == "reask"
    # vision turned off: nothing, and the wait starts again when it is back on
    assert watch.step(400.0, watching=False, idle=True) is None
    assert watch.step(430.0, watching=True, idle=True) is None
    assert watch.step(461.0, watching=True, idle=True) == "reask"
    # a unit in a turn does not stream by design
    assert watch.step(900.0, watching=True, idle=False) is None
    assert watch.step(930.0, watching=True, idle=True) is None


class _FakeSocket:
    def __init__(self):
        self.sent, self.closed = [], None

    async def send(self, data):
        self.sent.append(data)

    async def close(self, code, reason=""):
        self.closed = (code, reason)


def test_the_avatar_server_acts_on_each_rung():
    from maipai_body.bodies.stackchan.avatar.server import AvatarServer

    async def run():
        server = AvatarServer.__new__(AvatarServer)
        server._stall = CameraStallWatch()
        restarts = []
        server.request_restart = lambda: restarts.append(1)
        server.unit_idle = lambda: True
        server.start_camera_on_connect = lambda: True
        socket = _FakeSocket()
        server._stall.note_frame(0.0)
        for t in (61.0, 122.0, 183.0):
            await server._stall_step(socket, "dev", t)
        assert len(socket.sent) == 3 and socket.closed is None
        await server._stall_step(socket, "dev", 244.0)
        assert socket.closed is not None
        await server._stall_step(socket, "dev", 305.0)
        assert restarts == [1]

    asyncio.run(run())


# ---- the host stops asking while the unit holds ----------------------------------------------


def test_the_server_does_not_ask_a_held_unit_to_restart():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        server = XiaozhiServer.__new__(XiaozhiServer)
        server._loop = loop
        server.heal = SelfHealState()
        sent = []

        async def send_system(command, **fields):
            sent.append(command)

        server.send_system = send_system
        server._request_unit_restart()
        assert sent == ["reboot"]
        server.heal.observe("wake_stats", {"heal_hold": 1})
        server._request_unit_restart()
        assert sent == ["reboot"]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(2)
