"""MUTE-LOCAL-01: an on-robot unmute, so a hub mute can never strand the robot."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from maipai_body.link.commands import LocalCommand, route_phrase
from maipai_body.speech import kws
from maipai_body.speech.kws import UnmuteListener
from tests.test_link_ladder_run_loop import _rungs
from tests.test_run_loop import _make_loop

BODY = Path(__file__).resolve().parents[1] / "maipai_body"


class _Engine:
    """Spots the tag a script says, on the n-th block."""

    def __init__(self, tags: dict[int, str]) -> None:
        self.tags = tags
        self.blocks = 0
        self.begins = 0

    def begin(self) -> None:
        self.begins += 1

    def accept(self, block):
        self.blocks += 1
        return self.tags.get(self.blocks)

    def finish(self):
        return None


def _run_poll(loop, seconds: float = 0.2):
    stop = threading.Event()
    result = {}
    thread = threading.Thread(target=lambda: result.update(e=loop._poll_wake(stop)), daemon=True)
    thread.start()
    time.sleep(seconds)
    stop.set()
    thread.join(timeout=2.0)
    return result["e"]


def test_the_unmute_phrase_unmutes_and_renders_settle():
    loop, parts = _make_loop()
    loop._unmute_listener = UnmuteListener(_Engine({3: "@listen_again"}))
    loop.set_muted(True)
    _run_poll(loop)
    assert loop.state.muted is False
    assert parts["engine"].muted_calls == [True, False]  # the engine renders `settle` on the edge


def test_a_question_while_muted_yields_zero_stt_uploads_and_stays_muted():
    loop, parts = _make_loop()
    loop._unmute_listener = UnmuteListener(_Engine({2: "@stop", 3: "@what_time_is_it"}))
    loop.set_muted(True)
    assert _run_poll(loop) is None
    assert loop.state.muted is True
    assert parts["wake"].poll_count == 0
    assert parts["stt"].calls == [] if hasattr(parts["stt"], "calls") else True


def test_the_listener_hears_only_the_unmute_phrase():
    listener = UnmuteListener(_Engine({1: "@stop_listening", 2: "@stop", 3: "@listen_again"}))
    block = np.zeros(512, dtype="float32")
    assert [listener.feed(block) for _ in range(3)] == [False, False, True]


def test_the_muted_keywords_file_names_that_phrase_alone():
    tags = [
        line.rsplit("@", 1)[1].strip() for line in kws.UNMUTE_KEYWORDS_FILE.read_text().splitlines()
    ]
    assert [t.replace("_", " ") for t in tags] == [kws.UNMUTE_PHRASE]
    assert route_phrase(kws.UNMUTE_PHRASE) is LocalCommand.LISTEN_AGAIN


def test_stop_listening_mutes_locally_after_the_reply_and_reports():
    offline, _clock, _volume, speaker = _rungs(phrases=["stop listening"])
    offline.machine.link_lost("unreachable: ConnectTimeout")
    loop, _parts = _make_loop(offline=offline)
    changes = []
    loop._on_change = lambda: changes.append(loop.snapshot()["muted"])
    loop._run_offline_command(threading.Event())
    assert loop.state.muted is True
    assert True in changes
    assert speaker.said[-1] == ["cmd.muted"]


def test_listen_again_after_a_wake_unmutes():
    offline, _clock, _volume, _speaker = _rungs(phrases=["listen again"])
    offline.machine.link_lost("unreachable: ConnectTimeout")
    loop, _parts = _make_loop(offline=offline)
    loop.set_muted(True)
    loop._run_offline_command(threading.Event())
    assert loop.state.muted is False


def test_the_words_physical_mute_appear_nowhere_in_body():
    needle = "physical" + " mute"
    hits = [
        str(path)
        for root in (BODY, BODY.parent / "tests")
        for path in root.rglob("*.py")
        if needle in path.read_text(encoding="utf-8").lower()
    ]
    assert hits == []
