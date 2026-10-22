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

# Held off 2026-10-22 (owner): no picture goes to Home for a model caption until the Look design
# (docs/design/look-component-2026-10-22.md in the home repo) is ruled on. The poster stays, tested,
# for when it is wanted again; the app does not create one while this is False.
PICTURE_POSTS_ENABLED = False
MAX_FRAME_BYTES = 512 * 1024
SCENE_MIN_GAP_S = 10.0
SCENE_REFRESH_S = 60.0
SCENE_STALE_S = 300.0  # post even an unchanged scene this often, so Home's look does not go cold
MAX_INTERVAL_S = 600.0
NO_VISION_BACKOFF_S = 60.0
TOO_FAST_BACKOFF_S = 10.0
THUMB_CHANGE = 6.0  # mean gray change (0..255) that counts as a different scene
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


def thumbnail(frame_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
    """A tiny gray picture (about 12 by 16) to tell whether a scene changed; never sent anywhere."""
    sample = frame_bgr[::20, ::20].astype(np.float32)
    return 0.114 * sample[:, :, 0] + 0.587 * sample[:, :, 1] + 0.299 * sample[:, :, 2]


def differs(a: npt.NDArray[np.float32] | None, b: npt.NDArray[np.float32] | None) -> bool:
    """True when two thumbnails differ enough to be worth a new description (or one is missing)."""
    if a is None or b is None or a.shape != b.shape:
        return True
    return float(np.mean(np.abs(a - b))) >= THUMB_CHANGE


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
        self._scale = 1.0  # doubles (up to 10x) after a refusal, back to 1 after a success

    @property
    def mode(self) -> str:
        return "none" if self._vision_off else self._mode

    def set_mode(self, value: object) -> None:
        self._mode = value if isinstance(value, str) and value in MODES else "continual"
        self._vision_off = False

    def scene_due(
        self, now: float | None = None, *, bucket_changed: bool = False, differs: bool = True
    ) -> bool:
        """Time for a background picture? Slow by default: Home spends a model call on each.

        At most every SCENE_MIN_GAP_S (Home's floor); at once when the brightness bucket changed;
        otherwise every SCENE_REFRESH_S if the picture differs from the last one posted, and every
        SCENE_STALE_S even if it does not. After a refusal the intervals double, up to ten times."""
        current = self._clock() if now is None else now
        if self._mode != "continual" or self._vision_off or current < self._backoff_until:
            return False
        if self._last_scene_at is None:
            return True
        elapsed = current - self._last_scene_at
        if elapsed < SCENE_MIN_GAP_S:
            return False
        if bucket_changed:
            return True
        if elapsed >= min(MAX_INTERVAL_S, SCENE_STALE_S * self._scale):
            return True
        return differs and elapsed >= min(MAX_INTERVAL_S, SCENE_REFRESH_S * self._scale)

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
                    self._scale = 1.0
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
                    self._scale = min(10.0, self._scale * 2)
                    self._backoff_until = self._clock() + TOO_FAST_BACKOFF_S
                    result = PostResult(False, "too_fast", status)
                elif status == 503:
                    self._scale = min(10.0, self._scale * 2)
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
