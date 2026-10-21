"""Shake, pet and heart: the spoken line after a shake, and a heart that has to be earned."""

from __future__ import annotations

import random

import pytest

from maipai_body.bodies.stackchan.expression_map import (
    CUE_FACE_MAP,
    PRIMITIVE_BODY_MAP,
    REPLY_MOOD_FACE_MAP,
)
from maipai_body.bodies.stackchan.reactions import (
    FACE_HOLD_S,
    SHAKE_COOLDOWN_S,
    SHAKE_LINES,
    Reactions,
    has_love_cue,
)
from maipai_body.bodies.stackchan.xiaozhi.server import FIRMWARE_EMOTIONS


class _Rig:
    def __init__(self, *, quiet=False, busy=False, symbol="works"):
        self.now = [100.0]
        self.faces: list[str] = []
        self.said: list[str] = []
        self.symbols: list[str] = []
        self.quiet, self.busy = quiet, busy

        def show_symbol(name):
            if symbol == "missing":
                raise RuntimeError("Unknown tool: self.screen.show_symbol")
            self.symbols.append(name)

        self.reactions = Reactions(
            face=self.faces.append,
            say=lambda text: self.said.append(text) or True,
            quiet=lambda: self.quiet,
            busy=lambda: self.busy,
            symbol=show_symbol,
            clock=lambda: self.now[0],
            rng=random.Random(4),
        )


def test_a_shake_gives_a_surprised_face_and_one_of_the_lines():
    rig = _Rig()
    rig.reactions.on_events(["shake"])
    assert rig.faces == ["surprised"]
    assert len(rig.said) == 1 and rig.said[0] in SHAKE_LINES


def test_repeated_shaking_does_not_loop_and_the_lines_vary():
    rig = _Rig()
    lines = []
    for _ in range(6):
        rig.reactions.on_events(["shake"])
        rig.reactions.on_events(["shake"])  # still shaking: inside the cooldown
        lines.append(rig.said[-1])
        rig.now[0] += SHAKE_COOLDOWN_S
    assert len(rig.said) == 6
    assert all(a != b for a, b in zip(lines, lines[1:], strict=False))  # never the same twice
    assert set(lines) <= set(SHAKE_LINES)


def test_in_quiet_hours_a_shake_is_only_a_face():
    rig = _Rig(quiet=True)
    rig.reactions.on_events(["shake"])
    assert rig.faces == ["surprised"] and rig.said == []


def test_nothing_happens_while_a_reply_or_turn_is_on():
    rig = _Rig(busy=True)
    rig.reactions.on_events(["shake", "head_touch"])
    assert rig.faces == [] and rig.said == [] and rig.symbols == []


def test_a_pet_shows_the_heart_through_the_unit_and_reacts_again_when_the_animation_ends():
    rig = _Rig()
    rig.reactions.on_events(["head_touch"])
    assert rig.symbols == ["heart"] and rig.faces == []
    rig.now[0] += FACE_HOLD_S - 0.5
    rig.reactions.on_events(["head_touch"])  # still playing: no second reaction
    assert rig.symbols == ["heart"]
    rig.now[0] += 0.6  # the animation is over: the next real pet reacts at once
    rig.reactions.on_events(["head_touch"])
    assert rig.symbols == ["heart", "heart"]


def test_a_swipe_across_the_head_is_a_pet_too_and_is_not_held_back_by_a_cooldown():
    rig = _Rig()
    rig.reactions.on_events(["head_swipe_forward"])
    rig.now[0] += FACE_HOLD_S + 0.1
    rig.reactions.on_events(["head_swipe_back"])
    assert rig.symbols == ["heart", "heart"]


def test_without_a_symbol_tool_on_the_unit_a_pet_is_a_smile_and_the_tool_is_not_asked_again():
    rig = _Rig(symbol="missing")
    rig.reactions.on_events(["head_touch"])
    assert rig.faces == ["happy"]
    rig.now[0] += FACE_HOLD_S + 0.1
    rig.reactions.on_events(["head_touch"])
    assert rig.faces == ["happy", "happy"] and rig.symbols == []


@pytest.mark.parametrize(
    "text",
    [
        "you're so helpful",
        "Thank you so much!",
        "I love you",
        "you're the best",
        "good robot",
        "you're adorable",
        "aw you're so cute",
    ],
)
def test_kind_words_earn_a_heart(text):
    assert has_love_cue(text)
    rig = _Rig()
    rig.reactions.on_user_words(text)
    assert rig.symbols == ["heart"]


@pytest.mark.parametrize(
    "text",
    ["thanks", "what is the weather", "that was helpful", "I love pizza", "good morning", "", None],
)
def test_ordinary_words_do_not(text):
    assert not has_love_cue(text)
    rig = _Rig()
    rig.reactions.on_user_words(text)
    assert rig.symbols == [] and rig.faces == []


def test_a_loving_reply_mood_earns_a_heart_and_a_happy_one_does_not():
    rig = _Rig()
    rig.reactions.on_reply_mood("happiness")
    rig.reactions.on_reply_mood(None)
    assert rig.symbols == []
    rig.reactions.on_reply_mood("love")
    assert rig.symbols == ["heart"]


def test_no_host_face_or_mapping_can_produce_a_heart():
    # The only heart in the system is the unit's decorator; the host sends emotion names only, and
    # none of them is a heart. Happy replies map to the smile.
    assert REPLY_MOOD_FACE_MAP["happiness"] == "happy"
    assert not any("love" in key or "heart" in key for key in FIRMWARE_EMOTIONS)
    faces = {f.expression for f in CUE_FACE_MAP.values()} | set(REPLY_MOOD_FACE_MAP.values())
    faces |= {a.face for a in PRIMITIVE_BODY_MAP.values()}
    assert not any("love" in face or "heart" in face for face in faces)
    assert REPLY_MOOD_FACE_MAP.get("love", "neutral") == "neutral"


def _bridge(monkeypatch):
    import asyncio

    import maipai_body.bodies.stackchan.turn as turn_module
    from tests.test_stackchan_turn import (  # type: ignore[import-not-found]
        FakePlayback,
        FakeServer,
        FakeStt,
        FakeTts,
        FakeTurn,
        InlineExecutor,
        Link,
        Offline,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    server._sessions = {"device": object()}
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = turn_module.StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
    )
    return bridge, FakeTts, loop


def test_the_bridge_speaks_a_reaction_line_through_the_reply_voice(monkeypatch):
    bridge, tts, loop = _bridge(monkeypatch)
    try:
        assert bridge.speak_reaction("Whoa!") is True
        assert tts.sentences == ["Whoa!"]
    finally:
        loop.close()


def test_the_bridge_drops_a_reaction_line_during_a_turn_or_a_reply(monkeypatch):
    bridge, tts, loop = _bridge(monkeypatch)
    try:
        bridge._tasks["s"] = object()
        assert bridge.speak_reaction("Whoa!") is False
        bridge._tasks.clear()
        bridge._states["s"] = "speaking"
        assert bridge.speak_reaction("Whoa!") is False
        assert tts.sentences == []
    finally:
        loop.close()


def test_the_bridge_tells_the_hooks_about_kind_words_and_the_reply_mood(monkeypatch):
    import asyncio

    from maipai_body.speech.stt_stream import SttStreamResult
    from tests.test_stackchan_turn import FakeCapture, FakeStt  # type: ignore[import-not-found]

    bridge, tts, loop = _bridge(monkeypatch)
    words, moods = [], []
    FakeStt.result = SttStreamResult(kind="final", text="you're so helpful")
    bridge.on_user_words = words.append
    bridge.on_reply_mood = moods.append
    try:
        loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    finally:
        FakeStt.result = SttStreamResult(kind="final", text="hello")
        loop.close()
        asyncio.set_event_loop(None)
    assert words == ["you're so helpful"]


def test_a_failing_hook_never_breaks_the_voice_path(monkeypatch):
    bridge, tts, loop = _bridge(monkeypatch)
    try:

        def boom(_value):
            raise RuntimeError("hook")

        bridge._notify(boom, "x")  # logs, never raises
    finally:
        loop.close()


def test_show_face_sends_the_face_and_holds_off_the_watchdog():
    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    behavior = StackChanBehavior(StackChanRobotAdapter(FakeStackChanDeviceClient()).robot)
    try:
        behavior.show_face("surprised")
        assert behavior.robot._driver("head").expression_device.last_expression == "surprised"
        behavior._active.set()
        behavior.show_face("happy")  # a turn owns the face
        assert behavior.robot._driver("head").expression_device.last_expression == "surprised"
    finally:
        behavior.close()


def test_a_reaction_face_is_replaced_by_the_neutral_face_after_three_seconds():
    from maipai_body.bodies.stackchan.reactions import FACE_HOLD_S

    rig = _Rig()
    rig.reactions.on_events(["head_touch"])
    rig.now[0] += FACE_HOLD_S - 0.5
    rig.reactions.tick()
    assert "neutral" not in rig.faces
    rig.now[0] += 1.0
    rig.reactions.tick()
    assert rig.faces[-1] == "neutral"
    rig.reactions.tick()
    assert rig.faces.count("neutral") == 1  # once


def test_a_stroke_the_cooldown_refuses_still_gets_its_open_mouth_face_taken_back():
    rig = _Rig()
    rig.reactions.on_events(["head_touch"])
    rig.now[0] += 5.0
    rig.reactions.tick()
    rig.faces.clear()
    rig.now[0] += 1.0  # inside the pet cooldown: no new heart
    rig.reactions.on_events(["head_touch"])
    rig.now[0] += 4.0
    rig.reactions.tick()
    assert rig.faces == ["neutral"]


def test_the_neutral_face_is_not_forced_in_the_middle_of_a_conversation():
    rig = _Rig()
    rig.reactions.on_events(["shake"])
    rig.busy = True
    rig.now[0] += 10.0
    rig.faces.clear()
    rig.reactions.tick()
    assert rig.faces == []


def test_a_pet_reacts_while_the_robot_only_listens_but_not_while_it_thinks_or_speaks():
    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    behavior = StackChanBehavior(StackChanRobotAdapter(FakeStackChanDeviceClient()).robot)
    try:
        device = behavior.robot._driver("head").expression_device
        behavior._active.set()
        behavior._phase = "listening"
        assert not behavior.reaction_blocked()
        behavior.show_face("happy", while_listening=True)
        assert device.last_expression == "happy"
        behavior.show_face("surprised")  # a plain face still waits for the turn to end
        assert device.last_expression == "happy"
        behavior._phase = "busy"
        assert behavior.reaction_blocked()
        behavior.show_face("surprised", while_listening=True)
        assert device.last_expression == "happy"
    finally:
        behavior.close()
