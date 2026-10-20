"""Spoken volume control and the in-order face reset (owner request 2026-10-20)."""

from __future__ import annotations

import asyncio
import json

import pytest

from maipai_body.bodies.stackchan.volume import (
    STEP,
    VolumeCommand,
    VolumeControl,
    confirmation,
    next_level,
    parse_volume_command,
)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Turn it up", "up"),
        ("can you be a bit louder please", "up"),
        ("volume up", "up"),
        ("I can't hear you", "up"),
        ("quieter", "down"),
        ("Turn the volume down.", "down"),
        ("that is too loud", "down"),
        ("set the volume to 40 percent", "set"),
        ("volume to 80", "set"),
        ("maximum volume", "max"),
        ("mute", "mute"),
    ],
)
def test_volume_phrases_are_recognised(text, kind):
    command = parse_volume_command(text)
    assert command is not None and command.kind == kind


@pytest.mark.parametrize(
    "text",
    ["what is the weather", "turn on the living room light", "tell me about volume knobs", ""],
)
def test_other_speech_goes_to_the_hub(text):
    assert parse_volume_command(text) is None


def test_set_extracts_the_level_and_clamps_it():
    assert parse_volume_command("volume to 55").level == 55
    assert parse_volume_command("volume to 250").level == 100


def test_levels_step_and_clamp_and_mute_is_zero():
    assert next_level(60, VolumeCommand("up")) == 60 + STEP
    assert next_level(95, VolumeCommand("up")) == 100
    assert next_level(25, VolumeCommand("down")) == 20  # never inaudible by accident
    assert next_level(60, VolumeCommand("set", 30)) == 30
    assert next_level(60, VolumeCommand("set", 5)) == 20
    assert next_level(60, VolumeCommand("mute")) == 0
    assert next_level(60, VolumeCommand("max")) == 100


def test_the_confirmation_is_one_short_plain_line():
    assert confirmation(VolumeCommand("up"), 60, 75) == "Volume 75."
    assert confirmation(VolumeCommand("up"), 100, 100) == "That is as loud as I go."
    assert confirmation(VolumeCommand("down"), 20, 20) == "That is as quiet as I go."
    assert confirmation(VolumeCommand("mute"), 60, 0) == ""


def test_the_control_reads_the_device_level_then_sets_the_new_one():
    calls: list[tuple[str, dict]] = []
    set_to: list[int] = []

    def call(name, arguments):
        calls.append((name, arguments))
        return json.dumps({"audio_speaker": {"volume": 40}})

    control = VolumeControl(call, set_to.append)
    assert control.apply(VolumeCommand("up")) == (40, 40 + STEP)
    assert set_to == [40 + STEP]
    assert calls[0][0] == "self.get_device_status"


def test_when_the_device_cannot_say_its_level_the_last_known_one_is_used():
    set_to: list[int] = []

    def call(name, arguments):
        raise RuntimeError("no answer")

    control = VolumeControl(call, set_to.append)
    before, after = control.apply(VolumeCommand("down"))
    assert after < before
    assert control.apply(VolumeCommand("down"))[0] == after  # remembers what it set


def test_the_bridge_answers_a_volume_command_without_asking_the_hub(monkeypatch):
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

    class LoudStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, **kwargs):
            return SttStreamResult(kind="final", text="Please turn it up")

    set_to: list[int] = []
    control = VolumeControl(lambda name, args: {"audio_speaker": {"volume": 50}}, set_to.append)
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
        stt_factory=LoudStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        volume_control=control,
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert set_to == [50 + STEP]
    assert FakeTurn.streams == []  # the hub was never asked
    assert FakeTts.sentences == [f"Volume {50 + STEP}."]


def test_the_face_is_reset_in_order_before_every_tts_stop():
    from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiServer

    sent: list[dict] = []

    class _Socket:
        async def send(self, data):
            sent.append(json.loads(data) if isinstance(data, str) else {"binary": len(data)})

    async def scenario() -> None:
        server = XiaozhiServer(PairingStore(), robot=None)
        server._sessions["d"] = _Socket()
        server._session_ids["d"] = "sid"
        server._session_authorized = lambda device_id: True  # type: ignore[method-assign]
        await server.stop_audio("d")
        await server.send_idle("d")

    asyncio.run(scenario())
    kinds = [(m.get("type"), m.get("emotion") or m.get("state") or m.get("command")) for m in sent]
    assert kinds == [("llm", "neutral"), ("tts", "stop"), ("system", "idle")]
