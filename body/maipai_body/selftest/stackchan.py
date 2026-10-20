"""BOT-SELF-TEST-01: the StackChan's seven part checks, one per part.

The context carries injectable callables, so the tests run against fakes and
the real wiring passes the real ones. Nothing the checks learn about audio,
the hub's answer or the camera is kept: the results carry a line of detail
and a fix, never the reply text, the frames or the picture bytes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from maipai_body.hal.seam import Look
from maipai_body.indicator import looks
from maipai_body.selftest.core import Check, Status

SKIP_FIX = "This robot cannot run this check."
MOVEMENT_FIX = "The head did not move. Check the power cable and that nothing blocks it."
WAKE_FIX = (
    "The wake word was not heard. Check the firmware log for 'Model 0:' at boot; "
    "if it is missing the wake word model is not loaded."
)
HUB_FIX = "The hub did not answer. Check that the Bot is paired and the hub is reachable."
CAMERA_FIX = "No picture came back. Reconnect the robot and retry."

SPEECH_LINE = "Speech check. One, two, three."
HUB_QUESTION = "Reply with the single word ready."

_LED_KEYS = (
    looks.LookKey.IDLE,
    looks.LookKey.LISTENING,
    looks.LookKey.LIVE,
    looks.LookKey.CAMERA,
    looks.LookKey.CHARGING,
)


@dataclass
class StackChanSelfTestContext:
    """The callables the seven checks run against; a None means the part is
    absent and that check is skipped."""

    look_writer: Callable[[Look | None], object] | None = None
    head_angles: Callable[[], Mapping[str, int]] | None = None
    set_head: Callable[[int | None, int | None], object] | None = None
    listen_frames: Callable[[float], tuple[int, float]] | None = None
    wake_heard: Callable[[float], bool] | None = None
    speak: Callable[[str], object] | None = None
    ask_hub: Callable[[str], tuple[str, Mapping[str, float]]] | None = None
    take_photo: Callable[[], bytes | None] | None = None
    decodes_as_jpeg: Callable[[bytes], bool] | None = None
    hold_s: float = 1.0
    sleep: Callable[[float], None] = time.sleep


def _skip() -> tuple[Status, str, str]:
    return (Status.SKIP, "Not available on this robot.", SKIP_FIX)


def stackchan_checks(ctx: StackChanSelfTestContext) -> list[Check]:
    """The seven checks in order: led, movement, hearing, wakeword, speech,
    reply, camera."""

    def led() -> tuple[Status, str, str]:
        if ctx.look_writer is None:
            return _skip()
        writer = ctx.look_writer
        for key in _LED_KEYS:
            colour, weight, style = looks.LOOKS[key]
            writer(
                Look(
                    colour=colour,
                    brightness=max(weight, 0.5),
                    style=style,
                    period_s=looks.period_s(key),
                )
            )
            ctx.sleep(ctx.hold_s)
        writer(None)
        return (
            Status.PASS,
            "Showed 5 looks: idle, listening, live, camera, charging. "
            "Watch the ring: white, blue, green, pink, green breathing.",
            "",
        )

    def movement() -> tuple[Status, str, str]:
        if ctx.head_angles is None or ctx.set_head is None:
            return _skip()
        start = ctx.head_angles()
        yaw0 = start["yaw"]
        pitch0 = start["pitch"]
        ctx.set_head(yaw0 + 4, pitch0)
        moved = ctx.head_angles()["yaw"]
        if abs(moved - yaw0) < 2:
            return (
                Status.FAIL,
                f"Yaw moved {abs(moved - yaw0)} degrees, expected at least 2.",
                MOVEMENT_FIX,
            )
        ctx.set_head(yaw0, pitch0)
        back = ctx.head_angles()["yaw"]
        if abs(back - yaw0) > 2:
            return (
                Status.FAIL,
                f"Head was {abs(back - yaw0)} degrees off its starting position.",
                MOVEMENT_FIX,
            )
        return (Status.PASS, "Moved the head 4 degrees and back.", "")

    def hearing() -> tuple[Status, str, str]:
        if ctx.listen_frames is None:
            return _skip()
        frames, peak = ctx.listen_frames(3.0)
        detail = f"Heard {frames} frames, peak level {peak:.3f}"
        if frames == 0:
            return (
                Status.FAIL,
                detail,
                "No audio arrived. Reconnect the robot and check its microphone.",
            )
        if peak <= 0.01:
            return (
                Status.FAIL,
                detail,
                "Audio arrived but silent. Speak near the robot and retry.",
            )
        return (Status.PASS, detail, "")

    def wakeword() -> tuple[Status, str, str]:
        if ctx.wake_heard is None:
            return _skip()
        if ctx.wake_heard(10.0):
            return (Status.PASS, "Heard the wake word.", "")
        return (
            Status.FAIL,
            "Say the wake word within 10 seconds. The wake word was not heard.",
            WAKE_FIX,
        )

    def speech() -> tuple[Status, str, str]:
        if ctx.speak is None:
            return _skip()
        ctx.speak(SPEECH_LINE)
        return (Status.PASS, "Spoke the test line.", "")

    def reply() -> tuple[Status, str, str]:
        if ctx.ask_hub is None:
            return _skip()
        try:
            answer, timings = ctx.ask_hub(HUB_QUESTION)
        except Exception as exc:
            return (Status.FAIL, f"{type(exc).__name__}: {exc}", HUB_FIX)
        if not answer:
            return (Status.FAIL, "The hub sent back an empty answer.", HUB_FIX)
        # The answer text itself is never shown: only the step timings.
        parts = ", ".join(f"{step} {seconds:.1f} s" for step, seconds in timings.items())
        detail = "Replied through the hub." if not parts else f"Replied through the hub. {parts}"
        return (Status.PASS, detail, "")

    def camera() -> tuple[Status, str, str]:
        if ctx.take_photo is None or ctx.decodes_as_jpeg is None:
            return _skip()
        photo = ctx.take_photo()
        if photo is None or not ctx.decodes_as_jpeg(photo):
            return (Status.FAIL, "No usable picture came back.", CAMERA_FIX)
        del photo
        return (Status.PASS, "Took a picture and it decodes as a JPEG.", "")

    return [
        Check(name="led", title="LED looks", needs=("robot.eyes",), run=led),
        Check(name="movement", title="Head movement", needs=("robot.head",), run=movement),
        Check(name="hearing", title="Hearing", needs=("robot.audio",), run=hearing),
        Check(name="wakeword", title="Wake word", needs=("robot.audio",), run=wakeword),
        Check(name="speech", title="Speech", needs=("robot.speech",), run=speech),
        Check(name="reply", title="Hub reply", needs=("robot.hub",), run=reply),
        Check(name="camera", title="Camera", needs=("robot.camera",), run=camera),
    ]
