"""MOVES-01: the plan's ``react`` slot entry point, behind a flag (off by default).

The turn stream does not carry a move name on the wire yet, so the hook is
fed by ``TurnEvent.react_move`` (never set by the real client today). With
the flag off nothing plays; with it on a move plays only when the plan's
own ``react`` is allowed, after the reply has been spoken.
"""

from __future__ import annotations

import pytest

from maipai_body.expression.cue import Cue, Phase
from maipai_body.moves.react import REACT_FLAG, ReactHook, react_moves_enabled
from maipai_body.presence.arbitration import ArbitrationState
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.turn_client import TurnEvent
from maipai_body.speech.wake import WakeEvent
from tests.test_moves import _OPEN, _service
from tests.test_run_loop import _make_loop, _start, _wait_for_idle_after_turn


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({REACT_FLAG: ""}, False),
        ({REACT_FLAG: "0"}, False),
        ({REACT_FLAG: "false"}, False),
        ({REACT_FLAG: "1"}, True),
        ({REACT_FLAG: "true"}, True),
    ],
)
def test_the_flag_is_off_unless_set(env, expected):
    assert react_moves_enabled(env) is expected


def test_a_disabled_hook_plays_nothing_even_when_the_plan_allows_it(tmp_path):
    service, client, _ = _service(tmp_path)
    hook = ReactHook(service, enabled=False)
    assert hook("happy1", _OPEN, react_allowed=True) is False
    assert client.sent_commands == []


def test_an_enabled_hook_plays_when_the_plan_allows_it(tmp_path):
    service, client, _ = _service(tmp_path)
    hook = ReactHook(service, enabled=True)
    assert hook("happy1", _OPEN, react_allowed=True) is True
    assert any(c.kind == "set_target" for c in client.sent_commands)


def test_an_enabled_hook_refuses_quietly_when_the_plan_forbids_it(tmp_path):
    service, client, _ = _service(tmp_path)
    hook = ReactHook(service, enabled=True)
    assert hook("happy1", _OPEN, react_allowed=False) is False
    assert client.sent_commands == []


def _turn_events(*, react_move, react_allowed):
    return [
        TurnEvent(
            cue=Cue(
                phase=Phase.SIGNAL,
                cue_seq=1,
                primary_act="inform",
                react_allowed=react_allowed,
            ),
            turn_id="turn-1",
        ),
        TurnEvent(
            cue=Cue(phase=Phase.DONE, cue_seq=2),
            reply_text="hello",
            turn_id="turn-1",
            react_move=react_move,
        ),
    ]


def _run_one_turn(react_hook, events):
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hi"),
        turn_events=events,
        react_hook=react_hook,
    )
    stop_event, thread = _start(loop)
    try:
        _wait_for_idle_after_turn(loop)
    finally:
        stop_event.set()
        thread.join(timeout=5)
    return parts


def test_the_loop_calls_the_hook_after_the_reply_is_spoken():
    calls = []

    def hook(move, arbitration, *, react_allowed, muted):
        calls.append((move, react_allowed, muted, isinstance(arbitration, ArbitrationState)))
        return True

    parts = _run_one_turn(hook, _turn_events(react_move="happy1", react_allowed=True))
    assert calls == [("happy1", True, False, True)]
    assert parts["tts"].speak_calls == ["hello"]


def test_the_loop_passes_the_plans_react_permission_through():
    calls = []

    def hook(move, arbitration, *, react_allowed, muted):
        calls.append(react_allowed)
        return False

    _run_one_turn(hook, _turn_events(react_move="happy1", react_allowed=False))
    assert calls == [False]


def test_no_hook_and_no_move_name_means_no_call():
    _run_one_turn(None, _turn_events(react_move="happy1", react_allowed=True))
    calls = []
    _run_one_turn(
        lambda *a, **k: calls.append(1), _turn_events(react_move=None, react_allowed=True)
    )
    assert calls == []


def test_a_failing_hook_never_breaks_the_turn():
    def hook(move, arbitration, *, react_allowed, muted):
        raise RuntimeError("move library unreachable")

    parts = _run_one_turn(hook, _turn_events(react_move="happy1", react_allowed=True))
    assert parts["tts"].speak_calls == ["hello"]


def test_a_cancelled_turn_plays_no_move():
    calls = []
    events = [
        TurnEvent(cue=Cue(phase=Phase.CANCEL, cue_seq=1), turn_id="turn-1", react_move="happy1"),
    ]
    _run_one_turn(lambda *a, **k: calls.append(1), events)
    assert calls == []


def test_nothing_in_the_loop_module_imports_the_moves_package():
    import ast
    from pathlib import Path

    import maipai_body.run_loop as run_loop

    tree = ast.parse(Path(run_loop.__file__).read_text())
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        assert not any("moves" in n.split(".") for n in names)


def test_build_react_hook_is_none_with_the_flag_off(tmp_path):
    from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
    from maipai_body.moves.react import build_react_hook

    assert build_react_hook(FakeReachyMiniClient(), tmp_path, {}) is None


def test_build_react_hook_with_the_flag_on_is_a_hook_over_the_pinned_library(tmp_path):
    from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
    from maipai_body.moves.react import build_react_hook

    hook = build_react_hook(FakeReachyMiniClient(), tmp_path, {REACT_FLAG: "1"})
    assert isinstance(hook, ReactHook)
    # The shipped pins are empty until pin_moves_library.py has run with
    # network, so nothing can be fetched: an unpinned name fails loudly.
    with pytest.raises(Exception, match="not in the pinned|no pin"):
        hook("happy1", _OPEN, react_allowed=True)
