"""G4's own acceptance: the link state machine, driven by fakes - no
network, no real hub, matching the session's established pattern of
testing a state machine against scripted collaborators."""

from __future__ import annotations

import threading
import time

from maipai_body.link.client import PairingRefused, PairingResult, PairingTimedOut
from maipai_body.link.discovery import HubAddress
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.store import HubPairing, PairingStore


class _FakeClient:
    """A `HubLinkClient`-shaped fake: scripted results, call counts."""

    def __init__(self) -> None:
        self.request_code_calls = 0
        self.await_approval_calls = 0
        self.refresh_calls = 0
        self.refresh_results: list[bool] = [True]
        self.request_code_result = _pending()
        self.await_approval_result: PairingResult | Exception = _result()

    def request_code(self, address, *, label, capabilities=None):
        self.request_code_calls += 1
        return self.request_code_result

    def await_approval(self, pending):
        self.await_approval_calls += 1
        if isinstance(self.await_approval_result, Exception):
            raise self.await_approval_result
        return self.await_approval_result

    def refresh(self) -> bool:
        self.refresh_calls += 1
        if len(self.refresh_results) > 1:
            return self.refresh_results.pop(0)
        return self.refresh_results[0]


def _pending():
    from maipai_body.link.client import PendingCode

    return PendingCode(
        base_url="http://192.0.2.10:80",
        fingerprint="hub-test",
        code="AB12CD",
        poll_token="poll-xyz",
        hub_instance_id="hub-test",
    )


def _result():
    return PairingResult(
        pairing=HubPairing(
            base_url="http://192.0.2.10:80",
            device_token="tok-123",
            hub_instance_id="hub-test",
            fingerprint="hub-test",
        ),
        code="AB12CD",
    )


def _address():
    return HubAddress(
        host="192.0.2.10", port=80, instance_id="hub-test", name="Test Hub", tls=False
    )


def _run_until(lifecycle: LinkLifecycle, condition, timeout_s: float = 2.0) -> threading.Event:
    stop_event = threading.Event()
    thread = threading.Thread(target=lifecycle.run, args=(stop_event,), daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            break
        time.sleep(0.01)
    stop_event.set()
    thread.join(timeout=2.0)
    return stop_event


def test_starts_unpaired_with_no_code(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    lifecycle = LinkLifecycle(store, _FakeClient(), discover=lambda timeout_s: None)

    assert lifecycle.state.paired is False
    assert lifecycle.state.code is None


def test_resumes_an_existing_pairing_without_discovering(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    client = _FakeClient()
    discover_calls = []
    lifecycle = LinkLifecycle(
        store, client, discover=lambda timeout_s: discover_calls.append(1) or None
    )

    _run_until(lifecycle, lambda: lifecycle.state.paired)

    assert lifecycle.state.paired is True
    assert lifecycle.state.hub_instance_id == "hub-test"
    assert client.refresh_calls == 1
    assert not discover_calls  # never needed to discover; the pairing worked


def test_discovers_and_pairs_when_unpaired(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    client = _FakeClient()
    lifecycle = LinkLifecycle(store, client, discover=lambda timeout_s: _address())

    _run_until(lifecycle, lambda: lifecycle.state.paired)

    assert lifecycle.state.paired is True
    assert client.request_code_calls == 1
    assert client.await_approval_calls == 1
    # Persistence itself is HubLinkClient's own job (test_link_client.py);
    # this fake doesn't simulate it, so it isn't asserted here.


def test_the_code_is_visible_before_approval_completes(tmp_path):
    """The whole reason request_code()/await_approval() are split: a
    caller (the settings page) must see the code before the blocking
    wait, not after."""
    store = PairingStore(tmp_path / "pairing.json")
    client = _FakeClient()
    approval_blocked = threading.Event()
    approval_may_proceed = threading.Event()

    def blocking_await(pending):
        approval_blocked.set()
        approval_may_proceed.wait(timeout=2.0)
        return _result()

    client.await_approval = blocking_await
    lifecycle = LinkLifecycle(store, client, discover=lambda timeout_s: _address())

    stop_event = threading.Event()
    thread = threading.Thread(target=lifecycle.run, args=(stop_event,), daemon=True)
    thread.start()
    try:
        assert approval_blocked.wait(timeout=2.0)
        assert lifecycle.state.code == "AB12CD"
        assert lifecycle.state.paired is False
    finally:
        approval_may_proceed.set()
        stop_event.set()
        thread.join(timeout=2.0)


def test_no_hub_found_sets_an_error_and_keeps_retrying(tmp_path, monkeypatch):
    import maipai_body.link.lifecycle as lifecycle_module

    monkeypatch.setattr(lifecycle_module, "DISCOVERY_RETRY_S", 0.05)
    store = PairingStore(tmp_path / "pairing.json")
    client = _FakeClient()
    discover_calls = []
    lifecycle = LinkLifecycle(
        store,
        client,
        discover=lambda timeout_s: discover_calls.append(1) or None,
    )

    _run_until(lifecycle, lambda: len(discover_calls) >= 2)

    assert lifecycle.state.paired is False
    assert lifecycle.state.last_error == "no hub found on the network"
    assert len(discover_calls) >= 2


def test_pairing_refused_is_recorded_and_retried(tmp_path, monkeypatch):
    import maipai_body.link.lifecycle as lifecycle_module

    monkeypatch.setattr(lifecycle_module, "DISCOVERY_RETRY_S", 0.05)
    store = PairingStore(tmp_path / "pairing.json")
    client = _FakeClient()
    client.await_approval_result = PairingRefused("the pairing code expired")
    lifecycle = LinkLifecycle(store, client, discover=lambda timeout_s: _address())

    _run_until(lifecycle, lambda: client.request_code_calls >= 2)

    assert lifecycle.state.paired is False
    assert "expired" in (lifecycle.state.last_error or "")


def test_pairing_timeout_is_recorded(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    client = _FakeClient()
    client.await_approval_result = PairingTimedOut("no approval within 300s")
    lifecycle = LinkLifecycle(store, client, discover=lambda timeout_s: _address())

    _run_until(lifecycle, lambda: lifecycle.state.last_error is not None)

    assert lifecycle.state.paired is False
    assert "300s" in lifecycle.state.last_error


def test_on_code_is_called_once_with_the_code_before_approval_completes(tmp_path):
    """G4b: the pairing flow speaks the code (via the offline clips), so
    the lifecycle hands the fresh code to a caller-supplied hook the
    moment it exists, not after approval."""
    store = PairingStore(tmp_path / "pairing.json")
    client = _FakeClient()
    heard: list[str] = []
    approval_may_proceed = threading.Event()
    in_await = threading.Event()

    def blocking_await(pending):
        in_await.set()
        approval_may_proceed.wait(timeout=2.0)
        return _result()

    client.await_approval = blocking_await
    lifecycle = LinkLifecycle(
        store, client, discover=lambda timeout_s: _address(), on_code=heard.append
    )

    stop_event = threading.Event()
    thread = threading.Thread(target=lifecycle.run, args=(stop_event,), daemon=True)
    thread.start()
    try:
        assert in_await.wait(timeout=2.0)
        assert heard == ["AB12CD"]
    finally:
        approval_may_proceed.set()
        stop_event.set()
        thread.join(timeout=2.0)


def test_a_failing_on_code_hook_never_breaks_pairing(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")

    def boom(code):
        raise RuntimeError("speaker unplugged")

    lifecycle = LinkLifecycle(
        store, _FakeClient(), discover=lambda timeout_s: _address(), on_code=boom
    )
    stop_event = _run_until(lifecycle, lambda: lifecycle.state.paired)
    stop_event.set()
    assert lifecycle.state.paired is True
