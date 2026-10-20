"""Regressions from the 2026-10-19 unit bench: faces, speech start, encoder, control page."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import pytest

from maipai_body.bodies.stackchan.turn import StackChanAudioPlayback
from maipai_body.bodies.stackchan.xiaozhi.server import SPEAK_SETTLE_S, XiaozhiServer

ROOT = Path(__file__).resolve().parents[1]


class AllowPairing:
    def authorize(self, device_id, client_id, token):
        return True


class Socket:
    def __init__(self, log):
        self.log = log

    async def send(self, message):
        self.log.append(("send", json.loads(message) if isinstance(message, str) else message))


def _server(log):
    server = XiaozhiServer(AllowPairing(), robot=None)
    server._sessions["device"] = Socket(log)
    server._session_ids["device"] = "session"
    server._session_authorized = lambda _device: True
    return server


def test_face_goes_over_voice_channel_as_llm_emotion():
    log: list = []
    server = _server(log)
    assert asyncio.run(server.send_emotion("doubt")) == "doubtful"
    assert log == [("send", {"session_id": "session", "type": "llm", "emotion": "doubtful"})]
    with pytest.raises(ValueError, match="Pick one of"):
        asyncio.run(server.send_emotion("smug"))


def test_mint_skin_faces_use_the_display_names():
    log: list = []
    server = _server(log)
    assert asyncio.run(server.send_emotion("surprised")) == "surprised"
    assert asyncio.run(server.send_emotion("wink")) == "winking"


def test_face_needs_one_connected_robot():
    server = XiaozhiServer(AllowPairing(), robot=None)
    with pytest.raises(ConnectionError):
        asyncio.run(server.send_emotion("happy"))


def test_speech_waits_for_speaking_state_before_first_frame():
    log: list = []
    server = _server(log)

    async def record_sleep(delay):
        log.append(("sleep", delay))

    with patch("maipai_body.bodies.stackchan.xiaozhi.server.asyncio.sleep", record_sleep):
        asyncio.run(server.send_audio("device", [b"frame"], start=True))
    start = log.index(("send", {"session_id": "session", "type": "tts", "state": "start"}))
    assert log[start + 1] == ("sleep", SPEAK_SETTLE_S)
    assert log.index(("send", b"frame")) > start + 1


def test_speech_encoder_sends_silk_wideband_60ms_packets():
    encoder = StackChanAudioPlayback._new_encoder()
    tone = (np.sin(np.arange(24000) * 2 * np.pi * 220 / 24000) * 8000).astype(np.int16)
    packets = []
    for start in range(0, len(tone), 1440):
        frame = av.AudioFrame.from_ndarray(
            tone[start : start + 1440].reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = 24000
        packets.extend(bytes(packet) for packet in encoder.encode(frame))
    assert packets[0][0] == 0x58  # SILK wideband, one 60 ms frame
    # The default music mode sent fullband (TOC config 28 and up) 64 kbps packets of about
    # 480 bytes, which the robot decoded slower than real time.
    assert all(packet[0] >> 3 < 24 for packet in packets)
    assert sum(map(len, packets)) / len(packets) <= 200


@pytest.fixture
def control():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import stackchan_control

        yield stackchan_control
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_head_moves_stay_within_limit_of_center(control):
    center = {"yaw": 0, "pitch": 45}
    assert control.head_target(center, 30, -30, 10) == {"yaw": 10, "pitch": 35}
    assert control.head_target(center, 4, 2, 10) == {"yaw": 4, "pitch": 47}


def test_color_parsing_and_led_ceiling(control):
    assert control.parse_rgb("#ff0080") == (255, 0, 128)
    with pytest.raises(ValueError, match="#00ff40"):
        control.parse_rgb("red")
    assert 255 * control.LED_MAX // 255 == 168
