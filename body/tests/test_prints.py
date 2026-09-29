"""FACE-03's snapshot sync into the local face gallery."""

from __future__ import annotations

import threading
from unittest.mock import Mock

import numpy as np
import requests

from maipai_body.link.prints import PrintSync
from maipai_body.vision.gallery import FaceGallery, FacePrint

MODEL_ID = "sface-2021dec"
MODEL_SHA = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"as_of": "2026-09-28T00:00:00Z", "prints": []}

    def json(self) -> dict:
        return self._payload


class _StopAfterWait:
    """Stop after one sync iteration without adding a real interval delay."""

    def is_set(self) -> bool:
        return False

    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = iter(results or [True])

    def wait(self, _timeout: float) -> bool:
        return next(self.results)


def _entry(person_id: str, embedding: list[float], *, model_id=MODEL_ID, model_sha=MODEL_SHA):
    return {
        "id": f"print-{person_id}",
        "person_id": person_id,
        "model_id": model_id,
        "model_sha256": model_sha,
        "embedding": embedding,
    }


def _gallery() -> FaceGallery:
    return FaceGallery(MODEL_ID, MODEL_SHA, threshold=0.5, margin=0.05)


def _sync(responses: list[_Response], *, gallery=None, stop_event=None, wait_results=None):
    session = Mock(spec=requests.Session)
    session.get.side_effect = responses
    event = stop_event or _StopAfterWait(wait_results)
    sync = PrintSync(
        gallery or _gallery(),
        lambda: ("cookie-value", "https://hub.example.test"),
        event,
        session=session,
    )
    return sync, session, event


def _identified(gallery: FaceGallery, probe=(1.0, 0.0, 0.0)):
    return gallery.identify(np.array(probe, dtype=np.float32))


def test_successful_pull_replaces_gallery_and_uses_cookie_header():
    gallery = _gallery()
    response = _Response(200, {"as_of": "now", "prints": [_entry("sage", [1, 0, 0])]})
    sync, session, _ = _sync([response], gallery=gallery)

    sync.run()

    assert _identified(gallery).person_id == "sage"
    session.get.assert_called_once_with(
        "https://hub.example.test/api/biometric-prints/sync",
        headers={"Cookie": "session=cookie-value"},
        timeout=5,
    )


def test_a_later_snapshot_removes_a_person_who_is_no_longer_enrolled():
    gallery = _gallery()
    first = _Response(
        200,
        {"as_of": "one", "prints": [_entry("sage", [1, 0, 0]), _entry("bramble", [0, 1, 0])]},
    )
    second = _Response(200, {"as_of": "two", "prints": [_entry("bramble", [0, 1, 0])]})
    sync, _, _ = _sync([first, second], gallery=gallery, wait_results=[False, True])

    sync.run()

    assert _identified(gallery).person_id is None
    assert _identified(gallery, (0.0, 1.0, 0.0)).person_id == "bramble"


def test_401_or_403_clears_a_populated_gallery():
    for status in (401, 403):
        gallery = _gallery()
        gallery.replace_all(
            [
                FacePrint(
                    id="print-sage",
                    person_id="sage",
                    model_id=MODEL_ID,
                    model_sha256=MODEL_SHA,
                    embedding=np.array([1, 0, 0], dtype=np.float32),
                )
            ]
        )
        sync, _, _ = _sync([_Response(status)], gallery=gallery)

        sync.run()

        assert _identified(gallery).person_id is None


def test_foreign_model_print_is_skipped_without_aborting_the_batch(caplog):
    gallery = _gallery()
    response = _Response(
        200,
        {
            "as_of": "now",
            "prints": [
                _entry("foreign", [0, 1, 0], model_id="other", model_sha="f" * 64),
                _entry("sage", [1, 0, 0]),
            ],
        },
    )
    sync, _, _ = _sync([response], gallery=gallery)

    with caplog.at_level("WARNING", logger="maipai_body.vision.gallery"):
        sync.run()

    assert _identified(gallery).person_id == "sage"
    assert "skipping foreign's print" in caplog.text


def test_connection_failure_keeps_the_existing_gallery():
    gallery = _gallery()
    sync, session, _ = _sync([], gallery=gallery)
    session.get.side_effect = requests.RequestException("offline")
    gallery.add(
        FacePrint(
            id="print-sage",
            person_id="sage",
            model_id=MODEL_ID,
            model_sha256=MODEL_SHA,
            embedding=np.array([1, 0, 0], dtype=np.float32),
        )
    )

    sync.run()

    assert _identified(gallery).person_id == "sage"


def test_a_pre_set_stop_event_returns_without_waiting_for_the_interval():
    stop_event = threading.Event()
    stop_event.set()
    sync, session, _ = _sync([], stop_event=stop_event)

    thread = threading.Thread(target=sync.run, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    session.get.assert_not_called()
