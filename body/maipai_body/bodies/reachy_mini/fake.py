"""Replays recorded Reachy Mini fixtures through the same seam as the live client.

Loads ``fixtures/state_frames.jsonl`` (recorded by
``scripts/record_fixtures.py`` against a running simulator, in the sample
shape ``client.daemon_state_to_sample`` produces) and answers ``goto``,
``set_target``, ``hold``, ``enable``, ``disable`` and ``state_feed``
exactly as ``client.ReachyMiniClient`` does: the same envelope clamp
(``envelope.clamp_target``), the same ``BodyLost``/``OutOfEnvelope``
errors, nothing reaching the daemon (here, an in-memory log) when a
target is out of the envelope. The pytest suite in ``tests/`` runs
unmodified against either.
"""

from __future__ import annotations

import json
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from maipai_body.hal.errors import BodyLost
from maipai_body.hal.seam import (
    AntennaPositions,
    BodyProfile,
    DirectionOfArrival,
    FaceTrackTarget,
    HeadPose,
    ImuReading,
    InterpolationMethod,
    StateFrame,
)

from .envelope import clamp_target
from .profile import REACHY_MINI_PROFILE

FIXTURES_DIR = Path(__file__).parent / "fixtures"
STATE_FRAMES_PATH = FIXTURES_DIR / "state_frames.jsonl"


@dataclass
class SentCommand:
    """One command the fake recorded as "reaching the daemon"."""

    kind: str  # "goto" | "set_target" | "hold" | "enable" | "disable"
    pose: HeadPose | None = None
    antennas: AntennaPositions | None = None
    body_yaw: float | None = None
    duration_s: float | None = None
    method: InterpolationMethod | None = None


def load_recorded_samples() -> list[dict[str, Any]]:
    """Read ``state_frames.jsonl``, one sample dict per recorded frame."""
    if not STATE_FRAMES_PATH.exists():
        return []
    with STATE_FRAMES_PATH.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _load_wav_as_stereo_16k(path: Path) -> npt.NDArray[np.float32]:
    """Read a 16-bit PCM WAV fixture into float32 stereo samples, ``(n, 2)``.

    Only 16 kHz is accepted: this fake stands in for real hardware that is
    always 16 kHz (``audio_base.py``'s own ``SAMPLE_RATE`` constant), and
    resampling a test fixture we authored ourselves would hide a mistake
    in the fixture rather than catch one. Mono fixtures are duplicated to
    both channels, matching what a single boom mic would look like
    through the array's own stereo capture path.
    """
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != 16000:
            raise ValueError(f"{path}: expected 16000 Hz, got {handle.getframerate()}")
        if handle.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit PCM, got {handle.getsampwidth() * 8}-bit")
        channels = handle.getnchannels()
        raw = handle.readframes(handle.getnframes())
    ints = np.frombuffer(raw, dtype=np.int16)
    floats = (ints.astype(np.float32) / 32768.0).reshape(-1, channels)
    if channels == 1:
        floats = np.column_stack((floats[:, 0], floats[:, 0]))
    elif channels != 2:
        raise ValueError(f"{path}: expected mono or stereo, got {channels} channels")
    return floats.astype(np.float32)


class FakeReachyMiniClient:
    """Answers the HAL seam from recorded fixtures; never opens a socket."""

    # A real chunk from the gstreamer appsink is whatever one GStreamer
    # buffer holds, not a fixed size; this is just small enough (64 ms)
    # that a 3 s fixture needs several calls to drain, exercising a
    # consumer's own accumulation logic the same way the real client would.
    _MIC_CHUNK_FRAMES = 1024

    def __init__(
        self,
        profile: BodyProfile = REACHY_MINI_PROFILE,
        microphone_wav: Path | None = None,
    ) -> None:
        self.profile = profile
        self._lost = False
        self.sent_commands: list[SentCommand] = []
        self.motors_enabled = True
        self._current_pose = HeadPose()
        self._current_antennas = AntennaPositions(left=0.0, right=0.0)
        self._current_body_yaw = 0.0
        self.tracking_enabled = False
        self.tracking_weight = 0.0
        self.face_target = FaceTrackTarget(detected=False)
        self._microphone_wav = microphone_wav
        self._mic_samples: npt.NDArray[np.float32] | None = None
        self._mic_cursor = 0
        self._recording = False
        self._playing = False
        self.pushed_audio: list[npt.NDArray[np.float32]] = []

    # -- test control, not part of the seam --

    def simulate_disconnect(self) -> None:
        """Mark the fake lost, as a real client would after the daemon drops it."""
        self._lost = True

    # -- connection lifecycle --

    def _require_connected(self) -> None:
        if self._lost:
            raise BodyLost(f"{self.profile.id}: refusing a command after a prior connection loss")

    # -- HeadActuator --

    def goto(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
        duration_s: float = 0.5,
        method: InterpolationMethod = "minjerk",
    ) -> None:
        self._require_connected()
        clamp_target(self.profile, pose, antennas, body_yaw)
        self.sent_commands.append(
            SentCommand(
                kind="goto",
                pose=pose,
                antennas=antennas,
                body_yaw=body_yaw,
                duration_s=duration_s,
                method=method,
            )
        )
        self._apply(pose, antennas, body_yaw)

    def set_target(
        self,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
    ) -> None:
        self._require_connected()
        clamp_target(self.profile, pose, antennas, body_yaw)
        self.sent_commands.append(
            SentCommand(kind="set_target", pose=pose, antennas=antennas, body_yaw=body_yaw)
        )
        self._apply(pose, antennas, body_yaw)

    def hold(self) -> None:
        self._require_connected()
        # A code review (2026-09-27) noted: this reads _current_pose/
        # _current_antennas as separate, non-atomic attribute assignments,
        # so a concurrent goto()'s own _apply() could interleave a torn
        # read here (a stop's `hold` recording half the old pose, half
        # the new). Real risk only in this fake's shared in-process
        # state, never the real client (an HTTP call per connection, no
        # shared Python object); not exercised by any current test.
        self.sent_commands.append(
            SentCommand(
                kind="hold",
                pose=self._current_pose,
                antennas=self._current_antennas,
                body_yaw=self._current_body_yaw,
            )
        )

    def enable(self) -> None:
        self._require_connected()
        self.motors_enabled = True
        self.sent_commands.append(SentCommand(kind="enable"))

    def disable(self) -> None:
        self._require_connected()
        self.motors_enabled = False
        self.sent_commands.append(SentCommand(kind="disable"))

    def _apply(
        self, pose: HeadPose | None, antennas: AntennaPositions | None, body_yaw: float | None
    ) -> None:
        if pose is not None:
            self._current_pose = pose
        if antennas is not None:
            self._current_antennas = antennas
        if body_yaw is not None:
            self._current_body_yaw = body_yaw

    # -- AudioIO --
    #
    # G1: plays ``microphone_wav`` (given to __init__) back as though it
    # were a live microphone stream once ``start_recording()`` is called,
    # in fixed-size chunks so a consumer genuinely has to accumulate
    # across several ``get_audio_sample()`` calls rather than getting the
    # whole fixture in one - the real gstreamer appsink never hands back
    # more than one buffer's worth either. Real hardware is always 16 kHz
    # stereo (``audio_base.py``'s own ``SAMPLE_RATE``/``CHANNELS``
    # constants, read in the installed 1.11.0 package); the fixture is
    # loaded once, duplicated to stereo if it was recorded mono.

    def start_recording(self) -> None:
        """Resets the cursor to 0 on every call, replaying the fixture from
        the start rather than resuming - deliberate fake semantics, not a
        real microphone's behavior: each test constructs one client per
        utterance it wants to feed, so a start/stop/start within the same
        test is "the next test wants the same fixture again," never "the
        mic kept recording while stopped."""
        self._require_connected()
        self._recording = True
        self._mic_cursor = 0
        if self._microphone_wav is not None and self._mic_samples is None:
            self._mic_samples = _load_wav_as_stereo_16k(self._microphone_wav)

    def stop_recording(self) -> None:
        self._require_connected()
        self._recording = False

    def get_audio_sample(self) -> npt.NDArray[np.float32] | None:
        self._require_connected()
        if not self._recording or self._mic_samples is None:
            return None
        if self._mic_cursor >= len(self._mic_samples):
            # Exhausted, same return value as a live mic with nothing new
            # queued - deliberate, not fixed here: a test that polls longer
            # than its fixture's own duration gets silent starvation, not
            # an error, so size the fixture to the window under test.
            return None
        end = min(self._mic_cursor + self._MIC_CHUNK_FRAMES, len(self._mic_samples))
        chunk = self._mic_samples[self._mic_cursor : end]
        self._mic_cursor = end
        return chunk

    def get_input_audio_samplerate(self) -> int:
        self._require_connected()
        return 16000

    def start_playing(self) -> None:
        self._require_connected()
        self._playing = True

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        self._require_connected()
        self.pushed_audio.append(data)

    def stop_playing(self) -> None:
        self._require_connected()
        self._playing = False

    def get_output_audio_samplerate(self) -> int:
        self._require_connected()
        return 16000

    def get_doa(self) -> DirectionOfArrival | None:
        self._require_connected()
        for sample in load_recorded_samples():
            if sample.get("doa") is not None:
                return DirectionOfArrival(**sample["doa"])
        return None

    # -- Camera --

    def get_frame(self) -> Any:
        self._require_connected()
        return None

    # -- Imu --

    def read(self) -> ImuReading | None:
        self._require_connected()
        return None

    # -- FaceTracker --

    def enable_tracking(self, weight: float = 1.0) -> None:
        self._require_connected()
        self.tracking_enabled = True
        self.tracking_weight = weight

    def disable_tracking(self) -> None:
        self._require_connected()
        self.tracking_enabled = False
        self.tracking_weight = 0.0

    def get_face_target(self) -> FaceTrackTarget:
        self._require_connected()
        return self.face_target

    # -- StateFeed --

    def state_feed(self, frequency: float = 10.0) -> FakeStateFeed:
        self._require_connected()
        return FakeStateFeed(self)


class FakeStateFeed:
    """Replays the recorded fixture's frames, stamped on "receipt" like the live feed."""

    def __init__(self, client: FakeReachyMiniClient) -> None:
        self._client = client
        self._samples = load_recorded_samples()
        self._index = 0

    def __iter__(self) -> Iterator[StateFrame]:
        return self

    def __next__(self) -> StateFrame:
        self._client._require_connected()
        if self._index >= len(self._samples):
            raise StopIteration
        sample = self._samples[self._index]
        frame = StateFrame.stamped(
            self._index,
            head_pose=HeadPose(**sample["head_pose"]) if sample.get("head_pose") else None,
            antennas=(AntennaPositions(**sample["antennas"]) if sample.get("antennas") else None),
            body_yaw=sample.get("body_yaw"),
            doa=DirectionOfArrival(**sample["doa"]) if sample.get("doa") else None,
        )
        self._index += 1
        return frame

    def close(self) -> None:
        pass
