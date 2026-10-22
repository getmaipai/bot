"""Post a short-lived camera frame to Home for a scene description."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import requests

logger = logging.getLogger("maipai_body.bodies.stackchan.vision_post")

MAX_FRAME_BYTES = 512 * 1024
SCENE_MIN_GAP_S = 10.0
SCENE_REFRESH_S = 60.0
NO_VISION_BACKOFF_S = 60.0
TOO_FAST_BACKOFF_S = 10.0
MODES = ("continual", "on_demand", "none")
VISION_PATH = "/api/devices/me/vision"


@dataclass(frozen=True)
class PostResult:
    ok: bool
    reason: str
    status: int | None = None


def light_bucket(mean_luma: float | None, lux: float | None = None) -> str | None:
    """Classify illumination, preferring measured image luma when available."""
    if mean_luma is not None:
        if mean_luma < 35:
            return "dark"
        if mean_luma < 85:
            return "dim"
        return "bright"
    if lux is None:
        return None
    if lux < 1.5:
        return "dark"
    if lux < 5.0:
        return "dim"
    return "bright"


def mean_luma(frame_bgr: npt.NDArray[np.uint8]) -> float:
    """Return mean gray level from every fourth pixel in each dimension."""
    sample = frame_bgr[::4, ::4]
    return float(
        np.mean(0.114 * sample[:, :, 0] + 0.587 * sample[:, :, 1] + 0.299 * sample[:, :, 2])
    )


class VisionPoster:
    """Send camera frames to Home without retaining frame or response content."""

    def __init__(
        self,
        hub_credentials: Callable[[], tuple[str, str]],
        *,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 6.0,
    ) -> None:
        self._hub_credentials = hub_credentials
        self._session = session or requests.Session()
        self._clock = clock
        self._timeout = timeout
        self._mode = "continual"
        self._vision_off = False
        self._last_scene_at: float | None = None
        self._backoff_until = float("-inf")

    @property
    def mode(self) -> str:
        return "none" if self._vision_off else self._mode

    def set_mode(self, value: object) -> None:
        self._mode = value if isinstance(value, str) and value in MODES else "continual"
        self._vision_off = False

    def scene_due(self, now: float | None = None, *, changed: bool = False) -> bool:
        current = self._clock() if now is None else now
        if self._mode != "continual" or self._vision_off or current < self._backoff_until:
            return False
        if self._last_scene_at is None:
            return True
        elapsed = current - self._last_scene_at
        return elapsed >= SCENE_MIN_GAP_S and (changed or elapsed >= SCENE_REFRESH_S)

    def ask_possible(self) -> bool:
        return self._mode != "none" and not self._vision_off

    def post(
        self,
        jpeg: bytes,
        *,
        purpose: str,
        people: int | None = None,
        light: str | None = None,
        timeout: float | None = None,
    ) -> PostResult:
        result: PostResult
        status: int | None = None
        try:
            if self._mode == "none" or self._vision_off:
                result = PostResult(False, "vision_off" if self._vision_off else "mode")
            elif purpose == "scene" and self._mode != "continual":
                result = PostResult(False, "mode")
            elif len(jpeg) > MAX_FRAME_BYTES:
                result = PostResult(False, "too_big")
            elif (
                purpose == "scene"
                and self._last_scene_at is not None
                and self._clock() - self._last_scene_at < SCENE_MIN_GAP_S
            ):
                result = PostResult(False, "gap")
            else:
                cookie, base_url = self._hub_credentials()
                params: dict[str, object] = {"purpose": purpose}
                if people is not None:
                    params["people"] = min(20, max(0, people))
                if light in {"dark", "dim", "bright"}:
                    params["light"] = light
                response = self._session.post(
                    f"{base_url}{VISION_PATH}",
                    params=params,
                    data=jpeg,
                    headers={"Cookie": f"session={cookie}", "Content-Type": "image/jpeg"},
                    timeout=self._timeout if timeout is None else timeout,
                )
                status = response.status_code
                if status == 200:
                    if purpose == "scene":
                        self._last_scene_at = self._clock()
                    result = PostResult(True, "ok", status)
                elif status == 403:
                    code = response.json().get("code")
                    if code == "vision_off":
                        self._vision_off = True
                        result = PostResult(False, "vision_off", status)
                    elif code == "vision_on_demand":
                        self._mode = "on_demand"
                        result = PostResult(False, "vision_on_demand", status)
                    else:
                        result = PostResult(False, "error", status)
                elif status == 429:
                    self._backoff_until = self._clock() + TOO_FAST_BACKOFF_S
                    result = PostResult(False, "too_fast", status)
                elif status == 503:
                    self._backoff_until = self._clock() + NO_VISION_BACKOFF_S
                    result = PostResult(False, "no_vision", status)
                elif status in {400, 413, 415}:
                    result = PostResult(False, "bad_frame", status)
                else:
                    result = PostResult(False, "unreachable", status)
        except requests.RequestException:
            result = PostResult(False, "unreachable", status)
        except Exception:
            result = PostResult(False, "error", status)
        logger.info("vision post purpose=%s status=%s reason=%s", purpose, status, result.reason)
        return result
