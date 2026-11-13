"""The `listening` and `thinking` faces (owner, 2026-11-13: the face carries both, not the ring)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from maipai_body.app import FACE_QUIET_S, StackChanBehavior
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.avatar.server import EXPRESSIONS, control_avatar
from maipai_body.bodies.stackchan.expression_map import (
    CUE_FACE_MAP,
    FACES_MIN_FIRMWARE,
    face_for_firmware,
    version_at_least,
)
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.renderer import render_cue
from maipai_body.bodies.stackchan.xiaozhi.server import FIRMWARE_EMOTIONS

PACKAGE = Path(__file__).parents[1] / "maipai_body" / "bodies" / "stackchan"
NEW = ".".join(str(part) for part in FACES_MIN_FIRMWARE)
OLD = "0.2.61"


class _Sink:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def send_avatar_frame(self, frame: bytes) -> None:
        self.frames.append(frame)


def test_the_cue_table_names_the_two_new_faces_and_the_firmware_knows_them():
    assert CUE_FACE_MAP["listening"].expression == "listening"
    assert CUE_FACE_MAP["listening"].mouth is False  # mouth closed
    assert CUE_FACE_MAP["thinking"].expression == "thinking"
    faces = set(json.loads((PACKAGE / "face_set.json").read_text())["faces"])
    assert {"listening", "thinking"} <= faces
    assert {"listening", "thinking"} <= set(EXPRESSIONS)
    assert FIRMWARE_EMOTIONS["listening"] == "listening"
    assert FIRMWARE_EMOTIONS["thinking"] == "thinking"


def test_the_new_faces_encode_as_ordinary_avatar_frames():
    for name in ("listening", "thinking"):
        frame = control_avatar(name, mouth=False)
        assert frame.expression == name
        assert len(frame) > 5


def test_a_unit_without_the_new_faces_is_sent_neutral():
    assert face_for_firmware("listening", NEW) == "listening"
    assert face_for_firmware("thinking", "0.3.0") == "thinking"
    for old in (OLD, None, "", "garbage", "0.2"):
        assert face_for_firmware("listening", old) == "neutral"
        assert face_for_firmware("thinking", old) == "neutral"
    # Faces the unit always had are never changed.
    assert face_for_firmware("happy", OLD) == "happy"
    assert version_at_least("0.2.66", (0, 2, 66)) and not version_at_least("0.2.65", (0, 2, 66))


@pytest.mark.parametrize(
    ("cue", "version", "shown"),
    [
        ("listening", NEW, "listening"),
        ("thinking", NEW, "thinking"),
        ("listening", OLD, "neutral"),
        ("thinking", None, "neutral"),
        ("speaking", NEW, "neutral"),  # the firmware animates the mouth: the face stays neutral
    ],
)
def test_render_cue_sends_the_face_for_the_units_firmware(cue, version, shown):
    sink = _Sink()
    render_cue(cue, sink, firmware_version=version)
    assert sink.frames[-1].expression == shown


def _behavior(version):
    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    behavior.unit_facts = SimpleNamespace(snapshot=lambda: {"fw_version": version})
    return behavior, behavior.robot._driver("head").expression_device


def test_a_turn_shows_listening_then_thinking_then_the_mood_then_neutral():
    behavior, head = _behavior(NEW)
    try:
        shown = []
        for state, mood in (
            ("listening", None),
            ("thinking", None),
            ("speaking", None),
            ("reply_mood", "happiness"),
            ("settle", None),
        ):
            behavior.render_turn_state(state, mood=mood)
            shown.append(head.last_expression)
        # Speaking draws neutral (the firmware moves the mouth); the reply mood then sets its
        # own face, and settling the head after the turn puts the idle face back.
        assert shown == ["listening", "thinking", "neutral", "happy", "neutral"]
    finally:
        behavior.close()


def test_a_turn_that_never_gets_a_reply_does_not_leave_the_listening_face_up():
    behavior, head = _behavior(NEW)
    try:
        behavior.render_turn_state("listening")
        assert head.last_expression == "listening"
        behavior.render_turn_state("settle")  # the turn closes with no reply
        start = 2000.0
        behavior.face_watchdog(start)
        assert behavior.face_watchdog(start + FACE_QUIET_S + 1) is True
        assert head.last_expression == "neutral"
    finally:
        behavior.close()


def test_an_older_unit_keeps_neutral_for_the_whole_turn():
    behavior, head = _behavior(OLD)
    try:
        for state in ("listening", "thinking"):
            behavior.render_turn_state(state)
            assert head.last_expression == "neutral"
    finally:
        behavior.close()


def test_the_head_moves_that_go_with_the_new_faces_do_not_paint_over_them():
    """perk (listening) and attend (thinking) lift and tilt the head; the face is the cue's."""
    import inspect

    from maipai_body.bodies.stackchan.expression_map import PRIMITIVE_BODY_MAP

    source = inspect.getsource(StackChanBehavior.render_turn_state)
    assert '"listening": "perk"' in source and '"thinking": "attend"' in source
    for move in ("perk", "attend", "speak"):
        assert PRIMITIVE_BODY_MAP[move].face is None, move
    sink = _Sink()
    from maipai_body.bodies.stackchan.profile import STACKCHAN_PROFILE
    from maipai_body.bodies.stackchan.renderer import render

    class _Head(_Sink):
        def command(self, name, **kwargs):
            pass

    head = _Head()
    render("attend", head, STACKCHAN_PROFILE)
    assert head.frames == []  # no face frame from the move itself
    render("settle", head, STACKCHAN_PROFILE)
    assert head.frames[-1].expression == "neutral"  # settle still restores the idle face
    del sink
