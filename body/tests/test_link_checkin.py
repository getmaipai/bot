import threading

from maipai_body.link.checkin import CHECKIN_PATH, RobotCheckin, UnitFacts, build_payload


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _Session:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.calls = []

    def put(self, url, json, headers, timeout):
        self.calls.append((url, json, headers))
        return _Response(self.status_code)


def test_facts_keep_the_latest_boot_memory_and_firmware():
    facts = UnitFacts()
    facts.observe("boot", {"reason": 1, "crash_resets": 2})
    facts.observe("heap_stats", {"int_free": 30000, "int_min": 9971, "psram_free": 5000000})
    facts.observe("fw", {"version": "0.2.31", "rssi": -61})
    facts.observe("touch_down", {"x": 1})
    snap = facts.snapshot()
    assert snap["boot_reason"] == 1 and snap["boot_crash_resets"] == 2
    assert snap["int_free"] == 30000 and snap["psram_free"] == 5000000
    assert snap["fw_version"] == "0.2.31" and snap["fw_rssi"] == -61
    assert facts.changed.is_set()


def test_payload_always_has_every_key_and_nulls_for_unknowns():
    payload = build_payload(
        device_id=None,
        address=None,
        connected_since=None,
        facts={},
        status=None,
        bot_version=None,
        now=0,
    )
    assert payload["online"] is False
    assert payload["last_seen"] == "1970-01-01T00:00:00+00:00"
    assert payload["firmware_version"] is None and payload["ip"] is None
    assert payload["board"] == "m5stack-stack-chan"


def test_payload_reports_a_connected_unit():
    payload = build_payload(
        device_id="aa:bb:cc:dd:ee:ff",
        address="192.0.2.7",
        connected_since=60.0,
        facts={"fw_version": "0.2.31", "int_free": 25000, "boot_reason": 3},
        status={
            "network": {"signal": "strong", "ssid": "never sent"},
            "battery": {"level": 80, "charging": False},
        },
        bot_version="0.2.31",
        now=120.0,
    )
    assert payload["online"] is True and payload["ip"] == "192.0.2.7"
    assert payload["signal"] == "strong" and payload["battery_level"] == 80
    assert payload["charging"] is False and payload["boot_reason"] == 3
    assert "never sent" not in str(payload)


def _checkin(session, **kw):
    return RobotCheckin(
        lambda: ("cookie", "http://hub"),
        threading.Event(),
        lambda: {"online": True},
        UnitFacts(),
        threading.Event(),
        session=session,
        **kw,
    )


def test_send_puts_to_the_checkin_route_with_the_session_cookie():
    session = _Session()
    assert _checkin(session, interval_s=60.0).send_once() == 60.0
    url, body, headers = session.calls[0]
    assert url == "http://hub" + CHECKIN_PATH and body == {"online": True}
    assert headers == {"Cookie": "session=cookie"}


def test_a_hub_without_the_route_is_asked_again_in_ten_minutes():
    assert _checkin(_Session(404)).send_once() == 600.0


def test_the_light_tool_keeps_the_raw_channel_counts_for_the_minute_log():
    from maipai_body.bodies.stackchan.xiaozhi.server import XiaozhiDeviceClient

    client = XiaozhiDeviceClient.__new__(XiaozhiDeviceClient)
    client._call = lambda name, args: {"lux": 3.5, "ch0": 12, "ch1": 4}
    assert client.get_ambient_light() == 3.5
    assert client.last_light_raw == (12, 4)
