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
                self.post_with_request,
                lambda: self.sit,
                lambda: self.setting,
                spawn=lambda worker: worker(),
            )
        )

    def post(self, pcm):
        return self.post_with_request(pcm, None)

    def post_with_request(self, pcm, request_id=None):
        if isinstance(self.result, Exception):
            raise self.result
        self.calls.append(("post", pcm) if request_id is None else ("post", pcm, request_id))
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


def test_explicit_request_ignores_setting_and_in_turn_and_posts_request_id():
    f = Fixture(in_turn=True)
    f.setting = "off"
    f.read_answers = [answer(b"\xff", True)]
    identify = f.build()
    assert identify.listen_now("req7", 15, 0) == {"listen_song": "started", "why": ""}
    assert ("self.music.capture_clip", {"seconds": 15}) in f.calls
    identify.on_clip_event("music_clip_ready", ready(1), 1)
    assert ("post", b"\x00\x00", "req7") in f.calls


def test_explicit_request_refuses_when_muted_and_when_capture_busy():
    muted = Fixture(muted=True).build()
    assert muted.listen_now("a", 10, 0)["listen_song"] == "refused"
    f = Fixture()
    identify = f.build()
    assert identify.listen_now("a", 10, 0)["listen_song"] == "started"
    assert identify.listen_now("b", 10, 1)["listen_song"] == "refused"


def test_second_explicit_request_works_after_the_first_finished():
    f = Fixture()
    f.read_answers = [answer(b"\xff", True), answer(b"\xff", True)]
    identify = f.build()
    assert identify.listen_now("one", 10, 0)["listen_song"] == "started"
    identify.on_clip_event("music_clip_ready", ready(1), 1)
    assert identify.listen_now("two", 10, 2)["listen_song"] == "started"


def test_cancel_forgets_explicit_request_id():
    f = Fixture()
    identify = f.build()
    identify.listen_now("a", 10, 0)
    identify.on_clip_event("music_clip_cancelled", {"why": "wake"}, 1)
    f.read_answers = [answer(b"\xff", True)]
    identify.on_session_start(2)
    identify.on_clip_event("music_clip_ready", ready(1), 3)
    assert ("post", b"\x00\x00") in f.calls
    assert not any(call[0] == "post" and len(call) == 3 for call in f.calls)


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"request_id": "abc123"}, "started"),
        ({"request_id": "abc123", "seconds": 5}, "started"),
        ({"request_id": "", "seconds": 10}, "refused"),
        ({"request_id": "bad-id", "seconds": 10}, "refused"),
        ({"request_id": "x" * 65, "seconds": 10}, "refused"),
        ({"request_id": "abc", "seconds": True}, "refused"),
        ({"request_id": "abc", "seconds": 4}, "refused"),
    ],
)
def test_listen_song_command_validates_payload(payload, expected):
    from types import SimpleNamespace

    from maipai_body.bodies.stackchan.music_dance_wiring import wire_music_dance

    f = Fixture()
    # Exercise command validation through the public behavior handler.
    behavior = SimpleNamespace(
        dance_settings=SimpleNamespace(), dance_events=None, show_face=lambda _face: None
    )
    runner = SimpleNamespace(
        situation=lambda: f.sit,
        request=lambda *_args: SimpleNamespace(started=True, why=""),
        stop=lambda: None,
        running=False,
        tick=lambda _now: None,
    )
    wire_music_dance(
        behavior=behavior,
        runner=runner,
        move_head=lambda *_args: None,
        centre_pitch=0,
        speed=1,
        start_ticker=False,
        identify_post=f.post_with_request,
        identify_setting=lambda: f.setting,
        identify_call_tool=lambda name, args: f.calls.append((name, args)) or True,
        identify_spawn=lambda worker: None,
    )
    result = behavior.listen_song_command(payload)
    assert result["listen_song"] == expected


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


def test_cancel_retries_once_after_twelve_seconds_only_in_running_ambient_session():
    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.on_clip_event("music_clip_cancelled", {"why": "wake"}, 1)
    identify.tick(12)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 1
    identify.tick(13)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2
    identify.on_clip_event("music_clip_cancelled", {"why": "again"}, 14)
    identify.tick(30)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2


def test_expired_clip_retries_after_twelve_seconds():
    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.tick(25)
    identify.tick(36)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 1
    identify.tick(37)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2


def test_explicit_cancel_is_not_retried():
    f = Fixture()
    identify = f.build()
    identify.listen_now("id", 10, 0)
    identify.on_clip_event("music_clip_cancelled", {"why": "wake"}, 1)
    identify.tick(20)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 1


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
        "waits for the confirm" in record.message for record in caplog.records
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
