"""One test per route the stand-in hub now serves, against the real clients where one exists.

Pairing, the turn stream with `signal`, `plan` and `cancel`, the `stt`
websocket, `tts`, the device state `PUT`, the print sync, the hub
endpoint book and the flag-gated mute channel. Link faults are
``test_stand_in_hub.py``'s; this file is the routes' own contract.
"""

from __future__ import annotations

import ipaddress
import json
import threading

import numpy as np
import pytest
import requests
from websockets.sync.client import connect

from maipai_body.expression.cue import Phase
from maipai_body.link.client import HubLinkClient
from maipai_body.link.discovery import HubAddress
from maipai_body.link.prints import PrintSync
from maipai_body.link.store import PairingStore
from maipai_body.measure.stand_in_hub import StandInHub
from maipai_body.speech.turn_client import TurnClient
from maipai_body.vision.gallery import FaceGallery


@pytest.fixture
def hub():
    with StandInHub(reply_text="hello back") as running:
        yield running


def _cookie(hub: StandInHub) -> dict[str, str]:
    return {"Cookie": f"session={hub.session_cookie}"}


def _address(hub: StandInHub) -> HubAddress:
    host, port = hub.http_url.removeprefix("http://").split(":")
    return HubAddress(host=host, port=int(port), instance_id="hub-bench", name="Bench", tls=False)


# -- pairing --


def test_pairing_runs_code_poll_redeem_and_hands_out_the_session_cookie(hub, tmp_path):
    client = HubLinkClient(PairingStore(tmp_path / "p.json"), discover=lambda timeout_s: None)
    result = client.pair(_address(hub), label="Bench Reachy", capabilities=["voice"])

    assert result.pairing.device_token == hub.device_token
    assert client.session_cookie == hub.session_cookie
    assert hub.paired_requests == [
        {"label": "Bench Reachy", "kind": "robot", "capabilities": ["voice"]}
    ]
    assert hub.redeemed_tokens == [hub.device_token]


def test_a_pairing_code_can_wait_for_approval_polls(tmp_path):
    with StandInHub(approve_after_polls=2) as hub:
        pending = requests.post(f"{hub.http_url}/api/auth/quick-connect/code", json={}).json()
        statuses = [
            requests.get(
                f"{hub.http_url}/api/auth/quick-connect/poll",
                params={"poll_token": pending["poll_token"]},
            ).json()["status"]
            for _ in range(3)
        ]
    assert statuses == ["pending", "pending", "approved"]


def test_redeeming_an_unknown_token_is_refused(hub):
    response = requests.post(f"{hub.http_url}/api/auth/devices/redeem", json={"token": "nope"})
    assert response.status_code == 401


# -- turn stream: signal, plan, cancel --


def test_the_default_turn_script_still_streams_signal_then_done(hub):
    events = list(TurnClient(hub.http_url, hub.session_cookie).stream("hi"))
    assert [e.cue.phase for e in events] == [Phase.SIGNAL, Phase.DONE]


def test_a_scripted_plan_event_rides_the_stream_and_the_body_tolerates_it():
    plan = {"type": "plan", "plan": {"steps": [{"slot": "react", "move": "nod"}]}}
    with StandInHub(plan_event=plan) as hub:
        lines = []
        with requests.post(
            f"{hub.http_url}/api/turn/stream",
            json={"text": "hi"},
            headers=_cookie(hub),
            stream=True,
        ) as response:
            lines = [json.loads(line) for line in response.iter_lines() if line]
        assert [line["type"] for line in lines] == ["turn_meta", "signal", "plan", "delta", "done"]
        assert lines[2] == plan
        events = list(TurnClient(hub.http_url, hub.session_cookie).stream("hi"))
    assert events[-1].reply_text == "hello back"  # a plan has no cue mapping at the floor


def test_cancel_ends_an_in_flight_turn_with_an_error_the_body_reads_as_cancel():
    with StandInHub(event_delay_s=0.15) as hub:
        client = TurnClient(hub.http_url, hub.session_cookie)
        stream = client.stream("hi")
        first = next(stream)
        assert first.cue.phase is Phase.SIGNAL
        assert client.cancel(first.turn_id) is True
        rest = list(stream)
    assert [e.cue.phase for e in rest] == [Phase.CANCEL]
    assert hub.cancelled_turns == ["turn-bench"]


def test_cancelling_a_turn_that_is_not_in_flight_answers_false(hub):
    assert TurnClient(hub.http_url, hub.session_cookie).cancel("turn-gone") is False


# -- stt websocket --


def test_stt_websocket_sends_ready_vad_and_final_and_notes_its_handshake(hub):
    url = hub.stt_url.replace("http://", "ws://") + "/api/stt/stream"
    seen = []
    with connect(url, additional_headers=_cookie(hub)) as ws:
        for _ in range(3):
            seen.append(json.loads(ws.recv(timeout=5)))
        ws.send(np.zeros(160, dtype=np.int16).tobytes())
    assert seen == [
        {"t": "ready"},
        {"t": "vad", "speaking": True},
        {"t": "final", "v": "hello maipai"},
    ]
    assert hub.stt_handshakes == [
        {"path": "/api/stt/stream", "cookie": f"session={hub.session_cookie}"}
    ]


# -- tts --


def test_tts_streams_a_wav_for_the_text_asked(hub):
    response = requests.post(
        f"{hub.http_url}/api/tts", json={"text": "hi there"}, headers=_cookie(hub)
    )
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert hub.tts_requests == ["hi there"]


# -- PUT /api/devices/me/state --


def test_the_device_state_put_keeps_every_frame_the_body_reported(hub):
    frame = {"activity": "listening", "muted": False, "tracking": True}
    response = requests.put(
        f"{hub.http_url}/api/devices/me/state", json=frame, headers=_cookie(hub)
    )
    assert response.status_code == 200
    assert hub.state_frames == [frame]
    assert len(hub.state_reports) == 1  # the timestamps the link-loss harness reads


# -- GET /api/biometric-prints/sync --


def test_print_sync_serves_the_scripted_snapshot_to_the_real_sync_client(hub):
    hub.prints = [
        {
            "id": "p1",
            "person_id": "person-a",
            "model_id": "m",
            "model_sha256": "0" * 64,
            "embedding": [0.0, 1.0],
        }
    ]
    gallery = FaceGallery(model_id="m", model_sha256="0" * 64)
    stop = threading.Event()
    sync = PrintSync(gallery, lambda: (hub.session_cookie, hub.http_url), stop, interval_s=60.0)
    thread = threading.Thread(target=sync.run, daemon=True)
    thread.start()
    for _ in range(100):
        if gallery.identify(np.array([0.0, 1.0], dtype=np.float32)).person_id == "person-a":
            break
        threading.Event().wait(0.02)
    stop.set()
    thread.join(timeout=2)
    assert gallery.identify(np.array([0.0, 1.0], dtype=np.float32)).person_id == "person-a"


def test_print_sync_without_the_session_is_a_401_when_auth_is_required():
    with StandInHub(require_auth=True) as hub:
        bare = requests.get(f"{hub.http_url}/api/biometric-prints/sync")
        authed = requests.get(f"{hub.http_url}/api/biometric-prints/sync", headers=_cookie(hub))
    assert bare.status_code == 401
    assert authed.json() == {"prints": []}


# -- GET /api/devices/me/hub-endpoints --


def test_hub_endpoints_serve_the_book_in_priority_order_on_documentation_addresses(hub):
    body = requests.get(f"{hub.http_url}/api/devices/me/hub-endpoints", headers=_cookie(hub)).json()
    endpoints = body["endpoints"]
    assert [e["priority"] for e in endpoints] == sorted(e["priority"] for e in endpoints)
    assert [e["kind"] for e in endpoints] == ["lan", "overlay"]
    for endpoint in endpoints:
        host = endpoint["url"].split("//")[1].split(":")[0]
        if host.replace(".", "").isdigit():
            assert ipaddress.ip_address(host) in ipaddress.ip_network("192.0.2.0/24")
        else:
            assert host.endswith(".example.com")


# -- the mute command channel, behind a flag --


def test_the_mute_channel_is_absent_unless_flagged(hub):
    response = requests.get(f"{hub.http_url}/api/devices/me/commands", headers=_cookie(hub))
    assert response.status_code == 404
    with pytest.raises(RuntimeError, match="mute_channel"):
        hub.send_mute(True)


def test_the_mute_channel_delivers_each_command_once_in_order():
    with StandInHub(mute_channel=True) as hub:
        url = f"{hub.http_url}/api/devices/me/commands"
        assert requests.get(url, headers=_cookie(hub)).json() == {"commands": []}
        hub.send_mute(True)
        hub.send_mute(False)
        first = requests.get(url, headers=_cookie(hub)).json()["commands"]
        assert first == [
            {"seq": 1, "type": "mute", "muted": True},
            {"seq": 2, "type": "mute", "muted": False},
        ]
        after = requests.get(url, params={"after": 1}, headers=_cookie(hub)).json()["commands"]
        assert [c["seq"] for c in after] == [2]
