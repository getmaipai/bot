"""The StackChan light wiring: the poller that feeds the light service.

Covers docs/dev/led-standard-2026-10-20.md wiring step 2: the poller reads
the link phase, the device link and the battery into the
``StackChanLightService``, reads the battery at most once a minute, keeps
the last good battery values when a read fails or the payload is invalid,
and never lets a read failure break the loop. ``start_stackchan_light``
binds the service and the poller to the adapter's 12-pixel ring.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from maipai_body.bodies.stackchan.light_service import StackChanLightService
from maipai_body.bodies.stackchan.light_wiring import LightPoller, start_stackchan_light
from maipai_body.hal.seam import Look, Palette
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.link.state_machine import LinkPhase

LOGGER = "maipai_body.bodies.stackchan.light_wiring"

DAY = 12 * 60


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeRing:
    """A recording stand-in for StackChanRingIndicator."""

    def __init__(self) -> None:
        self.looks: list[Look | None] = []
        self.ticks = 0
        self.current: Look | None = None

    def set_look(self, look: Look) -> None:
        self.looks.append(look)
        self.current = look

    def off(self) -> None:
        self.looks.append(None)
        self.current = None

    def tick(self) -> None:
        self.ticks += 1


def _service() -> tuple[StackChanLightService, FakeRing, Clock]:
    ring = FakeRing()
    clock = Clock()
    service = StackChanLightService(
        ring,
        settings=lambda: IndicatorSettings(),
        minute=lambda: DAY,
        clock=clock,
    )
    return service, ring, clock


def _poller(
    service: StackChanLightService,
    *,
    clock: Clock,
    connected: bool = True,
    phase: str | None = "connected",
    battery: Any = None,
    **kwargs: Any,
) -> LightPoller:
    if battery is None:

        def battery() -> dict[str, object]:
            return {"percent": 80, "charging": False}

    return LightPoller(
        service,
        link_phase=lambda: phase,
        device_connected=lambda: connected,
        battery=battery,
        clock=clock,
        **kwargs,
    )


def _warnings(caplog: pytest.LogCaptureFixture) -> list[Any]:
    return [record for record in caplog.records if record.name == LOGGER]


def test_a_robot_that_has_not_reached_the_hub_reads_as_connecting():
    service, ring, clock = _service()
    _poller(service, clock=clock, connected=False).poll()
    assert service.facts.connecting is True
    assert service.facts.offline is False
    assert ring.current is not None
    assert ring.current.colour is Palette.BLUE


@pytest.mark.parametrize("phase", ["reconnecting", "sleeping"])
def test_a_connected_robot_with_an_unreachable_hub_reads_as_offline(phase: str):
    service, ring, clock = _service()
    _poller(service, clock=clock, phase=phase).poll()
    assert service.facts.connecting is False
    assert service.facts.offline is True
    assert ring.current is not None
    assert ring.current.colour is Palette.AMBER


@pytest.mark.parametrize("phase", ["connected", None])
def test_a_connected_robot_with_a_reachable_hub_sets_neither(phase: str | None):
    service, _, clock = _service()
    _poller(service, clock=clock, phase=phase).poll()
    assert service.facts.connecting is False
    assert service.facts.offline is False


def test_the_battery_is_read_at_most_once_per_window():
    service, _, clock = _service()
    reads: list[float] = []

    def battery() -> dict[str, object]:
        reads.append(clock())
        return {"percent": 80, "charging": False}

    poller = _poller(service, clock=clock, battery=battery)
    poller.poll()
    clock.now += 59.0
    poller.poll()
    assert len(reads) == 1
    clock.now += 1.0
    poller.poll()
    assert len(reads) == 2


@pytest.mark.parametrize(
    ("payload", "low", "charging"),
    [
        ({"percent": 14, "charging": False}, True, False),
        ({"percent": 14, "charging": True}, False, True),
        ({"percent": 80, "charging": False}, False, False),
    ],
)
def test_battery_low_is_below_the_threshold_and_not_charging(
    payload: dict[str, object], low: bool, charging: bool
):
    service, _, clock = _service()
    _poller(service, clock=clock, battery=lambda: payload).poll()
    assert service.facts.battery_low is low
    assert service.facts.charging is charging


def test_a_battery_failure_keeps_the_last_values_and_warns_once(caplog: pytest.LogCaptureFixture):
    service, _, clock = _service()
    calls = []

    def battery() -> dict[str, object]:
        calls.append(1)
        if len(calls) > 1:
            raise OSError("the hub does not answer")
        return {"percent": 10, "charging": False}

    poller = _poller(service, clock=clock, battery=battery)
    poller.poll()
    assert service.facts.battery_low is True
    clock.now += 60.0
    poller.poll()
    assert service.facts.battery_low is True
    assert service.facts.charging is False
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "battery" in warnings[0].message


def test_repeated_battery_failures_warn_at_most_once_a_minute(caplog: pytest.LogCaptureFixture):
    service, _, clock = _service()

    def battery() -> dict[str, object]:
        raise OSError("the hub does not answer")

    poller = _poller(service, clock=clock, battery=battery, battery_every_s=1.0)
    for _ in range(3):
        poller.poll()
        clock.now += 1.0
    assert len(_warnings(caplog)) == 1
    assert service.facts.battery_low is False


@pytest.mark.parametrize(
    "payload",
    [
        {"charging": False},
        {"percent": "80", "charging": False},
        {"percent": 80.0, "charging": False},
        {"percent": 80, "charging": "yes"},
        {"percent": True, "charging": False},
    ],
)
def test_an_invalid_battery_payload_is_a_failure(
    caplog: pytest.LogCaptureFixture, payload: dict[str, object]
):
    service, _, clock = _service()
    _poller(service, clock=clock, battery=lambda: payload).poll()
    assert service.facts.charging is False
    assert service.facts.battery_low is False
    assert _warnings(caplog)


def test_an_invalid_battery_payload_keeps_the_last_values():
    service, _, clock = _service()
    calls = []

    def battery() -> object:
        calls.append(1)
        if len(calls) == 1:
            return {"percent": 10, "charging": True}
        return {"percent": None, "charging": False}

    poller = _poller(service, clock=clock, battery=battery)
    poller.poll()
    assert service.facts.charging is True
    assert service.facts.battery_low is False
    clock.now += 60.0
    poller.poll()
    assert service.facts.charging is True
    assert service.facts.battery_low is False


def test_run_polls_and_stops_on_the_event():
    service, _, _ = _service()
    reads = []

    def battery() -> dict[str, object]:
        reads.append(1)
        return {"percent": 80, "charging": False}

    poller = _poller(service, clock=Clock(), battery=battery)
    stop = threading.Event()
    thread = threading.Thread(
        target=poller.run, args=(stop,), kwargs={"every_s": 0.01}, daemon=True
    )
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert reads


def test_run_never_lets_a_poll_exception_escape(caplog: pytest.LogCaptureFixture):
    service, _, _ = _service()

    def broken_phase() -> str:
        raise OSError("the link reader is gone")

    poller = LightPoller(
        service,
        link_phase=broken_phase,
        device_connected=lambda: True,
        battery=lambda: {"percent": 80, "charging": False},
        clock=Clock(),
    )
    stop = threading.Event()
    thread = threading.Thread(
        target=poller.run, args=(stop,), kwargs={"every_s": 0.01}, daemon=True
    )
    thread.start()
    time.sleep(0.05)
    assert thread.is_alive()
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert _warnings(caplog)


class _Leds:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def many(self, entries: list[dict[str, object]]) -> object:
        self.calls.append([dict(entry) for entry in entries])
        return True


class _FakeVoiceRobot:
    def __init__(self) -> None:
        self.robot = SimpleNamespace(leds=_Leds())
        self.client = SimpleNamespace(get_battery_status=lambda: {"percent": 80, "charging": False})


def _fake_link(phase: LinkPhase = LinkPhase.CONNECTED):
    return SimpleNamespace(machine=SimpleNamespace(phase=phase))


def _join_started_threads(stop: threading.Event) -> list[threading.Thread]:
    stop.set()
    threads = [t for t in threading.enumerate() if t.name.startswith("stackchan-light-")]
    for thread in threads:
        thread.join(timeout=2.0)
    return threads


def test_start_builds_the_light_and_starts_stoppable_threads():
    voice = _FakeVoiceRobot()
    stop = threading.Event()
    service = start_stackchan_light(voice, _fake_link(), stop)
    assert isinstance(service, StackChanLightService)
    deadline = time.monotonic() + 2.0
    while not voice.robot.leds.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    threads = _join_started_threads(stop)
    assert threads
    assert all(not thread.is_alive() for thread in threads)
    first = voice.robot.leds.calls[0]
    assert [entry["index"] for entry in first] == list(range(12))
    values = {tuple(entry["rgb"]) for entry in first}
    assert values == {(0, 0, 0)}  # idle, awake is dark


def test_start_works_without_a_link_object():
    voice = _FakeVoiceRobot()
    stop = threading.Event()
    service = start_stackchan_light(voice, None, stop)
    time.sleep(0.05)
    threads = _join_started_threads(stop)
    assert threads
    assert all(not thread.is_alive() for thread in threads)
    assert voice.robot.leds.calls
    assert service is not None


def test_the_turn_bridge_raises_the_live_cue_around_the_hub_stream_only():
    import asyncio

    from maipai_body.bodies.stackchan.turn import StackChanTurnBridge

    events: list[bool] = []

    class _Inline:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)

    bridge = StackChanTurnBridge.__new__(StackChanTurnBridge)
    bridge._side = _Inline()
    bridge._light_side = _Inline()
    bridge.live_sink = events.append
    bridge._set_live(True)
    bridge._set_live(False)
    assert events == [True, False]
    bridge.live_sink = lambda active: (_ for _ in ()).throw(RuntimeError("boom"))
    bridge._set_live(True)  # a failing light never breaks the voice path
    bridge.live_sink = None
    bridge._set_live(True)
    assert asyncio.iscoroutinefunction(StackChanTurnBridge._run)


def test_the_camera_adapter_tells_the_light_service_when_the_cue_goes_up_and_down():
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    device = FakeStackChanDeviceClient()
    device.photo = b"\xff\xd8sample"
    robot = StackChanRobotAdapter(device).robot
    cues: list[bool] = []
    robot._driver("camera").cue_sink = cues.append
    assert robot.camera.frame() == device.photo
    assert cues == [True, False]
