"""BARGE-02: the speech request carries the turn and generation; a cut reply is refused."""

from __future__ import annotations

import json

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient
from tests.test_tts_playback import _make_wav_bytes


class Response:
    def __init__(self, status: int, body: bytes = b"", json_body: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self._json = json_body
        self.text = body.decode("latin-1")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self._body), 1024):
            yield self._body[i : i + 1024]

    def iter_lines(self, decode_unicode=False):
        yield from self._body.decode().splitlines()


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.sent: list[dict] = []

    def post(self, url, json=None, **kw):
        self.sent.append(json)
        return self.response


def test_the_request_names_the_turn_and_generation() -> None:
    playback = AudioPlayback(FakeReachyMiniClient())
    session = Session(Response(200, _make_wav_bytes(0.5)))
    client = TtsPlaybackClient("http://hub.example.com", "c", playback, session=session)
    client.speak("hello", turn_id="turn-1", generation=3)
    assert session.sent == [{"text": "hello", "turn_id": "turn-1", "generation": 3}]
    plain = Session(Response(200, _make_wav_bytes(0.5)))
    TtsPlaybackClient("http://hub.example.com", "c", playback, session=plain).speak("hi")
    assert plain.sent == [{"text": "hi"}]


def test_a_stale_reply_409_is_a_cancel_and_plays_nothing() -> None:
    fake = FakeReachyMiniClient()
    playback = AudioPlayback(fake)
    stale = Response(409, b"{}", {"code": "turn_cancelled"})
    client = TtsPlaybackClient("http://hub.example.com", "c", playback, session=Session(stale))
    result = client.speak("hello", turn_id="turn-1", generation=1)
    assert result.kind == "cancelled" and fake.pushed_audio == []


def test_a_chunk_from_before_a_flush_never_reaches_the_device() -> None:
    fake = FakeReachyMiniClient()
    playback = AudioPlayback(fake)
    wav = _make_wav_bytes(1.0)

    class FlushingSession(Session):
        def post(self, url, json=None, **kw):
            playback.flush()  # a barge-in lands between the request and the first chunk
            return super().post(url, json=json, **kw)

    client = TtsPlaybackClient(
        "http://hub.example.com", "c", playback, session=FlushingSession(Response(200, wav))
    )
    # the generation is read before the request, so the cut makes every chunk stale
    result = client.speak("hello")
    assert result.kind == "cancelled"
    assert fake.pushed_audio == []


def test_the_turn_client_hands_the_hub_generation_to_the_done_event() -> None:
    lines = [
        {"type": "turn_meta", "conversation_id": "c1", "turn_id": "t1"},
        {"type": "delta", "text": "Hi", "generation": 4},
        {"type": "done", "value": {}},
    ]
    body = "\n".join(json.dumps(x) for x in lines).encode()
    client = TurnClient("http://hub.example.com", "c", session=Session(Response(200, body)))
    events = list(client.stream("hello"))
    assert events[-1].reply_text == "Hi" and events[-1].generation == 4
