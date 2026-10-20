"""Headless end-to-end voice path: firmware simulator -> real service -> real bridge -> the hub's
own speech clients -> stand-in hub, and back. It finds the loop-blocking class of bug (a reply that
never plays, a frozen event loop) without the unit.
"""

from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace

from stackchan_sim import StackChanFirmware
from websockets.asyncio.server import serve

import maipai_body.bodies.stackchan.turn as turn_module
from maipai_body.bodies.stackchan.avatar.server import control_avatar
from maipai_body.bodies.stackchan.turn import StackChanTurnBridge
from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer
from maipai_body.measure.stand_in_hub import StandInHub
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient

DEVICE_ID = "02:00:00:00:00:77"
CLIENT_ID = "00000000-0000-4000-8000-000000000077"
APOLOGY = "I couldn't understand that. Please try again."


class VoiceEndToEnd(unittest.IsolatedAsyncioTestCase):
    hub_options: dict = {}

    async def asyncSetUp(self) -> None:
        self.hub = StandInHub(**self.hub_options)
        self.hub.start()
        self.pairing = PairingStore()
        self.service = XiaozhiServer(self.pairing, robot=None)
        link = SimpleNamespace(
            hub_client=SimpleNamespace(
                session_cookie=self.hub.session_cookie, active_base_url=self.hub.http_url
            ),
            pairing_store=SimpleNamespace(load=lambda: SimpleNamespace(base_url=self.hub.http_url)),
        )
        self.expression_log: list[str] = []
        self.bridge = StackChanTurnBridge(
            self.service,
            link,
            SimpleNamespace(speaker=None),
            stt_factory=lambda base, cookie: SttStreamClient(self.hub.stt_url, cookie),
            turn_factory=TurnClient,
            tts_factory=TtsPlaybackClient,
        )
        self.service.audio_handler = self.bridge.on_audio
        self.service.turn_handler = self.bridge.listen
        self.server = await serve(self.service.handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.pairing.request(DEVICE_ID, CLIENT_ID)
        token = self.pairing.approve(DEVICE_ID, CLIENT_ID)
        self.device = StackChanFirmware(
            f"ws://127.0.0.1:{port}", token, device_id=DEVICE_ID, client_id=CLIENT_ID
        )
        await self.device.start()
        await self.device.wait_connected()
        self.lag: list[float] = []
        self._probe = asyncio.create_task(self._loop_lag_probe())

    async def asyncTearDown(self) -> None:
        self._probe.cancel()
        await self.device.stop()
        self.server.close()
        await self.server.wait_closed()
        self.bridge.close()
        await asyncio.to_thread(self.hub.stop)

    async def _loop_lag_probe(self) -> None:
        """How late does a 10 ms sleep wake? A blocked event loop shows up here."""
        while True:
            started = time.monotonic()
            await asyncio.sleep(0.01)
            self.lag.append(time.monotonic() - started - 0.01)

    async def wait_until(self, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        self.assertTrue(predicate(), "condition did not become true before the deadline")

    async def speak_a_phrase(self, *, frames: int = 14, tap: bool = True) -> float:
        """A tap (or wake word), the tone hold, then a spoken phrase. Returns when speech ended."""
        await self.device.send_listen("start" if tap else "detect", "auto")
        await asyncio.sleep(turn_module.POPUP_HOLD_S + 0.05)
        await self.device.stream_opus(frames)
        return self.device.uplink_log[-1][0]


class AnsweredTurnTests(VoiceEndToEnd):
    hub_options = {"stt_min_blocks": 2, "tts_seconds": 0.4}

    async def test_tap_phrase_reaches_hub_and_audio_returns_within_2s(self):
        ended = await self.speak_a_phrase()
        await self.wait_until(lambda: len(self.device.downlink_log) > 3)
        self.assertGreaterEqual(self.hub.stt_blocks_received[0], 2)  # real audio reached the hub
        self.assertLess(self.device.downlink_log[0][0] - ended, 2.0)
        self.assertTrue(self.hub.tts_requests)  # the reply was synthesized

    async def test_tts_start_precedes_first_frame_and_loop_never_blocks_over_100ms(self):
        await self.speak_a_phrase()
        await self.wait_until(lambda: len(self.device.downlink_log) > 3)
        starts = [t for t, frame in self.device.tts_events if frame.get("state") == "start"]
        self.assertTrue(starts)
        self.assertLess(starts[0], self.device.downlink_log[0][0])
        await self.wait_until(
            lambda: any(f.get("state") == "stop" for _, f in self.device.tts_events)
        )
        self.assertLess(max(self.lag), 0.25, f"the event loop stalled: {max(self.lag):.3f} s")

    async def test_face_is_reset_to_neutral_before_the_tts_stop(self):
        await self.speak_a_phrase()
        await self.wait_until(
            lambda: any(f.get("state") == "stop" for _, f in self.device.tts_events)
        )
        self.assertTrue(
            any(f.get("emotion") == "neutral" for f in self.device.llm_frames),
            "the face must be set neutral in order with the end of the reply",
        )

    async def test_mcp_calls_answer_during_a_reply_with_slow_tool_replies(self):
        self.device.tool_latency_s = 0.2
        client = XiaozhiDeviceClient(self.service)
        await self.speak_a_phrase()
        await self.wait_until(lambda: len(self.device.downlink_log) > 1)
        started = time.monotonic()
        angles = await asyncio.to_thread(client.get_head_angles)  # during the reply
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIn("yaw", angles)

    async def test_avatar_channel_down_still_speaks_and_sets_emotion_over_voice_socket(self):
        async def refusing(device_id, frame):
            raise ConnectionError("StackChan avatar channel is not connected.")

        self.service._avatar_frame_sender = refusing
        client = XiaozhiDeviceClient(self.service)
        await asyncio.to_thread(client.send_avatar_frame, control_avatar("doubt"))
        await self.wait_until(
            lambda: any(f.get("emotion") == "doubtful" for f in self.device.llm_frames)
        )
        await self.speak_a_phrase()
        await self.wait_until(lambda: len(self.device.downlink_log) > 3)  # and it still speaks

    async def test_uplink_inside_the_tone_hold_is_dropped_and_the_rest_kept(self):
        await self.device.send_listen("start", "auto")
        await self.device.stream_opus(3)  # right away: this is the pop-up tone
        await asyncio.sleep(turn_module.POPUP_HOLD_S + 0.05)
        await self.device.stream_opus(10)
        await self.wait_until(lambda: self.hub.stt_blocks_received)
        self.assertEqual(self.bridge._popup_dropped, 3)
        self.assertGreaterEqual(self.hub.stt_blocks_received[0], 2)


class NoSpeechTests(VoiceEndToEnd):
    hub_options = {"stt_results": ["no_speech", "what time is it"], "tts_seconds": 0.3}

    async def test_early_no_speech_keeps_listening_and_still_answers(self):
        await self.device.send_listen("start", "auto")
        await asyncio.sleep(turn_module.POPUP_HOLD_S + 0.05)
        await self.device.stream_opus(14, realtime=True)
        await self.wait_until(lambda: len(self.device.downlink_log) > 3, timeout=8.0)
        self.assertEqual(len(self.hub.stt_handshakes), 2)  # a fresh stream opened
        self.assertNotIn(APOLOGY, self.hub.tts_requests)


class SilentRoomTests(VoiceEndToEnd):
    hub_options = {"stt_results": ["no_speech"] * 20}

    async def test_silence_speaks_nothing_and_sends_the_device_to_idle(self):
        original = turn_module.WAKE_PATIENCE_S
        turn_module.WAKE_PATIENCE_S = 1.2  # the real patience is 6 s; keep the test short
        self.addCleanup(setattr, turn_module, "WAKE_PATIENCE_S", original)
        await self.device.send_listen("start", "auto")
        await asyncio.sleep(turn_module.POPUP_HOLD_S + 0.05)
        await self.device.stream_opus(4, realtime=True)
        await self.wait_until(
            lambda: any(f.get("command") == "idle" for f in self.device.system_frames),
            timeout=8.0,
        )
        self.assertEqual(self.hub.tts_requests, [])  # not a single spoken line
        self.assertEqual(self.device.downlink_log, [])


if __name__ == "__main__":
    unittest.main()
