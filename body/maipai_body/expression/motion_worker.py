"""S-EXPR-01R's one 50 Hz writer and bounded per-axis motion mixer.

All expression targets are submitted as layers.  The worker is the only
expression path that calls ``HeadActuator.set_target``; tests can tick it
with an injected monotonic timestamp instead of starting a thread.
Constants are dated design defaults pending the M-R2 simulator and unit
rows, never calibration values.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum

from maipai_body.bodies.reachy_mini.envelope import axis_bounds_rad
from maipai_body.hal.seam import (
    AntennaPositions,
    BodyProfile,
    HeadActuator,
    HeadPose,
    StateFeed,
    StateFrame,
)

_PERIOD_S = 0.02
_MAX_DT_S = 0.07
_SOURCE = "design default pending M-R2 simulator and unit rows; UNMEASURED"
_DATE = "2026-10-06"


class MotionLayer(IntEnum):
    """Layer order from the Reachy v2 arbitration table."""

    SAFETY = 0
    SERVICE = 1
    GAZE = 2
    EXPRESSION = 3
    IDLE = 4


@dataclass(frozen=True)
class MotionTarget:
    pose: HeadPose = field(default_factory=HeadPose)
    antennas: AntennaPositions = field(
        default_factory=lambda: AntennaPositions(left=0.0, right=0.0)
    )
    body_yaw: float = 0.0
    owned_axes: frozenset[str] | None = None

    def axes(self) -> dict[str, float]:
        return {
            "head_pitch": self.pose.pitch,
            "head_roll": self.pose.roll,
            "head_yaw": self.pose.yaw,
            "antenna_left": self.antennas.left,
            "antenna_right": self.antennas.right,
            "body_yaw": self.body_yaw,
        }

    def owns(self, axis: str) -> bool:
        return self.owned_axes is None or axis in self.owned_axes


@dataclass
class _Request:
    target: MotionTarget
    source: MotionTarget
    started: float
    duration: float
    active: bool = True


class MotionWorker:
    """Mix, limit and write actuator targets at 50 Hz on one owner thread."""

    def __init__(
        self,
        client: HeadActuator,
        profile: BodyProfile,
        *,
        threaded: bool = False,
        clock: Callable[[], float] = time.monotonic,
        speech_rms_provider: Callable[[], float] | None = None,
        initial_target: MotionTarget | None = None,
        state_feed_factory: Callable[[], StateFeed] | None = None,
    ) -> None:
        self._client = client
        self._profile = profile
        self._clock = clock
        self._speech_rms_provider = speech_rms_provider
        self._state_feed_factory = state_feed_factory
        self._state_feed: StateFeed | None = None
        self._feed_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        neutral = MotionTarget()
        self._requests = {
            layer: _Request(neutral, neutral, clock(), 0.0, False) for layer in MotionLayer
        }
        self._output = (initial_target or neutral).axes()
        self._velocity = {axis: 0.0 for axis in self._output}
        self._last_tick: float | None = None
        self._last_write: MotionTarget | None = initial_target or neutral
        self._last_write_axes: set[str] = set()
        self._target_axes: set[str] = set()
        self._initialized_axes: set[str] = set()
        self._release_axes: set[str] = set()
        self._force_write = False
        self._release_axes: set[str] = set()
        self._stopped = False
        self._safety_stop = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._dropped_cues = 0
        self._speech_rms = 0.0
        self._speech_energy = 0.0
        self._speech_active = False
        self._speech_target: MotionTarget | None = None
        self._speak_enabled = False
        self._sequence: list[tuple[MotionTarget, float]] = []
        self._sequence_layer: MotionLayer | None = None
        if threaded:
            self.start()

    @property
    def dropped_cues(self) -> int:
        return self._dropped_cues

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_target(self) -> MotionTarget:
        with self._lock:
            return self._target_from_axes(self._output)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._state_feed_factory is not None:
            self._feed_thread = threading.Thread(
                target=self._read_state_feed, name="expression-state-feed", daemon=True
            )
            self._feed_thread.start()
        self._thread = threading.Thread(target=self._run, name="expression-motion", daemon=True)
        self._thread.start()

    def close(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._state_feed is not None:
            self._state_feed.close()
        if self._feed_thread is not None:
            self._feed_thread.join(timeout=timeout)
        self._running = False

    def set_layer(
        self,
        layer: MotionLayer,
        *,
        pose: HeadPose | None = None,
        antennas: AntennaPositions | None = None,
        body_yaw: float | None = None,
        duration_s: float | None = None,
    ) -> None:
        """Replace one layer's target; unspecified axes return to neutral."""
        now = self._clock()
        owned = set()
        if pose is not None:
            owned.update(("head_pitch", "head_roll", "head_yaw"))
        if antennas is not None:
            owned.update(("antenna_left", "antenna_right"))
        if body_yaw is not None:
            owned.add("body_yaw")
        target = MotionTarget(
            pose=pose or HeadPose(),
            antennas=antennas or AntennaPositions(left=0.0, right=0.0),
            body_yaw=body_yaw or 0.0,
            owned_axes=frozenset(owned),
        )
        with self._lock:
            old = self._requests[layer].target
            duration = duration_s if duration_s is not None else entry_blend_seconds(old, target)
            self._requests[layer] = _Request(target, self._requests[layer].target, now, duration)
            self._requests[layer].active = bool(owned)
            self._force_write = bool(owned)
            self._target_axes = set(owned)
            self._stopped = False
            self._safety_stop.clear()

    def submit_sequence(self, layer: MotionLayer, steps: list[tuple[MotionTarget, float]]) -> None:
        """Run a discrete primitive's target steps through the same mixer."""
        if not steps:
            self.clear_layer(layer)
            return
        self._sequence_layer = layer
        self._sequence = list(steps)
        first, duration = self._sequence.pop(0)
        if not self._sequence:
            self._sequence_layer = None
        self.set_layer(
            layer,
            pose=first.pose if first.owns("head_pitch") else None,
            antennas=first.antennas if first.owns("antenna_left") else None,
            body_yaw=first.body_yaw if first.owns("body_yaw") else None,
            duration_s=duration,
        )

    def clear_layer(self, layer: MotionLayer) -> None:
        with self._lock:
            old = self._requests[layer]
            self._release_axes.update(
                old.target.axes() if old.target.owned_axes is None else old.target.owned_axes
            )
            self._requests[layer] = _Request(MotionTarget(), old.target, self._clock(), 0.0, False)
            self._requests[layer].active = False
            self._force_write = False
            self._release_axes = set(
                old.target.axes() if old.target.owned_axes is None else old.target.owned_axes
            )
            if self._sequence_layer == layer:
                self._sequence.clear()
                self._sequence_layer = None

    def set_speech_rms(self, rms: float) -> None:
        """Feed measured playback energy; no transcript or generated text enters."""
        self._speech_rms = max(0.0, rms)
        self._speak_enabled = True

    def drop_stale_target(self) -> None:
        self._dropped_cues += 1

    def flush(self, *, real_time: bool = False) -> None:
        """Drive a finite sequence without an owner thread; tests may use virtual time."""
        if self._running:
            return
        now = self._clock()
        with self._lock:
            remaining = sum(duration for _, duration in self._sequence)
            settling = 0.0
            for request in self._requests.values():
                if not request.active:
                    continue
                delta = request.target.axes()
                settling = max(
                    settling,
                    max(
                        (
                            abs(delta[axis] - self._output[axis]) / _RATE_LIMITS[axis]
                            + _RATE_LIMITS[axis] / _ACCEL_LIMITS[axis]
                            for axis in delta
                            if request.target.owns(axis)
                        ),
                        default=0.0,
                    ),
                )
            deadline = (
                max(
                    [
                        now,
                        *(
                            request.started + request.duration
                            for request in self._requests.values()
                            if request.active
                        ),
                    ]
                )
                + remaining
                + settling
            )
        if not real_time:
            steps = max(1, math.ceil((deadline - now) / _PERIOD_S) + 1)
            for _ in range(min(steps, 500)):
                if self._safety_stop.is_set():
                    break
                self.tick(now)
                now += _PERIOD_S
            return
        while self._clock() <= deadline + _PERIOD_S and not self._safety_stop.is_set():
            self.tick()
            time.sleep(_PERIOD_S)

    def stop(self) -> None:
        """Stop bypasses blending and issues the actuator hold immediately."""
        self._safety_stop.set()
        self._client.hold()
        self._stopped = True
        self._sequence.clear()
        self._sequence_layer = None
        for request in self._requests.values():
            request.active = False

    def tick(self, now: float | None = None) -> MotionTarget:
        """Advance once and issue one bounded set_target, for tests and the thread."""
        if self._safety_stop.is_set():
            return self._target_from_axes(self._output)
        stamp = self._clock() if now is None else now
        with self._lock:
            if self._stopped:
                return self._target_from_axes(self._output)
            self._advance_sequence(stamp)
            if self._speech_rms_provider is not None:
                self._speech_rms = max(0.0, self._speech_rms_provider())
                self._speak_enabled = True
            dt = (
                _PERIOD_S
                if self._last_tick is None
                else min(max(stamp - self._last_tick, 0.0), _MAX_DT_S)
            )
            self._last_tick = stamp
            raw = self._mix(stamp)
            self._update_speech_layer(dt, stamp)
            raw = self._mix(stamp)
            alpha_tau = 0.065
            if self._is_relaxing(raw):
                alpha_tau = 0.120
            alpha = 1.0 - math.exp(-dt / alpha_tau) if dt > 0 else 0.0
            limited: dict[str, float] = {}
            for axis, target in raw.items():
                if abs(target - self._output[axis]) < 2e-4:
                    self._velocity[axis] = 0.0
                    limited[axis] = target
                    continue
                filtered = self._output[axis] + alpha * (target - self._output[axis])
                rate = _RATE_LIMITS[axis]
                accel = _ACCEL_LIMITS[axis]
                desired_velocity = max(
                    -rate, min(rate, (filtered - self._output[axis]) / max(dt, 1e-9))
                )
                max_dv = accel * dt
                velocity = max(
                    self._velocity[axis] - max_dv,
                    min(self._velocity[axis] + max_dv, desired_velocity),
                )
                value = self._output[axis] + velocity * dt
                low, high = axis_bounds_rad(self._profile.axis(axis))
                limited[axis] = min(high, max(low, value))
                self._velocity[axis] = velocity
            self._output = limited
            target = self._target_from_axes(limited)
            if self._same_target(target, self._last_write) and not self._force_write:
                return target
            changed = {
                axis
                for axis, value in target.axes().items()
                if self._last_write is None or abs(value - self._last_write.axes()[axis]) >= 1e-7
            }
            if self._force_write:
                for request in self._requests.values():
                    if request.active:
                        changed.update(
                            request.target.axes().keys()
                            if request.target.owned_axes is None
                            else request.target.owned_axes
                        )
                self._force_write = False
            changed.update(self._release_axes)
            self._release_axes.clear()
            changed.update(self._target_axes - self._initialized_axes)
            self._initialized_axes.update(self._target_axes)
            self._target_axes.clear()
            if self._last_write is not None and not self._same_target(target, self._last_write):
                # A request that releases axes back to rest still has to
                # transmit those axes even when the numerical delta is tiny.
                previous_active = set()
                current_active = set()
                for axis in target.axes():
                    if any(req.active and req.target.owns(axis) for req in self._requests.values()):
                        current_active.add(axis)
                    if axis in self._last_write_axes:
                        previous_active.add(axis)
                changed.update(previous_active - current_active)
            pose = target.pose if changed & {"head_pitch", "head_roll", "head_yaw"} else None
            antennas = target.antennas if changed & {"antenna_left", "antenna_right"} else None
            body_yaw = target.body_yaw if "body_yaw" in changed else None
            if pose is not None or antennas is not None or body_yaw is not None:
                self._client.set_target(pose=pose, antennas=antennas, body_yaw=body_yaw)
            if self._safety_stop.is_set():
                self._client.hold()
            self._last_write = target
            self._last_write_axes = set(changed)
            return target

    def _mix(self, now: float) -> dict[str, float]:
        values = {layer: self._request_value(layer, now) for layer in MotionLayer}
        result: dict[str, float] = {}
        for axis in self._output:
            active = {
                layer
                for layer, request in self._requests.items()
                if request.active and request.target.owns(axis)
            }
            speech_axis = (
                axis in ("head_pitch", "antenna_left", "antenna_right")
                and self._speech_target is not None
            )
            if not active:
                result[axis] = (
                    self._speech_target.axes()[axis] if speech_axis else self._output[axis]
                )
            elif MotionLayer.SAFETY in active or MotionLayer.SERVICE in active:
                result[axis] = values[min(active)][axis]
            elif (
                axis in ("head_pitch", "head_yaw")
                and {
                    MotionLayer.GAZE,
                    MotionLayer.EXPRESSION,
                }
                <= active
            ):
                result[axis] = (
                    0.7 * values[MotionLayer.GAZE][axis]
                    + 0.3 * values[MotionLayer.EXPRESSION][axis]
                )
            elif MotionLayer.EXPRESSION in active:
                result[axis] = values[MotionLayer.EXPRESSION][axis]
            elif MotionLayer.GAZE in active:
                result[axis] = values[MotionLayer.GAZE][axis]
            elif MotionLayer.IDLE in active:
                result[axis] = values[MotionLayer.IDLE][axis]
            elif speech_axis:
                result[axis] = self._speech_target.axes()[axis]
            else:
                result[axis] = self._output[axis]
        return result

    def _request_value(self, layer: MotionLayer, now: float) -> dict[str, float]:
        request = self._requests[layer]
        start, end = request.source.axes(), request.target.axes()
        if request.duration <= 0:
            return end
        progress = min(1.0, max(0.0, (now - request.started) / request.duration))
        eased = progress * progress * (3.0 - 2.0 * progress)
        return {axis: start[axis] + (end[axis] - start[axis]) * eased for axis in end}

    def _advance_sequence(self, now: float) -> None:
        layer = self._sequence_layer
        if layer is None or not self._sequence:
            return
        request = self._requests[layer]
        if now - request.started < request.duration:
            return
        target, duration = self._sequence.pop(0)
        self.set_layer(
            layer,
            pose=target.pose if target.owns("head_pitch") else None,
            antennas=target.antennas if target.owns("antenna_left") else None,
            body_yaw=target.body_yaw if target.owns("body_yaw") else None,
            duration_s=duration,
        )
        if not self._sequence:
            self._sequence_layer = None

    def _update_speech_layer(self, dt: float, now: float) -> None:
        if not self._speak_enabled:
            return
        # RMS to dBFS; open at -35 dBFS, close at -45 dBFS, with 0.2 s lag.
        db = 20.0 * math.log10(max(self._speech_rms, 1e-6))
        if self._speech_active:
            if db <= -45.0:
                self._speech_active = False
        elif db >= -35.0:
            self._speech_active = True
        energy = 0.0 if not self._speech_active else min(1.0, max(0.0, (db + 45.0) / 25.0))
        alpha = 1.0 - math.exp(-dt / 0.2) if dt > 0 else 0.0
        self._speech_energy += alpha * (energy - self._speech_energy)
        if not self._speech_active and self._speech_energy < 0.01:
            self._speech_energy = 0.0
        scale = self._speech_energy
        spec = self._profile
        from .envelope import REACHY_MINI_EXPRESSION_ENVELOPE

        envelope = REACHY_MINI_EXPRESSION_ENVELOPE["speak"]
        pose = HeadPose(
            pitch=axis_bounds_rad(spec.axis("head_pitch"))[1] * envelope.pitch_fraction * scale
        )
        antennas = AntennaPositions(
            left=axis_bounds_rad(spec.axis("antenna_left"))[1] * envelope.antenna_fraction * scale,
            right=axis_bounds_rad(spec.axis("antenna_right"))[1]
            * envelope.antenna_fraction
            * scale,
        )
        self._speech_target = MotionTarget(
            pose=pose,
            antennas=antennas,
            owned_axes=frozenset(("head_pitch", "antenna_left", "antenna_right")),
        )
        request = self._requests[MotionLayer.EXPRESSION]
        if request.active and request.target.owns("head_pitch"):
            # Speech modulation only substitutes the pitch axis while an
            # explicit speak primitive owns the expression layer.
            pass

    def _is_relaxing(self, target: dict[str, float]) -> bool:
        return any(abs(value) < abs(self._output[axis]) - 1e-8 for axis, value in target.items())

    def _target_from_axes(self, axes: dict[str, float]) -> MotionTarget:
        return MotionTarget(
            pose=HeadPose(pitch=axes["head_pitch"], roll=axes["head_roll"], yaw=axes["head_yaw"]),
            antennas=AntennaPositions(left=axes["antenna_left"], right=axes["antenna_right"]),
            body_yaw=axes["body_yaw"],
        )

    @staticmethod
    def _same_target(left: MotionTarget, right: MotionTarget | None) -> bool:
        return right is not None and all(
            abs(a - b) < 1e-7 for a, b in zip(left.axes().values(), right.axes().values())
        )

    def _run(self) -> None:
        deadline = self._clock()
        while not self._stop_event.is_set():
            self.tick()
            deadline += _PERIOD_S
            self._stop_event.wait(max(0.0, deadline - self._clock()))

    def _read_state_feed(self) -> None:
        try:
            feed = self._state_feed_factory()
            self._state_feed = feed
            for frame in feed:
                if self._stop_event.is_set():
                    return
                self._apply_observation(frame)
        except Exception:
            if not self._stop_event.is_set():
                import logging

                logging.getLogger(__name__).warning("expression state feed failed", exc_info=True)

    def _apply_observation(self, frame: StateFrame) -> None:
        with self._lock:
            if frame.head_pose is not None:
                self._output.update(
                    head_pitch=frame.head_pose.pitch,
                    head_roll=frame.head_pose.roll,
                    head_yaw=frame.head_pose.yaw,
                )
            if frame.antennas is not None:
                self._output.update(
                    antenna_left=frame.antennas.left,
                    antenna_right=frame.antennas.right,
                )
            if frame.body_yaw is not None:
                self._output["body_yaw"] = frame.body_yaw
            self._last_write = self._target_from_axes(self._output)
            self._last_write_axes.clear()
            self._target_axes.clear()


_RATE_LIMITS = {
    "head_yaw": 1.0,
    "head_pitch": 0.7,
    "head_roll": 0.2,
    "antenna_left": 2.0,
    "antenna_right": 2.0,
    "body_yaw": 0.5,
}
_ACCEL_LIMITS = {
    "head_yaw": 4.0,
    "head_pitch": 4.0,
    "head_roll": 4.0,
    "antenna_left": 8.0,
    "antenna_right": 8.0,
    "body_yaw": 4.0,
}


def entry_blend_seconds(start: MotionTarget, end: MotionTarget) -> float:
    """Distance-scaled primitive entry blend; constants are UNMEASURED defaults."""
    a, b = start.axes(), end.axes()
    owned = end.owned_axes if end.owned_axes is not None else frozenset(b)
    head_axes = owned & {"head_pitch", "head_roll", "head_yaw"}
    antenna_axes = owned & {"antenna_left", "antenna_right"}
    head_mm = max((abs(b[key] - a[key]) for key in head_axes), default=0.0) * 1000.0
    antenna_deg = max((math.degrees(abs(b[key] - a[key])) for key in antenna_axes), default=0.0)
    body_deg = math.degrees(abs(b["body_yaw"] - a["body_yaw"])) if "body_yaw" in owned else 0.0
    raw = max(0.015 * head_mm, 0.005 * antenna_deg, 0.015 * body_deg)
    if raw < 0.15:
        return 0.0
    return min(1.5, max(0.2, raw))
