"""StackChan mute, vision off and full quiet on the host (firmware patches 105 to 108). Fake unit,
fake clock, no sockets: the unit is the authority and the host reads its state back."""

from __future__ import annotations

import json
import logging

import pytest

from maipai_body.bodies.stackchan.adapter import _CameraAdapter, _HeadAdapter
from maipai_body.bodies.stackchan.privacy import (
    SETTLE_S,
    PrivacyController,
    PrivacyState,
)
from maipai_body.link.checkin import UnitFacts, build_payload
from maipai_body.settings_keys import (
    LOCAL_UNMUTE_KEY,
    MUTED_KEY,
    QUIET_KEY,
    VISION_OFF_KEY,
)


class FakeUnit:
    """The three privacy tools of firmware patch 106, with the microphone read-back."""

    def __init__(self, *, verifies: bool = True) -> None:
        self.muted = self.vision_off = self.quiet = False
        self.verifies = verifies
        self.local_unmute = True
        self.calls: list[tuple[str, dict]] = []
        self.offline = False

    def report(self) -> dict:
        mic_off = self.muted or self.quiet
        return {
            "muted": int(self.muted),
            "vision_off": int(self.vision_off),
            "quiet": int(self.quiet),
            "mic_off": int(mic_off),
            "mic_off_verified": int(mic_off and self.verifies),
            "mute_source": "home",
            "local_unmute": int(self.local_unmute),
            "mic_regs": "47:ff,48:ff",
        }

    def __call__(self, tool: str, arguments: dict) -> object:
        self.calls.append((tool, dict(arguments)))
        if self.offline:
            raise ConnectionError("no unit")
        if tool == "self.privacy.set":
            for name, attr in (("mute", "muted"), ("vision_off", "vision_off"), ("quiet", "quiet")):
                if arguments.get(name, -1) >= 0:
                    setattr(self, attr, bool(arguments[name]))
            return json.dumps(self.report())
        if tool == "self.privacy.get":
            return json.dumps(self.report())
        if tool == "self.privacy.set_policy":
            self.local_unmute = bool(arguments["local_unmute"])
            return True
        raise AssertionError(tool)


def _setup(unit: FakeUnit | None = None):
    now = [1000.0]
    unit = unit or FakeUnit()
    state = PrivacyState(clock=lambda: now[0])
    controller = PrivacyController(unit, state, clock=lambda: now[0])
    return unit, state, controller, now


# ---- the state the unit reports ---------------------------------------------------------------


def test_nothing_is_known_until_the_unit_reports():
    state = PrivacyState()
    assert state.known is False and state.muted_reason() is None
    assert state.facts()["muted"] is None
    state.observe("privacy", {"muted": 1, "vision_off": 0, "quiet": 0, "mic_off_verified": 1})
    assert state.known and state.muted and state.muted_reason() == "muted"
    assert state.facts() == {
        "muted": True,
        "vision_off": False,
        "quiet": False,
        "mic_off_verified": True,
        "mute_source": None,
    }


def test_full_quiet_is_a_reason_and_blocks_the_head_but_vision_off_does_not():
    state = PrivacyState()
    state.observe("privacy", {"muted": 0, "vision_off": 1, "quiet": 0})
    assert state.muted_reason() is None and state.head_blocked() is None
    state.observe("privacy", {"muted": 0, "vision_off": 1, "quiet": 1})
    assert state.muted_reason() == "full quiet" and state.head_blocked() == "full quiet"
    state.observe("privacy", {"muted": 1, "vision_off": 1, "quiet": 1})
    assert state.muted_reason() == "muted"  # mute names the cause first


def test_a_change_logs_one_line_and_calls_every_listener(caplog):
    state = PrivacyState()
    seen: list[bool] = []
    state.listeners.append(lambda s: seen.append(s.muted))
    state.listeners.append(lambda s: 1 / 0)  # a failing listener never stops the others
    with caplog.at_level(logging.INFO):
        state.observe("privacy", {"muted": 1, "mic_off_verified": 0, "mute_source": "face"})
        state.observe("wake_stats", {"muted": 1, "mic_off_verified": 0, "armed": 0})  # no change
    assert seen == [True]
    lines = [r.getMessage() for r in caplog.records if "privacy:" in r.getMessage()]
    assert len(lines) == 1 and "face" in lines[0] and "not verified" in lines[0]


# ---- the leak check ---------------------------------------------------------------------------


def _leaks(state: PrivacyState) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    state.on_leak = lambda what, detail: found.append((what, detail))
    return found


def test_a_muted_unit_with_a_fetch_or_detection_is_an_error_event(caplog):
    unit, state, controller, now = _setup()
    found = _leaks(state)
    state.observe("privacy", {"muted": 1, "mic_off_verified": 1})
    quiet_minute = {"muted": 1, "armed": 0, "fetches": 0, "detections": 0, "vad_speech": 0}
    state.observe("wake_stats", quiet_minute)
    assert found == []  # a mute that just began: the minute's counters began before it
    now[0] += SETTLE_S + 1
    state.observe("wake_stats", quiet_minute)
    assert found == []
    with caplog.at_level(logging.ERROR):
        state.observe("wake_stats", {**quiet_minute, "fetches": 12})
    assert [what for what, _ in found] == ["microphone"] and "fetches=12" in found[0][1]
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    state.observe("wake_stats", {**quiet_minute, "detections": 1})  # logged once a minute only
    assert len(found) == 1
    now[0] += 61
    state.observe("wake_stats", {**quiet_minute, "armed": 1})
    assert len(found) == 2


def test_full_quiet_listens_to_nothing_either():
    _, state, _, now = _setup()
    found = _leaks(state)
    state.observe("privacy", {"muted": 0, "quiet": 1, "mic_off_verified": 1})
    now[0] += SETTLE_S + 1
    state.observe("wake_stats", {"muted": 0, "quiet": 1, "fetches": 3})
    assert len(found) == 1


def test_an_unmuted_unit_fetching_is_normal():
    _, state, _, now = _setup()
    found = _leaks(state)
    state.observe("wake_stats", {"muted": 0, "quiet": 0, "armed": 1, "fetches": 5900})
    assert found == []


def test_vision_off_with_captured_frames_is_a_leak_and_a_late_frame_too():
    _, state, _, now = _setup()
    found = _leaks(state)
    state.observe("privacy", {"muted": 0, "vision_off": 1, "quiet": 0})
    state.observe("camera", {"vision_off": 1, "captured": 4, "sent": 4})
    assert found == []  # inside the settle window
    state.frame_arrived()
    assert found == []
    now[0] += SETTLE_S + 1
    state.observe("camera", {"vision_off": 1, "captured": 0, "sent": 0, "vision_skipped": 170})
    assert found == []
    state.observe("camera", {"vision_off": 1, "captured": 2, "sent": 2})
    assert [what for what, _ in found] == ["camera"]
    now[0] += 61
    state.frame_arrived()
    assert [what for what, _ in found] == ["camera", "camera"]


def test_the_camera_report_with_vision_on_is_not_a_leak():
    _, state, _, _ = _setup()
    found = _leaks(state)
    state.observe("camera", {"vision_off": 0, "captured": 170, "sent": 170})
    assert found == []


def test_a_mic_that_stays_unverified_is_said_once(caplog):
    _, state, _, now = _setup()
    state.observe("privacy", {"muted": 1, "mic_off_verified": 0})
    with caplog.at_level(logging.WARNING):
        state.tick()
        now[0] += 61
        state.tick()
        state.tick()
    assert len([r for r in caplog.records if "not confirmed" in r.getMessage()]) == 1


# ---- asking the unit --------------------------------------------------------------------------


def test_a_mute_is_confirmed_only_from_the_units_read_back():
    unit, state, controller, _ = _setup()
    answer = controller.command(True)
    assert answer == {"muted": True, "status": "confirmed", "mic_off_verified": True}
    assert unit.calls == [("self.privacy.set", {"mute": 1})]


def test_a_mute_the_unit_cannot_verify_is_never_called_confirmed():
    unit, state, controller, _ = _setup(FakeUnit(verifies=False))
    answer = controller.command(True)
    assert answer["status"] == "unconfirmed" and answer["mic_off_verified"] is False
    assert answer["muted"] is True  # the unit did mute; Home must not say "Muted" yet


def test_a_lost_unit_leaves_the_request_pending_and_it_is_retried_on_connect():
    unit, state, controller, _ = _setup()
    unit.offline = True
    answer = controller.command(True)
    assert answer["status"] == "unconfirmed" and answer["muted"] is False
    unit.offline = False
    unit.calls.clear()
    controller.on_connect()
    assert ("self.privacy.get", {}) in unit.calls
    assert ("self.privacy.set", {"mute": 1}) in unit.calls
    assert state.muted


def test_a_remote_unmute_needs_a_confirm():
    unit, state, controller, _ = _setup()
    controller.command(True)
    unit.calls.clear()
    refused = controller.command(False)
    assert refused["status"] == "needs_confirm" and refused["muted"] is True
    assert "confirmation" in refused["error"] and unit.calls == []
    refused = controller.command(False, {"confirm": "yes"})  # only a real true counts
    assert refused["status"] == "needs_confirm"
    done = controller.command(False, {"confirm": True})
    assert done["status"] == "confirmed" and done["muted"] is False
    assert unit.calls == [("self.privacy.set", {"mute": 0})]


def test_the_hub_commands_are_wired_to_the_controller():
    unit, state, controller, _ = _setup()
    handlers = controller.handlers()
    assert handlers["mute"]({})["status"] == "confirmed"
    assert handlers["unmute"]({})["status"] == "needs_confirm"
    assert handlers["unmute"]({"confirm": True})["muted"] is False


# ---- Home's settings --------------------------------------------------------------------------


def test_connecting_never_resets_a_mute_the_unit_holds():
    unit, state, controller, _ = _setup()
    unit.muted = True
    controller.on_connect()
    assert state.muted and not [c for c in unit.calls if c[0] == "self.privacy.set"]
    # Home's first settings dump says unmuted: the unit's own state stands.
    controller.apply_settings({MUTED_KEY: False, VISION_OFF_KEY: False, QUIET_KEY: False})
    assert unit.muted and not [c for c in unit.calls if c[0] == "self.privacy.set"]


def test_a_first_settings_dump_that_restricts_is_applied():
    unit, state, controller, _ = _setup()
    controller.apply_settings({MUTED_KEY: True, VISION_OFF_KEY: False})
    assert unit.muted and not unit.vision_off
    assert ("self.privacy.set", {"mute": 1}) in unit.calls


def test_a_changed_setting_is_pushed_in_both_directions():
    unit, state, controller, _ = _setup()
    controller.apply_settings({MUTED_KEY: False, QUIET_KEY: False, VISION_OFF_KEY: False})
    controller.apply_settings({VISION_OFF_KEY: True})
    assert unit.vision_off and state.vision_off
    controller.apply_settings({QUIET_KEY: True})
    assert unit.quiet and state.quiet and state.muted_reason() == "full quiet"
    controller.apply_settings({VISION_OFF_KEY: False, QUIET_KEY: False})
    assert not unit.vision_off and not unit.quiet
    # A repeat of the same value does nothing.
    unit.calls.clear()
    controller.apply_settings({VISION_OFF_KEY: False, QUIET_KEY: False})
    assert unit.calls == []


def test_vision_off_and_mute_combine_and_come_back_separately():
    unit, state, controller, _ = _setup()
    controller.push(mute=True, vision_off=True)
    assert state.muted and state.vision_off and not state.quiet
    controller.push(mute=False)
    assert not state.muted and state.vision_off


def test_the_local_unmute_policy_is_sent_once_and_again_on_connect():
    unit, state, controller, _ = _setup()
    controller.apply_settings({LOCAL_UNMUTE_KEY: False})
    controller.apply_settings({LOCAL_UNMUTE_KEY: False})
    assert [c for c in unit.calls if c[0] == "self.privacy.set_policy"] == [
        ("self.privacy.set_policy", {"local_unmute": False})
    ]
    unit.local_unmute = True  # a restarted unit that lost it
    controller.on_connect()
    assert unit.local_unmute is False


def test_an_unconfirmed_request_is_said_once_after_a_minute(caplog):
    unit, state, controller, now = _setup(FakeUnit(verifies=False))
    controller.command(True)
    with caplog.at_level(logging.WARNING):
        controller.tick()
        now[0] += 61
        controller.tick()
        controller.tick()
    assert len([r for r in caplog.records if "has not confirmed" in r.getMessage()]) == 1


# ---- the check-in -----------------------------------------------------------------------------


def test_the_checkin_carries_the_three_states_and_the_microphone_proof():
    facts = UnitFacts()
    facts.observe(
        "privacy",
        {"muted": 1, "vision_off": 0, "quiet": 0, "mic_off_verified": 1, "mute_source": "face"},
    )
    assert facts.changed.is_set()  # a change on the unit reports at once
    payload = build_payload(
        device_id="x",
        address=None,
        connected_since=None,
        facts=facts.snapshot(),
        status=None,
        bot_version=None,
        now=0,
    )
    assert payload["muted"] is True and payload["vision_off"] is False and payload["quiet"] is False
    assert payload["mic_off_verified"] is True and payload["mute_source"] == "face"


def test_the_checkin_says_null_until_the_unit_has_reported():
    payload = build_payload(
        device_id=None,
        address=None,
        connected_since=None,
        facts={},
        status=None,
        bot_version=None,
        now=0,
    )
    for key in ("muted", "vision_off", "quiet", "mic_off_verified", "mute_source"):
        assert payload[key] is None


def test_the_minute_report_keeps_the_state_too():
    facts = UnitFacts()
    facts.observe("wake_stats", {"muted": 1, "vision_off": 1, "quiet": 0, "mic_off_verified": 0})
    snap = facts.snapshot()
    assert snap["muted"] == 1 and snap["vision_off"] == 1 and snap["mic_off_verified"] == 0


# ---- the host honours the state ---------------------------------------------------------------


class _Client:
    def __init__(self) -> None:
        self.head: list[tuple] = []

    def set_head_angles(self, yaw, pitch, speed):
        self.head.append((yaw, pitch, speed))
        return {"yaw": yaw, "pitch": pitch, "speed": speed}

    def get_head_angles(self):
        return {"yaw": 0, "pitch": 0}

    def cancel_pending(self):
        pass


def test_the_head_adapter_makes_no_move_in_full_quiet():
    client = _Client()
    head = _HeadAdapter(client, profile=None)
    state = PrivacyState()
    head.move_blocked = state.head_blocked
    head.command("set", yaw=0.2, pitch=0.1)
    assert len(client.head) == 1
    state.observe("privacy", {"muted": 0, "quiet": 1})
    result = head.command("set", yaw=0.4, pitch=0.1)
    assert result["blocked"] == "full quiet" and len(client.head) == 1
    state.observe("privacy", {"muted": 0, "quiet": 0})
    head.command("goto", yaw=0.1, pitch=0.0)
    assert len(client.head) == 2


class _CamClient:
    def __init__(self) -> None:
        self.photos = 0
        self.sent: list[bytes] = []

    def take_photo(self):
        self.photos += 1
        return b"jpeg"

    def send_avatar_frame(self, frame):
        self.sent.append(frame)
        return True


def test_the_camera_takes_no_picture_and_starts_no_stream_while_vision_is_off():
    client = _CamClient()
    leds = type("L", (), {"camera_indicator_active": False})()
    robot = type(
        "R", (), {"estop": type("E", (), {"engaged": False})(), "_driver": lambda self, _n: leds}
    )()
    cam = _CameraAdapter(client, robot=robot)
    off = {"on": True}
    cam.vision_off = lambda: off["on"]
    cam.silent_capture_allowed = lambda: True
    with pytest.raises(PermissionError, match="vision is off"):
        cam.command("frame")
    with pytest.raises(PermissionError, match="vision is off"):
        cam.command("frame", silent=True)
    assert cam.command("stream_frame", 0.4) is None
    assert cam.command("stream", enabled=True, silent=True) is False
    assert cam.command("stream", enabled=True) is False
    assert client.photos == 0 and client.sent == []
    cam.command("stream", enabled=False)  # stopping the stream is always allowed
    assert len(client.sent) == 1
    off["on"] = False
    assert cam.command("frame", silent=True) == b"jpeg"


# ---- a camera frame that arrives while vision is off is dropped and reported --------------------


def test_the_avatar_server_drops_and_reports_a_frame_while_vision_is_off():
    import asyncio

    from websockets.asyncio.server import serve

    from maipai_body.bodies.stackchan.avatar.server import AvatarServer
    from maipai_body.bodies.stackchan.xiaozhi.pairing import PairingStore
    from tests.stackchan_sim.avatar_peer import AvatarPeer
    from tests.stackchan_sim.camera_sender import jpeg_frame

    async def run() -> tuple[list[bytes], int, int]:
        store = PairingStore()
        device, client = "02:00:00:00:00:36", "00000000-0000-4000-8000-000000000036"
        store.request(device, client)
        token = store.approve(device, client)
        avatar = AvatarServer(store)
        seen: list[bytes] = []
        reported = [0]
        blocked = {"on": True}
        avatar.on_camera_frame = lambda _device, frame: seen.append(frame)
        avatar.vision_blocked = lambda: blocked["on"]
        avatar.on_frame_while_vision_off = lambda: reported.__setitem__(0, reported[0] + 1)
        server = await serve(avatar.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        peer = AvatarPeer(
            f"ws://127.0.0.1:{port}/stackChan/ws?deviceType=StackChan", device, client, token
        )
        try:
            await peer.connect()
            await peer.send_camera_frame(jpeg_frame(b"dropped"))
            await asyncio.sleep(0.2)
            dropped = (len(seen), avatar.camera_frames_received)
            blocked["on"] = False
            await peer.send_camera_frame(jpeg_frame(b"kept"))
            await avatar.wait_for_camera_frame(device)
            return seen, reported[0], dropped[0] + dropped[1]
        finally:
            await peer.close()
            server.close()
            await server.wait_closed()

    seen, reported, dropped_total = asyncio.run(run())
    assert dropped_total == 0  # nothing was kept or analysed while it was off
    assert reported == 1
    assert len(seen) == 1  # the frame after vision came back is normal


def test_a_unit_in_full_quiet_is_not_treated_as_deaf():
    from maipai_body.bodies.stackchan.self_heal import SelfHealState

    heal = SelfHealState()
    heal.observe("wake_stats", {"muted": 0, "quiet": 1, "armed": 0, "fetches": 0})
    assert heal.muted is True
    heal.observe("wake_stats", {"muted": 0, "quiet": 0, "armed": 1, "fetches": 5900})
    assert heal.muted is False
