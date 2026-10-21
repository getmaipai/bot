"""StackChan voice-turn regressions, with the independent simulator peer."""

import asyncio
from types import SimpleNamespace

import pytest
from stackchan_sim import StackChanFirmware

from maipai_body.bodies.stackchan.turn import StackChanTurnBridge, _sentences
from maipai_body.speech.stt_stream import SttStreamResult


class InlineExecutor:
    """Runs side effects at once so a test can assert them right after the call."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, **kwargs):
        pass


class FakeServer:
    def __init__(self):
        self._loop = None
        self.sent = []
        self.stops = []
        self.idles = []

    async def send_audio(self, device_id, frames, *, sentence_start=False):
        self.sent.append((device_id, frames, sentence_start))

    async def stop_audio(self, device_id):
        self.stops.append(device_id)

    async def send_idle(self, device_id):
        self.idles.append(device_id)


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
        side_executor=InlineExecutor(),
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
        FakeServer(),
        Link(),
        Offline(),
        side_executor=InlineExecutor(),
        expression_sink=lambda state, **kw: states.append(state),
    )
    bridge.abort("session")
    assert states == ["settle"]


def test_a_hub_failure_after_real_speech_apologises_once_and_never_twice_in_a_row(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)

    class FailedStt(FakeStt):
        def run(self, capture):
            return SttStreamResult(kind="error", error="recognition failed", speech_s=1.2)

    FakeTts.sentences = []
    bridge = StackChanTurnBridge(
        server, Link(), Offline(), stt_factory=FailedStt, tts_factory=FakeTts
    )
    loop.run_until_complete(bridge._run("session", "02:00:00:00:00:15", FakeCapture()))
    assert FakeTts.sentences == ["I couldn't understand that. Please try again."]
    loop.run_until_complete(bridge._run("session2", "02:00:00:00:00:15", FakeCapture()))
    loop.close()
    assert len(FakeTts.sentences) == 1  # the apology is never spoken twice in a row


def test_silence_ends_the_turn_quietly_and_sends_the_device_to_idle(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    for kind, text in (("timeout", None), ("final", "   "), ("error", None)):

        class QuietStt(FakeStt):
            result = SttStreamResult(kind=kind, text=text)

            def run(self, capture, **kwargs):
                return self.result

        FakeTts.sentences = []
        server.idles = []
        bridge = StackChanTurnBridge(
            server, Link(), Offline(), stt_factory=QuietStt, tts_factory=FakeTts
        )
        loop.run_until_complete(bridge._run("session", "02:00:00:00:00:15", FakeCapture()))
        assert FakeTts.sentences == [], kind  # nothing is spoken
        assert server.idles == ["02:00:00:00:00:15"], kind  # the device goes back to idle
    loop.close()


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


def test_the_voice_session_logs_each_stage_with_counts_and_never_the_words(monkeypatch, caplog):
    import logging

    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(
        server, Link(), Offline(), stt_factory=FakeStt, turn_factory=FakeTurn, tts_factory=FakeTts
    )
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.turn"):
        loop.run_until_complete(bridge.listen("session-0123456789", "device", "start"))
        loop.run_until_complete(bridge.on_audio("session-0123456789", b"\x01\x02\x03"))
        loop.run_until_complete(bridge._tasks["session-0123456789"])
        loop.close()
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "listen start" in text
    assert "first audio frame (3 bytes)" in text
    assert "turn started" in text
    assert "speech-to-text ended (final, 5 characters)" in text
    assert "chat ended" in text
    assert "turn ended" in text and "1 audio frames, 3 bytes" in text
    assert "hello" not in text.replace("hello there", "")  # the transcript is never logged


def test_a_missing_hub_session_is_logged_as_a_warning_with_the_fix(monkeypatch, caplog):
    import logging

    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(server, Link(cookie=None), Offline())
    bridge._offline_line = lambda playback: None
    with caplog.at_level(logging.WARNING, logger="maipai_body.bodies.stackchan.turn"):
        loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
        loop.close()
    assert any("no hub session (cookie missing" in record.getMessage() for record in caplog.records)


def test_the_bridge_counts_uplink_frames_and_wake_detects_without_keeping_audio(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module
    from maipai_body.bodies.stackchan.uplink_stats import UplinkStats

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    stats = UplinkStats(sleep=lambda seconds: None)
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        uplink_stats=stats,
    )
    loop.run_until_complete(bridge.listen("session-abcdef012345", "device", "detect"))
    loop.run_until_complete(bridge.on_audio("session-abcdef012345", b"\x01\x02\x03\x04"))
    loop.run_until_complete(bridge.on_audio("session-abcdef012345", b"\x05\x06"))
    loop.run_until_complete(bridge._tasks["session-abcdef012345"])
    loop.close()
    assert stats.total_frames == 2
    assert stats.total_bytes == 6
    assert stats.total_detects == 1


def test_a_slow_face_or_light_never_holds_up_the_voice_turn():
    import threading
    import time

    release = threading.Event()
    ran: list[str] = []

    def slow_sink(state, **kwargs):
        release.wait(2.0)
        ran.append(state)

    bridge = StackChanTurnBridge(
        FakeServer(),
        Link(),
        Offline(),
        expression_sink=slow_sink,
        live_sink=lambda active: release.wait(2.0),
    )
    started = time.monotonic()
    bridge._emit_expression("listening")
    bridge._set_live(True)
    bridge._emit_expression("thinking")
    assert time.monotonic() - started < 0.2  # nothing waited for the slow device
    release.set()
    bridge.close()
    deadline = time.monotonic() + 2.0
    while len(ran) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ran[:1] == ["listening"]  # the first update still ran, in order


def test_playback_stop_never_runs_on_the_event_loop_thread(monkeypatch, caplog):
    """stop() waits on a coroutine of the very loop that called it; inline it deadlocks for 30 s."""
    import logging
    import threading

    import maipai_body.bodies.stackchan.turn as turn_module

    stop_threads: list[int] = []

    class ThreadRecordingPlayback(FakePlayback):
        def stop(self):
            stop_threads.append(threading.get_ident())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", ThreadRecordingPlayback)
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
    )
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.turn"):
        loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert stop_threads and threading.get_ident() not in stop_threads
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "text-to-speech sentence 1 started" in text
    assert "synthesized in" in text and "reply finished playing" in text


def test_the_first_audio_of_an_utterance_is_kept_when_no_reply_was_playing(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    now = [100.0]
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        clock=lambda: now[0],
    )
    loop.run_until_complete(bridge.listen("session-first-audio", "device", "start"))
    assert "session-first-audio" not in bridge._speech_ended  # nothing was playing: no echo tail
    now[0] += 0.31  # past the pop-up hold
    loop.run_until_complete(bridge.on_audio("session-first-audio", b"\x01\x02"))
    assert bridge._uplink_dropped == 0 and bridge._popup_dropped == 0
    loop.run_until_complete(bridge._tasks["session-first-audio"])
    loop.close()


def test_a_real_playback_still_leaves_an_echo_tail_to_ignore(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    bridge = StackChanTurnBridge(
        server, Link(), Offline(), stt_factory=FakeStt, side_executor=InlineExecutor()
    )
    bridge._playbacks["session-echo"] = FakePlayback(server, "device")
    bridge._cancel_turn("session-echo", send_stop=False)
    assert "session-echo" in bridge._speech_ended
    loop.close()


def test_uplink_right_after_the_listening_tone_is_held_back_from_recognition(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    now = [10.0]
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        clock=lambda: now[0],
    )
    loop.run_until_complete(bridge.listen("session-tone", "device", "detect"))
    now[0] += 0.1
    loop.run_until_complete(bridge.on_audio("session-tone", b"\x01\x02"))  # the tone
    now[0] += 0.3
    loop.run_until_complete(bridge.on_audio("session-tone", b"\x03\x04"))  # the person
    assert bridge._popup_dropped == 1
    loop.run_until_complete(bridge._tasks["session-tone"])
    loop.close()


class _SequencedStt:
    """Answers each stream with the next result; records the patience each was given."""

    results: list = []
    patiences: list = []
    hook = None

    def __init__(self, base, cookie):
        pass

    def run(self, capture, *, patience_s=None):
        type(self).patiences.append(patience_s)
        if type(self).hook is not None:
            type(self).hook()
        return type(self).results.pop(0)


def _bridge_for_no_speech(monkeypatch, results, *, closed=False, clock=None):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    _SequencedStt.results = list(results)
    _SequencedStt.patiences = []
    _SequencedStt.hook = None
    FakeTurn.streams = []
    FakeTts.sentences = []
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=_SequencedStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        clock=clock or (lambda: 0.0),
    )
    capture = FakeCapture()
    capture.closed = closed
    errors: list[str] = []
    bridge._speak_plain_error = lambda playback, base, cookie: errors.append("error line")
    return loop, bridge, capture, errors


def test_early_no_speech_keeps_listening_and_then_answers(monkeypatch):
    results = [SttStreamResult(kind="no_speech"), SttStreamResult(kind="final", text="hello")]
    loop, bridge, capture, errors = _bridge_for_no_speech(monkeypatch, results)
    loop.run_until_complete(bridge._run("session", "device", capture))
    loop.close()
    assert errors == []
    assert FakeTurn.streams and FakeTurn.streams[0][0] == "hello"
    assert _SequencedStt.patiences[0] is None and _SequencedStt.patiences[1] >= 0.5


def test_no_speech_after_the_patience_is_over_ends_the_turn_quietly(monkeypatch):
    now = [0.0]
    results = [SttStreamResult(kind="no_speech")]
    loop, bridge, capture, errors = _bridge_for_no_speech(
        monkeypatch, results, clock=lambda: now[0]
    )
    _SequencedStt.hook = lambda: now.__setitem__(0, 6.0)  # the patience runs out while listening
    loop.run_until_complete(bridge._run("session", "device", capture))
    loop.close()
    assert errors == [] and len(_SequencedStt.patiences) == 1  # silence is not an error


def test_no_speech_once_the_device_has_stopped_listening_is_not_retried_and_stays_quiet(
    monkeypatch,
):
    results = [SttStreamResult(kind="no_speech")]
    loop, bridge, capture, errors = _bridge_for_no_speech(monkeypatch, results, closed=True)
    loop.run_until_complete(bridge._run("session", "device", capture))
    loop.close()
    assert errors == [] and len(_SequencedStt.patiences) == 1


def test_a_listen_the_device_reopens_after_a_reply_gets_the_follow_up_window(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    now = [100.0]
    patiences: list[object] = []

    class SilentStt(FakeStt):
        def run(self, capture, *, patience_s=None):
            patiences.append(patience_s)
            return SttStreamResult(kind="timeout")

    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=SilentStt,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        clock=lambda: now[0],
    )
    bridge.follow_up_s = 8.0
    # A wake word opens a normal listen, which gets the default patience.
    loop.run_until_complete(bridge.listen("s", "device", "detect"))
    loop.run_until_complete(asyncio.sleep(0.2))  # let the turn run to its end
    # The device re-opens listening 0.2 s after the turn ended: a follow-up.
    now[0] += 0.2
    loop.run_until_complete(bridge.listen("s", "device", "start"))
    loop.run_until_complete(asyncio.sleep(0.2))  # let the turn run to its end
    # Much later a tap opens a fresh normal listen.
    now[0] += 60.0
    loop.run_until_complete(bridge.listen("s", "device", "start"))
    loop.run_until_complete(asyncio.sleep(0.2))  # let the turn run to its end
    loop.close()
    assert patiences == [None, 8.0, None]
    assert server.idles == ["device", "device", "device"]  # every silent end goes idle


def test_an_abnormal_end_while_speaking_sends_a_tts_stop_so_the_mouth_closes(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)

    class ExplodingTts(FakeTts):
        def speak(self, sentence, **kwargs):
            raise RuntimeError("synthesis broke mid-sentence")

    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=FakeStt,
        turn_factory=FakeTurn,
        tts_factory=ExplodingTts,
        side_executor=InlineExecutor(),
    )
    bridge._speak_plain_error = lambda playback, base, cookie: None
    loop.run_until_complete(bridge._run("session", "device", FakeCapture()))
    loop.close()
    assert server.stops == ["device"]


def test_a_follow_up_listen_holds_nothing_back_because_no_tone_plays(monkeypatch):
    import maipai_body.bodies.stackchan.turn as turn_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = FakeServer()
    server._loop = loop
    monkeypatch.setattr(turn_module, "StackChanAudioPlayback", FakePlayback)
    now = [10.0]
    import threading

    release = threading.Event()

    class WaitingStt(FakeStt):
        def run(self, capture, patience_s=None):
            release.wait(5)
            return self.result

    bridge = StackChanTurnBridge(
        server,
        Link(),
        Offline(),
        stt_factory=WaitingStt,
        turn_factory=FakeTurn,
        tts_factory=FakeTts,
        side_executor=InlineExecutor(),
        clock=lambda: now[0],
    )
    bridge._last_turn_end["session-follow"] = now[0] - 0.5  # a reply just ended
    loop.run_until_complete(bridge.listen("session-follow", "device", "start"))
    assert bridge._followup["session-follow"] is True
    now[0] += 0.05
    loop.run_until_complete(bridge.on_audio("session-follow", b"\x01\x02"))  # "yes"
    assert bridge._popup_dropped == 0
    assert bridge._captures["session-follow"] is not None  # the audio was not held back
    release.set()
    loop.run_until_complete(bridge._tasks["session-follow"])
    loop.close()


def test_a_dropped_stt_socket_reconnects_instead_of_ending_the_turn():
    from maipai_body.speech.stt_stream import SttStreamError

    calls = []

    class FlakyStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, patience_s=None):
            calls.append(patience_s)
            if len(calls) == 1:
                raise SttStreamError("hub stt connection failed: reset")
            return SttStreamResult(kind="final", text="hello")

    bridge = StackChanTurnBridge(
        FakeServer(), Link(), Offline(), stt_factory=FlakyStt, side_executor=InlineExecutor()
    )
    bridge._current_session = "s"
    capture = SimpleNamespace(closed=False)
    result = asyncio.run(bridge._recognise("b", "c", capture, bridge._clock()))
    assert result.kind == "final" and len(calls) == 2


def test_a_dropped_stt_socket_near_the_deadline_still_raises():
    from maipai_body.speech.stt_stream import SttStreamError

    class DeadStt:
        def __init__(self, base, cookie):
            pass

        def run(self, capture, patience_s=None):
            raise SttStreamError("down")

    bridge = StackChanTurnBridge(
        FakeServer(), Link(), Offline(), stt_factory=DeadStt, side_executor=InlineExecutor()
    )
    bridge._current_session = "s"
    with pytest.raises(SttStreamError):
        asyncio.run(
            bridge._recognise("b", "c", SimpleNamespace(closed=False), bridge._clock() - 10.0)
        )
