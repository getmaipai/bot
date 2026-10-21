"""Spoken head movement: "look left", "nod", "look straight" (owner request 2026-10-21)."""

from __future__ import annotations

import asyncio

import pytest

from maipai_body.bodies.stackchan.head_commands import (
    CAN_DO,
    CANT_NOW,
    MAX_COMMANDS_PER_MIN,
    HeadCommand,
    HeadCommander,
    parse_head_command,
    target_for,
)


@pytest.mark.parametrize(
    ("text", "kind", "direction", "amount"),
    [
        ("Can you look down?", "look", "down", "normal"),  # the real transcript of 2026-10-21
        ("look left", "look", "left", "normal"),
        ("look right", "look", "right", "normal"),
        ("look up", "look", "up", "normal"),
        ("please look to your left", "look", "left", "normal"),
        ("turn left", "look", "left", "normal"),
        ("turn right", "look", "right", "normal"),
        ("turn your head to the right", "look", "right", "normal"),
        ("look up a little", "look", "up", "little"),
        ("look to the left a bit", "look", "left", "little"),
        ("look all the way left", "look", "left", "far"),
        ("A garbled word look down please", "look", "down", "normal"),
        ("look straight", "centre", None, "normal"),
        ("look straight ahead", "centre", None, "normal"),
        ("look forward", "centre", None, "normal"),
        ("look at me", "centre", None, "normal"),
        ("center", "centre", None, "normal"),
        ("face forward", "centre", None, "normal"),
        ("look around", "around", None, "normal"),
        ("nod", "nod", None, "normal"),
        ("say yes", "nod", None, "normal"),
        ("shake your head", "shake", None, "normal"),
        ("say no", "shake", None, "normal"),
        ("stay there", "stay", None, "normal"),
        ("turn around", "cannot", None, "normal"),
        ("spin", "cannot", None, "normal"),
        ("dance", "cannot", None, "normal"),
        ("look over there", "cannot", None, "normal"),
    ],
)
def test_phrases_are_recognised(text, kind, direction, amount):
    command = parse_head_command(text)
    assert command == HeadCommand(kind, direction, amount), text


@pytest.mark.parametrize(
    "text",
    [
        "what is the weather",
        "how do I turn right on red",
        "look at this and tell me what it is",
        "look down and tell me what you see",
        "look around the room and tell me what you see",
        "tell me about a dance",
        "turn on the living room light",
        "why is the sky blue",
        "",
    ],
)
def test_other_speech_goes_to_the_hub(text):
    assert parse_head_command(text) is None


def test_targets_are_in_the_robots_own_directions_and_scale_with_the_amount():
    assert target_for(HeadCommand("look", "left")) == (-45, 45)
    assert target_for(HeadCommand("look", "right")) == (45, 45)
    assert target_for(HeadCommand("look", "up")) == (0, 70)
    assert target_for(HeadCommand("look", "down")) == (0, 20)
    assert target_for(HeadCommand("look", "left", "little"))[0] == -20
    assert target_for(HeadCommand("look", "left", "far"))[0] == -90


class _Recorder:
    def __init__(self):
        self.moves = []
        self.held = []
        self.timers = []
        self.now = [0.0]

    def move(self, yaw, pitch, speed):
        self.moves.append((yaw, pitch, speed))

    def timer(self, seconds, callback):
        record = {"seconds": seconds, "callback": callback, "cancelled": False}

        class Handle:
            def cancel(self_inner):
                record["cancelled"] = True

        self.timers.append(record)
        return Handle()

    def commander(self, blocked=lambda: None):
        return HeadCommander(
            self.move,
            blocked=blocked,
            hold_pose=self.held.append,
            clock=lambda: self.now[0],
            sleep=lambda seconds: None,
            start_timer=self.timer,
        )


def test_look_left_moves_says_one_line_holds_the_pose_and_returns_to_centre_after_five_seconds():
    rec = _Recorder()
    line = rec.commander().run(HeadCommand("look", "left"))
    assert line == "Looking left."
    assert rec.moves == [(-45, 45, 120)]
    assert rec.held and rec.held[0] > 5.0  # the post-turn settle must not undo it
    assert rec.timers[0]["seconds"] == 5.0
    rec.timers[0]["callback"]()
    assert rec.moves[-1] == (0, 45, 120)


def test_stay_cancels_the_return_and_a_new_command_replaces_it():
    rec = _Recorder()
    commander = rec.commander()
    commander.run(HeadCommand("look", "up"))
    assert commander.run(HeadCommand("stay")) == ""
    assert rec.timers[0]["cancelled"] is True
    commander.run(HeadCommand("look", "down"))
    commander.run(HeadCommand("look", "right"))
    assert rec.timers[1]["cancelled"] is True and rec.timers[2]["cancelled"] is False


def test_nod_shake_and_look_around_are_sequences_that_end_at_centre():
    rec = _Recorder()
    commander = rec.commander()
    commander.run(HeadCommand("nod"))
    assert len(rec.moves) == 5 and rec.moves[-1][:2] == (0, 45)
    rec.moves.clear()
    commander.run(HeadCommand("shake"))
    assert len(rec.moves) == 5 and rec.moves[-1][:2] == (0, 45)
    rec.moves.clear()
    commander.run(HeadCommand("around"))
    assert [m[0] for m in rec.moves] == [-60, 60, 0]
    assert all(m[2] <= 120 for m in rec.moves)


def test_a_charging_unit_or_a_latched_stop_says_so_and_does_not_move():
    rec = _Recorder()
    assert (
        rec.commander(blocked=lambda: "the unit is charging").run(HeadCommand("look", "left"))
        == CANT_NOW
    )
    assert rec.moves == []


def test_a_failed_move_says_so_instead_of_falling_through():
    def broken(yaw, pitch, speed):
        raise RuntimeError("the head is stopped")

    commander = HeadCommander(broken, start_timer=lambda s, c: None)
    assert commander.run(HeadCommand("look", "left")) == CANT_NOW


def test_commands_have_their_own_limit_per_minute():
    rec = _Recorder()
    commander = rec.commander()
    results = [commander.run(HeadCommand("look", "left")) for _ in range(MAX_COMMANDS_PER_MIN + 3)]
    assert results[:MAX_COMMANDS_PER_MIN] == ["Looking left."] * MAX_COMMANDS_PER_MIN
    assert results[MAX_COMMANDS_PER_MIN:] == [CANT_NOW] * 3
    rec.now[0] += 61
    assert commander.run(HeadCommand("look", "left")) == "Looking left."


def test_an_unsupported_movement_gets_the_fixed_reply_and_moves_nothing():
    rec = _Recorder()
    assert rec.commander().run(HeadCommand("cannot")) == CAN_DO
    assert rec.moves == []


def _bridge_says(monkeypatch, text, head_control):
    import maipai_body.bodies.stackchan.turn as turn_module
    from maipai_body.speech.stt_stream import SttStreamResult
    from tests.test_stackchan_turn import (  # type: ignore[import-not-found]
        FakeCapture,
        FakePlayback,
        FakeServer,
        FakeTts,
        FakeTurn,
        InlineExecutor,
        Link,
        Offline,
    )

    class Stt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return SttStreamResult(kind="final", text=text)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=Stt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        head_control=head_control,
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    return FakeTurn.streams, FakeTts.sentences


def test_the_bridge_answers_can_you_look_down_without_asking_the_hub(monkeypatch):
    rec = _Recorder()
    streams, said = _bridge_says(monkeypatch, "Can you look down?", rec.commander())
    assert streams == [] and said == ["Looking down."]
    assert rec.moves == [(0, 20, 120)]


def test_the_bridge_gives_the_fixed_reply_for_turn_around_and_never_asks_the_hub(monkeypatch):
    rec = _Recorder()
    streams, said = _bridge_says(monkeypatch, "turn around", rec.commander())
    assert streams == [] and said == [CAN_DO] and rec.moves == []


def test_the_bridge_says_it_cannot_move_when_blocked_and_never_asks_the_hub(monkeypatch):
    rec = _Recorder()
    commander = rec.commander(blocked=lambda: "the unit is charging")
    streams, said = _bridge_says(monkeypatch, "look left", commander)
    assert streams == [] and said == [CANT_NOW] and rec.moves == []


def test_a_normal_question_still_reaches_the_hub(monkeypatch):
    rec = _Recorder()
    streams, said = _bridge_says(monkeypatch, "what is the weather", rec.commander())
    assert streams and rec.moves == []


def test_the_post_turn_settle_waits_while_a_requested_pose_is_held():
    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    try:
        behavior.render_turn_state("listening")
        behavior.hold_pose(6.0)
        before = sum(c.name == "self.robot.set_head_angles" for c in device.calls)
        behavior.render_turn_state("settle")
        assert sum(c.name == "self.robot.set_head_angles" for c in device.calls) == before
    finally:
        behavior.close()


def test_through_the_real_robot_the_head_goes_where_asked_and_a_latched_stop_refuses():
    import math

    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
    from maipai_body.hal.seam import HeadPose

    device = FakeStackChanDeviceClient()
    robot = StackChanRobotAdapter(device).robot
    behavior = StackChanBehavior(robot)
    try:

        def move(yaw, pitch, speed):
            pose = HeadPose(yaw=math.radians(yaw), pitch=math.radians(pitch))
            if not behavior._with_lease(lambda: robot.head.set(pose=pose, speed=speed)):
                raise RuntimeError("busy")

        commander = HeadCommander(
            move,
            blocked=lambda: "stopped" if robot.estop_engaged else None,
            start_timer=lambda s, c: None,
        )
        assert commander.run(HeadCommand("look", "left")) == "Looking left."
        assert device.head_angles["yaw"] == -45
        robot.emergency_stop()
        assert commander.run(HeadCommand("look", "right")) == CANT_NOW
        assert device.head_angles["yaw"] == -45
    finally:
        behavior.close()
