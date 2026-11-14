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


def _song_title_behavior(f: Fixture, call_tool=None):
    from types import SimpleNamespace

    from maipai_body.bodies.stackchan.music_dance_wiring import wire_music_dance

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
        identify_call_tool=call_tool or (lambda name, args: f.calls.append((name, args)) or True),
        identify_spawn=lambda worker: None,
    )
    return behavior


def test_song_title_command_shows_and_clears_through_face_tool(caplog):
    f = Fixture()
    behavior = _song_title_behavior(f)
    with caplog.at_level(logging.INFO):
        assert behavior.song_title_command({"text": "  Song - Artist  "}) == {"song_title": "shown"}
        assert behavior.song_title_command({"text": ""}) == {"song_title": "cleared"}
    assert f.calls == [
        ("self.face.song_title", {"text": "Song - Artist"}),
        ("self.face.song_title", {"text": ""}),
    ]
    assert [record.message for record in caplog.records] == [
        "StackChan song title: shown ()",
        "StackChan song title: cleared ()",
    ]


@pytest.mark.parametrize(
    "payload,why",
    [
        ({"text": "x" * 81}, "too long"),
        (None, "payload must be an object"),
        ({"text": 3}, "text must be a string"),
    ],
)
def test_song_title_command_refuses_invalid_payload(payload, why):
    f = Fixture()
    result = _song_title_behavior(f).song_title_command(payload)
    assert result == {"song_title": "refused", "why": why}
    assert not f.calls


@pytest.mark.parametrize(
    "situation,why",
    [({"muted": True}, "muted"), ({"full_quiet": "quiet hours"}, "full quiet")],
)
def test_song_title_command_refuses_while_silenced(situation, why):
    f = Fixture(**situation)
    result = _song_title_behavior(f).song_title_command({"text": "Song"})
    assert result == {"song_title": "refused", "why": why}
    assert not f.calls


@pytest.mark.parametrize("failure", [False, RuntimeError("face tool failed")])
def test_song_title_command_face_tool_failure_is_refused(failure):
    f = Fixture()

    def fail(_name, _args):
        if isinstance(failure, Exception):
            raise failure
        return failure

    result = _song_title_behavior(f, fail).song_title_command({"text": "Song"})
    assert result == {"song_title": "refused", "why": "face tool failed"}


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


def test_pending_capture_finishes_after_session_ends():
    f = Fixture()
    f.read_answers = [answer(b"\xff", True)]
    identify = f.build()
    identify.on_session_start(0)
    identify.on_session_end()
    identify.on_clip_event("music_clip_ready", ready(1), 10)
    assert sum(name == "self.music.read_clip" for name, _ in f.calls) == 1
    assert sum(name == "post" for name, *_ in f.calls) == 1


def test_pending_capture_times_out_after_session_ends_and_later_session_can_capture():
    from maipai_body.bodies.stackchan.music_identify import READY_TIMEOUT_S

    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.on_session_end()
    identify.tick(READY_TIMEOUT_S)
    identify.on_session_start(READY_TIMEOUT_S + 1)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2


def test_cancelled_pending_capture_clears_after_session_ends():
    f = Fixture()
    identify = f.build()
    identify.on_session_start(0)
    identify.on_session_end()
    identify.on_clip_event("music_clip_cancelled", {"why": "wake"}, 8)
    identify.on_clip_event("music_clip_ready", ready(1), 9)
    assert not any(name == "self.music.read_clip" for name, _ in f.calls)


def test_new_session_does_not_capture_again_while_finished_clip_is_in_result_window():
    f = Fixture()
    f.read_answers = [answer(b"\xff", True)]
    identify = f.build()
    identify.on_session_start(0)
    identify.on_session_end()
    identify.on_clip_event("music_clip_ready", ready(1), 8)
    identify.on_session_start(9)
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 1


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


def test_suppressed_music_capture_busy_then_retry_guard_and_cancel_releases(caplog):
    f = Fixture()
    identify = f.build()
    with caplog.at_level(logging.INFO):
        identify.on_music_heard(0, "a nod was less than 2 minutes ago")
        identify.on_music_heard(1, "a nod was less than 2 minutes ago")
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 1
    identify.on_clip_event("music_clip_ready", ready(0), 2)
    with caplog.at_level(logging.INFO):
        identify.on_music_heard(10, "a nod was less than 2 minutes ago")
    assert "retry window" in caplog.records[-1].message


def test_suppressed_music_cancelled_clip_frees_the_slot_for_the_next_song():
    f = Fixture()
    identify = f.build()
    identify.on_music_heard(0, "a nod was less than 2 minutes ago")
    identify.on_clip_event("music_clip_cancelled", {"why": "wake"}, 2)
    identify.on_music_heard(13, "a nod was less than 2 minutes ago")
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2


@pytest.mark.parametrize(
    "situation,setting,reason",
    [
        ({"awake": False}, "on", "asleep"),
        ({"night": True}, "on", "night"),
        ({"muted": True}, "on", "muted"),
        ({}, "off", "setting=off"),
    ],
)
def test_suppressed_music_capture_safety_guards(situation, setting, reason, caplog):
    f = Fixture(**situation)
    f.setting = setting
    identify = f.build()
    with caplog.at_level(logging.INFO):
        identify.on_music_heard(0, "dance refused")
    assert not any(name == "self.music.capture_clip" for name, _ in f.calls)
    assert any(reason in record.message for record in caplog.records)


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


def test_suppressed_music_capture_is_freed_when_the_post_to_home_raises():
    f = Fixture()
    identify = f.build()
    identify.on_music_heard(0, "a nod was less than 2 minutes ago")
    f.result = RuntimeError("Home answered 500")
    identify.on_clip_event("music_clip_ready", ready(0), 1)
    f.result = None
    identify.on_music_heard(2, "a nod was less than 2 minutes ago")
    assert sum(name == "self.music.capture_clip" for name, _ in f.calls) == 2


def test_the_real_home_answer_nests_the_song_under_result(caplog):
    """Home's identifyView returns {status, result: {title, artist, album, year, source}} (live log
    2026-11-14 12:33: 'Home matched without a title' because the body read the top level)."""
    f = Fixture()
    f.result = {
        "status": "matched",
        "result": {
            "title": "Nested Song",
            "artist": "Nested Artist",
            "album": "An Album",
            "year": 2001,
            "source": "shazam",
        },
    }
    f.read_answers = [answer(b"\xff", True)]
    seen = []
    identify = f.build()
    identify._hooks.on_result = seen.append  # how music_dance_wiring attaches the genre mood hook
    with caplog.at_level(logging.INFO):
        start_and_ready(f, identify, 1)
    assert f.calls[-1] == ("self.face.song_title", {"text": "Nested Song - Nested Artist"})
    assert seen and seen[0]["title"] == "Nested Song"  # the genre hook gets the song fields
    assert "without a title" not in " ".join(r.message for r in caplog.records)
