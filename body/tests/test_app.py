"""The app's real boot path: hold neutral until paired, log state
changes, stop within a second while waiting, then run the real
conversation loop once G4's hub link reports paired."""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from maipai_body.app import (
    _hub_credentials_reader,
    _sigint_handler,
    run_paired_body,
)
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.link.store import HubPairing


@dataclass
class _FakeLinkState:
    paired: bool


class _FakePairingStore:
    def __init__(self, pairing: HubPairing | None) -> None:
        self._pairing = pairing

    def load(self) -> HubPairing | None:
        return self._pairing


class _FakeHubClient:
    def __init__(self, session_cookie: str | None) -> None:
        self.session_cookie = session_cookie


class _FakeLink:
    """Duck-types `run_paired_body`'s own `link` surface
    (`state`, `pairing_store`, `hub_client`) without a real
    `LinkLifecycle`, `HubLinkClient` or on-disk pairing file - the same
    scripted-stand-in style `test_run_loop.py` already uses for every
    network-facing dependency."""

    def __init__(
        self,
        *,
        paired: bool = False,
        pairing: HubPairing | None = None,
        session_cookie: str | None = "cookie-value",
    ) -> None:
        self._paired = paired
        self.pairing_store = _FakePairingStore(pairing)
        self.hub_client = _FakeHubClient(session_cookie)

    @property
    def state(self) -> _FakeLinkState:
        return _FakeLinkState(paired=self._paired)

    def set_paired(self, paired: bool) -> None:
        self._paired = paired


def _fake_pairing() -> HubPairing:
    return HubPairing(
        base_url="https://hub.example.test",
        device_token="dev-token",
        hub_instance_id="hub-1",
    )


def test_hub_credentials_reader_retains_latest_successful_pairing_url():
    class RotatingStore:
        calls = 0

        def load(self):
            self.calls += 1
            if self.calls == 1:
                return HubPairing(
                    base_url="https://new-hub.example.test",
                    device_token="dev-token",
                    hub_instance_id="hub-1",
                )
            raise OSError("transient read failure")

    link = _FakeLink(pairing=_fake_pairing(), session_cookie="rotated-cookie")
    link.pairing_store = RotatingStore()
    read_credentials = _hub_credentials_reader(link, "https://original-hub.example.test")

    assert read_credentials() == ("rotated-cookie", "https://new-hub.example.test")
    assert read_credentials() == ("rotated-cookie", "https://new-hub.example.test")


def test_run_paired_body_holds_neutral_then_honors_stop_event_while_never_paired(caplog):
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=False)
    stop_event = threading.Event()

    with caplog.at_level("INFO", logger="maipai_body.app"):
        thread = threading.Thread(
            target=run_paired_body,
            args=(client, link, stop_event),
            kwargs={"cache_dir": Path("/tmp/unused")},
        )
        thread.start()
        time.sleep(0.3)  # let it reach the neutral hold and start waiting for pairing
        stop_event.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive(), "run_paired_body did not stop within its join timeout"

    kinds = [command.kind for command in client.sent_commands]
    assert kinds[:2] == ["goto", "hold"], "the run loop did not go neutral then hold"

    messages = [record.getMessage() for record in caplog.records]
    assert "state: starting" in messages
    assert "state: holding_neutral" in messages
    assert "state: waiting_for_pairing" in messages
    assert "state: conversation_loop" not in messages
    assert "state: stopped" in messages


def test_run_paired_body_stops_within_one_second_of_the_stop_event_while_waiting():
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=False)
    stop_event = threading.Event()

    thread = threading.Thread(
        target=run_paired_body,
        args=(client, link, stop_event),
        kwargs={"cache_dir": Path("/tmp/unused")},
    )
    thread.start()
    time.sleep(0.3)

    started = time.monotonic()
    stop_event.set()
    thread.join(timeout=2.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive()
    assert elapsed < 1.0, f"run_paired_body took {elapsed:.2f}s to stop after stop_event was set"


def test_run_paired_body_survives_a_lost_connection(caplog):
    client = FakeReachyMiniClient()
    client.simulate_disconnect()
    link = _FakeLink(paired=False)
    stop_event = threading.Event()

    with caplog.at_level("INFO", logger="maipai_body.app"):
        run_paired_body(
            client, link, stop_event, cache_dir=Path("/tmp/unused")
        )  # a lost connection returns immediately, never blocks

    messages = [record.getMessage() for record in caplog.records]
    assert "state: body_lost" in messages
    assert "state: stopped" in messages


def test_run_paired_body_builds_and_runs_the_conversation_loop_once_paired(caplog):
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=_fake_pairing(), session_cookie="real-cookie")
    stop_event = threading.Event()

    fake_loop = MagicMock()
    fake_loop.snapshot.return_value = {"activity": "idle", "muted": False, "tracking": False}

    def fake_run(event: threading.Event) -> None:
        event.wait(5.0)  # blocks like the real ConversationLoop.run() until told to stop

    fake_loop.run.side_effect = fake_run

    with (
        patch("maipai_body.app._build_conversation_loop", return_value=fake_loop) as build,
        caplog.at_level("INFO", logger="maipai_body.app"),
    ):
        thread = threading.Thread(
            target=run_paired_body,
            args=(client, link, stop_event),
            kwargs={"cache_dir": Path("/tmp/models")},
        )
        thread.start()
        time.sleep(0.3)
        stop_event.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    build.assert_called_once_with(
        client,
        "real-cookie",
        "https://hub.example.test",
        Path("/tmp/models"),
        link,
        stop_event,
    )
    fake_loop.run.assert_called_once_with(stop_event)

    messages = [record.getMessage() for record in caplog.records]
    assert "state: conversation_loop" in messages
    assert "state: stopped" in messages


def test_state_reporter_sends_starting_while_conversation_loop_builds():
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=_fake_pairing(), session_cookie="real-cookie")
    stop_event = threading.Event()
    build_started = threading.Event()
    release_build = threading.Event()
    reporter_started = threading.Event()
    snapshots = []

    class _FakeReporter:
        def __init__(self, _credentials, _stop, snapshot, _change):
            self.snapshot = snapshot

        def run(self):
            reporter_started.set()
            snapshots.append(self.snapshot())

    def blocked_build(*_args):
        build_started.set()
        release_build.wait(2.0)
        return MagicMock(
            snapshot=MagicMock(return_value={"activity": "idle", "muted": False, "tracking": False})
        )

    with (
        patch("maipai_body.app.StateReporter", _FakeReporter),
        patch("maipai_body.app._build_conversation_loop", side_effect=blocked_build),
    ):
        thread = threading.Thread(
            target=run_paired_body,
            args=(client, link, stop_event),
            kwargs={"cache_dir": Path("/tmp/models")},
        )
        thread.start()
        assert reporter_started.wait(1.0)
        assert build_started.wait(1.0)
        stop_event.set()
        thread.join(timeout=1.0)
        release_build.set()

    assert not thread.is_alive()
    assert snapshots[0]["activity"] == "starting"
    assert snapshots[0]["on_battery"] is None
    assert snapshots[0]["battery_level"] is None
    assert snapshots[0]["daemon_version"]


def test_run_paired_body_stops_within_one_second_during_conversation_loop_build(caplog):
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=_fake_pairing(), session_cookie="real-cookie")
    stop_event = threading.Event()
    build_started = threading.Event()
    release_build = threading.Event()

    def blocked_build(*args):
        build_started.set()
        release_build.wait(5.0)
        return MagicMock()

    with (
        patch("maipai_body.app._build_conversation_loop", side_effect=blocked_build),
        caplog.at_level("INFO", logger="maipai_body.app"),
    ):
        thread = threading.Thread(
            target=run_paired_body,
            args=(client, link, stop_event),
            kwargs={"cache_dir": Path("/tmp/models")},
        )
        thread.start()
        assert build_started.wait(1.0), "conversation loop build did not start"
        started = time.monotonic()
        stop_event.set()
        thread.join(timeout=2.0)
        elapsed = time.monotonic() - started
        release_build.set()

    assert not thread.is_alive()
    assert elapsed < 1.0, f"run_paired_body took {elapsed:.2f}s to stop after stop_event was set"
    messages = [record.getMessage() for record in caplog.records]
    assert "stop requested during model download; abandoning conversation loop build" in messages
    assert "state: conversation_loop" not in messages
    assert "state: stopped" in messages


def test_run_paired_body_stops_cleanly_if_the_pairing_record_is_unreadable(caplog):
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=None)  # paired per in-memory state, but nothing on disk
    stop_event = threading.Event()

    with (
        patch("maipai_body.app._build_conversation_loop") as build,
        caplog.at_level("INFO", logger="maipai_body.app"),
    ):
        run_paired_body(client, link, stop_event, cache_dir=Path("/tmp/unused"))

    build.assert_not_called()
    messages = [record.getMessage() for record in caplog.records]
    assert "state: conversation_loop" not in messages
    assert "state: stopped" in messages


def test_run_paired_body_stops_cleanly_if_paired_with_no_session_cookie(caplog):
    """Code review, 2026-09-28: this used to silently fall back to an
    empty-string cookie and build every hub client anyway, surfacing
    only as an opaque 401 deep inside the first real turn."""
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=_fake_pairing(), session_cookie=None)
    stop_event = threading.Event()

    with (
        patch("maipai_body.app._build_conversation_loop") as build,
        caplog.at_level("INFO", logger="maipai_body.app"),
    ):
        run_paired_body(client, link, stop_event, cache_dir=Path("/tmp/unused"))

    build.assert_not_called()
    messages = [record.getMessage() for record in caplog.records]
    assert "state: conversation_loop" not in messages
    assert "state: stopped" in messages


def test_run_paired_body_survives_a_conversation_loop_construction_failure(caplog):
    """Code review, 2026-09-28: a model-download failure
    (AssetUnavailable/ChecksumMismatch, or a bare network error) is a
    plain RuntimeError subclass, not BodyLost - it used to propagate
    uncaught and crash the whole daemon process."""
    client = FakeReachyMiniClient()
    link = _FakeLink(paired=True, pairing=_fake_pairing(), session_cookie="real-cookie")
    stop_event = threading.Event()

    with (
        patch(
            "maipai_body.app._build_conversation_loop",
            side_effect=RuntimeError("checksum mismatch"),
        ),
        caplog.at_level("INFO", logger="maipai_body.app"),
    ):
        run_paired_body(client, link, stop_event, cache_dir=Path("/tmp/unused"))  # must not raise

    messages = [record.getMessage() for record in caplog.records]
    assert "state: conversation_loop" not in messages
    assert "state: stopped" in messages


def test_sigint_handler_sets_the_stop_event():
    stop_event = threading.Event()
    handler = _sigint_handler(stop_event)

    handler(signal.SIGINT, None)

    assert stop_event.is_set()
