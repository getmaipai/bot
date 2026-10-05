"""LINK-STATE-01 rung 1: the sherpa-onnx keyword spotter behind ``CommandRecognizer``.

While the hub is away, a wake is followed by a short listen for one of six
fixed phrases (``link.commands.COMMAND_PHRASES``, first phrase of each).
The spotter is a streaming transducer that matches only the token sequences
in ``kws_keywords.txt``; it has no vocabulary beyond them, so speech off the
list returns ``None`` rather than a guess at a transcript.

Two pieces, so the funnel is testable with no model:

* :class:`SherpaKeywordEngine` is the seam to sherpa-onnx (``begin``,
  ``accept`` a 16 kHz float block, ``finish``).
* :class:`KeywordSpotterRecognizer` pulls blocks from ``AudioCapture`` for a
  bounded window of audio and returns the first phrase heard.

It listens in audio time (a block count) with a wall-clock cap, so a stream
that runs dry cannot hold the funnel. Keyword spotting is substring-like:
"stopping by the shop" contains "stop". The window after the wake and the
router's closed list are what keep that to a rung 1 command, never a turn.

The model is an optional download (``uv sync --extra kws``): CPU and
false-accepts on the Compute Module beside the wake model are UNVERIFIED
(``docs/dev/measurements.md``, ``docs/dev/offline-ladder-unit-checks.md``),
and the app does not wire this recognizer until that row is measured.
"""

from __future__ import annotations

import logging
import math
import tarfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from maipai_body.link.commands import COMMAND_PHRASES
from maipai_body.model_assets import PinnedAsset, ensure_asset
from maipai_body.speech.capture import BLOCK_DURATION_S

logger = logging.getLogger("maipai_body.speech.kws")

SAMPLE_RATE = 16000
# The spotter's default operating point (sherpa-onnx's own defaults). A sweep
# on synthesized speech (docs/dev/measurements.md) found no better setting.
KEYWORDS_THRESHOLD = 0.25
KEYWORDS_SCORE = 1.0
# How long after the wake a command may start and finish. UNMEASURED.
DEFAULT_WINDOW_S = 4.0
_POLL_SLEEP_S = 0.01
_TAIL_PAD_S = 0.3  # zeros that let the last token of a phrase decode

KEYWORD_PHRASES: tuple[str, ...] = tuple(phrases[0] for phrases in COMMAND_PHRASES.values())

KEYWORDS_FILE = Path(__file__).with_name("kws_keywords.txt")

_MODEL_DIR = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
_SUFFIX = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
MODEL_FILES = {
    "tokens": "tokens.txt",
    "encoder": f"encoder-{_SUFFIX}",
    "decoder": f"decoder-{_SUFFIX}",
    "joiner": f"joiner-{_SUFFIX}",
}
# Apache 2.0, k2-fsa/sherpa-onnx's `kws-models` release; fetched, never vendored.
KWS_MODEL = PinnedAsset(
    file=f"{_MODEL_DIR}.tar.bz2",
    url=f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{_MODEL_DIR}.tar.bz2",
    sha256="f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a",
)


class KeywordSpotterUnavailable(RuntimeError):
    """The optional ``kws`` extra (sherpa-onnx) is not installed."""


def keywords_text() -> str:
    return KEYWORDS_FILE.read_text(encoding="utf-8")


def render_keywords(bpe_model: Path) -> str:
    """Rebuild ``kws_keywords.txt`` from the closed list and the model's BPE model.

    Dev only (needs ``sentencepiece``, not an extra): the file is committed so
    the robot never tokenizes. Run it again, and diff, whenever the list or
    the pinned model changes::

        python -c "from pathlib import Path; from maipai_body.speech.kws import *; \\
        KEYWORDS_FILE.write_text(render_keywords(Path('<model dir>/bpe.model')), encoding='utf-8')"
    """
    import sentencepiece

    processor = sentencepiece.SentencePieceProcessor(model_file=str(bpe_model))
    lines = []
    for phrase in KEYWORD_PHRASES:
        tokens = processor.encode(phrase.upper(), out_type=str)
        lines.append(f"{' '.join(tokens)} @{phrase.replace(' ', '_')}")
    return "\n".join(lines) + "\n"


def tag_to_phrase(tag: str) -> str | None:
    """The command phrase a spotter tag names, or ``None`` off the list."""
    phrase = tag.strip().lstrip("@").replace("_", " ")
    return phrase if phrase in KEYWORD_PHRASES else None


def ensure_kws_model(cache_dir: Path) -> Path:
    """Fetch, verify and unpack the model's four files; returns their directory."""
    dest = cache_dir / "kws"
    if all((dest / name).exists() for name in MODEL_FILES.values()):
        return dest
    archive = ensure_asset(KWS_MODEL, cache_dir)
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {f"{_MODEL_DIR}/{name}": name for name in MODEL_FILES.values()}
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar.getmembers():
            name = wanted.get(member.name)
            if name is None or not member.isfile():
                continue
            source = tar.extractfile(member)
            assert source is not None
            part = dest / f"{name}.part"
            part.write_bytes(source.read())
            part.rename(dest / name)
    return dest


class KeywordEngine(Protocol):
    def begin(self) -> None: ...

    def accept(self, block: npt.NDArray[np.float32]) -> str | None: ...

    def finish(self) -> str | None: ...


class SherpaKeywordEngine:
    """sherpa-onnx's ``KeywordSpotter`` over the pinned model, one stream per listen."""

    def __init__(
        self,
        model_dir: Path,
        *,
        threshold: float = KEYWORDS_THRESHOLD,
        score: float = KEYWORDS_SCORE,
        num_threads: int = 1,
    ) -> None:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise KeywordSpotterUnavailable(
                "sherpa-onnx is not installed; `uv sync --extra kws` adds it"
            ) from exc
        paths = {key: str(model_dir / name) for key, name in MODEL_FILES.items()}
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=paths["tokens"],
            encoder=paths["encoder"],
            decoder=paths["decoder"],
            joiner=paths["joiner"],
            keywords_file=str(KEYWORDS_FILE),
            keywords_threshold=threshold,
            keywords_score=score,
            num_threads=num_threads,
            provider="cpu",
        )
        self._stream = None

    def begin(self) -> None:
        self._stream = self._spotter.create_stream()

    def accept(self, block: npt.NDArray[np.float32]) -> str | None:
        assert self._stream is not None
        self._stream.accept_waveform(SAMPLE_RATE, block)
        return self._decode()

    def finish(self) -> str | None:
        assert self._stream is not None
        self._stream.accept_waveform(SAMPLE_RATE, np.zeros(int(_TAIL_PAD_S * SAMPLE_RATE), "f4"))
        self._stream.input_finished()
        return self._decode()

    def _decode(self) -> str | None:
        stream = self._stream
        while self._spotter.is_ready(stream):
            self._spotter.decode_stream(stream)
            tag = self._spotter.get_result(stream)
            if tag:
                return tag
        return None


class KeywordSpotterRecognizer:
    """``CommandRecognizer``: the phrase heard in the window after a wake, or ``None``."""

    def __init__(
        self,
        engine: KeywordEngine,
        *,
        window_s: float = DEFAULT_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine = engine
        self._window_s = window_s
        self._clock = clock
        self._sleep = sleep

    @property
    def window_s(self) -> float:
        return self._window_s

    def listen(self, capture, stop_event: threading.Event) -> str | None:
        engine = self._engine
        engine.begin()
        budget = math.ceil(self._window_s / BLOCK_DURATION_S)
        # The wall cap is looser than the audio window: it only ends a stream that stopped.
        deadline = self._clock() + self._window_s * 2
        fed = 0
        while fed < budget and not stop_event.is_set() and self._clock() < deadline:
            blocks = capture.poll_blocks()
            if not blocks:
                self._sleep(_POLL_SLEEP_S)
                continue
            for block in blocks:
                fed += 1
                phrase = tag_to_phrase(engine.accept(block) or "")
                if phrase is not None:
                    return phrase
                if fed >= budget:
                    break
        if stop_event.is_set():
            return None
        return tag_to_phrase(engine.finish() or "")
