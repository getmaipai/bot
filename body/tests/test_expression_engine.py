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
from maipai_body.presence.arbitration import ArbitrationState


class _SlowSetTargetClient(FakeReachyMiniClient):
    """Hold a worker write in flight while a stop arrives on another thread."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.windows: list[tuple[float, float]] = []

    def set_target(self, *args, **kwargs):  # type: ignore[override]
        start = time.monotonic()
        self.started.set()
        self.release.wait(timeout=5)
        super().set_target(*args, **kwargs)
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


def test_muted_suppresses_a_cue_to_nothing_rendered_from_handle():
    """`muted` is a state, not a cue-driven primitive (primitives.py's own
    contract): handle() only ever suppresses for it, exactly like any other
    reason. set_muted() below is the mute contract's own render."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)

    outcome = engine.handle(Cue(phase=Phase.HEARD, cue_seq=0), SuppressionContext(muted=True))

    assert outcome.rendered is False
    assert outcome.primitive == "listen"
    assert outcome.suppressed_reason == "muted"
    assert client.sent_commands == []


def test_set_muted_renders_the_pose_once_on_the_rising_edge_only():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    arbitration = ArbitrationState(expression_active=True)

    first = engine.set_muted(True, arbitration)
    first_count = len(client.sent_commands)
    second = engine.set_muted(True, arbitration)  # no edge: already muted

    assert first is not None
    assert first.rendered_primitive == "muted"
    assert second is None
    assert first_count > 1
    assert len(client.sent_commands) == first_count
    sent = client.sent_commands[0]
    assert sent.antennas.left < 0
    assert sent.antennas.right < 0
    assert sent.pose == HeadPose()


def test_set_muted_settles_once_on_the_falling_edge():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    arbitration = ArbitrationState(expression_active=True)

    engine.set_muted(True, arbitration)
    muted_count = len(client.sent_commands)
    outcome = engine.set_muted(False, arbitration)

    assert outcome is not None
    assert outcome.rendered_primitive == "settle"
    assert len(client.sent_commands) > muted_count
    settle_command = client.sent_commands[-1]
    assert abs(settle_command.antennas.left) < 1e-4
    assert abs(settle_command.antennas.right) < 1e-4
    assert settle_command.pose == HeadPose()


def test_set_muted_defers_to_a_higher_priority_render():
    """expression_may_drive() says nothing under tracking/service/stop; a
    mute edge while tracking owns the head renders nothing to it."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    tracking = ArbitrationState(tracking_active=True)

    outcome = engine.set_muted(True, tracking)

    assert outcome is None
    assert client.sent_commands == []
    # still deferred, so a repeat call with the same value keeps trying
    # rather than looking like "no edge, already handled":
    assert engine.set_muted(True, tracking) is None


def test_set_muted_catches_up_once_arbitration_releases():
    """A code review (2026-09-27) found a mute requested while tracking
    owned the head was never rendered even after tracking ended, because
    the edge was consumed (self._muted updated) the moment it was first
    deferred, leaving nothing to trigger a render once arbitration
    allowed it. The fix: the edge stays pending until it actually
    renders, so the same `muted` value tried again after tracking ends
    (the docstring's own "every tick") renders the pose then."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    tracking = ArbitrationState(tracking_active=True)
    idle = ArbitrationState(expression_active=True)

    deferred = engine.set_muted(True, tracking)
    assert deferred is None
    assert client.sent_commands == []

    tracking_ends = engine.set_muted(True, idle)
    assert tracking_ends is not None
    assert tracking_ends.rendered_primitive == "muted"
    assert len(client.sent_commands) > 1


def test_duplicate_and_after_done_cues_are_dropped_and_counted():
    engine = ExpressionEngine(FakeReachyMiniClient(), REACHY_MINI_PROFILE)
    context = SuppressionContext()
    engine.handle(Cue(phase=Phase.HEARD, cue_seq=1), context)
    engine.handle(Cue(phase=Phase.HEARD, cue_seq=1), context)
    engine.handle(Cue(phase=Phase.DONE, cue_seq=2), context)
    late = engine.handle(Cue(phase=Phase.OUTCOME, cue_seq=3, outcome_ok=True), context)

    assert late.suppressed_reason == "out_of_sequence"
    assert engine.dropped_cues == 2


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


def test_stop_preempts_a_motion_write_in_flight_on_the_worker_thread():
    client = _SlowSetTargetClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE, threaded=True)
    engine.handle(Cue(phase=Phase.HEARD, cue_seq=0), SuppressionContext())
    assert client.started.wait(timeout=2), "the worker never started its target write"

    stop_start = time.monotonic()
    engine.handle(Cue(phase=Phase.CANCEL, cue_seq=1), SuppressionContext())
    stop_returned_at = time.monotonic()

    client.release.set()
    engine.close()
    assert stop_returned_at - stop_start < 0.1
    assert any(c.kind == "hold" for c in client.sent_commands)


def test_one_motion_worker_serializes_targets_from_concurrent_callers():
    client = _SlowSetTargetClient()
    client.release.set()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE, threaded=True)
    listen_cue = Cue(phase=Phase.HEARD, cue_seq=0)
    nod_cue = Cue(phase=Phase.OUTCOME, cue_seq=1, outcome_ok=True)
    threads = [
        threading.Thread(target=engine.handle, args=(listen_cue, SuppressionContext())),
        threading.Thread(target=engine.handle, args=(nod_cue, SuppressionContext())),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    time.sleep(0.1)
    engine.close()

    ordered = sorted(client.windows)
    for (_, end), (next_start, _) in zip(ordered, ordered[1:]):
        assert end <= next_start, "two target writes overlapped"


def test_a_direction_free_cue_falls_back_to_the_live_direction_of_arrival():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.HEARD, cue_seq=0)

    engine.handle(cue, SuppressionContext(), doa_angle_rad=-0.7)

    first = client.sent_commands[0]
    assert first.pose.yaw < 0, "listen did not orient toward the live direction of arrival"


def test_a_newer_cue_renders_after_an_earlier_one_was_suppressed():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.OUTCOME, cue_seq=0, outcome_ok=True)

    suppressed_outcome = engine.handle(cue, SuppressionContext(guard_forbidden=True))
    allowed_outcome = engine.handle(
        cue.model_copy(update={"cue_seq": 1}), SuppressionContext(guard_forbidden=False)
    )

    assert suppressed_outcome.rendered is False
    assert allowed_outcome.rendered is True
    assert allowed_outcome.rendered_primitive == "nod"
    assert client.sent_commands  # only the second call reached the client
