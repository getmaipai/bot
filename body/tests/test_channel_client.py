from __future__ import annotations

import json
import threading
import time

from maipai_body.link.channel import CommandChannel
from maipai_body.measure.stand_in_hub import StandInHub


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(json.loads(message))


def _command(event_id: str, kind: str, payload=None) -> str:
    return json.dumps(
        {
            "type": "device-command",
            "id": event_id,
            "kind": kind,
            "payload": payload or {},
            "issued_at": "2026-10-06T12:00:00Z",
            "expires_at": "2026-10-07T12:00:00Z",
            "hlc": "1:0:abcdef",
        }
    )


def test_command_is_dispatched_once_then_acknowledged():
    calls = []
    channel = CommandChannel(
        "http://hub.test", "token", handlers={"mute": lambda payload: calls.append(payload)}
    )
    ws = FakeWebSocket()

    channel._handle_text(_command("event-1", "mute", {"muted": True}), ws)
    channel._handle_text(_command("event-1", "mute", {"muted": True}), ws)

    assert calls == [{"muted": True}]
    assert [message["type"] for message in ws.sent] == ["ack", "ack"]
    assert channel.last_event_id == "event-1"


def test_unknown_kind_is_acked_and_ignored():
    channel = CommandChannel("http://hub.test", "token")
    ws = FakeWebSocket()

    channel._handle_text(_command("event-2", "future_kind"), ws)

    assert ws.sent == [{"type": "ack", "id": "event-2"}]


def test_time_and_settings_commands_reach_registered_hooks():
    seen = []
    channel = CommandChannel(
        "http://hub.test",
        "token",
        time_handler=lambda value: seen.append(("time", value)),
        settings_handler=lambda value: seen.append(("settings", value)),
    )
    ws = FakeWebSocket()

    channel._handle_text(_command("event-time", "time", {"hub_time": "2026-10-06T12:00:00Z"}), ws)
    channel._handle_text(
        _command("event-settings", "settings_changed", {"key": "volume", "value": 50}),
        ws,
    )

    assert seen == [
        ("time", "2026-10-06T12:00:00Z"),
        ("settings", {"key": "volume", "value": 50}),
    ]


def test_heartbeat_reports_robot_time():
    channel = CommandChannel("http://hub.test", "token", wall_clock=lambda: 1791288000.0)
    ws = FakeWebSocket()

    channel._handle_text(json.dumps({"type": "heartbeat", "hub_time": "2026-10-06T12:00:00Z"}), ws)

    assert ws.sent[0]["type"] == "heartbeat"
    assert ws.sent[0]["device_time"] == "2026-10-06T12:00:00Z"


def test_stand_in_replays_after_drop_and_last_event_id(monkeypatch):
    handled = []
    drops = []
    stop = threading.Event()
    with StandInHub(require_auth=True, command_channel=True) as hub:
        hub.push_command("event-replay", "mute", {"muted": True})
        channel = CommandChannel(
            hub.stt_url,
            hub.session_cookie,
            handlers={"mute": lambda payload: handled.append(payload)},
            reconnect_delay_s=0.05,
            on_drop=drops.append,
        )
        thread = threading.Thread(target=channel.run, args=(stop,), daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(hub.command_acks) < 1:
            time.sleep(0.01)
        assert len(hub.command_acks) == 1

        # Reconnect replays the same event id; the handler remains exactly once.
        hub.cut("reset")
        hub.restore()
        hub.push_command("event-replay", "mute", {"muted": True})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(hub.command_acks) < 2:
            time.sleep(0.01)
        stop.set()
        thread.join(timeout=2)

        assert len(hub.command_acks) >= 2
        assert handled == [{"muted": True}]
        assert drops
        assert any(
            request.get("last_event_id") == "event-replay" for request in hub.command_handshakes
        )
