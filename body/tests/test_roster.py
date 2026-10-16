"""FOLLOWUP-01 (bot half): the roster poller fills the PeopleDirectory from the
hub's `GET /api/devices/me/people`, keeps the last roster on a failed fetch,
and lets a stale roster read as unknown."""

from __future__ import annotations

import threading
from unittest.mock import Mock

import requests

from maipai_body.link.roster import RosterPoller
from maipai_body.speech.follow_up import PeopleDirectory


class _Response:
    def __init__(self, status_code: int, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _roster(*entries: tuple[str, str, bool]) -> _Response:
    return _Response(
        200,
        {
            "as_of": "2026-10-16T00:00:00Z",
            "people": [
                {"person_id": p, "age_band": band, "follow_up": f} for p, band, f in entries
            ],
        },
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _poller(responses, *, clock=None, directory=None, stale_s=300.0):
    session = Mock(spec=requests.Session)
    session.get.side_effect = responses
    directory = directory if directory is not None else PeopleDirectory()
    poller = RosterPoller(
        directory,
        lambda: ("cookie-value", "https://hub.example.test"),
        threading.Event(),
        stale_s=stale_s,
        clock=clock or _Clock(),
        session=session,
    )
    return poller, directory, session


def test_a_fetch_fills_the_directory_and_uses_the_robot_cookie():
    poller, directory, session = _poller(
        [_roster(("sage", "adult", True), ("pippa", "child", False))]
    )

    poller.refresh()

    assert directory.band_of("sage") == "adult"
    assert directory.follow_up_switch("sage") is True
    assert directory.band_of("pippa") == "child"
    assert directory.follow_up_switch("pippa") is False
    session.get.assert_called_once_with(
        "https://hub.example.test/api/devices/me/people",
        headers={"Cookie": "session=cookie-value"},
        timeout=5,
    )


def test_a_later_snapshot_forgets_a_person_who_is_missing():
    poller, directory, _ = _poller(
        [
            _roster(("sage", "adult", True), ("pippa", "child", True)),
            _roster(("sage", "adult", True)),
        ]
    )

    poller.refresh()
    poller.refresh()

    assert directory.band_of("pippa") is None
    assert directory.follow_up_switch("pippa") is None
    assert directory.band_of("sage") == "adult"


def test_a_failed_fetch_keeps_the_last_roster():
    for failure in (
        requests.ConnectionError("down"),
        _Response(500),
        _Response(200, {"people": "nope"}),
        _Response(200, {"people": [{"person_id": "x", "age_band": "wizard", "follow_up": True}]}),
    ):
        poller, directory, _ = _poller([_roster(("sage", "adult", True)), failure])
        poller.refresh()

        poller.refresh()

        assert directory.band_of("sage") == "adult"


def test_a_credentials_failure_keeps_the_last_roster():
    poller, directory, _ = _poller([_roster(("sage", "adult", True))])
    poller.refresh()
    poller._hub_credentials = Mock(side_effect=RuntimeError("no creds"))

    poller.refresh()

    assert directory.band_of("sage") == "adult"


def test_a_rejected_session_clears_the_roster():
    for status in (401, 403):
        poller, directory, _ = _poller([_roster(("sage", "adult", True)), _Response(status)])
        poller.refresh()

        poller.refresh()

        assert directory.band_of("sage") is None


def test_a_stale_roster_reads_as_unknown_and_a_fresh_fetch_restores_it():
    clock = _Clock()
    poller, directory, _ = _poller(
        [
            _roster(("sage", "adult", True)),
            requests.ConnectionError("down"),
            _roster(("sage", "adult", True)),
        ],
        clock=clock,
        stale_s=300,
    )
    poller.refresh()

    clock.now += 200
    poller.refresh()  # fails, still inside the window
    assert directory.band_of("sage") == "adult"

    clock.now += 200
    poller.refresh()  # restored by the third response
    assert directory.band_of("sage") == "adult"

    poller2, directory2, _ = _poller(
        [_roster(("sage", "adult", True)), requests.ConnectionError("down")], clock=clock
    )
    poller2.refresh()
    clock.now += 301
    poller2.refresh()
    assert directory2.band_of("sage") is None
    assert directory2.follow_up_switch("sage") is None


def test_the_loop_survives_a_raising_fetch_and_stops_on_the_event():
    stop = threading.Event()
    session = Mock(spec=requests.Session)
    calls = []

    def get(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        stop.set()
        return _roster(("sage", "adult", True))

    session.get.side_effect = get
    directory = PeopleDirectory()
    poller = RosterPoller(
        directory,
        lambda: ("c", "https://hub.example.test"),
        stop,
        interval_s=0.01,
        session=session,
    )

    poller.run()

    assert directory.band_of("sage") == "adult"


def test_poke_refreshes_without_waiting_for_the_interval():
    stop = threading.Event()
    session = Mock(spec=requests.Session)
    seen = threading.Event()

    def get(*_a, **_k):
        seen.set()
        return _roster(("sage", "adult", True))

    session.get.side_effect = get
    poller = RosterPoller(
        PeopleDirectory(), lambda: ("c", "https://x.test"), stop, interval_s=3600, session=session
    )
    thread = threading.Thread(target=poller.run, daemon=True)
    thread.start()
    assert seen.wait(2)
    seen.clear()

    poller.poke()

    assert seen.wait(2)
    stop.set()
    poller.poke()
    thread.join(2)
    assert not thread.is_alive()


def test_the_fetched_roster_reaches_the_follow_up_window_and_presence_entries():
    from types import SimpleNamespace

    from maipai_body.presence.entries import presence_entries_from
    from maipai_body.speaker_evidence import speaker_evidence
    from maipai_body.speech.follow_up import FollowUpPolicy
    from maipai_body.vision.watch import WatchSnapshot

    clock = _Clock()
    poller, directory, _ = _poller(
        [
            _roster(("person-sage01", "adult", True), ("person-pippa2", "child", False)),
            requests.ConnectionError("x"),
        ],
        clock=clock,
    )
    policy = FollowUpPolicy(directory, seconds=8)
    heard = speaker_evidence("person-sage01", "voice", "confirmed")
    snapshot = WatchSnapshot("identify", 1, SimpleNamespace(person_id="person-pippa2"))
    assert policy.window(heard) == 0  # nothing fetched yet: the child default

    poller.refresh()

    assert policy.window(heard) == 8
    entries = presence_entries_from(snapshot, directory.band_of)
    assert [e.kind for e in entries] == ["child"]

    clock.now += 301
    poller.refresh()  # fails and the roster is stale

    assert policy.window(heard) == 0
    entries = presence_entries_from(snapshot, directory.band_of)
    assert [e.kind for e in entries] == ["unknown"]
