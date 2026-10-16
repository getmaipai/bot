"""FACE-WATCH-01 end to end: `vision_watch` on a sync entry reaches the gallery."""

from __future__ import annotations

from tests.test_prints import _entry, _gallery, _Response, _sync


def _with_watch(entry: dict, value) -> dict:
    return {**entry, "vision_watch": value}


def test_each_persons_vision_watch_reaches_the_gallery():
    gallery = _gallery()
    payload = {
        "as_of": "now",
        "prints": [
            _with_watch(_entry("sage", [1, 0, 0]), "identify"),
            _with_watch(_entry("bramble", [0, 1, 0]), "off"),
            _with_watch(_entry("iris", [0, 0, 1]), "presence"),
        ],
    }
    sync, _, _ = _sync([_Response(200, payload)], gallery=gallery)

    sync.run()

    assert gallery.person_watch("sage") == "identify"
    assert gallery.person_watch("bramble") == "off"
    assert gallery.person_watch("iris") == "presence"


def test_a_missing_or_unknown_vision_watch_reads_as_presence():
    gallery = _gallery()
    payload = {
        "as_of": "now",
        "prints": [_entry("sage", [1, 0, 0]), _with_watch(_entry("iris", [0, 1, 0]), "bogus")],
    }
    sync, _, _ = _sync([_Response(200, payload)], gallery=gallery)

    sync.run()

    assert gallery.person_watch("sage") == "presence"
    assert gallery.person_watch("iris") == "presence"
