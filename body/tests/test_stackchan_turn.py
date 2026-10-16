"""StackChan voice-turn regressions, with the independent simulator peer."""

import asyncio
from types import SimpleNamespace

import pytest
from stackchan_sim import StackChanFirmware

from maipai_body.bodies.stackchan.turn import StackChanTurnBridge, _sentences
from maipai_body.speech.stt_stream import SttStreamResult


class FakeServer:
    def __init__(self):
        self._loop = None
        self.sent = []
        self.stops = []

    async def send_audio(self, device_id, frames, *, sentence_start=False):
        self.sent.append((device_id, frames, sentence_start))

    async def stop_audio(self, device_id):
        self.stops.append(device_id)


class Link:
    def __init__(self, base="http://192.0.2.10", cookie="cookie"):
        self.hub_client = SimpleNamespace(session_cookie=cookie, active_base_url=base)
        self.pairing_store = SimpleNamespace(load=lambda: SimpleNamespace(base_url=base))


class Offline:
    speaker = None


class FakeCapture:
    def close(self):
        pass

    def abort(self):
        pass


class FakePlayback:
    def __init__(self, server, device):
        self.server = server
        self.device = device
        self.flushed = False

    def stop(self):
        pass

    def end(self):
        pass

    def flush(self):
        self.flushed = True
        asyncio.run_coroutine_threadsafe(self.server.stop_audio(self.device), self.server._loop)


class FakeStt:
    result = SttStreamResult(kind="final", text="hello")
    urls = []

    def __init__(self, base, cookie):
        self.urls.append((base, cookie))

    def run(self, capture):
        return self.result


class FakeTurn:
    urls = []
    streams = []

    def __init__(self, base, cookie):
        self.urls.append((base, cookie))

    def stream(self, text, **kwargs):
        self.streams.append((text, kwargs))
        return iter([SimpleNamespace(reply_text="Hello there. How are you?")])


class FakeTts:
    sentences = []

    def __init__(self, base, cookie, playback):
        self.playback = playback

    def speak(self, text, *, stop_event=None):
        self.sentences.append(text)


def test_happy_path_streams_reply_sentences_only_to_live_hub(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeStt.urls = []
    FakeTurn.urls = []
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(
        server, Link(), Offline(), stt_factory=FakeStt, turn_factory=FakeTurn, tts_factory=FakeTts
    )
    bridge._offline_line = lambda playback: pytest.fail("offline line must not run")
    loop.run_until_complete(bridge._run("session", "02:00:00:00:00:15", FakeCapture()))
    loop.close()
    assert FakeTts.sentences == ["Hello there.", "How are you?"]
    assert FakeStt.urls == [("http://192.0.2.10", "cookie")]
    assert FakeTurn.urls == [("http://192.0.2.10", "cookie")]
    assert FakeTurn.streams == [("hello", {"speaker_evidence": None})]


def test_person_attribution_is_passed_as_turn_speaker_evidence(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        person_attribution=lambda: {"person_id": "person-abc123", "confidence": 0.87},
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert FakeTurn.streams == [
        (
            "hello",
            {
                "speaker_evidence": {
                    "person": "person-abc123",
                    "basis": "voice",
                    "level": "confirmed",
                }
            },
        )
    ]


def test_turn_states_and_mood_are_emitted_and_sink_failure_is_isolated(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    states = []

    def sink(state, *, mood=None):
        states.append((state, mood))
        if state == "speaking":
            raise RuntimeError("renderer unavailable")

    class MoodTurn(FakeTurn):
        def stream(self, text, **kwargs):
            return iter(
                [
                    SimpleNamespace(
                        cue=SimpleNamespace(expressed_emotion="happiness"), reply_text=None
                    ),
                    SimpleNamespace(cue=None, reply_text="Hello there."),
                ]
            )

    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=MoodTurn,
        tts_factory=FakeTts,
        expression_sink=sink,
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert states == [
        ("listening", None),
        ("thinking", None),
        ("reply_mood", "happiness"),
        ("speaking", None),
        ("settle", None),
    ]


def test_abort_emits_settle_state():
    states = []
    bridge = StackChanTurnBridge(
        FakeServer(), Link(), Offline(), expression_sink=lambda state, **kw: states.append(state)
    )
    bridge.abort("session")
    assert states == ["settle"]


def test_stt_failure_speaks_plain_words_and_keeps_session_usable(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)

    class FailedStt(FakeStt):
        def run(self, capture):
            return SttStreamResult(kind="error", error="recognition failed")

    FakeTts.sentences = []
    bridge = StackChanTurnBridge(
        server, Link(), Offline(), stt_factory=FailedStt, tts_factory=FakeTts
    )
    loop.run_until_complete(bridge._run("session", "02:00:00:00:00:15", FakeCapture()))
    assert FakeTts.sentences == ["I couldn't understand that. Please try again."]
    loop.run_until_complete(bridge._run("session2", "02:00:00:00:00:15", FakeCapture()))
    loop.close()
    assert len(FakeTts.sentences) == 2


def test_abort_clears_audio_and_simulator_fixture_is_available():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    bridge = StackChanTurnBridge(server, Link(), Offline())
    playback = FakePlayback(server, "02:00:00:00:00:15")
    bridge._playbacks["s"] = playback
    bridge._captures["s"] = FakeCapture()
    bridge.abort("s")
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()
    assert playback.flushed
    assert server.stops == ["02:00:00:00:00:15"]
    assert StackChanFirmware is not None


def test_unreachable_hub_uses_offline_spoken_line(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)

    class UnpairedLink(Link):
        def __init__(self):
            super().__init__(cookie=None)

    bridge = StackChanTurnBridge(server, UnpairedLink(), Offline())
    spoken = []
    bridge._offline_line = lambda playback: spoken.append("hub unavailable")
    loop.run_until_complete(bridge._run("session", "02:00:00:00:00:15", FakeCapture()))
    loop.close()
    assert spoken == ["hub unavailable"]


def test_reply_sentence_split_and_configured_hub_is_documentation_address():
    assert _sentences("A reply! Next sentence.") == ["A reply!", "Next sentence."]
    assert Link().hub_client.active_base_url == "http://192.0.2.10"


def test_opus_uplink_decodes_to_steady_float32_blocks():
    import av
    import numpy as np

    from maipai_body.bodies.stackchan.turn import StackChanAudioCapture

    encoder = av.CodecContext.create("opus", "w")
    encoder.sample_rate = 16000
    encoder.layout = "mono"
    encoder.format = "s16"
    encoder.open()
    frame = av.AudioFrame.from_ndarray(
        np.zeros((1, 960), dtype=np.int16), format="s16", layout="mono"
    )
    frame.sample_rate = 16000
    capture = StackChanAudioCapture()
    for packet in encoder.encode(frame):
        capture.feed_opus(bytes(packet))
    blocks = capture.poll_blocks()
    assert blocks
    assert all(block.shape == (512,) and block.dtype == np.float32 for block in blocks)


def test_a_malformed_person_id_is_dropped_not_sent(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        person_attribution=lambda: {"person": "person-7", "level": "confirmed"},
    )
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert FakeTurn.streams == [("hello", {"speaker_evidence": None})]
