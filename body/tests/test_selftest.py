"""BOT-SELF-TEST-01: the per-part self-test runner and the StackChan checks."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from maipai_body.hal.seam import Palette
from maipai_body.indicator import looks
from maipai_body.selftest import (
    Check,
    CheckResult,
    StackChanSelfTestContext,
    Status,
    format_report,
    overall_ok,
    run_selftest,
    stackchan_checks,
)

FAIL_FIX = "Retry; if it fails again, send this line to the person who set up the robot."
SKIP_FIX = "This robot cannot run this check."


def _check(name: str, run, title: str = "", needs: tuple[str, ...] = ()) -> Check:
    return Check(name=name, title=title, needs=needs, run=run)


def _abc() -> list[Check]:
    return [
        _check("a", lambda: (Status.PASS, "a ok", ""), "A"),
        _check("b", lambda: (Status.FAIL, "b bad", "fix b"), "B"),
        _check("c", lambda: (Status.SKIP, "no c", "no c here"), "C"),
    ]


def test_runner_runs_in_order_and_records_seconds() -> None:
    t = [0.0]

    def clock() -> float:
        t[0] += 1.0
        return t[0]

    results = run_selftest(_abc(), clock=clock)
    assert [r.name for r in results] == ["a", "b", "c"]
    assert [r.status for r in results] == [Status.PASS, Status.FAIL, Status.SKIP]
    assert [r.title for r in (_abc()[0], _abc()[1], _abc()[2])] == ["A", "B", "C"]
    assert results[0].seconds == 1.0
    assert results[1].fix == "fix b"
    assert results[2].detail == "no c"


def test_only_filters_by_name() -> None:
    results = run_selftest(_abc(), only={"b"})
    assert [r.name for r in results] == ["b"]


def test_only_unknown_name_raises_value_error_listing_valid() -> None:
    with pytest.raises(ValueError, match="zzz") as excinfo:
        run_selftest(_abc(), only={"zzz"})
    message = str(excinfo.value)
    assert "a" in message and "b" in message and "c" in message


def test_exception_becomes_fail_and_later_checks_still_run() -> None:
    def boom() -> tuple[Status, str, str]:
        raise RuntimeError("boom")

    checks = [
        _check("a", boom),
        _check("b", lambda: (Status.PASS, "b ok", "")),
    ]
    results = run_selftest(checks)
    assert results[0].status is Status.FAIL
    assert results[0].detail == "RuntimeError: boom"
    assert results[0].fix == FAIL_FIX
    assert results[1].status is Status.PASS


def test_run_none_is_skip() -> None:
    results = run_selftest([Check(name="a", title="A", needs=(), run=None)])
    assert results[0].status is Status.SKIP
    assert results[0].fix == ""


def test_format_report_layout_and_summary() -> None:
    results = [
        CheckResult(name="led", status=Status.PASS, detail="Showed 5 looks", fix="", seconds=1.0),
        CheckResult(
            name="movement",
            status=Status.FAIL,
            detail="did not move",
            fix="Check the power cable.",
            seconds=2.0,
        ),
        CheckResult(
            name="camera",
            status=Status.SKIP,
            detail="no camera",
            fix=SKIP_FIX,
            seconds=0.0,
        ),
    ]
    lines = format_report(results).splitlines()
    assert lines == [
        "PASS  led        Showed 5 looks",
        "FAIL  movement   did not move",
        "    fix: Check the power cable.",
        "SKIP  camera     no camera",
        f"    fix: {SKIP_FIX}",
        "1 passed, 1 failed, 1 skipped",
    ]


def test_overall_ok() -> None:
    assert overall_ok(
        [
            CheckResult(name="a", status=Status.PASS, detail=""),
            CheckResult(name="b", status=Status.SKIP, detail=""),
        ]
    )
    assert not overall_ok([CheckResult(name="a", status=Status.FAIL, detail="")])


PHOTO = b"\xff\xd8secret-bytes-xyz"
REPLY = "ready-secret-xyz"


def make_ctx(**overrides):
    state = {
        "looks": [],
        "yaw": 10,
        "pitch": 20,
        "spoke": [],
        "asked": [],
    }

    def look_writer(look) -> None:
        state["looks"].append(look)

    def head_angles() -> Mapping[str, int]:
        return {"yaw": state["yaw"], "pitch": state["pitch"]}

    def set_head(yaw, pitch) -> None:
        if yaw is not None:
            state["yaw"] = yaw
        if pitch is not None:
            state["pitch"] = pitch

    def speak(line: str) -> None:
        state["spoke"].append(line)

    def ask_hub(question: str) -> tuple[str, Mapping[str, float]]:
        state["asked"].append(question)
        return (REPLY, {"stt": 0.8, "chat": 2.1, "tts": 0.6})

    ctx = StackChanSelfTestContext(
        look_writer=look_writer,
        head_angles=head_angles,
        set_head=set_head,
        listen_frames=lambda seconds: (100, 0.5),
        wake_heard=lambda seconds: True,
        speak=speak,
        ask_hub=ask_hub,
        take_photo=lambda: PHOTO,
        decodes_as_jpeg=lambda data: data.startswith(b"\xff\xd8"),
        hold_s=0.0,
        sleep=lambda seconds: None,
    )
    for name, value in overrides.items():
        setattr(ctx, name, value)
    return ctx, state


def _run(**overrides):
    ctx, state = make_ctx(**overrides)
    results = run_selftest(stackchan_checks(ctx))
    return results, state


def _one(results, name: str) -> CheckResult:
    return next(r for r in results if r.name == name)


def test_stackchan_check_names_and_order() -> None:
    results, _ = _run()
    assert [r.name for r in results] == [
        "led",
        "movement",
        "hearing",
        "wakeword",
        "speech",
        "reply",
        "camera",
    ]


def test_all_seven_pass_with_good_fakes() -> None:
    results, state = _run()
    assert [r.status for r in results] == [Status.PASS] * 7
    assert overall_ok(results)
    looks_seen = state["looks"]
    assert looks_seen[-1] is None
    assert [look.colour for look in looks_seen[:-1]] == [
        Palette.WHITE,
        Palette.BLUE,
        Palette.GREEN,
        Palette.PINK,
        Palette.GREEN,
    ]
    keys = [
        looks.LookKey.IDLE,
        looks.LookKey.LISTENING,
        looks.LookKey.LIVE,
        looks.LookKey.CAMERA,
        looks.LookKey.CHARGING,
    ]
    for row, look in zip(keys, looks_seen[:-1], strict=True):
        colour, weight, style = looks.LOOKS[row]
        assert look.brightness == max(weight, 0.5)
        assert look.style == style
        assert look.period_s == looks.period_s(row)
    assert state["yaw"] == 10
    assert state["pitch"] == 20
    hearing = _one(results, "hearing")
    assert hearing.detail == "Heard 100 frames, peak level 0.500"
    reply = _one(results, "reply")
    assert "stt 0.8 s" in reply.detail
    assert "chat 2.1 s" in reply.detail
    assert "tts 0.6 s" in reply.detail
    assert state["spoke"] == ["Speech check. One, two, three."]


def test_led_fails_when_a_write_raises() -> None:
    def bad_writer(look) -> None:
        raise OSError("ring unplugged")

    results, _ = _run(look_writer=bad_writer)
    led = _one(results, "led")
    assert led.status is Status.FAIL
    assert led.detail == "OSError: ring unplugged"
    assert led.fix == FAIL_FIX


def test_movement_fails_when_the_head_does_not_move() -> None:
    results, _ = _run(set_head=lambda yaw, pitch: None)
    movement = _one(results, "movement")
    assert movement.status is Status.FAIL
    assert movement.fix == (
        "The head did not move. Check the power cable and that nothing blocks it."
    )


def test_movement_fails_when_the_head_does_not_come_back() -> None:
    # The angles fake reports: at start 10, after the move 14, after the return still 14.
    reads = iter([10, 14, 14])

    def moving_angles() -> Mapping[str, int]:
        return {"yaw": next(reads), "pitch": 20}

    results, _ = _run(set_head=lambda yaw, pitch: None, head_angles=moving_angles)
    assert _one(results, "movement").status is Status.FAIL


def test_hearing_fails_with_no_frames() -> None:
    results, _ = _run(listen_frames=lambda seconds: (0, 0.0))
    hearing = _one(results, "hearing")
    assert hearing.status is Status.FAIL
    assert hearing.fix == "No audio arrived. Reconnect the robot and check its microphone."


def test_hearing_fails_when_silent() -> None:
    results, _ = _run(listen_frames=lambda seconds: (50, 0.005))
    hearing = _one(results, "hearing")
    assert hearing.status is Status.FAIL
    assert hearing.fix == "Audio arrived but silent. Speak near the robot and retry."


def test_wakeword_fails_when_not_heard() -> None:
    results, _ = _run(wake_heard=lambda seconds: False)
    wakeword = _one(results, "wakeword")
    assert wakeword.status is Status.FAIL
    assert "Say the wake word within 10 seconds" in wakeword.detail
    assert (
        wakeword.fix
        == "The wake word was not heard. Check the firmware log for 'Model 0:' at boot; "
        "if it is missing the wake word model is not loaded."
    )


def test_speech_fails_when_speak_raises() -> None:
    def speak(line: str) -> None:
        raise RuntimeError("tts down")

    results, _ = _run(speak=speak)
    speech = _one(results, "speech")
    assert speech.status is Status.FAIL
    assert speech.detail == "RuntimeError: tts down"
    assert speech.fix == FAIL_FIX


def test_reply_fails_when_empty() -> None:
    results, state = _run(ask_hub=lambda q: ("", {"stt": 0.8}))
    reply = _one(results, "reply")
    assert reply.status is Status.FAIL
    assert reply.fix == (
        "The hub did not answer. Check that the Bot is paired and the hub is reachable."
    )


def test_reply_fails_when_the_hub_raises() -> None:
    def ask_hub(question: str) -> tuple[str, Mapping[str, float]]:
        raise ConnectionError("hub gone")

    results, _ = _run(ask_hub=ask_hub)
    reply = _one(results, "reply")
    assert reply.status is Status.FAIL
    assert reply.detail == "ConnectionError: hub gone"
    assert reply.fix == (
        "The hub did not answer. Check that the Bot is paired and the hub is reachable."
    )


def test_camera_fails_when_no_photo() -> None:
    results, _ = _run(take_photo=lambda: None)
    camera = _one(results, "camera")
    assert camera.status is Status.FAIL
    assert camera.fix == "No picture came back. Reconnect the robot and retry."


def test_camera_fails_when_not_decodable() -> None:
    results, _ = _run(take_photo=lambda: b"not-a-jpeg", decodes_as_jpeg=lambda data: False)
    camera = _one(results, "camera")
    assert camera.status is Status.FAIL
    assert camera.fix == "No picture came back. Reconnect the robot and retry."


def test_missing_callable_is_skip() -> None:
    ctx = StackChanSelfTestContext()
    results = run_selftest(stackchan_checks(ctx))
    assert [r.status for r in results] == [Status.SKIP] * 7
    assert all(r.fix == SKIP_FIX for r in results)
    assert overall_ok(results)


def test_led_skip_when_only_the_writer_is_missing() -> None:
    results, _ = _run(look_writer=None)
    led = _one(results, "led")
    assert led.status is Status.SKIP
    assert led.fix == SKIP_FIX
    assert _one(results, "movement").status is Status.PASS


def test_report_never_contains_the_reply_text() -> None:
    results, _ = _run()
    report = format_report(results)
    assert REPLY not in report
    assert "ready" not in report
    for result in results:
        assert REPLY not in result.detail
        assert REPLY not in result.fix
        assert "ready" not in result.detail
        assert "ready" not in result.fix


def test_report_never_contains_the_camera_bytes() -> None:
    results, _ = _run()
    report = format_report(results)
    assert "secret-bytes-xyz" not in report
    for result in results:
        assert "secret-bytes-xyz" not in result.detail
        assert "secret-bytes-xyz" not in result.fix


def test_check_carries_needs() -> None:
    ctx = StackChanSelfTestContext()
    checks = stackchan_checks(ctx)
    by_name = {check.name: check for check in checks}
    assert all(isinstance(check.needs, tuple) for check in checks)
    assert "robot.head" in by_name["movement"].needs
    assert "robot.camera" in by_name["camera"].needs


def test_report_summary_counts_all_three() -> None:
    results, _ = _run(listen_frames=lambda seconds: (0, 0.0), look_writer=None)
    report = format_report(results)
    assert report.splitlines()[-1] == "5 passed, 1 failed, 1 skipped"
