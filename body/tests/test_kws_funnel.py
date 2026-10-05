"""Rung 1 through the funnel: the keyword-spotter recognizer behind `ConversationLoop`.

Scripted-engine tests always run. The tests that push the fixtures' audio
through the real model are gated on ``MAIPAI_KWS_MODELS_DIR`` like
`test_kws_real_model.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from maipai_body.link.commands import LocalCommand
from maipai_body.measure.kws import load_wav_16k_mono
from maipai_body.run_loop import FunnelState
from maipai_body.speech import kws
from maipai_body.speech.capture import BLOCK_SAMPLES
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.wake import WakeEvent
from tests.test_link_ladder_run_loop import TIME_CLIPS, _run_one_wake, _rungs
from tests.test_run_loop import _make_loop

FIXTURES = Path(__file__).parent / "fixtures" / "kws"


class _AudioCapture:
    """One silent block for the wake, then ``clip`` in blocks, then silence."""

    def __init__(self, clip: np.ndarray | None = None) -> None:
        silence = np.zeros(BLOCK_SAMPLES, np.float32)
        clip = np.zeros(0, np.float32) if clip is None else clip
        usable = len(clip) // BLOCK_SAMPLES * BLOCK_SAMPLES
        self._queue = [silence] + [
            clip[i : i + BLOCK_SAMPLES] for i in range(0, usable, BLOCK_SAMPLES)
        ]
        self._silence = silence
        self.poll_count = 0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def poll_blocks(self):
        self.poll_count += 1
        return [self._queue.pop(0) if self._queue else self._silence]


class _ScriptedEngine:
    """Hears ``tag`` once ``after_blocks`` blocks of a listen have gone by."""

    def __init__(self, tag: str | None, after_blocks: int = 20) -> None:
        self.tag, self.after = tag, after_blocks
        self.n = 0

    def begin(self) -> None:
        self.n = 0

    def accept(self, block):
        self.n += 1
        return self.tag if self.tag and self.n == self.after else None

    def finish(self):
        return None


def _funnel(engine, *, capture=None):
    offline, _clock, volume, speaker = _rungs(recognizer=False)
    offline.recognizer = kws.KeywordSpotterRecognizer(engine)
    offline.machine.link_lost("unreachable: ConnectTimeout")
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="never used"),
        offline=offline,
    )
    if capture is not None:
        loop._capture = capture
    return loop, parts, offline, volume, speaker


@pytest.mark.parametrize(
    ("tag", "clip_ids", "text"),
    [
        ("stop", ["cmd.stopped"], "Stopped."),
        ("quieter", ["cmd.quieter"], "Quieter."),
        ("louder", ["cmd.louder"], "Louder."),
        ("timer", ["cmd.timer_set"], "Timer set."),
        ("what_time_is_it", TIME_CLIPS, "It is 08:00."),
        ("are_you_connected", ["line.unreachable"], None),
    ],
)
def test_each_spotted_command_gets_its_fixed_reply_and_never_a_turn(tag, clip_ids, text):
    loop, parts, offline, _volume, speaker = _funnel(_ScriptedEngine(tag))
    _run_one_wake(loop)
    assert speaker.said == [clip_ids]
    if text is not None:
        assert offline.last_reply.text == text
    assert [t.state for t in loop.state.trace] == [FunnelState.SPEAKING, FunnelState.IDLE]
    assert parts["stt"].call_count == 0
    assert parts["turn"].stream_calls == []


def test_a_wake_followed_by_nothing_on_the_list_never_leaves_idle():
    loop, parts, offline, _volume, speaker = _funnel(_ScriptedEngine(None))
    _run_one_wake(loop)
    assert loop.state.trace == []
    assert loop.state.funnel is FunnelState.IDLE
    assert speaker.said == []
    assert parts["stt"].call_count == 0
    assert parts["turn"].stream_calls == []
    assert offline.gate.pending == ()
    assert offline.gate.refused == 0  # the spotter returns no free text to refuse


def test_a_tag_off_the_list_is_the_same_as_silence():
    loop, parts, *_ = _funnel(_ScriptedEngine("play_music"))
    _run_one_wake(loop)
    assert loop.state.trace == []
    assert parts["turn"].stream_calls == []


# ---- the real model, on the fixtures' audio --------------------------------------------------

real_model = pytest.mark.skipif(
    not os.environ.get("MAIPAI_KWS_MODELS_DIR"), reason="MAIPAI_KWS_MODELS_DIR is not set"
)


def _real_engine():
    pytest.importorskip("sherpa_onnx", reason="the kws extra is not installed")
    path = Path(os.environ["MAIPAI_KWS_MODELS_DIR"])
    missing = [n for n in kws.MODEL_FILES.values() if not (path / n).exists()]
    if missing:
        pytest.skip(f"{path} is missing: {', '.join(missing)}")
    return kws.SherpaKeywordEngine(path)


def _entries():
    return json.loads((FIXTURES / "manifest.json").read_text())["fixtures"]


@real_model
def test_recorded_audio_of_each_command_reaches_its_reply_through_the_funnel():
    engine = _real_engine()
    replied = set()
    for entry in _entries():
        if entry["kind"] != "command":
            continue
        command = LocalCommand(entry["command"])
        if command in replied:
            continue
        clip = load_wav_16k_mono(FIXTURES / entry["file"])
        loop, parts, offline, _v, _s = _funnel(engine, capture=_AudioCapture(clip))
        _run_one_wake(loop)
        if offline.last_reply is None:
            continue  # this utterance was not heard; the next fixture of the command may be
        assert [t.state for t in loop.state.trace] == [FunnelState.SPEAKING, FunnelState.IDLE]
        assert parts["turn"].stream_calls == [] and parts["stt"].call_count == 0
        replied.add(command)
    assert replied == set(LocalCommand)


@real_model
def test_near_miss_audio_never_leaves_idle_through_the_funnel():
    engine = _real_engine()
    for entry in _entries():
        if entry["kind"] != "near_miss" or entry["voice"] != "amy-low":
            continue
        clip = load_wav_16k_mono(FIXTURES / entry["file"])
        loop, parts, offline, _v, speaker = _funnel(engine, capture=_AudioCapture(clip))
        _run_one_wake(loop)
        assert loop.state.trace == [], entry["phrase"]
        assert speaker.said == [] and offline.last_reply is None, entry["phrase"]
        assert parts["turn"].stream_calls == [] and parts["stt"].call_count == 0
