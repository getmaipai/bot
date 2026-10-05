"""LINK-STATE-01 rung 2: the offline status is a template over real values, no model."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from maipai_body.link import status as status_module
from maipai_body.link.state_machine import LadderSnapshot, LinkPhase
from maipai_body.link.status import NOTHING_SAVED, build_status

CONTACT_WALL = 1_800_000_000.0  # 2027-01-15 08:00:00 UTC
UTC = datetime.UTC


def _snap(**over) -> LadderSnapshot:
    base = dict(
        phase=LinkPhase.RECONNECTING,
        since=0.0,
        attempts=4,
        current_address="http://hub.tail1.ts.net:80",
        answered_path="lan",
        last_connected_wall=CONTACT_WALL,
        last_error="unreachable: ConnectTimeout",
    )
    base.update(over)
    return LadderSnapshot(**base)


def test_reconnecting_text_is_the_template_over_the_snapshot_values():
    text = build_status(_snap(), tz=UTC).text
    assert text == (
        "Can't reach home. Trying http://hub.tail1.ts.net:80 (attempt 4). "
        "Last contact 08:00, over lan. "
        "Last error: unreachable: ConnectTimeout. "
        "Nothing is saved for later."
    )


def test_sleeping_text_says_it_is_asleep_and_still_checking():
    text = build_status(_snap(phase=LinkPhase.SLEEPING, attempts=19), tz=UTC).text
    assert text.startswith("Asleep, can't reach home. Still checking, 19 attempts, last tried ")
    assert text.endswith("Nothing is saved for later.")


def test_connected_text_names_no_outage_and_no_queue_line():
    text = build_status(
        _snap(phase=LinkPhase.CONNECTED, attempts=0, last_error=None, current_address=None), tz=UTC
    ).text
    assert text == "Connected to home."


def test_values_that_are_absent_are_left_out_never_invented():
    text = build_status(
        _snap(
            attempts=0, current_address=None, answered_path=None, last_connected_wall=None,
            last_error=None,
        ),
        tz=UTC,
    ).text
    assert text == "Can't reach home. No contact since starting. Nothing is saved for later."


# Every word the templates may print. Anything else in the text must be a value.
_TEMPLATE_WORDS = {
    "can't", "reach", "home", "trying", "attempt", "last", "contact", "over", "error",
    "nothing", "is", "saved", "for", "later", "asleep", "still", "checking", "attempts",
    "tried", "no", "since", "starting", "connected", "to",
}  # fmt: skip


def test_the_text_contains_only_template_words_and_the_snapshot_values():
    snap = _snap(attempts=7, current_address="http://192.0.2.99:80", last_error="refused: 401")
    for phase in (LinkPhase.RECONNECTING, LinkPhase.SLEEPING):
        text = build_status(_snap(**{**snap.__dict__, "phase": phase}), tz=UTC).text
        remaining = text
        for value in ("http://192.0.2.99:80", "refused: 401", "08:00", "lan", "7"):
            remaining = remaining.replace(value, " ")
        words = re.findall(r"[A-Za-z']+", remaining)
        assert {w.lower() for w in words} <= _TEMPLATE_WORDS, words


def test_changing_each_value_changes_the_text():
    base = build_status(_snap(), tz=UTC).text
    assert build_status(_snap(attempts=5), tz=UTC).text != base
    assert build_status(_snap(current_address="http://x:1"), tz=UTC).text != base
    assert build_status(_snap(last_error="refused: 401"), tz=UTC).text != base
    assert build_status(_snap(answered_path="tailnet"), tz=UTC).text != base
    assert build_status(_snap(last_connected_wall=CONTACT_WALL + 3600), tz=UTC).text != base


def test_the_queue_line_is_the_one_the_backlog_names():
    assert NOTHING_SAVED == "Nothing is saved for later."


def test_it_speaks_only_through_the_existing_unreachable_clip_id():
    assert build_status(_snap(), tz=UTC).clip_ids == ("line.unreachable",)
    assert build_status(_snap(phase=LinkPhase.SLEEPING), tz=UTC).clip_ids == ("line.unreachable",)
    assert build_status(_snap(phase=LinkPhase.CONNECTED), tz=UTC).clip_ids == ()


def test_the_status_module_calls_no_model_and_no_network():
    source = Path(status_module.__file__).read_text()
    for forbidden in ("requests", "turn_client", "TurnClient", "websockets", "openai", "anthropic"):
        assert forbidden not in source
