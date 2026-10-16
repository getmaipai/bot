"""Voice evidence is per-turn, optional, and never derived from raw audio locally."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from stackchan_sim import FakeHubVoiceReply

from maipai_body.bodies.stackchan.turn import StackChanTurnBridge
from maipai_body.speech.stt_stream import SttStreamResult


class _Server:
    _loop = None

    async def send_audio(self, *_args, **_kwargs):
        pass

    async def stop_audio(self, *_args, **_kwargs):
        pass


class _Link:
    hub_client = SimpleNamespace(session_cookie="cookie", active_base_url="http://192.0.2.10")
    pairing_store = SimpleNamespace(load=lambda: SimpleNamespace(base_url="http://192.0.2.10"))


class _Offline:
    speaker = None


class _Capture:
    def feed_opus(self, _payload):
        raise ValueError("invalid Opus frame")

    def close(self):
        pass

    def abort(self):
        pass


class _Playback:
    def __init__(self, *_args, **_kwargs):
        pass

    def stop(self):
        pass

    def end(self):
        pass


class _Stt:
    response = None

    def __init__(self, *_args):
        pass

    def run(self, _capture):
        return self.response or SttStreamResult(kind="final", text="hello")


class _Turn:
    calls = []

    def __init__(self, *_args):
        pass

    def stream(self, text, *, speaker_evidence=None):
        self.calls.append((text, speaker_evidence))
        return iter([SimpleNamespace(reply_text="Hi.")])


class _Tts:
    def __init__(self, *_args):
        pass

    def speak(self, *_args, **_kwargs):
        pass


@pytest.fixture(autouse=True)
def _replace_playback(monkeypatch):
    import maipai_body.bodies.stackchan.turn as module

    monkeypatch.setattr(module, "StackChanAudioPlayback", _Playback)
    _Turn.calls = []
    _Stt.response = None


def _run(monkeypatch, attribution):
    loop = asyncio.new_event_loop()
    _Server._loop = loop
    bridge = StackChanTurnBridge(
        _Server(),
        _Link(),
        _Offline(),
        stt_factory=_Stt,
        turn_factory=_Turn,
        tts_factory=_Tts,
        person_attribution=attribution,
    )
    bridge._offline_line = lambda _playback: None
    bridge._speak_plain_error = lambda *_args: None
    loop.run_until_complete(bridge._run("session", "device", _Capture()))
    loop.close()
    return _Turn.calls


def test_confirmed_fake_hub_voice_match_attaches_per_turn_evidence(monkeypatch):
    result = SttStreamResult(kind="final", text="hello")
    result.speaker_evidence = FakeHubVoiceReply().speaker_evidence
    _Stt.response = result

    calls = _run(monkeypatch, lambda stt_result: stt_result.speaker_evidence)

    assert calls == [("hello", {"person": "person-7", "basis": "voice", "level": "confirmed"})]


@pytest.mark.parametrize(
    "match",
    [
        None,
        {"person_id": "person-7", "basis": "voice", "level": "tentative"},
        {"person_id": "person-7", "basis": "voice", "level": 0.2, "confidence": 0.2},
    ],
)
def test_absent_or_below_confidence_voice_result_sends_no_evidence(monkeypatch, match):
    _Stt.response = SttStreamResult(kind="final", text="hello")
    calls = _run(monkeypatch, lambda _result: match)
    assert calls == [("hello", None)]


def test_attribution_failure_keeps_turn_live_without_evidence(monkeypatch):
    _Stt.response = SttStreamResult(kind="final", text="hello")

    def broken(_result):
        raise RuntimeError("voice service unavailable")

    assert _run(monkeypatch, broken) == [("hello", None)]


def test_attribution_error_does_not_log_audio_bytes(monkeypatch, caplog):
    payload = b"private audio sentinel"
    _Stt.response = SttStreamResult(kind="final", text="hello")
    caplog.set_level(logging.WARNING)
    _run(monkeypatch, lambda _result: (_ for _ in ()).throw(ValueError("no match")))

    loop = asyncio.new_event_loop()
    bridge = StackChanTurnBridge(_Server(), _Link(), _Offline())
    bridge._captures["session"] = _Capture()
    loop.run_until_complete(bridge.on_audio("session", payload))
    loop.close()

    assert payload.decode() not in caplog.text
