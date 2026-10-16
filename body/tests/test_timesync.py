"""ROBOT-TIME-01: the robot's clock comes from the hub."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime

from maipai_body.link.channel import CommandChannel
from maipai_body.link.client import HubLinkClient
from maipai_body.link.timesync import ClockSync, system_clock_setter

NOW = 1_800_000_000.0


class Clock:
    def __init__(self) -> None:
        self.now = NOW
        self.sets: list[float] = []

    def __call__(self) -> float:
        return self.now

    def set(self, epoch: float) -> None:
        self.sets.append(epoch)
        self.now = epoch


def _date(epoch: float) -> str:
    return format_datetime(datetime.fromtimestamp(epoch, UTC), usegmt=True)


def test_a_redeem_date_90_s_ahead_corrects_the_clock_once():
    clock = Clock()
    sync = ClockSync(clock.set, wall_clock=clock)
    sync.observe_http_date(_date(NOW + 90))
    sync.observe_http_date(_date(NOW + 90))  # now in step: nothing more to do
    assert clock.sets == [NOW + 90]
    assert sync.corrections == 1
    assert sync.synced


def test_a_drift_under_a_second_changes_nothing_but_still_syncs():
    clock = Clock()
    sync = ClockSync(clock.set, wall_clock=clock)
    sync.observe(NOW + 0.6)
    sync.observe(NOW - 0.9)
    assert clock.sets == []
    assert sync.synced


def test_no_contact_since_boot_is_not_synced():
    sync = ClockSync(Clock().set, wall_clock=Clock())
    assert sync.synced is False
    assert sync.wait_synced(0.0) is False


def test_a_hub_time_command_corrects_through_the_channel():
    clock = Clock()
    sync = ClockSync(clock.set, wall_clock=clock)
    channel = CommandChannel("http://hub.test", "token", time_handler=sync.observe_iso)
    channel._time_command({"hub_time": datetime.fromtimestamp(NOW - 120, UTC).isoformat()})
    assert clock.sets == [NOW - 120]


def test_a_failing_setter_logs_and_still_marks_synced():
    def refuse(_epoch: float) -> None:
        raise PermissionError("no sudoers line")

    sync = ClockSync(refuse, wall_clock=Clock())
    sync.observe(NOW + 500)
    assert sync.synced
    assert sync.corrections == 0


def test_garbage_dates_are_ignored():
    sync = ClockSync(Clock().set, wall_clock=Clock())
    sync.observe_http_date("not a date")
    sync.observe_http_date(None)
    sync.observe_iso("nope")
    assert not sync.synced


def test_the_system_setter_runs_one_sudo_date_call():
    calls = []
    system_clock_setter(lambda *a, **k: calls.append(a[0]))(NOW)
    assert calls == [["sudo", "-n", "/bin/date", "-u", "-s", f"@{int(NOW)}"]]


def test_the_redeem_response_date_feeds_the_sync():
    seen = []

    class Resp:
        status_code = 200
        text = ""
        headers = {"Date": "Wed, 21 Oct 2026 07:28:00 GMT"}

        def raise_for_status(self):
            return None

    class Session:
        cookies: dict = {}

        def post(self, *a, **k):
            return Resp()

    client = HubLinkClient(
        store=None,  # type: ignore[arg-type]
        session=Session(),  # type: ignore[arg-type]
        clock_sync=ClockSync(seen.append, wall_clock=Clock()),
    )
    client._verify_identity = lambda pairing: None  # type: ignore[method-assign]

    class Pairing:
        base_url = "http://hub.test"
        device_token = "t"

    client._redeem(Pairing())  # type: ignore[arg-type]
    assert client.clock_sync.synced
