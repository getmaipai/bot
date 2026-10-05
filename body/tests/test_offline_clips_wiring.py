"""G4b: the clips wired in - the spoken pairing code, the reconnect clip in
place of the text prefix, and the freefall line.

Real :class:`OfflineSpeaker` runs against synthetic WAV clips and the fake
body's own audio sink; no voice is rendered in the cloud sandbox.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from maipai_body import app as app_module
from maipai_body.app import _build_link_stack, run_paired_body
from maipai_body.bodies.reachy_mini.fake import (
    FakeReachyMiniClient,
    LoopbackRecorder,
    freefall_reading,
    rest_reading,
)
from maipai_body.expression.cue import Cue, Phase
from maipai_body.link.store import PairingStore
from maipai_body.run_loop import LINK_RESTORED_LINE
from maipai_body.speech import offline_clips as oc
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.turn_client import TurnEvent
from maipai_body.speech.wake import WakeEvent
from tests.ladder_fakes import FakeSpeaker
from tests.test_app import _FakeLink
from tests.test_link_ladder_run_loop import _rungs
from tests.test_offline_clips import _install
from tests.test_run_loop import _make_loop, _start, _stop, _wait_for


def _real_speaker(tmp_path, client):
    directory, stamped = _install(tmp_path, oc.load_manifest())
    return oc.OfflineSpeaker(oc.ClipBundle(directory, stamped), AudioPlayback(client), gap_s=0.0)


# ---- the spoken pairing code --------------------------------------------------------------


def test_the_announcer_speaks_the_code_through_the_clips(tmp_path):
    recorder = LoopbackRecorder()
    client = FakeReachyMiniClient(recorder=recorder)
    speaker = _real_speaker(tmp_path, client)
    done = threading.Event()
    announcer = oc.CodeAnnouncer(on_spoken=done.set)
    announcer.current_code = lambda: "ABC-234"
    announcer.attach(speaker)

    announcer("ABC-234")

    assert done.wait(3.0)
    # the prompt plus the six characters, no gaps (gap_s=0), each 800 samples at 24 kHz
    # resampled to the fake's 16 kHz output
    assert len(recorder.chunks) == 7
    assert recorder.total_frames == pytest.approx(7 * 800 * 16_000 / 24_000, abs=14)


def test_a_code_that_arrives_before_the_speaker_is_spoken_on_attach(tmp_path):
    speaker = FakeSpeaker()
    done = threading.Event()
    announcer = oc.CodeAnnouncer(on_spoken=done.set)
    announcer.current_code = lambda: "K7M2"
    announcer("K7M2")  # no speaker yet: nothing to say it with, and no error
    assert speaker.said == []

    announcer.attach(speaker)

    assert done.wait(3.0)
    assert speaker.said == [oc.compose_pairing_code("K7M2")]


def test_a_code_already_gone_is_not_spoken_on_attach():
    speaker = FakeSpeaker()
    announcer = oc.CodeAnnouncer()
    announcer.current_code = lambda: None  # paired meanwhile
    announcer("K7M2")
    announcer.attach(speaker)
    announcer.join(3.0)
    assert speaker.said == []


def test_successive_codes_play_serially_and_skip_superseded_pending_code():
    first_started = threading.Event()
    release_first = threading.Event()

    class BlockingSpeaker(FakeSpeaker):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_active = 0
            self._active_lock = threading.Lock()

        def say(self, clip_ids, *, stop_event=None):
            with self._active_lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.said.append(clip_ids)
            try:
                if clip_ids == oc.compose_pairing_code("K7M2"):
                    first_started.set()
                    assert release_first.wait(3.0)
                return True
            finally:
                with self._active_lock:
                    self.active -= 1

    current = [None]
    speaker = BlockingSpeaker()
    announcer = oc.CodeAnnouncer()
    announcer.current_code = lambda: current[0]
    announcer.attach(speaker)

    current[0] = "K7M2"
    announcer("K7M2")
    assert first_started.wait(3.0)

    current[0] = "P4Q5"
    announcer("P4Q5")
    current[0] = "R6S7"
    announcer("R6S7")
    release_first.set()
    announcer.join(3.0)

    assert speaker.said == [
        oc.compose_pairing_code("K7M2"),
        oc.compose_pairing_code("R6S7"),
    ]
    assert speaker.max_active == 1


def test_an_unspeakable_code_or_missing_clips_never_raise():
    announcer = oc.CodeAnnouncer()
    announcer.attach(FakeSpeaker(available=set()))  # unrendered bundle
    announcer("K7M2")
    announcer.attach(FakeSpeaker())
    announcer("not a code!")  # characters the hub never issues
    announcer.join(3.0)


def test_the_link_stack_hands_the_lifecycle_the_announcer(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    stack = _build_link_stack(store, object(), discover=lambda timeout_s: None, sleep_after_s=600.0)
    assert stack.link._on_code is stack.announcer
    assert stack.announcer.current_code() is None


def test_run_paired_body_attaches_a_clip_speaker_to_the_announcer_before_pairing():
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=False)
    stop_event = threading.Event()
    speaker = FakeSpeaker()
    announcer = oc.CodeAnnouncer()
    attached = threading.Event()
    real_attach = announcer.attach
    announcer.attach = lambda s: (real_attach(s), attached.set())

    def run():
        run_paired_body(
            client, link, stop_event, cache_dir=Path("/tmp/models"), announcer=announcer
        )

    with patch.object(app_module, "_clip_speaker", return_value=speaker):
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        assert attached.wait(5.0)
        stop_event.set()
        thread.join(5.0)
    assert not thread.is_alive()


# ---- the reconnect clip replaces the text prefix -------------------------------------------


def _lost_turn_loop(speaker):
    offline, *_ = _rungs(speaker=speaker)
    reply = TurnEvent(
        cue=Cue(phase=Phase.DONE, cue_seq=2),
        reply_text="it is sunny",
        conversation_id="conv-1",
        turn_id="turn-1",
    )
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="weather"),
        turn_events=[reply],
        offline=offline,
    )
    loop._lost_turn_unannounced = True
    return loop, parts


def test_an_owed_reconnect_line_is_the_clip_when_it_can_be_said():
    speaker = FakeSpeaker()
    loop, parts = _lost_turn_loop(speaker)
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: parts["tts"].speak_calls)
    finally:
        _stop(stop_event, thread)
    assert speaker.said == [["line.reconnect"]]
    assert parts["tts"].speak_calls == ["it is sunny"]  # no text prefix
    assert loop._lost_turn_unannounced is False


def test_an_owed_reconnect_line_stays_text_when_the_clip_is_not_there():
    loop, parts = _lost_turn_loop(FakeSpeaker(available=set()))
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: parts["tts"].speak_calls)
    finally:
        _stop(stop_event, thread)
    assert parts["tts"].speak_calls == [f"{LINK_RESTORED_LINE} it is sunny"]
    assert loop._lost_turn_unannounced is False


# ---- the freefall line --------------------------------------------------------------------


def _freefall_loop(speaker):
    offline, *_ = _rungs(speaker=speaker)
    loop, parts = _make_loop(offline=offline, presence_interval_s=0.01)
    readings = [freefall_reading()]
    parts["client"].read = lambda: readings[0]
    return loop, parts, readings


def test_freefall_says_the_line_once_and_again_after_the_body_is_steady():
    speaker = FakeSpeaker()
    loop, parts, readings = _freefall_loop(speaker)
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: speaker.said)
        assert speaker.said == [["line.freefall"]]  # held in the air: not repeated
        readings[0] = rest_reading()
        _wait_for(lambda: not loop._freefall_active)
        readings[0] = freefall_reading()
        _wait_for(lambda: len(speaker.said) == 2)
    finally:
        _stop(stop_event, thread)
    assert speaker.said == [["line.freefall"], ["line.freefall"]]


def test_freefall_without_the_clip_is_silent_and_harmless():
    speaker = FakeSpeaker(available=set())
    loop, parts, _ = _freefall_loop(speaker)
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: loop._freefall_active)
    finally:
        _stop(stop_event, thread)
    assert speaker.said == []


@pytest.mark.parametrize("offline", [None])
def test_freefall_with_no_ladder_wired_is_harmless(offline):
    loop, parts = _make_loop(offline=offline, presence_interval_s=0.01)
    parts["client"].read = lambda: freefall_reading()
    stop_event, thread = _start(loop)
    try:
        _wait_for(lambda: loop._freefall_active)
    finally:
        _stop(stop_event, thread)
