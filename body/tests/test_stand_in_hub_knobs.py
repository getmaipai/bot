"""The stand-in hub's voice-path knobs for the headless tests (recognition latency, scripted
results, audio that must arrive first, chat delay, speech chunk pacing)."""

from __future__ import annotations

import json
import time

import numpy as np
import requests
from websockets.sync.client import connect

from maipai_body.measure.stand_in_hub import StandInHub


def _stt(hub: StandInHub):
    url = hub.stt_url.replace("http://", "ws://") + "/api/stt/stream"
    return connect(url, additional_headers={"Cookie": f"session={hub.session_cookie}"})


def _frames(ws, count: int) -> list[dict]:
    seen = []
    for _ in range(count):
        seen.append(json.loads(ws.recv(timeout=5)))
    return seen


def test_stt_delay_holds_back_the_final():
    with StandInHub(stt_delay_s=0.4) as hub, _stt(hub) as ws:
        assert _frames(ws, 1) == [{"t": "ready"}]
        started = time.monotonic()
        frames = _frames(ws, 2)
        assert frames[-1] == {"t": "final", "v": "hello maipai"}
        assert time.monotonic() - started >= 0.35


def test_scripted_results_are_consumed_one_per_stream_then_the_default_returns():
    with StandInHub(stt_results=["no_speech", "go"]) as hub:
        with _stt(hub) as ws:
            assert _frames(ws, 2) == [{"t": "ready"}, {"t": "no_speech"}]
        with _stt(hub) as ws:
            assert _frames(ws, 3)[-1] == {"t": "final", "v": "go"}
        with _stt(hub) as ws:
            assert _frames(ws, 3)[-1] == {"t": "final", "v": "hello maipai"}


def test_the_answer_waits_for_real_audio_and_the_count_is_recorded():
    with StandInHub(stt_min_blocks=3) as hub, _stt(hub) as ws:
        assert _frames(ws, 1) == [{"t": "ready"}]
        for _ in range(3):
            ws.send(np.zeros(160, dtype=np.float32).tobytes())
        assert _frames(ws, 2)[-1] == {"t": "final", "v": "hello maipai"}
    assert hub.stt_blocks_received == [3]


def test_without_audio_the_final_is_withheld_until_the_cap_or_an_end_frame():
    with StandInHub(stt_min_blocks=5) as hub, _stt(hub) as ws:
        assert _frames(ws, 1) == [{"t": "ready"}]
        ws.send(json.dumps({"t": "end"}))  # the client gives up: the hub stops waiting
        assert _frames(ws, 2)[-1]["t"] == "final"
    assert hub.stt_blocks_received == [0]


def test_turn_delay_and_tts_pacing_slow_the_responses():
    with StandInHub(turn_delay_s=0.3, tts_chunk_delay_s=0.15, tts_seconds=0.3) as hub:
        cookie = {"Cookie": f"session={hub.session_cookie}"}
        started = time.monotonic()
        with requests.post(
            hub.http_url + "/api/turn/stream",
            json={"surface": "robot", "text": "hi", "spoken": True},
            headers=cookie,
            stream=True,
            timeout=10,
        ) as response:
            first = next(response.iter_lines())
            assert first
            assert time.monotonic() - started >= 0.28
        started = time.monotonic()
        speech = requests.post(
            hub.http_url + "/api/tts", json={"text": "hi"}, headers=cookie, timeout=10
        )
        assert speech.status_code == 200
        assert time.monotonic() - started >= 0.14


def test_defaults_are_unchanged():
    with StandInHub() as hub, _stt(hub) as ws:
        seen = _frames(ws, 3)
    assert seen == [
        {"t": "ready"},
        {"t": "vad", "speaking": True},
        {"t": "final", "v": "hello maipai"},
    ]
    assert hub.stt_blocks_received == [0]
