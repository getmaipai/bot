"""Duplex, barge-in and wake-mode behavior for the StackChan turn bridge."""

import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from maipai_body.bodies.stackchan.turn import StackChanAudioPlayback, StackChanTurnBridge


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration

    async def async_sleep(self, duration):
        self.sleep(duration)


class Server:
    def __init__(self, loop=None):
        self._loop = loop
        self.sent = []
        self.stops = []
        self.gate = None

    async def send_audio(self, device, frames, **kwargs):
        self.sent.extend(frames)
        if self.gate:
            await self.gate.wait()

    async def stop_audio(self, device):
        self.stops.append(device)


class Capture:
    def __init__(self):
        self.closed = False
        self.aborted = False

    def close(self):
        self.closed = True

    def abort(self):
        self.aborted = True

    def feed_opus(self, frame):
        pass


class Playback:
    def __init__(self, server, device):
        self.server, self.device = server, device
        self.flushed = False

    def flush(self, *, send_stop=True):
        from concurrent.futures import Future

        self.flushed = True
        if send_stop:
            asyncio.run_coroutine_threadsafe(self.server.stop_audio(self.device), self.server._loop)
        future = Future()
        future.set_result(None)
        return future


class Link:
    hub_client = SimpleNamespace(session_cookie="cookie", active_base_url="http://192.0.2.10")
    pairing_store = SimpleNamespace(load=lambda: SimpleNamespace(base_url="http://192.0.2.10"))


class Offline:
    pass


def test_playback_leads_by_14_frames_then_paces_and_drains(monkeypatch):
    # The firmware drops packets once 40 frames are queued, and a burst on top of the lead
    # overflowed it; a 14-frame lead (0.84 s) leaves room for a late frame.
    clock = Clock()
    sent = []
    prebuffers = []

    async def send_audio(device, frames, **kwargs):
        sent.extend(frames)
        prebuffers.append(kwargs.get("prebuffer"))

    async def stop_audio(device):
        sent.append("stop")

    server = SimpleNamespace(_loop=None, send_audio=send_audio, stop_audio=stop_audio)
    server._loop = asyncio.new_event_loop()
    worker = threading.Thread(target=server._loop.run_forever, daemon=True)
    worker.start()
    playback = StackChanAudioPlayback(
        server, "device", clock=clock.monotonic, sleeper=clock.sleep, async_sleep=clock.async_sleep
    )
    playback._frames = [bytes([i]) for i in range(40)]
    playback._samples = np.zeros(0, dtype=np.float32)
    playback.stop_playing()
    assert len(sent) == 40
    assert prebuffers[0] == 14
    assert clock.sleeps == pytest.approx([0.06] * 26)
    playback.end()
    assert sent[-1] == "stop"
    # The paced sends took 1.56 s of the 2.4 s of audio, so the stop waits for the 0.84 s still
    # queued on the unit, plus the 0.12 s tail.
    assert clock.sleeps == pytest.approx([0.06] * 26 + [0.96])
    server._loop.call_soon_threadsafe(server._loop.stop)
    worker.join(timeout=1)
    server._loop.close()


def test_stop_waits_for_every_queued_sentence_to_play():
    # 2026-10-19 bench: the talking mouth stopped four words before the audio ended.
    clock = Clock()
    sent = []

    async def send_audio(device, frames, **kwargs):
        sent.extend(frames)

    async def stop_audio(device):
        sent.append("stop")

    server = SimpleNamespace(_loop=None, send_audio=send_audio, stop_audio=stop_audio)
    server._loop = asyncio.new_event_loop()
    worker = threading.Thread(target=server._loop.run_forever, daemon=True)
    worker.start()
    playback = StackChanAudioPlayback(
        server, "device", clock=clock.monotonic, sleeper=clock.sleep, async_sleep=clock.async_sleep
    )
    for _ in range(2):
        playback._frames = [bytes([i]) for i in range(10)]
        playback._samples = np.zeros(0, dtype=np.float32)
        playback.stop_playing()
    # Twenty frames play back to back (1.2 s); nothing was paced, so the clock is at 0.
    playback.end()
    assert sent[-1] == "stop"
    assert clock.sleeps == pytest.approx([1.32])
    server._loop.call_soon_threadsafe(server._loop.stop)
    worker.join(timeout=1)
    server._loop.close()


def test_uplink_during_speech_requires_aec_and_guard(monkeypatch):
    bridge = StackChanTurnBridge(Server(), Link(), Offline(), clock=lambda: 10.0)
    capture = Capture()
    bridge._captures["s"] = capture
    bridge._states["s"] = "speaking"
    bridge._aec["s"] = False
    bridge._speech_ended["s"] = 10.0
    asyncio.run(bridge.on_audio("s", b"ignored"))
    assert bridge._uplink_dropped == 1
    bridge._aec["s"] = True
    asyncio.run(bridge.on_audio("s", b"live"))
    assert bridge._uplink_live == 1
    bridge._states["s"] = "listening"
    bridge._speech_ended["s"] = 9.0
    asyncio.run(bridge.on_audio("s", b"guarded"))
    assert bridge._uplink_dropped == 1


def test_abort_cancels_reply_clears_frames_stops_once_and_records_latency(monkeypatch):
    loop = asyncio.new_event_loop()
    server = Server(loop)
    instant = [4.0]
    bridge = StackChanTurnBridge(server, Link(), Offline(), clock=lambda: instant[0])
    playback = Playback(server, "device")
    capture = Capture()
    bridge._playbacks["s"] = playback
    bridge._captures["s"] = capture
    bridge._speaking_since["s"] = 3.5
    bridge.abort("s")
    loop.run_until_complete(asyncio.sleep(0))
    assert capture.aborted and playback.flushed
    assert server.stops == ["device"]
    assert bridge.latency_counters["abort_to_silence_ms"] == 0
    loop.close()


@pytest.mark.parametrize("mode", ["auto", "manual", "realtime"])
def test_listen_modes_start_and_stop_a_capture(mode):
    loop = asyncio.new_event_loop()
    bridge = StackChanTurnBridge(Server(loop), Link(), Offline())
    bridge._run = lambda *args: asyncio.sleep(0)
    loop.run_until_complete(bridge.listen("s", "device", "start", mode=mode))
    assert bridge._states["s"] == "listening"
    capture = bridge._captures["s"]
    loop.run_until_complete(bridge.listen("s", "device", "stop", mode=mode))
    assert capture._closed.is_set()
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()


def test_barge_in_replaces_capture_without_starting_second_turn():
    loop = asyncio.new_event_loop()
    bridge = StackChanTurnBridge(Server(loop), Link(), Offline(), clock=lambda: 1.0)
    bridge._run = lambda *args: asyncio.sleep(0)
    loop.run_until_complete(bridge.listen("s", "device", "start", mode="auto"))
    old = bridge._captures["s"]
    bridge._states["s"] = "speaking"
    bridge._aec["s"] = True
    loop.run_until_complete(bridge.listen("s", "device", "start", mode="realtime"))
    assert old._aborted.is_set()
    assert bridge._states["s"] == "listening"
    assert len(bridge._tasks) == 1
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()


def test_abort_during_encode_does_not_send_pending_frames(monkeypatch):
    sent = []

    async def send_audio(device, frames, **kwargs):
        sent.extend(frames)

    async def stop_audio(device):
        sent.append("stop")

    loop = asyncio.new_event_loop()
    server = SimpleNamespace(_loop=loop, send_audio=send_audio, stop_audio=stop_audio)
    playback = StackChanAudioPlayback(server, "device")
    playback.push_audio_sample(np.zeros(1440 * 8, dtype=np.float32))
    playback._cancel_event = threading.Event()
    playback._cancel_event.set()
    playback.stop_playing()
    assert not sent
    playback.flush()
    loop.run_until_complete(asyncio.sleep(0))
    assert sent == ["stop"]
    loop.close()


def test_a_stall_is_caught_up_at_the_prebuffer_cadence_not_rebased(monkeypatch, caplog):
    # Fable review P2: re-basing after a stall permanently ate the 0.84 s cushion.
    import logging

    clock = Clock()
    sent = []
    state = {"stalled": False}

    async def send_audio(device, frames, **kwargs):
        sent.extend(frames)
        if len(sent) == 20 and not state["stalled"]:
            state["stalled"] = True
            clock.now += 0.3  # the loop stalled for 300 ms: five frames overdue

    async def stop_audio(device):
        sent.append("stop")

    server = SimpleNamespace(_loop=None, send_audio=send_audio, stop_audio=stop_audio)
    server._loop = asyncio.new_event_loop()
    worker = threading.Thread(target=server._loop.run_forever, daemon=True)
    worker.start()
    playback = StackChanAudioPlayback(
        server, "device", clock=clock.monotonic, sleeper=clock.sleep, async_sleep=clock.async_sleep
    )
    playback._frames = [bytes([i]) for i in range(40)]
    playback._samples = np.zeros(0, dtype=np.float32)
    with caplog.at_level(logging.WARNING, logger="maipai_body.bodies.stackchan.turn"):
        playback.stop_playing()
    assert len(sent) == 40
    assert any("behind by" in r.getMessage() for r in caplog.records)
    # The five overdue frames went out at the 15 ms cadence, then the 60 ms pacing resumed.
    assert clock.sleeps.count(0.015) >= 3  # 300 ms late is 5 frames; each catch-up gains 45 ms
    assert clock.sleeps.count(0.015) <= 10
    assert clock.sleeps[-1] == pytest.approx(0.06)
    server._loop.call_soon_threadsafe(server._loop.stop)
    worker.join(timeout=1)
    server._loop.close()


def test_a_drained_cushion_is_refilled_with_a_small_lead_not_a_trickle():
    # Fable review P1: after a slow sentence the unit has nothing left; frames arriving one by
    # one would play on an empty buffer. The sender holds them until six exist, then bursts.
    clock = Clock()
    calls = []
    server = SimpleNamespace(_loop=None)

    async def send_audio(device, frames, **kwargs):
        calls.append((len(frames), kwargs.get("prebuffer")))

    server.send_audio = send_audio
    playback = StackChanAudioPlayback(
        server, "device", clock=clock.monotonic, sleeper=clock.sleep, async_sleep=None
    )
    playback._frames = [bytes([i]) for i in range(14)]
    arrivals = [(1.5, 3), (1.7, 5)]  # (clock time, frames that arrive), after the cushion drained

    async def sleep(duration):
        clock.sleep(duration)
        while arrivals and clock.now >= arrivals[0][0]:
            _when, count = arrivals.pop(0)
            playback._frames.extend([bytes([9])] * count)
            if not arrivals:
                playback._finished = True

    playback._async_sleep = sleep
    asyncio.run(playback._sender())
    assert calls[0] == (14, 14)
    refills = [c for c in calls[1:] if c[1] and c[1] > 1]
    assert refills and refills[0][0] >= 6
    assert playback._refills == 1
