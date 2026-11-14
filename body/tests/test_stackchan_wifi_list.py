import json
import logging

from maipai_body.bodies.stackchan.wifi_list import WifiList, prefer_tailnet
from maipai_body.link.checkin import build_payload


class Unit:
    def __init__(self, names=()):
        self.names = list(names)
        self.calls = []
        self.fail_add = None
        self.tailnet_ready = True

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "self.wifi.list_saved":
            return json.dumps([{"index": i, "ssid": name} for i, name in enumerate(self.names)])
        if tool == "self.wifi.add":
            if self.fail_add:
                raise RuntimeError(self.fail_add)
            ssid = args["ssid"]
            self.names = [ssid, *[name for name in self.names if name != ssid]][:10]
            return True
        if tool == "self.wifi.forget":
            self.names.pop(args["index"])
            return True
        if tool == "self.wifi.use_now":
            if args["index"] >= len(self.names):
                return json.dumps({"ok": False, "error": "no_such_network"})
            return json.dumps({"ok": True, "revert_in_s": 180})
        if tool == "self.network.prefer_tailnet":
            if self.tailnet_ready:
                return json.dumps({"ok": True, "minutes": args["minutes"]})
            return json.dumps({"ok": False, "error": "tailnet_not_ready"})
        raise AssertionError(tool)


def test_add_refuses_full_but_accepts_duplicate_at_capacity():
    unit = Unit([f"network-{i}" for i in range(10)])
    wifi = WifiList(unit.call)
    assert wifi.add("new-network", "pw") == {
        "wifi": "refused",
        "why": "The robot already holds 10 networks. Forget one first.",
    }
    assert wifi.add("network-4", "new-password") == {"wifi": "saved"}
    assert unit.names[0] == "network-4"
    assert len(unit.names) == 10


def test_forget_by_name_uses_saved_index_and_unknown_refuses():
    unit = Unit(["first", "second", "third"])
    wifi = WifiList(unit.call)
    assert wifi.forget("second") == {"wifi": "forgotten"}
    assert ("self.wifi.forget", {"index": 1}) in unit.calls
    assert wifi.forget("missing") == {
        "wifi": "refused",
        "why": "That network is not saved on the robot.",
    }


def test_password_never_appears_in_logs_when_add_tool_exception_contains_it(caplog):
    sample_pw = "sample-wifi-pw-123"
    unit = Unit()
    unit.fail_add = f"tool rejected password {sample_pw}"
    wifi = WifiList(unit.call)
    with caplog.at_level(logging.DEBUG):
        result = wifi.add("guest", sample_pw)
    assert result["wifi"] == "refused"
    assert sample_pw not in caplog.text


def test_saved_keeps_last_list_when_unit_becomes_unreachable():
    unit = Unit(["home", "friend"])
    wifi = WifiList(unit.call)
    assert wifi.saved() == ["home", "friend"]
    unit.call = lambda *_args: (_ for _ in ()).throw(RuntimeError("offline"))
    assert wifi.saved() == ["home", "friend"]


def test_checkin_payload_includes_saved_names_and_encryption_flag():
    payload = build_payload(
        device_id="unit",
        address="192.0.2.1",
        connected_since=None,
        facts={},
        status=None,
        bot_version="1",
        now=0,
        wifi_saved=["home", "x" * 40],
        link_encrypted=True,
    )
    assert payload["wifi_saved"] == ["home", "x" * 32]
    assert payload["link_encrypted"] is True


def test_a_unit_that_answers_false_as_text_or_wrapper_is_a_refusal():
    for answer in ("false", {"result": False}, "False"):
        unit = Unit(["Home"])
        original = unit.call

        def call(tool, args, original=original, answer=answer):
            if tool == "self.wifi.add":
                return answer
            return original(tool, args)

        result = WifiList(call).add("Hotspot", "pw")
        assert result["wifi"] == "refused"


def test_checkin_says_how_the_robot_is_connected():
    from maipai_body.link.checkin import UnitFacts, build_payload, link_path

    assert link_path("198.51.100.20") == "home"
    assert link_path("100.64.0.9") == "away"  # the laptop relay's Tailscale address
    assert link_path("8.8.8.8") == "other"
    assert link_path(None) is None and link_path("not an address") is None
    facts = UnitFacts()
    facts.observe("wifi", {"state": "ws_retry", "attempt": 3, "rssi": -64, "wifi": 1})
    payload = build_payload(
        device_id="r1",
        address="100.64.0.9",
        connected_since=None,
        facts=facts.snapshot(),
        status=None,
        bot_version="0.2.103",
        now=0.0,
    )
    assert payload["link_path"] == "away"
    assert payload["link_state"] == "ws_retry" and payload["link_attempt"] == 3
    offline = build_payload(
        device_id=None,
        address=None,
        connected_since=None,
        facts={},
        status=None,
        bot_version=None,
        now=0.0,
    )
    assert (
        offline["link_path"] is None
        and offline["link_state"] is None
        and offline["link_attempt"] is None
    )


def _payload(address, facts):
    return build_payload(
        device_id="unit",
        address=address,
        connected_since=None,
        facts=facts,
        status=None,
        bot_version="1",
        now=0,
    )


def test_the_units_own_tailnet_connection_is_an_encrypted_channel():
    up = {"tailnet_state": "connected", "tailnet_ip": "100.84.176.31"}
    assert _payload("100.84.176.31", up)["link_encrypted"] is True
    # The laptop relay: a tailnet peer that is not the unit's own address (plain Wi-Fi last leg).
    assert _payload("100.70.0.9", up)["link_encrypted"] is False
    # A home address stays plain even while the tailnet client is up.
    assert _payload("192.0.2.5", up)["link_encrypted"] is False
    # The client must be connected, and must have reported an address.
    down = {"tailnet_state": "reconnecting", "tailnet_ip": "100.84.176.31"}
    assert _payload("100.84.176.31", down)["link_encrypted"] is False
    assert _payload("100.84.176.31", {"tailnet_state": "connected"})["link_encrypted"] is False
    assert _payload(None, up)["link_encrypted"] is False


def test_tailnet_events_are_kept_as_unit_facts():
    from maipai_body.link.checkin import UnitFacts

    facts = UnitFacts()
    facts.observe("tailnet_state", {"state": "connected", "ip": "100.84.176.31"})
    assert facts.snapshot()["tailnet_state"] == "connected"
    assert facts.snapshot()["tailnet_ip"] == "100.84.176.31"
    assert facts.changed.is_set()


def test_use_asks_the_unit_to_join_the_named_saved_network_by_index():
    unit = Unit(["Home", "Hotspot"])
    wifi = WifiList(unit.call)
    assert wifi.use("Hotspot") == {"wifi": "switching"}
    assert ("self.wifi.use_now", {"index": 1}) in unit.calls
    # Nothing in this path writes the saved list.
    assert not any(
        tool in {"self.wifi.add", "self.wifi.forget", "self.wifi.switch"} for tool, _ in unit.calls
    )


def test_use_refuses_an_unknown_name_and_a_bad_value():
    unit = Unit(["Home"])
    wifi = WifiList(unit.call)
    assert wifi.use("Missing")["wifi"] == "refused"
    assert wifi.use(None)["wifi"] == "refused"
    assert not any(tool == "self.wifi.use_now" for tool, _ in unit.calls)


def test_use_reports_a_unit_that_refuses_or_is_unreachable():
    unit = Unit(["Home"])
    wifi = WifiList(
        lambda tool, args: (
            json.dumps({"ok": False}) if tool == "self.wifi.use_now" else unit.call(tool, args)
        )
    )
    assert wifi.use("Home")["wifi"] == "refused"

    def broken(tool, args):
        if tool == "self.wifi.use_now":
            raise RuntimeError("unit gone")
        return unit.call(tool, args)

    assert WifiList(broken).use("Home")["wifi"] == "refused"


def test_prefer_tailnet_passes_minutes_and_reports_a_tailnet_that_is_not_up():
    unit = Unit()
    assert prefer_tailnet(unit.call, {"minutes": 10}) == {"tailnet": "preferred", "minutes": 10}
    assert ("self.network.prefer_tailnet", {"minutes": 10}) in unit.calls
    assert prefer_tailnet(unit.call, {"minutes": 0}) == {"tailnet": "off"}
    unit.tailnet_ready = False
    assert prefer_tailnet(unit.call, {"minutes": 5})["tailnet"] == "refused"
    for bad in ({}, {"minutes": -1}, {"minutes": 500}, {"minutes": "x"}, {"minutes": True}, None):
        assert prefer_tailnet(unit.call, bad)["tailnet"] == "refused"


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_every_change_records_a_result_the_card_can_show(caplog):
    caplog.set_level(logging.INFO)
    unit = Unit(["home"])
    clock = FakeClock()
    changed = []
    wifi = WifiList(unit.call, on_changed=lambda: changed.append(1), clock=clock)

    assert wifi.add("phone-hotspot", "secret-pw") == {"wifi": "saved"}
    assert wifi.last == {"action": "add", "result": "ok", "name": "phone-hotspot", "at": clock.now}
    assert wifi.saved_at == clock.now and wifi.change_seq == 1 and changed
    assert wifi.saved() == ["phone-hotspot", "home"]

    assert wifi.use("phone-hotspot") == {"wifi": "switching"}
    assert wifi.last["action"] == "use" and wifi.last["result"] == "switching"

    assert wifi.forget("home") == {"wifi": "forgotten"}
    assert wifi.last["result"] == "ok" and wifi.change_seq == 3

    lines = [r.getMessage() for r in caplog.records if "robot activity" in r.getMessage()]
    assert "robot activity: wifi_add result=ok" in lines
    assert "robot activity: wifi_use result=switching" in lines
    assert "robot activity: wifi_forget result=ok" in lines
    assert "secret-pw" not in caplog.text and "phone-hotspot" not in "\n".join(lines)


def test_add_says_why_when_the_unit_cannot_be_read_or_is_full():
    unit = Unit([f"n{i}" for i in range(10)])
    wifi = WifiList(unit.call, clock=FakeClock())
    assert wifi.add("extra", "pw")["wifi"] == "refused"
    assert wifi.last["result"] == "full" and wifi.last["name"] == "extra"

    def broken(tool, args):
        raise RuntimeError("no StackChan is connected")

    down = WifiList(broken, clock=FakeClock())
    assert down.add("net", "pw") == {"wifi": "refused", "why": "The robot could not be reached."}
    assert down.last["result"] == "unreachable" and down.saved_at is None
    assert down.has_saved is False


def test_a_refused_add_from_the_unit_is_recorded():
    class Refusing(Unit):
        def call(self, tool, args):
            if tool == "self.wifi.add":
                return False
            return super().call(tool, args)

    wifi = WifiList(Refusing([]).call, clock=FakeClock())
    assert wifi.add("net", "pw")["wifi"] == "refused"
    assert wifi.last["result"] == "refused"


def test_the_units_own_answer_to_a_switch_is_recorded_and_stale_ones_are_ignored():
    unit = Unit(["home", "hotspot"])
    clock = FakeClock()
    wifi = WifiList(unit.call, clock=clock)
    wifi.note_use_event("wifi_use_ok")  # no switch was asked for: ignored
    assert wifi.last is None
    wifi.use("hotspot")
    wifi.note_use_event("wifi_use_revert")
    assert wifi.last == {"action": "use", "result": "reverted", "name": "hotspot", "at": clock.now}
    wifi.use("hotspot")
    wifi.note_use_event("wifi_use_ok")
    assert wifi.last["result"] == "joined"
    clock.now += 601  # too late to belong to that switch
    before = wifi.change_seq
    wifi.note_use_event("wifi_use_revert")
    assert wifi.change_seq == before


def test_checkin_carries_when_the_list_was_read_what_the_last_change_did_and_the_current_network():
    payload = build_payload(
        device_id="d",
        address="192.0.2.7",
        connected_since=0.0,
        facts={},
        status={"network": {"signal": "strong", "ssid": "home"}},
        bot_version="0.2.0",
        now=10.0,
        wifi_saved=["home", "hotspot"],
        wifi_saved_at=1_700_000_000.0,
        wifi_last={"action": "add", "result": "ok", "name": "hotspot", "at": 1_700_000_005.0},
    )
    assert payload["wifi_saved"] == ["home", "hotspot"]
    assert payload["wifi_current"] == "home"
    assert payload["wifi_saved_at"].startswith("2023-11-14T")
    assert payload["wifi_last"]["action"] == "add" and payload["wifi_last"]["result"] == "ok"
    assert payload["wifi_last"]["name"] == "hotspot" and payload["wifi_last"]["at"].startswith(
        "2023-11-14T"
    )


def test_the_current_network_is_never_named_unless_it_is_a_saved_one():
    payload = build_payload(
        device_id="d",
        address="192.0.2.7",
        connected_since=0.0,
        facts={},
        status={"network": {"signal": "strong", "ssid": "someone-elses"}},
        bot_version="0.2.0",
        now=10.0,
        wifi_saved=["home"],
    )
    assert "wifi_current" not in payload and "someone-elses" not in str(payload)
    bad = build_payload(
        device_id="d",
        address=None,
        connected_since=None,
        facts={},
        status=None,
        bot_version=None,
        now=0.0,
        wifi_saved_at=True,
        wifi_last={"action": "drop-table", "result": "ok", "at": 1.0},
    )
    assert "wifi_saved_at" not in bad and "wifi_last" not in bad
