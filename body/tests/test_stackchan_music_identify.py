from __future__ import annotations

import base64
import json
import logging

import pytest

from maipai_body.bodies.stackchan.dance import DanceSituation
from maipai_body.bodies.stackchan.music_identify import MULAW, MusicIdentify, MusicIdentifyHooks


class Fixture:
    def __init__(self, **situation):
        self.sit = DanceSituation(**situation)
        self.setting = "on"
        self.calls = []
        self.result = {"status": "matched", "title": "Song", "artist": "Artist"}
        self.read_answers = []

    def build(self):
        def call(name, args):
            self.calls.append((name, args))
            if name == "self.music.capture_clip":
                return True
            if name == "self.music.read_clip":
                return self.read_answers.pop(0)
            return None

        return MusicIdentify(
            MusicIdentifyHooks(
                call,
                self.post,
                lambda: self.sit,
                lambda: self.setting,
                spawn=lambda worker: worker(),
            )
        )

    def post(self, pcm):
        if isinstance(self.result, Exception):
            raise self.result
        self.calls.append(("post", pcm))
        return self.result


def answer(data: bytes, eof: bool = False, *, count: int | None = None) -> str:
    return json.dumps(
        {
            "data": base64.b64encode(data).decode(),
            "bytes": len(data) if count is None else count,
            "eof": eof,
        }
    )


def ready(size: int) -> dict:
    return {"bytes": size, "rate": 8000, "codec": "mulaw"}


def start_and_ready(f: Fixture, identify: MusicIdentify, size: int) -> None:
    identify.on_session_start(0)
    identify.on_clip_event("music_clip_ready", ready(size), 1)


def test_mulaw_known_values():
    assert MULAW[0xFF] == 0
    assert MULAW[0x00] == -32124
    assert MULAW[0x80] == 32124


def test_full_pull_in_chunks_posts_decoded_pcm_and_sets_then_clears_title():
    f = Fixture()
    f.read_answers = [answer(b"\xff"), answer(b"\x00\x80", True)]
    identify = f.build()
    start_and_ready(f, identify, 3)
    assert next(value for name, value in f.calls if name == "post") == b"\x00\x00\x84\x82|}"
    assert [args for name, args in f.calls if name == "self.music.read_clip"] == [
        {"offset": 0, "length": 2400},
        {"offset": 1, "length": 2400},
    ]
    assert f.calls[-3] == ("self.music.drop_clip", {})
    assert f.calls[-1] == ("self.face.song_title", {"text": "Song - Artist"})
    identify.on_session_end()
    assert f.calls[-1] == ("self.face.song_title", {"text": ""})


def test_eof_before_advertised_size_posts_received_bytes():
    f = Fixture()
    f.read_answers = [answer(b"\xff", True)]
    identify = f.build()
    start_and_ready(f, identify, 4)
    assert next(value for name, value in f.calls if name == "post") == b"\x00\x00"


@pytest.mark.parametrize(
    "responses",
    [
        [RuntimeError("read failed")],
        ["not-json"],
        [answer(b"\xff", count=2)],
    ],
)
def test_failed_or_malformed_read_drops_clip(responses):
    f = Fixture()
    f.read_answers = responses
    identify = f.build()
    start_and_ready(f, identify, 1)
    assert [name for name, _ in f.calls].count("self.music.drop_clip") == 1
    assert not any(name == "post" for name, _ in f.calls)


def test_oversize_clip_drops_without_reading():
    f = Fixture()
    identify = f.build()
    start_and_ready(f, identify, 100001)
    assert not any(name == "self.music.read_clip" for name, _ in f.calls)
    assert [name for name, _ in f.calls].count("self.music.drop_clip") == 1


def test_cancelled_event_clears_pending_capture():
    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.on_clip_event("music_clip_cancelled", {"why": "wake word"}, 1)
    identify.on_clip_event("music_clip_ready", ready(1), 2)
    assert not any(name == "self.music.read_clip" for name, _ in f.calls)


def test_tick_drops_capture_that_never_reports_ready():
    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.tick(25)
    identify.on_clip_event("music_clip_ready", ready(1), 26)
    assert not any(name == "self.music.read_clip" for name, _ in f.calls)


@pytest.mark.parametrize(
    "situation,setting",
    [
        ({"in_turn": True}, "on"),
        ({"muted": True}, "on"),
        ({"full_quiet": "quiet"}, "on"),
        ({"connected": False}, "on"),
        ({"offline": True}, "on"),
        ({}, "off"),
        ({}, "ask"),
    ],
)
def test_capture_guards(situation, setting, caplog):
    f = Fixture(**situation)
    f.setting = setting
    identify = f.build()
    with caplog.at_level(logging.INFO):
        identify.on_session_start(0)
    assert not any(name == "self.music.capture_clip" for name, _ in f.calls)
    assert (setting == "ask") == any(
        "song naming waits for the confirm" in record.message for record in caplog.records
    )


def test_one_capture_per_session_and_600_second_result_cooldown():
    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.on_session_start(1)
    f.read_answers = [answer(b"\xff", True)]
    identify.on_clip_event("music_clip_ready", ready(1), 2)
    identify.on_session_end()
    identify.on_session_start(500)
    identify.on_session_end()
    identify.on_session_start(603)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2


@pytest.mark.parametrize(
    "result",
    [
        {"status": "no_match"},
        {"status": "not_ready"},
        {"status": "rate_limited"},
        {"status": "needs_confirm"},
        {"status": "failed"},
        None,
        RuntimeError("offline"),
    ],
)
def test_non_match_results_do_nothing(result):
    f = Fixture()
    f.result = result
    f.read_answers = [answer(b"\xff", True)]
    identify = f.build()
    start_and_ready(f, identify, 1)
    assert not any(name == "self.face.song_title" for name, _ in f.calls)


@pytest.mark.parametrize(
    "title,artist,expected",
    [
        ("Song", "Artist", "Song - Artist"),
        ("Song", None, "Song"),
        ("x" * 80, None, "x" * 60),
    ],
)
def test_match_title_variants_and_private_info_log(title, artist, expected, caplog):
    f = Fixture()
    f.result = {"status": "matched", "title": title, "artist": artist}
    f.read_answers = [answer(b"\xff", True)]
    identify = f.build()
    with caplog.at_level(logging.INFO):
        start_and_ready(f, identify, 1)
    assert f.calls[-1] == ("self.face.song_title", {"text": expected})
    assert all(title not in record.message for record in caplog.records)
