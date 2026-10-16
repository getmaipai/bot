from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient, XiaozhiServer


class DummyPairing:
    def __init__(self):
        self.checked = []

    def authorize(self, device_id, client_id, token):
        self.checked.append((device_id, client_id, token))
        return True


class DummySocket:
    async def send(self, message):
        self.message = json.loads(message)


def test_notify_frame_shape_and_hello_feature_gate():
    server = XiaozhiServer(DummyPairing(), robot=None)
    socket = DummySocket()
    server._sessions["device"] = socket
    server._session_ids["device"] = "session"
    server._session_features["device"] = {"notify": True}
    server._loop = asyncio.new_event_loop()
    server._session_authorized = lambda _device: True

    client = XiaozhiDeviceClient(server)
    assert client.device_supports("notify")

    async def exercise_notify():
        await server.send_notify("http://192.0.2.10:8766/notify/device/audio.ogg")

    server._loop.run_until_complete(exercise_notify())
    assert socket.message == {
        "session_id": "session",
        "type": "notify",
        "audio_url": "http://192.0.2.10:8766/notify/device/audio.ogg",
    }

    server._session_features["device"] = {}
    try:
        server._loop.run_until_complete(
            server.send_notify("http://192.0.2.10:8766/notify/device/audio.ogg")
        )
    except Exception as exc:
        assert "did not advertise notify" in str(exc)
    else:
        raise AssertionError("notify must be rejected without the hello feature")
    server._loop.close()


def test_audio_url_is_host_route_and_requires_paired_bearer_token():
    pairing = DummyPairing()
    server = XiaozhiServer(pairing, robot=None, vision_host="0.0.0.0")
    server._session_credentials["device"] = ("client", "pair-token")
    server._notification_audio[("device", "audio")] = b"ogg-bytes"
    url = server._notify_audio_url("device", "audio")
    assert url == "http://127.0.0.1:8766/notify/device/audio.ogg"

    request = SimpleNamespace(
        match_info={"device_id": "device", "audio_id": "audio"},
        headers={"Authorization": "Bearer pair-token"},
    )
    response = asyncio.run(server._serve_notify_audio(request))
    assert response.body == b"ogg-bytes"
    assert response.content_type == "audio/ogg"
    assert ("device", "client", "pair-token") in pairing.checked
    assert ("device", "client", "") not in pairing.checked
