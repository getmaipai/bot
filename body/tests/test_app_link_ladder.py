"""LINK-STATE-01 in the app: the page's state frame, the setting and the wiring."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from maipai_body import app as app_module
from maipai_body.app import _build_link_stack, _link_state_payload, _sleep_after_s, run_paired_body
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.link.commands import Reply
from maipai_body.link.state_machine import DEFAULT_SLEEP_AFTER_MINUTES, LinkPhase
from maipai_body.link.store import PairingStore
from tests.test_app import _fake_pairing, _FakeLink
from tests.test_link_lifecycle import _result
from tests.test_link_lifecycle_ladder import _AddressClient


def _stack(tmp_path, answering=frozenset()):
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    client = _AddressClient(set(answering))
    stack = _build_link_stack(store, client, discover=lambda timeout_s: None, sleep_after_s=600.0)
    return stack, client


def test_the_state_frame_carries_the_phase_and_the_status_text(tmp_path):
    stack, _ = _stack(tmp_path)
    payload = _link_state_payload(stack.link, stack.offline)
    assert payload["paired"] is False
    assert payload["link"] == {
        "phase": "connected",
        "status": "Connected to home.",
        "reply": None,
    }

    stack.machine.link_lost("unreachable: ConnectTimeout")
    link = _link_state_payload(stack.link, stack.offline)["link"]
    assert link["phase"] == "reconnecting"
    assert link["status"].startswith("Can't reach home.")
    assert link["status"].endswith("Nothing is saved for later.")


def test_the_last_rung_1_reply_is_visible_on_the_page(tmp_path):
    stack, _ = _stack(tmp_path)
    stack.offline.last_reply = Reply("Timer set.", ("cmd.timer_set",))
    assert _link_state_payload(stack.link, stack.offline)["link"]["reply"] == "Timer set."


def test_the_lifecycle_feeds_the_machine_and_walks_the_address_book(tmp_path):
    stack, client = _stack(tmp_path)
    assert stack.link.reconnect_once() is False
    assert stack.machine.phase is LinkPhase.RECONNECTING
    assert client.refreshed_at == ["http://192.0.2.10:80"]  # LAN only: the tailnet seam is empty
    assert stack.machine.snapshot().last_error == "unreachable: ConnectTimeout"

    client.answering = {"http://192.0.2.10:80"}
    stack.supervisor.step()
    assert stack.machine.phase is LinkPhase.CONNECTED


def test_the_sleep_after_setting_reads_minutes_from_the_environment():
    assert _sleep_after_s({}) == DEFAULT_SLEEP_AFTER_MINUTES * 60.0
    assert _sleep_after_s({"MAIPAI_LINK_SLEEP_AFTER_MIN": "12"}) == 720.0
    assert _sleep_after_s({"MAIPAI_LINK_SLEEP_AFTER_MIN": "0.5"}) == 30.0
    for bad in ("", "soon", "0", "-3", "nan"):
        assert _sleep_after_s({"MAIPAI_LINK_SLEEP_AFTER_MIN": bad}) == (
            DEFAULT_SLEEP_AFTER_MINUTES * 60.0
        ), bad


def test_run_paired_body_hands_the_ladder_to_the_loop_and_starts_the_supervisor():
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=_fake_pairing(), session_cookie="real-cookie")
    stop_event = threading.Event()
    offline = MagicMock()
    ran = threading.Event()

    class _Supervisor:
        def run(self, event):
            ran.set()

    fake_loop = MagicMock()
    fake_loop.snapshot.return_value = {"activity": "idle", "muted": False, "tracking": False}
    fake_loop.run.side_effect = lambda event: ran.wait(2.0)

    with patch.object(app_module, "_build_conversation_loop", return_value=fake_loop) as build:
        run_paired_body(
            client,
            link,
            stop_event,
            cache_dir=Path("/tmp/models"),
            offline=offline,
            supervisor=_Supervisor(),
        )

    assert ran.is_set()
    assert build.call_args.kwargs == {"offline": offline}


def test_the_app_page_shows_the_status_text():
    page = (Path(app_module.__file__).parent / "static" / "index.html").read_text()
    assert "state.link" in page
    assert "link.status" in page
