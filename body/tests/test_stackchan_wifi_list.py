import json
import logging

from maipai_body.bodies.stackchan.wifi_list import WifiList
from maipai_body.link.checkin import build_payload


class Unit:
    def __init__(self, names=()):
        self.names = list(names)
        self.calls = []
        self.fail_add = None

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
    unit.fail_add = f"tool rejected password {secret}"
    wifi = WifiList(unit.call)
    with caplog.at_level(logging.DEBUG):
        result = wifi.add("guest", secret)
    assert result["wifi"] == "refused"
    assert secret not in caplog.text


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
