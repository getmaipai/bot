"""BOT-SELF-TEST-01: the StackChan self-test context built from the live service parts.

The checks themselves live in ``selftest/stackchan.py`` and only see callables; this module is
the one place that knows how to reach the real robot, voice bridge and hub for them. Nothing here
keeps audio, a picture or a reply: it hands back counts, levels, timings and pass or fail.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from maipai_body.hal.seam import HeadPose, Look
from maipai_body.selftest.core import CheckResult, run_selftest
from maipai_body.selftest.stackchan import StackChanSelfTestContext, stackchan_checks

_SELFTEST_HOLDER = "selftest"
_JPEG_START = b"\xff\xd8"
_JPEG_END = b"\xff\xd9"


def decodes_as_jpeg(data: bytes) -> bool:
    """A cheap structural check: the bytes start and end like a JPEG and are not tiny."""
    return len(data) > 128 and data[:2] == _JPEG_START and data[-2:] == _JPEG_END


def build_context(
    *,
    robot: Any,
    client: Any,
    light: Any,
    uplink: Any,
    link: Any,
    turn_factory: Callable[[str, str], Any],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> StackChanSelfTestContext:
    """Compose the callables the StackChan checks need.

    ``robot`` is the shared Robot object, ``client`` the device client (head angles, speech push),
    ``light`` the StackChanLightService, ``uplink`` an UplinkStats, ``link`` the hub link (cookie
    and address), ``turn_factory(base, cookie)`` builds a TurnClient.
    """

    def show(look: Look | None) -> None:
        light.show(look)

    def head_angles() -> Mapping[str, int]:
        return client.get_head_angles()

    def set_head(yaw: int | None, pitch: int | None) -> object:
        # Through the Robot object so the lease and the emergency stop are honoured.
        import math

        pose = HeadPose(
            yaw=math.radians(yaw) if yaw is not None else 0.0,
            pitch=math.radians(pitch) if pitch is not None else 0.0,
        )
        robot.lease.acquire(priority="person", holder=_SELFTEST_HOLDER)
        try:
            return robot.head.set(pose=pose)
        finally:
            robot.lease.release(holder=_SELFTEST_HOLDER)

    def speak(text: str) -> object:
        # An explicit, person-started check: it bypasses the household's proactive-speech policy.
        return client.push_action("speak", {"text": text})

    def ask_hub(question: str) -> tuple[str, Mapping[str, float]]:
        cookie = link.hub_client.session_cookie
        pairing = link.pairing_store.load()
        base = getattr(link.hub_client, "active_base_url", None) or (
            pairing.base_url if pairing else None
        )
        if not cookie or not base:
            raise RuntimeError("no hub session: the Bot is not paired or the hub is unreachable")
        started = clock()
        events = list(turn_factory(base, cookie).stream(question))
        elapsed = clock() - started
        reply = next((e.reply_text for e in reversed(events) if e.reply_text), "")
        return reply, {"chat": elapsed}

    def take_photo() -> bytes | None:
        # A visible capture: the camera cue lights as for any photo, then the bytes are dropped.
        return robot.camera.frame()

    return StackChanSelfTestContext(
        look_writer=show,
        head_angles=head_angles,
        set_head=set_head,
        listen_frames=uplink.window,
        wake_heard=uplink.wait_detect,
        speak=speak,
        ask_hub=ask_hub,
        take_photo=take_photo,
        decodes_as_jpeg=decodes_as_jpeg,
        sleep=sleep,
    )


def build_service_hooks(
    context: StackChanSelfTestContext, light: Any
) -> tuple[
    Callable[[], list[dict[str, str]]], Callable[[Sequence[str] | None], list[dict[str, object]]]
]:
    """The two callables the xiaozhi service exposes: list the checks, run some of them."""
    checks = stackchan_checks(context)

    def listing() -> list[dict[str, str]]:
        return [{"name": check.name, "title": check.title} for check in checks]

    def run(only: Sequence[str] | None) -> list[dict[str, object]]:
        with light.suspended():
            results: list[CheckResult] = run_selftest(checks, only=only)
        return [
            {
                "name": r.name,
                "status": str(r.status.value).lower(),
                "detail": r.detail,
                "fix": r.fix,
                "seconds": round(r.seconds, 2),
            }
            for r in results
        ]

    return listing, run
