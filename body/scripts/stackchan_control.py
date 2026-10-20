"""Bench control page for one paired StackChan: LED, head, face, speech and volume.

Runs the same xiaozhi (8765), avatar (8766) and vision (8767) listeners as the Bot app,
plus a control page on this computer only. Run it instead of the Bot app, never beside it.

    uv run --extra voice python scripts/stackchan_control.py --host 192.0.2.10

Then open http://127.0.0.1:8790 on this computer.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
from aiohttp import web

from maipai_body.bodies.stackchan.avatar.server import EXPRESSIONS, AvatarServer
from maipai_body.bodies.stackchan.turn import StackChanAudioPlayback
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore, default_pairing_path
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer

LOG = logging.getLogger("stackchan_control")
MAX_SAY_CHARS = 400
# The firmware's set_led_color rejects any channel above 168.
LED_MAX = 168
# Gestures are offsets from the head's position when the page connected.
GESTURES = {
    "nod": [("pitch", 1.0), ("pitch", -0.5), ("pitch", 1.0), ("pitch", 0.0)],
    "shake": [("yaw", 1.0), ("yaw", -1.0), ("yaw", 1.0), ("yaw", 0.0)],
}


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def head_target(center: dict[str, int], yaw: int, pitch: int, limit: int) -> dict[str, int]:
    """Offsets from center, each kept within +-limit degrees."""
    return {
        "yaw": center["yaw"] + clamp(yaw, -limit, limit),
        "pitch": center["pitch"] + clamp(pitch, -limit, limit),
    }


def parse_rgb(value: str) -> tuple[int, int, int]:
    """Read #rrggbb as three 0 to 255 channels."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("Color must look like #00ff40.")
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError as exc:
        raise ValueError("Color must look like #00ff40.") from exc


def speech_samples(text: str, *, say_bin: str | None = None) -> np.ndarray:
    """Speak text with this computer's own voice into 24 kHz mono float samples."""
    text = text.strip()
    if not text:
        raise ValueError("Type something for the robot to say.")
    if len(text) > MAX_SAY_CHARS:
        raise ValueError(f"Keep it under {MAX_SAY_CHARS} characters.")
    say_bin = say_bin or shutil.which("say")
    if say_bin is None:
        raise RuntimeError("This computer has no 'say' command. Run the page on a Mac.")
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp) / "speech.wav"
        subprocess.run(
            [say_bin, "--file-format=WAVE", "--data-format=LEI16@24000", "-o", str(out), text],
            check=True,
            capture_output=True,
            timeout=30,
        )
        with wave.open(str(out)) as audio:
            if audio.getframerate() != 24000 or audio.getsampwidth() != 2:
                raise RuntimeError("The 'say' command did not write 24 kHz 16-bit audio.")
            pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
            if audio.getnchannels() > 1:
                pcm = pcm.reshape(-1, audio.getnchannels())[:, 0]
    return pcm.astype(np.float32) / 32768.0


class Controller:
    """Turns page requests into device calls; every call runs off the event loop."""

    def __init__(self, voice: XiaozhiServer, avatar: AvatarServer, *, limit: int, speed: int):
        self.voice, self.avatar = voice, avatar
        self.client = XiaozhiDeviceClient(voice)
        self.limit, self.speed = limit, speed
        self.center: dict[str, int] | None = None

    def device_id(self) -> str:
        if len(self.voice._sessions) != 1:
            raise ConnectionError(
                "The robot is not connected. Check it is on and on Wi-Fi, then wait a few seconds."
            )
        return next(iter(self.voice._sessions))

    async def status(self) -> dict[str, Any]:
        if len(self.voice._sessions) != 1:
            return {"connected": False}
        device_id = self.device_id()
        result: dict[str, Any] = {
            "connected": True,
            "face_channel": device_id in self.avatar._sessions,
            "limit": self.limit,
        }
        result["battery"] = await asyncio.to_thread(self.client.get_battery_status)
        result["head"] = await asyncio.to_thread(self.client.get_head_angles)
        if self.center is None:
            self.center = dict(result["head"])
        result["center"] = self.center
        return result

    async def led(self, color: str) -> object:
        red, green, blue = (channel * LED_MAX // 255 for channel in parse_rgb(color))
        return await asyncio.to_thread(self.client.set_led_color, red, green, blue)

    async def _center(self) -> dict[str, int]:
        if self.center is None:
            self.center = dict(await asyncio.to_thread(self.client.get_head_angles))
        return self.center

    async def head(self, yaw: int, pitch: int) -> dict[str, int]:
        target = head_target(await self._center(), yaw, pitch, self.limit)
        await asyncio.to_thread(
            self.client.set_head_angles, target["yaw"], target["pitch"], self.speed
        )
        return target

    async def gesture(self, name: str) -> str:
        if name not in GESTURES:
            raise ValueError(f"Pick one of: {', '.join(GESTURES)}.")
        for axis, fraction in GESTURES[name]:
            offsets = {"yaw": 0, "pitch": 0, axis: round(self.limit * fraction)}
            await self.head(offsets["yaw"], offsets["pitch"])
            await asyncio.sleep(0.6)
        return name

    async def face(self, expression: str) -> str:
        if expression not in EXPRESSIONS:
            raise ValueError(f"Pick one of: {', '.join(EXPRESSIONS)}.")
        # The avatar socket only runs in the firmware's avatar app; AI Agent mode
        # takes the face over the voice channel instead.
        if self.device_id() in self.avatar._sessions:
            await self.avatar.send_expression(self.device_id(), expression)
        else:
            await self.voice.send_emotion(expression)
        return expression

    async def volume(self, level: int) -> object:
        return await asyncio.to_thread(self.client.set_volume, clamp(level, 0, 100))

    async def say(self, text: str) -> dict[str, int]:
        device_id = self.device_id()
        samples = await asyncio.to_thread(speech_samples, text)
        stamps: list[float] = []
        send_audio = self.voice.send_audio

        async def timed_send(*args: Any, **kwargs: Any) -> None:
            stamps.append(time.monotonic())
            await send_audio(*args, **kwargs)

        playback = StackChanAudioPlayback(self.voice, device_id)
        self.voice.send_audio = timed_send  # type: ignore[method-assign]

        def speak() -> None:
            playback.push_audio_sample(samples)
            playback.stop_playing()
            playback.end()

        try:
            await asyncio.to_thread(speak)
        finally:
            del self.voice.send_audio
        gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:], strict=False)]
        # The largest pause between frame sends shows whether this computer stalled.
        return {
            "audio_ms": round(len(samples) / 24000 * 1000),
            "sends": len(stamps),
            "max_send_gap_ms": round(max(gaps, default=0) * 1000),
        }


def build_app(controller: Controller) -> web.Application:
    async def handle(request: web.Request, action) -> web.Response:
        try:
            body = await request.json() if request.can_read_body else {}
            return web.json_response({"ok": True, "result": await action(body)})
        except (ValueError, ConnectionError, PermissionError, RuntimeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            LOG.exception("control request failed")
            return web.json_response(
                {"ok": False, "error": f"The robot did not answer ({type(exc).__name__}). Retry."},
                status=502,
            )

    def route(action):
        return lambda request: handle(request, action)

    app = web.Application()
    app.router.add_get("/", lambda _: web.Response(text=PAGE, content_type="text/html"))
    app.router.add_get("/api/status", route(lambda _: controller.status()))
    app.router.add_post("/api/led", route(lambda b: controller.led(str(b.get("color", "")))))
    app.router.add_post(
        "/api/head",
        route(lambda b: controller.head(int(b.get("yaw", 0)), int(b.get("pitch", 0)))),
    )
    app.router.add_post("/api/gesture", route(lambda b: controller.gesture(str(b.get("name")))))
    app.router.add_post("/api/face", route(lambda b: controller.face(str(b.get("face")))))
    app.router.add_post("/api/volume", route(lambda b: controller.volume(int(b.get("level", 60)))))
    app.router.add_post("/api/say", route(lambda b: controller.say(str(b.get("text", "")))))
    return app


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StackChan control</title><style>
body{font:16px system-ui;margin:16px;max-width:560px}
fieldset{margin:0 0 12px;border:1px solid #bbb;border-radius:8px}
button{margin:4px;padding:8px 12px;font:inherit}
input[type=range]{width:100%}#log{white-space:pre-wrap;color:#555}
</style></head><body><h1>StackChan control</h1><p id="status">Checking...</p>
<fieldset><legend>Light</legend><input type="color" id="color" value="#00c040">
<button onclick="post('led',{color:color.value})">Set</button>
<button onclick="post('led',{color:'#000000'})">Off</button></fieldset>
<fieldset><legend>Head (offset from rest, degrees)</legend>
Turn <input type="range" id="yaw" value="0" step="1">
Tilt <input type="range" id="pitch" value="0" step="1">
<button onclick="post('head',{yaw:+yaw.value,pitch:+pitch.value})">Move</button>
<button onclick="yaw.value=0;pitch.value=0;post('head',{yaw:0,pitch:0})">Rest</button>
<button onclick="post('gesture',{name:'nod'})">Nod</button>
<button onclick="post('gesture',{name:'shake'})">Shake</button></fieldset>
<fieldset><legend>Face</legend><span id="faces"></span></fieldset>
<fieldset><legend>Say</legend><input id="text" size="40" value="Hello, I am StackChan.">
<button onclick="post('say',{text:text.value})">Say</button>
Volume <input type="range" id="vol" min="0" max="100" value="60"
onchange="post('volume',{level:+vol.value})"></fieldset><div id="log"></div>
<script>
const FACES=%FACES%;
faces.innerHTML=FACES.map(f=>`<button onclick="post('face',{face:'${f}'})">${f}</button>`).join('');
async function post(path,body){log.textContent='Sending '+path+'...';
 const r=await fetch('/api/'+path,{method:'POST',body:JSON.stringify(body)});
 const j=await r.json();log.textContent=j.ok?path+': done':path+': '+j.error;}
async function poll(){try{const j=(await (await fetch('/api/status')).json()).result;
 if(!j||!j.connected){status.textContent='Robot not connected yet.';}
 else{yaw.min=pitch.min=-j.limit;yaw.max=pitch.max=j.limit;
 status.textContent=`Connected. Battery ${j.battery.percent}%. Head yaw ${j.head.yaw}, `+
 `pitch ${j.head.pitch}. Face channel ${j.face_channel?'on':'off'}.`;}}
 catch(e){status.textContent='Control page lost: '+e;}setTimeout(poll,5000);}poll();
</script></body></html>
""".replace("%FACES%", "[" + ",".join(f'"{face}"' for face in EXPRESSIONS) + "]")


async def serve(args: argparse.Namespace) -> None:
    pairing = PairingStore(default_pairing_path())
    voice = XiaozhiServer(pairing, robot=None, vision_host=args.host, vision_port=8767)
    avatar = AvatarServer(pairing)
    await voice.start(args.host, 8765)
    await avatar.start(args.host, 8766)
    runner = web.AppRunner(build_app(Controller(voice, avatar, limit=args.limit, speed=args.speed)))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    LOG.info("Robot listeners on %s. Control page: http://127.0.0.1:%s", args.host, args.port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await avatar.close()
        await voice.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", required=True, help="This computer's LAN address.")
    parser.add_argument("--port", type=int, default=8790, help="Control page port.")
    parser.add_argument(
        "--limit", type=int, default=10, help="Largest head move from rest, in degrees."
    )
    parser.add_argument("--speed", type=int, default=100, help="Servo speed the firmware takes.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
