"""The scripted turn M-R1 and M-R4 run on a clock: a recorded utterance fed in real
time as the microphone, through the real hub clients, timed at each stage."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.expression.cue import Cue, Phase
from maipai_body.measure.turn_driver import WavCapture, run_scripted_turn
from maipai_body.speech.stt_stream import SttStreamClient, SttStreamResult
from maipai_body.speech.turn_client import TurnEvent


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _audio(seconds: float) -> np.ndarray:
    return np.ones(int(16000 * seconds), dtype=np.float32) * 0.1


def test_wav_capture_hands_out_blocks_at_real_time_pace():
    clock = _Clock()
    capture = WavCapture(_audio(1.0), clock=clock)
    assert capture.poll_blocks() == []  # the first poll starts the clock
    clock.now = 0.1  # 0.1 s of audio is due: 1600 samples = 3 whole blocks of 512
    blocks = capture.poll_blocks()
    assert len(blocks) == 3
    assert all(b.shape == (512,) and b.dtype == np.float32 for b in blocks)
    assert float(blocks[0][0]) == pytest.approx(0.1)


def test_wav_capture_runs_on_as_silence_after_the_utterance_so_the_hub_can_endpoint():
    clock = _Clock()
    capture = WavCapture(_audio(0.064), clock=clock)  # exactly two blocks
    capture.poll_blocks()
    clock.now = 0.2
    blocks = capture.poll_blocks()
    assert float(blocks[0][0]) == pytest.approx(0.1)
    assert float(blocks[1][0]) == pytest.approx(0.1)
    assert all(float(np.abs(b).max()) == 0.0 for b in blocks[2:])
    assert len(blocks) > 2


def test_the_end_of_speech_is_when_the_last_real_block_was_handed_over():
    clock = _Clock()
    capture = WavCapture(_audio(0.064), clock=clock)
    assert capture.end_of_audio_at is None
    capture.poll_blocks()
    clock.now = 0.5
    capture.poll_blocks()
    assert capture.end_of_audio_at == 0.5


class _Stt:
    def __init__(self, clock, result, advance_s=0.4):
        self._clock, self._result, self._advance = clock, result, advance_s

    def run(self, capture):
        capture.end_of_audio_at = self._clock.now
        self._clock.now += self._advance
        return self._result


class _Turn:
    def __init__(self, clock):
        self._clock = clock

    def stream(self, text, **kwargs):
        self._clock.now += 0.3
        yield TurnEvent(cue=Cue(phase=Phase.SIGNAL, cue_seq=1))
        self._clock.now += 0.2
        yield TurnEvent(cue=Cue(phase=Phase.DONE, cue_seq=2), reply_text="a reply")


class _Tts:
    def __init__(self, clock):
        self._clock = clock
        self.spoken: list[str] = []

    def speak(self, text, *, on_first_chunk=None, stop_event=None):
        self.spoken.append(text)
        self._clock.now += 0.25
        on_first_chunk()
        self._clock.now += 1.0


def _capture(clock):
    class Cap:
        end_of_audio_at = None

    return Cap()


def test_a_scripted_turn_times_endpoint_to_transcript_first_event_and_first_audio():
    clock = _Clock()
    tts = _Tts(clock)
    row = run_scripted_turn(
        _Stt(clock, SttStreamResult(kind="final", text="what time is it")),
        _Turn(clock),
        tts,
        capture_factory=lambda: _capture(clock),
        clock=clock,
    )
    assert row["endpoint_to_transcript_ms"] == pytest.approx(400.0)
    assert row["turn_first_event_ms"] == pytest.approx(300.0)
    assert row["turn_total_ms"] == pytest.approx(500.0)
    assert row["tts_first_audio_ms"] == pytest.approx(250.0)
    assert tts.spoken == ["a reply"]


def test_the_row_never_carries_the_transcript_text():
    clock = _Clock()
    row = run_scripted_turn(
        _Stt(clock, SttStreamResult(kind="final", text="private words")),
        _Turn(clock),
        _Tts(clock),
        capture_factory=lambda: _capture(clock),
        clock=clock,
    )
    assert "private words" not in str(row)
    assert row["transcript_chars"] == len("private words")


def test_a_turn_with_no_final_transcript_is_an_error_row_and_goes_no_further():
    clock = _Clock()
    tts = _Tts(clock)
    row = run_scripted_turn(
        _Stt(clock, SttStreamResult(kind="no_speech")),
        _Turn(clock),
        tts,
        capture_factory=lambda: _capture(clock),
        clock=clock,
    )
    assert row == {"error": "stt returned no_speech, not a final transcript"}
    assert tts.spoken == []


def test_a_turn_run_without_speech_skips_the_tts_stage_and_its_figure():
    clock = _Clock()
    tts = _Tts(clock)
    row = run_scripted_turn(
        _Stt(clock, SttStreamResult(kind="final", text="x")),
        _Turn(clock),
        tts,
        capture_factory=lambda: _capture(clock),
        clock=clock,
        speak=False,
    )
    assert tts.spoken == []
    assert "tts_first_audio_ms" not in row


def test_a_scripted_turn_runs_end_to_end_through_the_real_clients_against_the_stand_in_hub():
    from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
    from maipai_body.measure.stand_in_hub import StandInHub
    from maipai_body.speech.playback import AudioPlayback
    from maipai_body.speech.tts_playback import TtsPlaybackClient
    from maipai_body.speech.turn_client import TurnClient

    with StandInHub(reply_text="hello back") as hub:
        playback = AudioPlayback(FakeReachyMiniClient())
        row = run_scripted_turn(
            SttStreamClient(hub.stt_url, "cookie"),
            TurnClient(hub.http_url, "cookie"),
            TtsPlaybackClient(hub.http_url, "cookie", playback),
            capture_factory=lambda: WavCapture(_audio(0.3)),
        )
    assert "error" not in row
    assert row["transcript_chars"] == len("hello maipai")
    assert row["tts_first_audio_ms"] > 0.0
    assert playback.pushed_duration_s() > 0.0


def test_no_usable_pairing_is_a_clear_error_not_a_crash(tmp_path):
    from maipai_body.measure.turn_driver import NoUsablePairing, open_hub_session

    with pytest.raises(NoUsablePairing) as raised:
        open_hub_session(tmp_path / "hub-pairing.json")
    assert "pair the robot first" in str(raised.value)
