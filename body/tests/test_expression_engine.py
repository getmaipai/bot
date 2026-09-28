"""EXPR-01's own acceptance: every primitive renders from its cue against a scripted source."""

from __future__ import annotations

import threading
import time

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.scripted_source import scripted_bench_sequence
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.seam import HeadPose


class _SlowGotoClient(FakeReachyMiniClient):
    """A fake that blocks during ``goto``, the way the real client does.

    The vendor SDK's own ``goto_target`` calls ``wait_for_task_completion``
    before returning (verified in the installed ``reachy_mini`` package),
    so a real render occupies the calling thread for the motion's whole
    duration. This stands in for that to prove the engine's render lock
    actually serializes two threads, not just two calls on one thread.
    """

    def __init__(self, hold_s: float) -> None:
        super().__init__()
        self._hold_s = hold_s
        self.windows: list[tuple[float, float]] = []

    def goto(self, *args, **kwargs):  # type: ignore[override]
        start = time.monotonic()
        super().goto(*args, **kwargs)
        time.sleep(self._hold_s)
        self.windows.append((start, time.monotonic()))


def test_the_scripted_bench_sequence_renders_every_mapped_primitive():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    context = SuppressionContext()

    rendered_primitives = set()
    for cue in scripted_bench_sequence():
        outcome = engine.handle(cue, context)
        if outcome.rendered:
            rendered_primitives.add(outcome.primitive)

    assert rendered_primitives == {
        "listen",
        "glance",
        "tilt",
        "nod",
        "perk",
        "attend",
        "speak",
        "settle",
        "stop",
    }


def test_a_cue_that_maps_to_nothing_never_reaches_the_client():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)

    outcome = engine.handle(Cue(phase=Phase.PLAN, cue_seq=0), SuppressionContext())

    assert outcome.rendered is False
    assert outcome.primitive is None
    assert client.sent_commands == []


def test_a_suppressed_primitive_never_reaches_the_client():
    """guard_forbidden and the like suppress a primitive to nothing rendered."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.OUTCOME, cue_seq=0, outcome_ok=True)

    outcome = engine.handle(cue, SuppressionContext(guard_forbidden=True))

    assert outcome.rendered is False
    assert outcome.primitive == "nod"
    assert outcome.suppressed_reason == "guard_forbidden"
    assert client.sent_commands == []


def test_muted_renders_the_muted_pose_instead_of_the_suppressed_primitive():
    """dev.md's table suppresses listen/breathe when muted; the design record's
    own table says what that looks like on this body - antennas fully down,
    not silence."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)

    outcome = engine.handle(Cue(phase=Phase.HEARD, cue_seq=0), SuppressionContext(muted=True))

    assert outcome.rendered is True
    assert outcome.primitive == "listen"
    assert outcome.suppressed_reason == "muted"
    assert outcome.rendered_primitive == "muted"
    assert len(client.sent_commands) == 1
    sent = client.sent_commands[0]
    assert sent.antennas.left < 0
    assert sent.antennas.right < 0
    assert sent.pose == HeadPose()


def test_a_cues_own_target_direction_reaches_the_renderer():
    """A glance's target_direction_rad, not the runtime doa_angle_rad, decides its side."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.SIGNAL, cue_seq=0, has_target=True, target_direction_rad=-0.5)

    engine.handle(cue, SuppressionContext(), doa_angle_rad=0.9)

    first = client.sent_commands[0]
    assert first.pose.yaw < 0, "the cue's own left-side target was ignored"


def test_stop_still_renders_normally_while_muted():
    """suppression_reason("stop", ...) is always None, so muted never redirects it."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.CANCEL, cue_seq=0)

    outcome = engine.handle(cue, SuppressionContext(muted=True))

    assert outcome.rendered is True
    assert outcome.rendered_primitive == "stop"
    assert client.sent_commands[0].kind == "hold"


def test_the_render_lock_serializes_two_threads_calling_handle_concurrently():
    """Two goto-driven primitives from two threads never overlap on the actuator."""
    client = _SlowGotoClient(hold_s=0.05)
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    listen_cue = Cue(phase=Phase.HEARD, cue_seq=0)
    nod_cue = Cue(phase=Phase.OUTCOME, cue_seq=1, outcome_ok=True)

    threads = [
        threading.Thread(target=engine.handle, args=(listen_cue, SuppressionContext())),
        threading.Thread(target=engine.handle, args=(nod_cue, SuppressionContext())),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # nod is two goto steps (dip, recover), listen is one, so three windows
    # total; every one of them must be fully serialized against every other.
    assert len(client.windows) == 3
    ordered = sorted(client.windows)
    for (_, end), (next_start, _) in zip(ordered, ordered[1:]):
        assert end <= next_start, "two renders overlapped in time"


def test_a_direction_free_cue_falls_back_to_the_live_direction_of_arrival():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.HEARD, cue_seq=0)

    engine.handle(cue, SuppressionContext(), doa_angle_rad=-0.7)

    first = client.sent_commands[0]
    assert first.pose.yaw < 0, "listen did not orient toward the live direction of arrival"


def test_the_same_cue_renders_its_own_primitive_once_context_stops_suppressing_it():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.OUTCOME, cue_seq=0, outcome_ok=True)

    suppressed_outcome = engine.handle(cue, SuppressionContext(guard_forbidden=True))
    allowed_outcome = engine.handle(cue, SuppressionContext(guard_forbidden=False))

    assert suppressed_outcome.rendered is False
    assert allowed_outcome.rendered is True
    assert allowed_outcome.rendered_primitive == "nod"
    assert client.sent_commands  # only the second call reached the client
