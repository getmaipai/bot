"""The bench stand-in for the hub's robot-facing routes, and the link faults it injects.

Real sockets, the real ``TurnClient``/``TtsPlaybackClient``/``SttStreamClient``:
what M-R5's simulator rows are built on, so what it can and cannot fake
has to be proven here first.
"""

from __future__ import annotations

import threading
import time

import pytest
import requests

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.expression.cue import Phase
from maipai_body.measure.stand_in_hub import StandInHub
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient, SttStreamError
from maipai_body.speech.tts_playback import TtsLinkLost, TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient, TurnLinkLost


@pytest.fixture
def hub():
    with StandInHub(reply_text="hello back") as running:
        yield running


def _turn_phases(hub: StandInHub) -> list[Phase]:
    client = TurnClient(hub.http_url, "cookie")
    return [e.cue.phase for e in client.stream("hi") if e.cue is not None]


def test_a_turn_streams_signal_then_done_with_the_reply(hub):
    client = TurnClient(hub.http_url, "cookie")
    events = list(client.stream("hi"))
    assert [e.cue.phase for e in events] == [Phase.SIGNAL, Phase.DONE]
    assert events[-1].reply_text == "hello back"


def test_a_reset_after_the_first_event_is_a_link_lost_after_the_signal(hub):
    hub.fail_next("turn", after=1, mode="reset")
    stream = TurnClient(hub.http_url, "cookie").stream("hi")
    assert next(stream).cue.phase is Phase.SIGNAL
    with pytest.raises(TurnLinkLost):
        next(stream)
    assert hub.fault_fired_at is not None


def test_a_stream_that_ends_cleanly_without_done_or_error_is_a_lost_turn(hub):
    hub.fail_next("turn", after=1, mode="truncate")
    stream = TurnClient(hub.http_url, "cookie").stream("hi")
    assert next(stream).cue.phase is Phase.SIGNAL
    with pytest.raises(TurnLinkLost):
        next(stream)


def test_a_fault_is_one_shot_the_next_turn_is_clean(hub):
    hub.fail_next("turn", after=1, mode="reset")
    with pytest.raises(TurnLinkLost):
        list(TurnClient(hub.http_url, "cookie").stream("hi"))
    hub.restore()  # a reset fault takes the link down; the next turn needs it back
    assert _turn_phases(hub) == [Phase.SIGNAL, Phase.DONE]


def test_tts_streams_audio_and_a_mid_stream_reset_is_a_lost_link(hub):
    playback = AudioPlayback(FakeReachyMiniClient())
    client = TtsPlaybackClient(hub.http_url, "cookie", playback)
    assert client.speak("hello").kind == "done"
    assert playback.pushed_duration_s() > 0.0

    hub.fail_next("tts", after=2, mode="reset")
    with pytest.raises(TtsLinkLost):
        client.speak("hello again")
    assert hub.tts_requests == ["hello", "hello again"]


def test_stt_returns_the_scripted_final_and_a_reset_is_a_lost_link(hub):
    capture = AudioCapture(FakeReachyMiniClient())
    stt = SttStreamClient(hub.stt_url, "cookie")
    assert stt.run(capture).text == "hello maipai"

    hub.fail_next("stt", after=0, mode="reset")
    with pytest.raises(SttStreamError):
        stt.run(capture)


def test_cut_refuses_everything_at_once_and_restore_brings_the_hub_back(hub):
    hub.cut("reset")
    with pytest.raises(TurnLinkLost):
        list(TurnClient(hub.http_url, "cookie").stream("hi"))
    with pytest.raises(requests.RequestException):
        requests.put(f"{hub.http_url}/api/devices/me/state", json={}, timeout=2)
    assert hub.state_reports == []

    hub.restore()
    assert hub.restored_at is not None
    assert requests.put(f"{hub.http_url}/api/devices/me/state", json={}, timeout=2).ok
    assert len(hub.state_reports) == 1
    assert hub.state_reports[0] >= hub.restored_at


def test_a_blackhole_answers_nothing_so_the_client_waits_for_its_own_timeout(hub):
    hub.cut("blackhole")
    started = time.monotonic()
    with pytest.raises(requests.exceptions.ReadTimeout):
        requests.put(f"{hub.http_url}/api/devices/me/state", json={}, timeout=0.4)
    assert time.monotonic() - started >= 0.4
    hub.restore()  # releases the held connection


def test_stopping_the_hub_releases_blackholed_connections_promptly():
    hub = StandInHub()
    hub.start()
    hub.cut("blackhole")
    holder = threading.Thread(
        target=lambda: _swallow(lambda: requests.put(f"{hub.http_url}/x", timeout=5)), daemon=True
    )
    holder.start()
    time.sleep(0.2)
    started = time.monotonic()
    hub.stop()
    holder.join(timeout=3)
    assert not holder.is_alive()
    assert time.monotonic() - started < 3


def _swallow(call) -> None:
    try:
        call()
    except Exception:
        pass
