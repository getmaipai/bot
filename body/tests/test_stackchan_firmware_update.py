from __future__ import annotations

import hashlib

from maipai_body.bodies.stackchan.companion import DIAGNOSTIC_KINDS
from maipai_body.bodies.stackchan.firmware_update import FirmwareUpdater, should_update
from maipai_body.link.checkin import build_payload

BASE = {
    "unit_version": "1.0.0",
    "target_version": "1.1.0",
    "link_healthy": True,
    "in_turn": False,
    "in_call": False,
    "timer_active": False,
    "alarm_active": False,
    "timer_due_in": None,
    "muted": False,
    "full_quiet": False,
    "battery_percent": 80,
    "charging": False,
    "failed_at": None,
    "failed_version": None,
    "running": False,
    "firmware_auto": "on",
}


def test_should_update_accept_and_refusal_reasons():
    assert should_update(100_000, BASE).do
    cases = [
        ({"unit_version": None}, "unit_version_unknown"),
        ({"target_version": "bad"}, "target_version_invalid"),
        ({"unit_version": "1.1.0"}, "current_or_newer"),
        ({"unit_version": "1.0.0-rc1", "target_version": "1.0.0"}, "current_or_newer"),
        ({"link_healthy": False}, "link_unhealthy"),
        ({"in_turn": True}, "turn_in_progress"),
        ({"in_call": True}, "in_call"),
        ({"timer_active": True}, "timer_or_alarm"),
        ({"alarm_active": True}, "timer_or_alarm"),
        ({"timer_due_in": 600}, "timer_or_alarm"),
        ({"muted": True}, "muted"),
        ({"full_quiet": True}, "full_quiet"),
        ({"battery_percent": None}, "battery_low_or_unknown"),
        ({"battery_percent": 39}, "battery_low_or_unknown"),
        ({"failed_at": 99_000, "failed_version": "1.1.0"}, "failure_backoff"),
        ({"running": True}, "already_running"),
        ({"firmware_auto": "off"}, "setting_off"),
    ]
    for changes, why in cases:
        decision = should_update(100_000, BASE | changes)
        assert not decision.do and decision.why == why
    assert should_update(100_000, BASE | {"charging": True, "battery_percent": None}).do
    assert should_update(100_000, BASE | {"firmware_auto": None}).do


def _updater(tmp_path, *, reported=None):
    image = b"verified firmware image"
    answer = {
        "available": True,
        "version": "1.1.0",
        "sha256": hashlib.sha256(image).hexdigest(),
        "size": len(image),
    }
    served = []
    calls = []
    reports = []
    updater = FirmwareUpdater(
        ask_home=lambda: answer,
        download=lambda path: path.write_bytes(reported if reported is not None else image),
        serve_once=lambda path: served.append(path.read_bytes()) or "http://body/one-time",
        call_tool=lambda name, args: calls.append((name, args)),
        situation=lambda: BASE.copy(),
        battery=lambda: {"percent": 80, "charging": False},
        unit_version=lambda: "1.0.0",
        now=lambda: 100_000,
        report=lambda updating, progress: reports.append((updating, progress)),
    )
    return updater, answer, served, calls, reports


def test_hash_mismatch_fails_and_records_backoff(tmp_path):
    updater, _, served, calls, _ = _updater(tmp_path, reported=b"tampered")
    updater.tick(100_000)
    assert not served and not calls
    assert updater.failed_at == 100_000 and updater.failure_reason == "image_size_mismatch"
    assert (
        should_update(
            100_001, BASE | {"failed_at": updater.failed_at, "failed_version": "1.1.0"}
        ).why
        == "failure_backoff"
    )


def test_hash_mismatch_after_matching_size_fails(tmp_path):
    updater, answer, served, calls, _ = _updater(tmp_path, reported=b"x" * 23)
    answer["size"] = 23
    updater.tick(100_000)
    assert not served and not calls
    assert updater.failure_reason == "image_hash_mismatch"


def test_success_download_call_and_event_state(tmp_path):
    updater, _, served, calls, reports = _updater(tmp_path)
    updater.tick(100_000)
    assert len(served) == 1
    assert calls[0][0] == "self.firmware.update"
    assert calls[0][1]["version"] == "1.1.0"
    assert calls[0][1]["sha256"] == hashlib.sha256(served[0]).hexdigest()
    updater.on_unit_event("firmware_update_started", {}, 100_001)
    updater.on_unit_event("firmware_update_progress", {"percent": 42}, 100_002)
    assert updater.running and updater.progress == 42
    updater.on_unit_event("firmware_update_failed", {"reason": "write"}, 100_003)
    assert not updater.running and updater.failure_reason == "write"
    assert reports[-1] == (False, None)


def test_diagnostics_and_checkin_fields():
    kinds = {
        "firmware_update_started",
        "firmware_update_progress",
        "firmware_update_done",
        "firmware_update_failed",
        "firmware_update_validated",
    }
    assert kinds <= DIAGNOSTIC_KINDS
    payload = build_payload(
        device_id="device",
        address="192.0.2.1",
        connected_since=None,
        facts={},
        status=None,
        bot_version="0.1",
        now=1_800_000_000,
        updating=True,
        update_progress=42,
    )
    assert payload["updating"] is True and payload["update_progress"] == 42


def test_unit_that_comes_back_on_the_old_image_is_a_rollback_and_backs_off(tmp_path):
    updater, _, served, calls, _ = _updater(tmp_path)
    updater.tick(100_000)
    updater.on_unit_event("firmware_update_done", {"version": "1.1.0"}, 100_010)
    assert updater.done_version == "1.1.0"
    # Within 15 minutes the unit is still restarting: no new attempt.
    updater.tick(100_300)
    assert len(calls) == 1
    # Later it is still on the old version: the update is counted as rolled back.
    updater.tick(101_000)
    assert updater.failure_reason == "rolled_back" and updater.failed_version == "1.1.0"
    assert updater.done_version is None
    assert (
        should_update(
            101_001, BASE | {"failed_at": updater.failed_at, "failed_version": "1.1.0"}
        ).why
        == "failure_backoff"
    )


def test_validated_event_clears_the_pending_check(tmp_path):
    updater, _, _, _, _ = _updater(tmp_path)
    updater.tick(100_000)
    updater.on_unit_event("firmware_update_done", {"version": "1.1.0"}, 100_010)
    updater.on_unit_event("firmware_update_validated", {}, 100_090)
    assert updater.done_version is None and updater.failure_reason is None
