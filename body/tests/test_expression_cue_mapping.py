"""The cue-to-primitive mapping (dev.md section 5's trigger column)."""

from __future__ import annotations

from maipai_body.expression.cue import Cue, Phase, map_cue_to_primitive


def test_heard_maps_to_listen():
    assert map_cue_to_primitive(Cue(phase=Phase.HEARD, cue_seq=0)) == "listen"


def test_a_real_target_maps_to_glance():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=1, has_target=True, react_allowed=True)
    assert map_cue_to_primitive(cue) == "glance"


def test_a_question_maps_to_tilt():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=2, primary_act="question")
    assert map_cue_to_primitive(cue) == "tilt"


def test_a_safety_refusal_question_is_never_a_tilt():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=2, primary_act="question", is_safety_line=True)
    assert map_cue_to_primitive(cue) is None


def test_a_confirmation_ask_is_never_a_tilt():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=2, primary_act="question", is_confirmation_ask=True)
    assert map_cue_to_primitive(cue) is None


def test_high_happiness_maps_to_perk():
    cue = Cue(
        phase=Phase.SIGNAL,
        cue_seq=4,
        expressed_emotion="happiness",
        emotion_intensity="high",
    )
    assert map_cue_to_primitive(cue) == "perk"


def test_perk_is_withheld_when_react_is_forbidden():
    cue = Cue(
        phase=Phase.SIGNAL,
        cue_seq=4,
        expressed_emotion="happiness",
        emotion_intensity="high",
        react_allowed=False,
    )
    assert map_cue_to_primitive(cue) is None


def test_sadness_maps_to_attend():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=5, expressed_emotion="sadness")
    assert map_cue_to_primitive(cue) == "attend"


def test_fear_maps_to_attend():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=5, expressed_emotion="fear")
    assert map_cue_to_primitive(cue) == "attend"


def test_an_allowed_inform_maps_to_nod():
    cue = Cue(phase=Phase.SIGNAL, cue_seq=3, primary_act="inform", react_allowed=True)
    assert map_cue_to_primitive(cue) == "nod"


def test_speak_maps_to_speak():
    assert map_cue_to_primitive(Cue(phase=Phase.SPEAK, cue_seq=6)) == "speak"


def test_a_guard_replacement_withholds_the_nod_on_speak():
    cue = Cue(phase=Phase.SPEAK, cue_seq=6, replaced=True)
    assert map_cue_to_primitive(cue) is None


def test_done_maps_to_settle():
    assert map_cue_to_primitive(Cue(phase=Phase.DONE, cue_seq=7)) == "settle"


def test_cancel_maps_to_stop():
    assert map_cue_to_primitive(Cue(phase=Phase.CANCEL, cue_seq=8)) == "stop"


def test_plan_maps_to_nothing_yet():
    """The plan-driven half waits on ACT-03; out of EXPR-01's scope."""
    assert map_cue_to_primitive(Cue(phase=Phase.PLAN, cue_seq=9)) is None


def test_a_failed_outcome_maps_to_nothing():
    cue = Cue(phase=Phase.OUTCOME, cue_seq=10, outcome_ok=False)
    assert map_cue_to_primitive(cue) is None


def test_a_successful_outcome_maps_to_nod():
    cue = Cue(phase=Phase.OUTCOME, cue_seq=10, outcome_ok=True)
    assert map_cue_to_primitive(cue) == "nod"
