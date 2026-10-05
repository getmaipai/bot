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

import bisect
import json
import time
import wave
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
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
FACES_DIR = FIXTURES_DIR / "faces"

_GRAVITY_M_S2 = 9.81


class ManualClock:
    """A clock a test advances by hand, so a script's times are exact."""

    def __init__(self, start_s: float = 0.0) -> None:
        self._now = start_s

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class _Timeline[T]:
    """``[(t, value)]`` read by "the latest entry at or before now".

    ``t`` is seconds from the fake's own construction, so a script reads
    the same whichever clock drives it. Before the first entry there is
    no value (``None``), the way a sensor with nothing yet reports.
    """

    def __init__(self, name: str, entries: Sequence[tuple[float, T]]) -> None:
        times = [t for t, _ in entries]
        if times != sorted(times):
            raise ValueError(f"{name} script must be in time order, got {times}")
        self._times = times
        self._values = [value for _, value in entries]

    def at(self, now_s: float) -> T | None:
        index = bisect.bisect_right(self._times, now_s) - 1
        return self._values[index] if index >= 0 else None


def rest_reading() -> ImuReading:
    """Upright and still: 1 g on z, identity orientation."""
    return ImuReading(
        accelerometer=(0.0, 0.0, _GRAVITY_M_S2),
        gyroscope=(0.0, 0.0, 0.0),
        quaternion=(1.0, 0.0, 0.0, 0.0),
        temperature_c=30.0,
    )


def tipped_reading(angle_rad: float = 1.2) -> ImuReading:
    """Rolled over ``angle_rad`` about x (past 45 degrees by default), gravity following."""
    half = angle_rad / 2.0
    return ImuReading(
        accelerometer=(
            0.0,
            _GRAVITY_M_S2 * float(np.sin(angle_rad)),
            _GRAVITY_M_S2 * float(np.cos(angle_rad)),
        ),
        gyroscope=(0.0, 0.0, 0.0),
        quaternion=(float(np.cos(half)), float(np.sin(half)), 0.0, 0.0),
        temperature_c=30.0,
    )


def freefall_reading() -> ImuReading:
    """Near-zero proper acceleration, orientation unchanged."""
    return ImuReading(
        accelerometer=(0.0, 0.0, 0.05),
        gyroscope=(0.1, 0.0, 0.0),
        quaternion=(1.0, 0.0, 0.0, 0.0),
        temperature_c=30.0,
    )


def load_face_fixture(name: str) -> npt.NDArray[np.uint8]:
    """Read a synthetic frame from ``fixtures/faces/<name>.npy``: ``(h, w, 3)`` BGR uint8."""
    path = FACES_DIR / f"{name}.npy"
    if not path.exists():
        raise FileNotFoundError(f"no face fixture {name!r} under {FACES_DIR}")
    return np.load(path)


@dataclass(frozen=True)
class PushedChunk:
    """One ``push_audio_sample`` call as the loopback saw it."""

    t_s: float
    frames: int
    samples: npt.NDArray[np.float32] = field(repr=False, compare=False)


class LoopbackRecorder:
    """Captures what ``push_audio_sample`` received, with stamps.

    ``t_s`` is seconds on the recorder's clock (``time.monotonic`` unless
    a test supplies one), taken at the call, never from the audio.
    ``events`` is the start/push/stop order, so a test can prove a
    reply's first push followed ``start_playing``.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.chunks: list[PushedChunk] = []
        self.events: list[str] = []

    def on_start(self) -> None:
        self.events.append("start")

    def on_push(self, data: npt.NDArray[np.float32]) -> None:
        self.events.append("push")
        self.chunks.append(PushedChunk(t_s=self._clock(), frames=len(data), samples=data))

    def on_stop(self) -> None:
        self.events.append("stop")

    @property
    def total_frames(self) -> int:
        return sum(chunk.frames for chunk in self.chunks)

    @property
    def first_push_t_s(self) -> float | None:
        return self.chunks[0].t_s if self.chunks else None

    def duration_s(self, sample_rate: int) -> float:
        return self.total_frames / sample_rate

    def samples(self) -> npt.NDArray[np.float32]:
        if not self.chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate([chunk.samples for chunk in self.chunks])


@dataclass
class SentCommand:
    """One command the fake recorded as "reaching the daemon"."""

    kind: (
        str  # "goto" | "set_target" | "hold" | "enable" | "disable" | "gravity_on" | "gravity_off"
    )
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
        camera_frame: npt.NDArray[np.uint8] | None = None,
        camera_frame_jpeg: bytes | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        doa_script: Sequence[tuple[float, float, bool]] | None = None,
        imu_script: Sequence[tuple[float, ImuReading]] | None = None,
        frame_script: Sequence[tuple[float, str]] | None = None,
        face_script: Sequence[tuple[float, FaceTrackTarget]] | None = None,
        require_tracking: bool = False,
        recorder: LoopbackRecorder | None = None,
    ) -> None:
        self.profile = profile
        self._clock = clock
        self._t0 = clock()
        # Scripts are opt-in: with none given, every sensor answers as it
        # did before (recorded DoA sample, no IMU, the explicit frame, the
        # assignable `face_target`), so existing tests are unchanged.
        self._doa_script = (
            _Timeline(
                "DoA",
                [
                    (t, DirectionOfArrival(angle_rad=a, speech_detected=sp))
                    for t, a, sp in doa_script
                ],
            )
            if doa_script is not None
            else None
        )
        self._imu_script = _Timeline("IMU", imu_script) if imu_script is not None else None
        self._frame_script = _Timeline("frame", frame_script) if frame_script is not None else None
        self._face_script = _Timeline("face", face_script) if face_script is not None else None
        self._require_tracking = require_tracking
        self.recorder = recorder
        self._lost = False
        self.sent_commands: list[SentCommand] = []
        self.motors_enabled = True
        self.gravity_compensation = False
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
        # A real array when a caller wants a deterministic frame (the
        # design-vision-still-image-2026-09-28.md fixture pattern), None
        # otherwise - matching the real client's own `object | None`
        # contract rather than a MagicMock standing in for "unavailable."
        self._camera_frame = camera_frame
        # Independent of `_camera_frame`: the vendor SDK JPEG-encodes
        # itself (`get_frame_jpeg()`), so this fake does no encoding
        # either - a test wanting real JPEG bytes back supplies them.
        self._camera_frame_jpeg = camera_frame_jpeg

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

    # UNVERIFIED simulator path: this records requested gravity-compensation
    # state only; it does not confirm the Reachy SDK supports either method.
    def enable_gravity_compensation(self) -> None:
        self._require_connected()
        self.gravity_compensation = True
        self.sent_commands.append(SentCommand(kind="gravity_on"))

    def disable_gravity_compensation(self) -> None:
        self._require_connected()
        self.gravity_compensation = False
        self.sent_commands.append(SentCommand(kind="gravity_off"))

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

    def is_mic_fixture_exhausted(self) -> bool:
        """Public test-control surface, like :meth:`simulate_disconnect`:
        a test that drains the fixture in a loop checks this instead of
        reaching into ``_mic_cursor``/``_mic_samples`` directly, so a
        future change to how the fixture is stored doesn't break every
        test that polls to exhaustion."""
        return self._mic_samples is not None and self._mic_cursor >= len(self._mic_samples)

    def get_input_audio_samplerate(self) -> int:
        self._require_connected()
        return 16000

    def start_playing(self) -> None:
        self._require_connected()
        self._playing = True
        if self.recorder is not None:
            self.recorder.on_start()

    def push_audio_sample(self, data: npt.NDArray[np.float32]) -> None:
        self._require_connected()
        self.pushed_audio.append(data)
        if self.recorder is not None:
            self.recorder.on_push(data)

    def stop_playing(self) -> None:
        self._require_connected()
        self._playing = False
        if self.recorder is not None:
            self.recorder.on_stop()

    def get_output_audio_samplerate(self) -> int:
        self._require_connected()
        return 16000

    def _script_time(self) -> float:
        return self._clock() - self._t0

    def get_doa(self) -> DirectionOfArrival | None:
        self._require_connected()
        if self._doa_script is not None:
            return self._doa_script.at(self._script_time())
        for sample in load_recorded_samples():
            if sample.get("doa") is not None:
                return DirectionOfArrival(**sample["doa"])
        return None

    # -- Camera --

    def get_frame(self) -> Any:
        self._require_connected()
        if self._frame_script is not None:
            name = self._frame_script.at(self._script_time())
            if name is not None:
                return load_face_fixture(name)
        return self._camera_frame

    def get_frame_jpeg(self) -> bytes | None:
        self._require_connected()
        return self._camera_frame_jpeg

    # -- Imu --

    def read(self) -> ImuReading | None:
        self._require_connected()
        if self._imu_script is not None:
            return self._imu_script.at(self._script_time())
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
        if self._face_script is not None:
            if self._require_tracking and not self.tracking_enabled:
                return FaceTrackTarget(detected=False)
            scripted = self._face_script.at(self._script_time())
            return scripted if scripted is not None else FaceTrackTarget(detected=False)
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
