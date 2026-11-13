"""Spoken head movement: "look left", "nod", "look straight" (owner request 2026-10-21)."""

from __future__ import annotations

import asyncio

import pytest

from maipai_body.bodies.stackchan.head_commands import (
    CAN_DO,
    CANT_NOW,
    HOLD_TURN_S,
    LEVEL_ONLY,
    LOOK_AWAY,
    LOOKING_AT_YOU,
    LOOKING_FOR_YOU,
    MAX_COMMANDS_PER_MIN,
    TURN_AROUND,
    HeadCommand,
    HeadCommander,
    away_yaw,
    gaze_detail,
    parse_head_command,
    target_for,
)
from maipai_body.bodies.stackchan.profile import CENTRE_PITCH_DEG as C


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
        ("turn left a little", "look", "left", "little"),
        ("turn all the way right", "look", "right", "far"),
        ("look up a little", "look", "up", "little"),
        ("look to the left a bit", "look", "left", "little"),
        ("look all the way left", "look", "left", "far"),
        ("A garbled word look down please", "look", "down", "normal"),
        ("look straight", "centre", None, "normal"),
        ("look straight ahead", "centre", None, "normal"),
        ("look forward", "centre", None, "normal"),
        ("center", "centre", None, "normal"),
        ("face forward", "centre", None, "normal"),
        ("look around", "around", None, "normal"),
        ("nod", "nod", None, "normal"),
        ("say yes", "nod", None, "normal"),
        ("shake your head", "shake", None, "normal"),
        ("say no", "shake", None, "normal"),
        ("stay there", "stay", None, "normal"),
        ("turn around", "turnaround", None, "normal"),
        ("spin", "cannot", None, "normal"),
        ("dance", "cannot", None, "normal"),
        ("look over there", "cannot", None, "normal"),
        ("turn to me", "face", None, "normal"),
        ("turn toward me", "face", None, "normal"),
        ("look at me", "face", None, "normal"),
        ("face me", "face", None, "normal"),
        ("look over here", "face", None, "normal"),
        ("over here", "face", None, "normal"),
        ("I'm over here", "face", None, "normal"),
        ("I'm here", "face", None, "normal"),
        ("up here", "face", None, "normal"),
        ("I'm down here", "face", None, "normal"),
        ("find me", "face", None, "normal"),
        ("please stackchan turn to me", "face", None, "normal"),
        ("turn away", "away", None, "normal"),
        ("look away", "away", None, "normal"),
        ("look the other way", "away", None, "normal"),
    ],
)
def test_phrases_are_recognised(text, kind, direction, amount):
    command = parse_head_command(text)
    assert command is not None, text
    assert (command.kind, command.direction, command.amount) == (kind, direction, amount), text


@pytest.mark.parametrize(
    "text",
    [
        "what is the weather",
        "how do I turn right on red",
        "look at this and tell me what it is",
        "look down and tell me what you see",
        "look around the room and tell me what you see",
        "tell me about a dance",
        "where am I",
        "can you see me",
        "look at me and tell me what you see",
        "how do I get up here",
        "put the box down here on the table",
        "I was down here yesterday and the cat was over there",
        "turn on the living room light",
        "why is the sky blue",
        "",
    ],
)
def test_other_speech_goes_to_the_hub(text):
    assert parse_head_command(text) is None


def test_targets_are_in_the_robots_own_directions_and_scale_with_the_amount():
    assert target_for(HeadCommand("look", "left")) == (-45, C)
    assert target_for(HeadCommand("look", "right")) == (45, C)
    assert target_for(HeadCommand("look", "up")) == (0, C + 25)
    assert target_for(HeadCommand("look", "down")) == (0, C)
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
    assert rec.moves == [(-45, C, 120)]
    assert rec.held and rec.held[0] > 5.0  # the post-turn settle must not undo it
    assert rec.timers[0]["seconds"] == 5.0
    rec.timers[0]["callback"]()
    assert rec.moves[-1] == (0, C, 120)


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
    assert len(rec.moves) == 5 and rec.moves[-1][:2] == (0, C)
    rec.moves.clear()
    commander.run(HeadCommand("shake"))
    assert len(rec.moves) == 5 and rec.moves[-1][:2] == (0, C)
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
    assert streams == [] and said == [LEVEL_ONLY]
    assert rec.moves == [(0, C, 120)]


def test_the_bridge_answers_turn_around_honestly_and_never_asks_the_hub(monkeypatch):
    rec = _Recorder()
    streams, said = _bridge_says(monkeypatch, "turn around", rec.commander())
    assert streams == [] and said == [TURN_AROUND] and rec.moves == [(-90, C, 120)]


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


@pytest.mark.parametrize(
    ("text", "hold", "degrees"),
    [
        ("turn left", True, None),
        ("turn right", True, None),
        ("turn left 30 degrees", True, 30),
        ("turn right ninety degrees", True, 90),
        ("turn left 500 degrees", True, 90),  # clamped
        ("look left", False, None),
        ("look right", False, None),
        ("look up", False, None),
        ("turn up", False, None),
    ],
)
def test_a_turn_holds_its_heading_and_a_look_returns(text, hold, degrees):
    command = parse_head_command(text)
    assert command is not None and command.hold is hold and command.degrees == degrees


def test_degrees_and_amounts_set_the_size_of_the_turn():
    left30 = parse_head_command("turn left 30 degrees")
    right90 = parse_head_command("turn right ninety degrees")
    assert left30 and right90
    assert target_for(left30) == (-30, C)
    assert target_for(right90) == (90, C)
    assert target_for(parse_head_command("turn left a little")) == (-20, C)  # type: ignore[arg-type]
    assert target_for(parse_head_command("turn right all the way")) == (90, C)  # type: ignore[arg-type]


def test_the_face_requests_know_when_the_person_is_below_level():
    assert parse_head_command("I'm down here").level_only is True  # type: ignore[union-attr]
    assert parse_head_command("down here").level_only is True  # type: ignore[union-attr]
    assert parse_head_command("turn to me").level_only is False  # type: ignore[union-attr]
    assert parse_head_command("up here").level_only is False  # type: ignore[union-attr]


def test_a_turn_is_held_for_five_minutes_and_ends_on_centre_a_new_command_or_a_face():
    rec = _Recorder()
    commander = rec.commander()
    assert commander.run(HeadCommand("look", "left", hold=True)) == "Turning left."
    assert rec.moves == [(-45, C, 120)]
    assert rec.timers[0]["seconds"] == HOLD_TURN_S and rec.held == [HOLD_TURN_S + 1.0]
    commander.face_found()  # a face was found: the held turn ends, the face following takes over
    assert rec.timers[0]["cancelled"] is True
    commander.run(HeadCommand("look", "right", hold=True))
    commander.run(HeadCommand("centre"))  # "look straight"
    assert rec.timers[1]["cancelled"] is True
    assert rec.moves[-1] == (0, C, 120)


def test_a_found_face_does_not_end_a_plain_look_and_a_look_still_returns_after_five_seconds():
    rec = _Recorder()
    commander = rec.commander()
    commander.run(HeadCommand("look", "left"))
    commander.face_found()
    assert rec.timers[0]["cancelled"] is False and rec.timers[0]["seconds"] == 5.0


def test_look_down_says_it_can_only_look_level_and_goes_to_level():
    rec = _Recorder()
    assert rec.commander().run(HeadCommand("look", "down")) == LEVEL_ONLY
    assert rec.moves == [(0, C, 120)]


def test_turn_away_goes_about_45_degrees_from_the_face_and_returns_after_five_seconds():
    rec = _Recorder()
    commander = HeadCommander(
        rec.move,
        face_yaw=lambda: 10.0,
        hold_pose=rec.held.append,
        start_timer=rec.timer,
    )
    assert commander.run(HeadCommand("away")) == LOOK_AWAY
    assert rec.moves == [(-35, C, 120)]
    assert rec.timers[0]["seconds"] == 5.0
    rec.moves.clear()
    HeadCommander(rec.move, face_yaw=lambda: -20.0, start_timer=rec.timer).run(HeadCommand("away"))
    assert rec.moves == [(25, C, 120)]
    assert away_yaw(None) == -45  # no face tracked: to the left


def test_turn_around_turns_as_far_as_it_can_and_says_it_cannot_go_all_the_way():
    rec = _Recorder()
    assert rec.commander().run(HeadCommand("turnaround")) == TURN_AROUND
    assert "90 degrees" in TURN_AROUND and "not all the way around" in TURN_AROUND
    assert rec.moves == [(-90, C, 120)]


def test_a_face_request_starts_the_look_through_the_find_callback_and_moves_nothing_itself():
    rec = _Recorder()
    asked = []

    def find(level_only):
        asked.append(level_only)
        return "searching"

    commander = HeadCommander(rec.move, find_face=find, start_timer=rec.timer)
    assert commander.run(HeadCommand("face")) == LOOKING_FOR_YOU
    assert commander.run(HeadCommand("face", level_only=True)) == LOOKING_FOR_YOU
    assert asked == [False, True] and rec.moves == [] and rec.timers == []
    turned = HeadCommander(rec.move, find_face=lambda level_only: "turned")
    assert turned.run(HeadCommand("face")) == LOOKING_AT_YOU


def test_a_face_request_is_refused_when_the_head_may_not_move():
    rec = _Recorder()
    commander = HeadCommander(
        rec.move, blocked=lambda: "the unit is charging", find_face=lambda level_only: "searching"
    )
    assert commander.run(HeadCommand("face")) == CANT_NOW


def test_gaze_explains_a_spoken_request():
    from maipai_body.bodies.stackchan.gaze import GazeReason, GazeState

    gaze = GazeState()
    for command, said in (
        (HeadCommand("face"), "You asked me to turn to you!"),
        (HeadCommand("away"), "You asked me to look away!"),
        (HeadCommand("look", "left", hold=True), "You asked me to turn left!"),
        (HeadCommand("look", "left"), "You asked me to look left!"),
    ):
        gaze.note(GazeReason.COMMAND, gaze_detail(command))
        assert gaze.answer("why are you looking there") == said


def test_the_bridge_handles_turn_to_me_before_the_hub_and_the_sight_question(monkeypatch):
    rec = _Recorder()
    asked = []
    commander = HeadCommander(
        rec.move, find_face=lambda level_only: asked.append(level_only) or "searching"
    )
    streams, said = _bridge_says(monkeypatch, "turn to me", commander)
    assert streams == [] and said == [LOOKING_FOR_YOU] and asked == [False]
    streams, said = _bridge_says(monkeypatch, "I'm down here", commander)
    assert streams == [] and asked == [False, True]
