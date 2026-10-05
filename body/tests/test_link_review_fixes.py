"""LINK-STATE-01 review fixes: wakes in an outage, boot with the hub away,
the LAN address staying the pairing, and rung 0 waiting for its body."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

from maipai_body import app as app_module
from maipai_body.app import _build_link_stack, run_paired_body
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.link.address_walk import HubEndpoint, PathKind
from maipai_body.link.client import HubLinkClient
from maipai_body.link.lifecycle import LinkLifecycle
from maipai_body.link.rung0 import Rung0Cues
from maipai_body.link.state_machine import LinkPhase, LinkStateMachine
from maipai_body.link.store import PairingStore
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.wake import WakeEvent
from tests.ladder_fakes import FakeClock, FakeSpeaker
from tests.test_link_client import _never_discovers
from tests.test_link_client_refresh_address import _store, stand_in_hub  # noqa: F401
from tests.test_link_ladder_run_loop import N, _run_one_wake, _rungs
from tests.test_link_lifecycle import _result
from tests.test_link_lifecycle_ladder import _AddressClient
from tests.test_run_loop import _make_loop, _wait_for

LAN = "http://192.0.2.10:80"
TAILNET = HubEndpoint(PathKind.TAILNET, "http://hub.tail1.ts.net:80", "tailnet")


# ---- 1. a wake during an outage is never silent ---------------------------------------------


def test_a_wake_after_a_blip_that_already_recovered_runs_the_turn_at_once():
    offline, clock, *_ = _rungs(recognizer=False)
    offline.machine.link_lost("unreachable: ConnectTimeout")
    clock.advance(2.0)  # the hub is back, but the supervisor's next walk is 28 s away
    retries = []

    def retry() -> bool:
        retries.append(clock.now)
        offline.machine.redeemed("lan", LAN)
        return True

    offline.retry_link = retry
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        offline=offline,
    )
    _run_one_wake(loop)
    assert retries == [clock.now]
    assert parts["stt"].call_count == 1  # the normal turn ran, no dead time


def test_a_wake_while_still_down_gives_the_ack_animation_and_the_status_line():
    offline, _clock, _volume, speaker = _rungs(recognizer=False)
    offline.machine.link_lost("unreachable: ConnectTimeout")
    offline.retry_link = lambda: False
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert parts["engine"].ambient[-1] == "perk"
    assert speaker.said == [["line.unreachable"]]
    assert offline.last_reply.text.startswith("Can't reach home.")
    assert parts["stt"].call_count == 0
    assert parts["turn"].stream_calls == []


def test_a_wake_while_down_with_no_retry_wired_is_still_not_silent():
    offline, _clock, _volume, speaker = _rungs(recognizer=False)
    offline.machine.link_lost("x")
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert speaker.said == [["line.unreachable"]]


def test_with_a_recognizer_the_ack_plays_and_rung_1_still_listens():
    offline, _clock, volume, speaker = _rungs(phrases=["quieter"])
    offline.machine.link_lost("x")
    offline.retry_link = lambda: False
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=offline)
    _run_one_wake(loop)
    assert parts["engine"].ambient[-1] == "perk"
    assert offline.recognizer.listens == 1
    assert speaker.said == [["cmd.quieter"]]
    assert volume.level == 40


def test_a_wake_that_recovers_the_link_skips_rung_1():
    offline, *_ = _rungs(phrases=["quieter"])
    offline.machine.link_lost("x")
    offline.retry_link = lambda: offline.machine.redeemed("lan", LAN) or True
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        offline=offline,
    )
    _run_one_wake(loop)
    assert offline.recognizer.listens == 0
    assert parts["stt"].call_count == 1


# ---- 2. boot with the hub away --------------------------------------------------------------


def test_boot_with_the_hub_away_runs_the_ladder_before_the_loop_is_built(tmp_path):
    clock = FakeClock()
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    client = _AddressClient(set())  # no address answers
    client.session_cookie = None  # no redeem has ever succeeded this boot
    stack = _build_link_stack(
        store,
        client,
        discover=lambda timeout_s: None,
        sleep_after_s=N,
        clock=clock,
        wall_clock=clock.wall_clock,
    )
    speaker = FakeSpeaker()
    stack.offline.speaker = speaker
    stack.link.reconnect_once()  # what the hub-link thread does first at power-on
    assert stack.machine.phase is LinkPhase.RECONNECTING

    supervisor_started = threading.Event()
    release_build = threading.Event()
    loop_box = []

    class _Stepper:
        """Stands in for the supervisor thread: the test steps the real one."""

        def run(self, stop_event):
            supervisor_started.set()

    def build(*args, **kwargs):
        assert supervisor_started.is_set(), "the supervisor must start before the loop is built"
        release_build.wait(5.0)
        loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)], offline=stack.offline)
        loop_box.append((loop, parts))
        return loop

    stop_event = threading.Event()
    with patch.object(app_module, "_build_conversation_loop", side_effect=build):
        thread = threading.Thread(
            target=run_paired_body,
            args=(FakeReachyMiniClient(), stack.link, stop_event),
            kwargs={
                "cache_dir": Path("/tmp/models"),
                "offline": stack.offline,
                "supervisor": _Stepper(),
            },
            daemon=True,
        )
        thread.start()
        _wait_for(supervisor_started.is_set)  # started with the loop still unbuilt
        assert not loop_box

        clock.advance(N)
        stack.supervisor.step()
        assert stack.machine.phase is LinkPhase.SLEEPING

        release_build.set()
        _wait_for(lambda: speaker.said)
        stop_event.set()
        thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert speaker.said == [["line.unreachable"]]  # the wake produced a cue
    assert loop_box[0][1]["stt"].call_count == 0


def test_rung_0_renders_nothing_until_the_funnel_hands_it_a_body():
    clock = FakeClock()
    machine = LinkStateMachine(clock=clock, wall_clock=clock.wall_clock)
    rung0 = Rung0Cues(machine=machine, clock=clock)  # no render yet
    machine.link_lost("x")
    rung0.tick()  # the supervisor is already running, the loop is not built
    rendered = []
    rung0.attach(render=lambda p: rendered.append(p) or True)
    rung0.tick()
    assert rendered == ["settle", "breathe"]


# ---- 3. only a LAN answer is the pairing ----------------------------------------------------


def test_a_tailnet_answer_does_not_overwrite_the_stored_lan_address(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    persisted: list[tuple[str | None, bool]] = []

    class _Client(_AddressClient):
        def refresh(self, base_url=None, persist=True):
            persisted.append((base_url, persist))
            return super().refresh(base_url)

    client = _Client({TAILNET.base_url})
    link = LinkLifecycle(
        store,
        client,
        discover=lambda timeout_s: None,
        address_walk=True,
        tailnet=lambda: [TAILNET],
    )
    assert link.reconnect_once() is True
    assert persisted == [(LAN, True), (TAILNET.base_url, False)]  # LAN kept, tailnet not
    assert store.load().base_url == LAN


def test_the_real_client_keeps_the_lan_pairing_on_an_unpersisted_redeem(stand_in_hub, tmp_path):  # noqa: F811
    server, handler = stand_in_hub
    store = _store(tmp_path, "http://127.0.0.1:1")
    client = HubLinkClient(store, discover=_never_discovers)
    other = f"http://127.0.0.1:{server.server_port}"

    assert client.refresh(base_url=other, persist=False) is True

    assert store.load().base_url == "http://127.0.0.1:1"
    assert client.active_base_url == other  # the turn clients still reach the hub
    assert client.refresh(base_url=other) is True  # a LAN answer is kept
    assert store.load().base_url == other


def test_the_credentials_reader_prefers_the_address_that_answered(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    store.save(_result().pairing)
    client = _AddressClient(set())
    client.active_base_url = TAILNET.base_url
    client.session_cookie = "c"
    link = LinkLifecycle(store, client, discover=lambda timeout_s: None)
    assert app_module._hub_credentials_reader(link, LAN)() == ("c", TAILNET.base_url)
