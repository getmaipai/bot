"""EYES-02: LiveCaptureTap wraps the real AudioIO and Camera seam objects, so
a mic open or a frame read cannot happen without the live cue knowing."""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import AudioIO, Camera
from maipai_body.indicator.live import CaptureFacts, LiveCaptureTap
from maipai_body.speech.capture import AudioCapture

PACKAGE = Path(__file__).resolve().parent.parent / "maipai_body"


class _Inner:
    """Records every call; stands in for the real client behind the tap."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.marker = "untouched"

    def start_recording(self) -> None:
        self.calls.append("start_recording")

    def stop_recording(self) -> None:
        self.calls.append("stop_recording")

    def get_audio_sample(self):
        self.calls.append("get_audio_sample")
        return np.zeros(4, dtype=np.float32)

    def get_frame(self):
        self.calls.append("get_frame")
        return "frame"

    def get_frame_jpeg(self):
        self.calls.append("get_frame_jpeg")
        return b"jpeg"

    def enable_tracking(self, weight: float = 1.0) -> None:
        self.calls.append(f"enable_tracking:{weight}")

    def disable_tracking(self) -> None:
        self.calls.append("disable_tracking")

    def goto(self, *args, **kwargs):
        self.calls.append("goto")
        return "went"


class _Clock:
    now = 10.0

    def __call__(self) -> float:
        return self.now


def _tap():
    inner = _Inner()
    clock = _Clock()
    tap = LiveCaptureTap(inner, clock=clock)
    facts: list[CaptureFacts] = []
    tap.subscribe(facts.append)
    return tap, inner, clock, facts


def test_the_tap_satisfies_the_audio_and_camera_seams_and_forwards_the_rest():
    tap, inner, _, _ = _tap()
    assert isinstance(tap, AudioIO) or hasattr(tap, "start_recording")
    assert isinstance(tap, Camera)
    assert tap.goto() == "went"
    assert tap.marker == "untouched"
    assert tap.get_audio_sample().shape == (4,)
    assert tap.get_frame() == "frame" and tap.get_frame_jpeg() == b"jpeg"
    assert inner.calls == ["goto", "get_audio_sample", "get_frame", "get_frame_jpeg"]


def test_an_open_mic_is_not_live_until_audio_is_sent_to_the_hub():
    tap, _, _, facts = _tap()
    tap.start_recording()
    assert tap.facts().mic_live is False, "wake word scoring stays local"
    with tap.sending_to_hub():
        assert tap.facts().mic_live is True
    assert tap.facts().mic_live is False
    assert [f.mic_live for f in facts] == [False, True, False]


def test_sending_with_the_mic_closed_is_not_live_and_scopes_nest():
    tap, _, _, _ = _tap()
    with tap.sending_to_hub():
        assert tap.facts().mic_live is False
        tap.start_recording()
        assert tap.facts().mic_live is True
        with tap.sending_to_hub():
            pass
        assert tap.facts().mic_live is True
    assert tap.facts().mic_live is False
    tap.stop_recording()


def test_the_cue_is_raised_before_the_open_and_dropped_after_the_close():
    order: list[str] = []

    class Inner(_Inner):
        def start_recording(self):
            order.append(f"open(live={tap.facts().mic_live})")

        def stop_recording(self):
            order.append(f"close(live={tap.facts().mic_live})")

    tap = LiveCaptureTap(Inner())
    with tap.sending_to_hub():
        tap.start_recording()
        tap.stop_recording()
    assert order == ["open(live=True)", "close(live=True)"]


def test_a_frame_read_is_a_camera_fact_with_a_time_and_tracking_keeps_it_on():
    tap, _, clock, facts = _tap()
    clock.now = 42.0
    tap.get_frame()
    assert facts[-1].camera_read_at == 42.0
    tap.get_frame_jpeg()
    assert facts[-1].camera_read_at == 42.0
    tap.enable_tracking(0.5)
    assert tap.facts().camera_tracking is True
    tap.disable_tracking()
    assert tap.facts().camera_tracking is False


def test_a_failed_enable_does_not_leave_the_camera_cue_on():
    class Inner(_Inner):
        def enable_tracking(self, weight=1.0):
            raise RuntimeError("daemon refused")

    tap = LiveCaptureTap(Inner())
    with pytest.raises(RuntimeError):
        tap.enable_tracking()
    assert tap.facts().camera_tracking is False


def test_a_subscriber_that_raises_does_not_break_capture():
    tap, inner, _, _ = _tap()
    tap.subscribe(lambda facts: 1 / 0)
    tap.start_recording()
    assert inner.calls == ["start_recording"]


def test_audio_capture_through_the_tap_reaches_the_inner_client_and_marks_the_mic():
    inner = FakeReachyMiniClient(REACHY_MINI_PROFILE)
    tap = LiveCaptureTap(inner)
    capture = AudioCapture(tap)
    capture.start()
    with tap.sending_to_hub():
        assert tap.facts().mic_live is True
    capture.stop()
    assert tap.facts().mic_live is False


def test_run_loop_marks_the_stt_stream_as_sending_to_the_hub():
    from maipai_body.speech.stt_stream import SttStreamResult
    from tests.test_run_loop import _make_loop

    seen: list[bool] = []
    depth = {"n": 0}

    class Scope:
        def __enter__(self):
            depth["n"] += 1

        def __exit__(self, *exc):
            depth["n"] -= 1

    loop, parts = _make_loop(stt_result=SttStreamResult(kind="no_speech"))
    loop._capture_scope = Scope
    original = parts["stt"].run

    def run(capture):
        seen.append(depth["n"] == 1)
        return original(capture)

    parts["stt"].run = run
    loop._run_turn(threading.Event())
    assert seen == [True]
    assert depth["n"] == 0


# -- the inventory: every mic-open and frame-read site, and nothing else ----

WATCHED = {"start_recording", "get_audio_sample", "get_frame", "get_frame_jpeg"}
# (file, receiver) of each place that opens the mic or reads a frame. Each is
# either the tap itself, the one real implementation behind it, or a consumer
# that receives the tapped client from app wiring (checked below).
ALLOWED_SITES = {
    ("indicator/live.py", "self._inner"),
    ("bodies/reachy_mini/client.py", "self._reachy.media"),
    ("speech/capture.py", "self._client"),
    ("vision/capture.py", "client"),
    ("run_loop.py", "self._client"),
}


def _sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        rel = str(path.relative_to(PACKAGE))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in WATCHED:
                found.add((rel, ast.unparse(node.value)))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in WATCHED
            ):
                found.add((rel, f"getattr:{ast.unparse(node.args[0])}"))
    return found


def test_every_mic_open_and_frame_read_site_is_inventoried():
    found = _sites()
    bypasses = sorted(found - ALLOWED_SITES)
    assert bypasses == [], f"a mic or camera call site the live cue cannot see: {bypasses}"


def test_the_inventory_has_no_stale_entries():
    assert ALLOWED_SITES - _sites() == set()


def test_the_inventory_scan_catches_a_bypass(tmp_path, monkeypatch):
    rogue = tmp_path / "rogue.py"
    rogue.write_text("def grab(client):\n    return client.get_frame()\n")
    import tests.test_indicator_live as me

    monkeypatch.setattr(me, "PACKAGE", tmp_path)
    assert ("rogue.py", "client") in me._sites()
    rogue.write_text("fn = getattr(client, 'start_recording')\n")
    assert ("rogue.py", "getattr:client") in me._sites()
