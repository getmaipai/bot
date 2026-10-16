"""VOICE-01: the real engines behind ``engines.py``, over sherpa-onnx.

UNVERIFIED. ``sherpa_onnx`` does not load on the dev Mac (its
``libonnxruntime.dylib`` is not found) and the unit is not here, so none of
these classes has run against a model. They follow sherpa-onnx's documented
Python API and are exercised only for what they can prove without it: lazy
imports and a clear error when a model file is missing. M-06 (Moonshine and
Silero on the CM4), M-08 (CAM++) and M-09 (Piper time to first audio) are the
rows that turn this on. Model files are fetched by the pinned-asset path
(``speech.models``), never vendored; the spec does not pin Moonshine, Silero,
Piper or CAM++ yet, so these take paths and that pin work is blocked on a
commons spec change.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import numpy.typing as npt

from maipai_body.speech.engines import SpokenSegment

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class EngineUnavailable(RuntimeError):
    """A speech model is missing or the runtime cannot load; the message says what to do."""


def _need(path: Path | str, what: str) -> str:
    if not Path(path).is_file():
        raise EngineUnavailable(f"{what} is missing at {path}; fetch the robot's speech models")
    return str(path)


def _sherpa():
    try:
        import sherpa_onnx
    except ImportError as exc:  # also raised when the native library will not load
        raise EngineUnavailable(
            f"sherpa-onnx could not load ({exc}); run `uv sync --extra kws` on the robot"
        ) from exc
    return sherpa_onnx


class SileroVad:
    """``VadEngine`` over the Silero model, one 32 ms block at a time."""

    def __init__(self, model: Path | str, *, threshold: float = 0.5) -> None:
        sherpa = _sherpa()
        config = sherpa.VadModelConfig()
        config.silero_vad.model = _need(model, "the Silero VAD model")
        config.silero_vad.threshold = threshold
        config.sample_rate = 16000
        self._detector = sherpa.VoiceActivityDetector(config, buffer_size_in_seconds=5)

    def is_speech(self, block: npt.NDArray[np.float32]) -> bool:
        self._detector.accept_waveform(block)
        return bool(self._detector.is_speech_detected())

    def reset(self) -> None:
        self._detector.reset()


class MoonshineStt:
    """``SttEngine`` over a Moonshine tiny model directory (the legacy bench pick)."""

    def __init__(self, model_dir: Path | str, *, num_threads: int = 2) -> None:
        sherpa = _sherpa()
        root = Path(model_dir)
        self._recognizer = sherpa.OfflineRecognizer.from_moonshine(
            preprocessor=_need(root / "preprocess.onnx", "the Moonshine preprocessor"),
            encoder=_need(root / "encode.int8.onnx", "the Moonshine encoder"),
            uncached_decoder=_need(root / "uncached_decode.int8.onnx", "the Moonshine decoder"),
            cached_decoder=_need(root / "cached_decode.int8.onnx", "the Moonshine cached decoder"),
            tokens=_need(root / "tokens.txt", "the Moonshine tokens"),
            num_threads=num_threads,
        )

    def transcribe(self, samples: npt.NDArray[np.float32], sample_rate: int) -> str:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._recognizer.decode_stream(stream)
        return str(stream.result.text).strip()


class PiperTts:
    """``TtsEngine`` over a Piper voice package, one sentence per segment."""

    def __init__(
        self, voice_id: str, model: Path | str, tokens: Path | str, data_dir: Path | str
    ) -> None:
        sherpa = _sherpa()
        vits = sherpa.OfflineTtsVitsModelConfig(
            model=_need(model, "the Piper voice model"),
            tokens=_need(tokens, "the Piper voice tokens"),
            data_dir=str(data_dir),
        )
        config = sherpa.OfflineTtsConfig(
            model=sherpa.OfflineTtsModelConfig(vits=vits, num_threads=2)
        )
        self.voice_id = voice_id
        self._tts = sherpa.OfflineTts(config)

    def synthesize(self, text: str) -> Iterator[SpokenSegment]:
        for sentence in (s.strip() for s in _SENTENCE_END.split(text)):
            if not sentence:
                continue
            audio = self._tts.generate(sentence, sid=0, speed=1.0)
            yield SpokenSegment(
                text=sentence,
                samples=np.asarray(audio.samples, dtype=np.float32),
                sample_rate=int(audio.sample_rate),
            )


class CamPlusPlusEmbedder:
    """``SpeakerEmbedder`` over the CAM++ model (SPEAK-01's voice print input)."""

    def __init__(self, model: Path | str, model_sha256: str, *, num_threads: int = 1) -> None:
        sherpa = _sherpa()
        self.model_id = Path(model).name
        self.model_sha256 = model_sha256
        config = sherpa.SpeakerEmbeddingExtractorConfig(
            model=_need(model, "the CAM++ speaker model"), num_threads=num_threads
        )
        self._extractor = sherpa.SpeakerEmbeddingExtractor(config)

    def embed(self, samples: npt.NDArray[np.float32], sample_rate: int) -> npt.NDArray[np.float32]:
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=sample_rate, waveform=samples)
        stream.input_finished()
        return np.asarray(self._extractor.compute(stream), dtype=np.float32)
