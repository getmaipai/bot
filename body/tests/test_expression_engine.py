"""EXPR-01's own acceptance: every primitive renders from its cue against a scripted source."""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.scripted_source import scripted_bench_sequence
from maipai_body.expression.suppression import SuppressionContext


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
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)

    outcome = engine.handle(Cue(phase=Phase.HEARD, cue_seq=0), SuppressionContext(muted=True))

    assert outcome.rendered is False
    assert outcome.primitive == "listen"
    assert outcome.suppressed_reason == "muted"
    assert client.sent_commands == []


def test_a_cues_own_target_direction_reaches_the_renderer():
    """A glance's target_direction_rad, not the runtime doa_angle_rad, decides its side."""
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.SIGNAL, cue_seq=0, has_target=True, target_direction_rad=-0.5)

    engine.handle(cue, SuppressionContext(), doa_angle_rad=0.9)

    first = client.sent_commands[0]
    assert first.pose.yaw < 0, "the cue's own left-side target was ignored"


def test_a_direction_free_cue_falls_back_to_the_live_direction_of_arrival():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.HEARD, cue_seq=0)

    engine.handle(cue, SuppressionContext(), doa_angle_rad=-0.7)

    first = client.sent_commands[0]
    assert first.pose.yaw < 0, "listen did not orient toward the live direction of arrival"


def test_the_same_cue_renders_once_context_stops_suppressing_it():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    cue = Cue(phase=Phase.HEARD, cue_seq=0)

    muted_outcome = engine.handle(cue, SuppressionContext(muted=True))
    unmuted_outcome = engine.handle(cue, SuppressionContext(muted=False))

    assert muted_outcome.rendered is False
    assert unmuted_outcome.rendered is True
    assert client.sent_commands  # only the second call reached the client
