from __future__ import annotations

from types import SimpleNamespace

from maipai_body.bodies.reachy_mini import client as reachy_client_module
from maipai_body.bodies.reachy_mini.audio_config import XVF3800_CONFIG, AudioConfigurator
from maipai_body.bodies.reachy_mini.client import ReachyMiniClient


class FakeDaemon:
    def __init__(self):
        self.params = {name: list(values) for name, values in XVF3800_CONFIG.items()}
        self.calls = []
        self.fail_verify = False
        self.missing_apply = False

    def get_audio_parameter(self, name):
        self.calls.append(("get", name))
        if self.fail_verify and name == next(iter(XVF3800_CONFIG)):
            return [999]
        return self.params[name]

    def apply_audio_config(self, config, verify=True):
        self.calls.append(("apply", config, verify))
        if self.missing_apply:
            raise RuntimeError("404 not found")
        self.params.update({name: values for name, values in config.items()})
        return True

    def set_microphone_volume(self, volume):
        self.calls.append(("mic_volume", volume))

    def set_output_volume(self, volume):
        self.calls.append(("output_volume", volume))


def test_connect_reads_defaults_applies_profile_verifies_and_waits():
    daemon = FakeDaemon()
    sleeps = []
    result = AudioConfigurator(daemon, sleep=sleeps.append).on_connect()
    assert result.ok
    assert daemon.calls[0] == ("get", next(iter(XVF3800_CONFIG)))
    assert ("apply", XVF3800_CONFIG, True) in daemon.calls
    assert ("mic_volume", 100) in daemon.calls
    assert sleeps == [0.1]


def test_verify_mismatch_and_missing_config_endpoint_are_nonblocking():
    for setup in ("mismatch", "missing"):
        daemon = FakeDaemon()
        if setup == "mismatch":
            daemon.fail_verify = True
        else:
            daemon.missing_apply = True
        result = AudioConfigurator(daemon, sleep=lambda _: None).on_connect()
        assert not result.ok
        assert result.health == (
            "audio_config_failed" if setup == "mismatch" else "no_audio_device"
        )


def test_silent_capture_reboots_once_then_reapplies_after_five_seconds():
    daemon = FakeDaemon()
    clock = [0.0]
    actions = []
    config = AudioConfigurator(
        daemon,
        sleep=lambda seconds: actions.append(("sleep", seconds)),
        clock=lambda: clock[0],
        reboot=lambda: actions.append(("reboot",)),
    )
    config.on_connect()
    config.observe_capture_peak(0.0)
    clock[0] += 5.0
    assert config.observe_capture_peak(0.0)
    assert not config.observe_capture_peak(0.0)
    assert actions.count(("reboot",)) == 1
    assert ("sleep", 4.0) in actions


def test_requested_output_volume_waits_for_idle():
    daemon = FakeDaemon()
    config = AudioConfigurator(daemon, sleep=lambda _: None)
    config.request_output_volume(35)
    assert not config.apply_pending_output_volume(turn_active=True)
    assert not any(call[0] == "output_volume" for call in daemon.calls)
    assert config.apply_pending_output_volume(turn_active=False)
    assert ("output_volume", 35) in daemon.calls


def test_client_uses_the_pinned_daemon_http_contract(monkeypatch):
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def get(url, **kwargs):
        calls.append(("get", url, kwargs))
        param = url.rsplit("/", 1)[-1]
        return Response({"name": param, "values": XVF3800_CONFIG.get(param, [0.8])})

    def post(url, *, json, **kwargs):
        calls.append(("post", url, json, kwargs))
        return Response({"applied": True, "volume": json.get("volume", 100)})

    monkeypatch.setattr(reachy_client_module.requests, "get", get)
    monkeypatch.setattr(reachy_client_module.requests, "post", post)
    fake_sdk = SimpleNamespace(
        _daemon_http_url="http://fake-daemon:8000",
        client=SimpleNamespace(disconnect=lambda: None),
    )
    adapter = ReachyMiniClient(reachy=fake_sdk)
    assert adapter.get_audio_parameter("PP_MIN_NS") == [0.8]
    assert adapter.apply_audio_config({"PP_MIN_NS": [0.8]}, verify=True)
    assert adapter.set_microphone_volume(100) == 100
    assert adapter.set_output_volume(42) == 42
    assert any(
        call[0] == "get"
        and call[1] == "http://fake-daemon:8000/api/audio/config/parameter/PP_MIN_NS"
        for call in calls
    )
    assert any(
        call[0] == "post"
        and call[1] == "http://fake-daemon:8000/api/audio/config/apply"
        and call[2] == {"config": [{"name": "PP_MIN_NS", "values": [0.8]}], "verify": True}
        for call in calls
    )
    assert any(call[0] == "post" and call[2] == {"volume": 100} for call in calls)
    assert any(call[0] == "post" and call[2] == {"volume": 42} for call in calls)


def test_reconnect_hook_reapplies_mic_profile_each_time():
    daemon = FakeDaemon()
    config = AudioConfigurator(daemon, sleep=lambda _: None)
    assert config.on_connect().ok
    assert config.on_connect().ok
    assert sum(call == ("mic_volume", 100) for call in daemon.calls) == 2
