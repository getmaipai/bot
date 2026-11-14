"""The song title keeper (re-sends the title while the song plays) and the beat phrases that
alternate head nods and side-to-side sways (owner 2026-11-14)."""

from __future__ import annotations

from maipai_body.bodies.stackchan import dance_phrases as P
from maipai_body.bodies.stackchan.dance import Plan
from maipai_body.bodies.stackchan.music_dance import AUTO_PLAN, BUILD_S, DANCE_PLAN, DANCE_S
from maipai_body.bodies.stackchan.song_title import (
    GRACE_S,
    HOME_MAX_S,
    MIN_SHOW_S,
    REFRESH_S,
    TitleKeeper,
    TitleSituation,
)


class Rig:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.active = True
        self.sit = TitleSituation()
        self.refuse = False
        self.keeper = TitleKeeper(
            self.send, situation=lambda: self.sit, music_active=lambda: self.active
        )

    def send(self, tool: str, args: dict):
        self.calls.append((tool, dict(args)))
        return False if self.refuse else True

    def texts(self) -> list[str]:
        return [args["text"] for _tool, args in self.calls]


def test_title_is_resent_every_forty_seconds_while_the_music_plays() -> None:
    rig = Rig()
    assert rig.keeper.show("Song - Artist", 0.0)
    for now in range(1, 121):
        rig.keeper.tick(float(now))
    # shown at 0, then refreshed at 40, 80, 120
    assert rig.texts() == ["Song - Artist"] * 4


def test_title_is_cleared_a_grace_after_the_music_is_over() -> None:
    rig = Rig()
    rig.keeper.show("Song", 0.0)
    rig.active = False
    for now in range(1, 200):
        rig.keeper.tick(float(now))
        if rig.texts()[-1] == "":
            break
    assert rig.texts()[-1] == ""
    # not before the minimum show time and the grace
    assert now >= max(MIN_SHOW_S, GRACE_S)
    assert rig.keeper.text == ""


def test_music_coming_back_cancels_the_pending_clear() -> None:
    rig = Rig()
    rig.keeper.show("Song", 0.0)
    rig.active = False
    for now in range(1, 40):
        rig.keeper.tick(float(now))
    rig.active = True
    for now in range(40, 100):
        rig.keeper.tick(float(now))
    assert rig.keeper.text == "Song"


def test_a_new_title_replaces_the_old_one() -> None:
    rig = Rig()
    rig.keeper.show("One", 0.0)
    rig.keeper.show("Two", 10.0)
    for now in range(11, 60):
        rig.keeper.tick(float(now))
    assert rig.keeper.text == "Two"
    assert rig.texts()[-1] == "Two"


def test_mute_or_full_quiet_clears_it_and_nothing_is_resent() -> None:
    rig = Rig()
    rig.keeper.show("Song", 0.0)
    rig.sit = TitleSituation(muted=True)
    rig.keeper.tick(5.0)
    assert rig.texts()[-1] == ""
    n = len(rig.calls)
    for now in range(6, 100):
        rig.keeper.tick(float(now))
    assert len(rig.calls) == n


def test_home_title_is_kept_without_music_until_home_clears_it() -> None:
    rig = Rig()
    rig.active = False
    rig.keeper.show("Made at home", 0.0, source="home")
    for now in range(1, 300):
        rig.keeper.tick(float(now))
    assert rig.keeper.text == "Made at home"
    assert rig.texts().count("Made at home") >= 7
    rig.keeper.show("", 300.0, source="home")
    assert rig.texts()[-1] == ""
    assert rig.keeper.text == ""


def test_home_title_with_no_word_from_home_is_dropped_eventually() -> None:
    rig = Rig()
    rig.keeper.show("Made at home", 0.0, source="home")
    rig.keeper.tick(HOME_MAX_S + 1)
    assert rig.keeper.text == ""


def test_refresh_is_logged_without_the_title(caplog) -> None:
    rig = Rig()
    rig.keeper.show("Secret Title", 0.0)
    with caplog.at_level("INFO"):
        rig.keeper.tick(REFRESH_S + 1)
    assert "refreshed" in caplog.text
    assert "Secret Title" not in caplog.text


def test_a_failing_unit_does_not_raise() -> None:
    rig = Rig()
    rig.refuse = True
    assert rig.keeper.show("Song", 0.0) is False
    rig.keeper.tick(100.0)


# ------------------------------------------------------------------ phrases


def test_phrase_length_is_eight_beats_held_in_range() -> None:
    assert abs(P.phrase_seconds(120) - 4.0) < 1e-6
    assert P.phrase_seconds(187) == P.MIN_PHRASE_S  # 2.56 s is raised to 3 s
    assert P.phrase_seconds(60) == P.MAX_PHRASE_S  # 8 s is cut to 6 s
    assert P.phrase_seconds(0) == P.phrase_seconds(P.DEFAULT_BPM)


def test_tempo_is_folded_and_the_median_is_steady() -> None:
    assert P.fold_bpm(300) == 150
    assert P.fold_bpm(40) == 80
    assert P.steady_bpm([145, 147, 290, 0, 146]) == 145.5
    assert P.steady_bpm([]) == 0.0


def test_the_dance_alternates_nods_and_sways() -> None:
    steps = [s for s in P.dance_script(DANCE_S, 145) if s[1] == "dance"]
    moves = [name for _at, _kind, name in steps]
    assert moves[0] == "bob"
    assert "happy" in moves[:3]
    assert len(set(moves)) >= 3
    # no two moves in a row are the same
    assert all(a != b for a, b in zip(moves, moves[1:], strict=False))
    # phrases start on the beat grid: equal spacing of eight beats
    times = [at for at, _k, _n in steps]
    want = P.phrase_seconds(145)
    assert all(abs((b - a) - want) < 0.002 for a, b in zip(times, times[1:], strict=False))


def test_the_round_keeps_its_length_ring_and_build_up() -> None:
    plan = P.phrase_plan(AUTO_PLAN, bpm=130, dance_from_s=BUILD_S)
    assert isinstance(plan, Plan)
    assert plan.total_s == AUTO_PLAN.total_s
    assert plan.ring is AUTO_PLAN.ring
    build = [step for step in plan.script if step[0] < BUILD_S]
    assert build == [step for step in AUTO_PLAN.script if step[0] < BUILD_S]
    # every step lies inside the round (the controller's boundary is unchanged)
    assert max(step[0] for step in plan.script) < plan.total_s


def test_dance_only_plan_starts_at_zero() -> None:
    plan = P.phrase_plan(DANCE_PLAN, bpm=100, dance_from_s=0.0, offset=2)
    first = [s for s in plan.script if s[1] == "dance"][0]
    assert first[0] == 0.0
    assert first[2] == P.CYCLE[2][0]  # begins two steps into the cycle
    assert plan.total_s == DANCE_PLAN.total_s


def test_each_round_starts_one_step_further() -> None:
    offsets = P.PhraseOffset()
    firsts = []
    for _ in range(3):
        script = P.dance_script(DANCE_S, 120, offset=offsets.next())
        firsts.append([s for s in script if s[1] == "dance"][0][2])
    assert firsts == [P.CYCLE[0][0], P.CYCLE[1][0], P.CYCLE[2][0]]


def test_phrases_add_no_sound_and_no_head_moves_from_the_host() -> None:
    steps = P.dance_script(DANCE_S, 120)
    assert {kind for _at, kind, _name in steps} <= {"face", "dance"}
