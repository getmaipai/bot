"""Named failure-shape checks for StackChan fake peers and turn dependencies."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maipai_body.bodies.stackchan.turn import StackChanTurnBridge
from maipai_body.speech.stt_stream import SttStreamResult


class _Server:
    _loop = None

    async def send_audio(self, *args, **kwargs):
        raise ConnectionError("hub disappeared")

    async def stop_audio(self, *_args):
        pass


class _Capture:
    def close(self):
        pass

    def abort(self):
        pass


class _Playback:
    def __init__(self, *_args):
        self.stopped = False

    def stop(self):
        self.stopped = True

    def end(self):
        pass

    def flush(self):
        pass


class _Link:
    hub_client = SimpleNamespace(
        session_cookie="private-cookie", active_base_url="http://192.0.2.10"
    )
    pairing_store = SimpleNamespace(load=lambda: SimpleNamespace(base_url="http://192.0.2.10"))


class _Offline:
    speaker = None


@pytest.mark.parametrize("failure", ["hub_down_mid_turn", "hub_slow", "stt_error", "tts_error"])
def test_turn_failures_end_cleanly_without_leaking_credentials(monkeypatch, failure):
    import maipai_body.bodies.stackchan.turn as module

    class Stt:
        def __init__(self, *_args):
            pass

        def run(self, _capture):
            if failure == "stt_error":
                return SttStreamResult(kind="error", error="recognition failed")
            return SttStreamResult(kind="final", text="hello")

    class Turn:
        def __init__(self, *_args):
            pass

        def stream(self, *_args, **_kwargs):
            if failure in {"hub_down_mid_turn", "hub_slow"}:
                raise TimeoutError("hub did not answer")
            return iter([SimpleNamespace(reply_text="reply")])

    class Tts(_Playback):
        def speak(self, *_args, **_kwargs):
            if failure == "tts_error":
                raise RuntimeError("speech synthesis failed")

    monkeypatch.setattr(module, "StackChanAudioPlayback", _Playback)
    bridge = StackChanTurnBridge(
        _Server(), _Link(), _Offline(), stt_factory=Stt, turn_factory=Turn, tts_factory=Tts
    )
    import asyncio

    async def run():
        await bridge._run("session", "02:00:00:00:00:32", _Capture())

    asyncio.run(run())
    assert "private-cookie" not in repr(bridge.__dict__)


def test_revoked_pairing_token_is_not_authorized_after_rotation():
    from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore

    store = PairingStore()
    device, client = "02:00:00:00:00:33", "00000000-0000-4000-8000-000000000033"
    store.request(device, client)
    old = store.approve(device, client)
    assert store.authorize(device, client, old)
    store.revoke(device)
    assert not store.authorize(device, client, old)
    store.request(device, client)
    new = store.approve(device, client)
    assert new != old
    assert not store.authorize(device, client, old)
    assert store.authorize(device, client, new)
