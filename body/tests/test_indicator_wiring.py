"""EYES-02: the app hands the tap, never the bare client, to every consumer
that opens the mic or reads a frame, and connects the director to the funnel."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import maipai_body.app as app_module
from maipai_body.bodies.reachy_mini.fake import FakeEyes, FakeReachyMiniClient
from maipai_body.hal.seam import NullIndicator, Palette
from maipai_body.indicator.live import LiveCaptureTap
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.funnel import FunnelState, FunnelView


def _build(indicator, stop_event=None):
    client = FakeReachyMiniClient()
    seen: dict[str, object] = {}

    class _Capture:
        def __init__(self, c):
            seen["capture_client"] = c

    class _Loop:
        def __init__(self, **kwargs):
            seen["loop"] = kwargs
            self.views = []

        def subscribe_view(self, callback):
            self.views.append(callback)
            seen["view_callback"] = callback

    heavy = [
        "ensure_wakeword_models",
        "OpenWakeWordEngine",
        "WakeScorer",
        "FiveLandmarkDetector",
        "ensure_embedder",
        "FaceGallery",
        "PrintSync",
        "SttStreamClient",
        "TurnClient",
        "TtsPlaybackClient",
        "AudioPlayback",
        "build_react_hook",
        "ExpressionEngine",
        "_hub_credentials_reader",
    ]
    patches = [patch.object(app_module, name, MagicMock()) for name in heavy]
    patches.append(patch("maipai_body.link.assets.AssetSync.sync", return_value={}))
    patches.append(patch("maipai_body.link.channel.CommandChannel.run"))
    patches.append(patch.object(app_module, "AudioCapture", _Capture))
    patches.append(patch.object(app_module, "ConversationLoop", _Loop))
    patches.append(patch.object(app_module, "_start_eyes", return_value=indicator))
    for p in patches:
        p.start()
    try:
        loop = app_module._build_conversation_loop(
            client,
            "cookie",
            "https://hub.example.test",
            Path("/tmp/models"),
            MagicMock(),
            stop_event or threading.Event(),
        )
    finally:
        for p in reversed(patches):
            p.stop()
    return client, loop, seen


def test_the_loop_and_the_audio_capture_get_the_tap_not_the_bare_client():
    client, _, seen = _build(FakeEyes())
    assert isinstance(seen["capture_client"], LiveCaptureTap)
    loop_kwargs = seen["loop"]
    assert isinstance(loop_kwargs["client"], LiveCaptureTap)
    assert seen["capture_client"] is loop_kwargs["client"]
    assert seen["capture_client"]._inner is client
    assert callable(loop_kwargs["capture_scope"])


def test_the_funnel_view_reaches_the_director_and_the_eyes():
    eyes = FakeEyes()
    _, _, seen = _build(eyes)
    seen["view_callback"](FunnelView(shown=FunnelState.LISTENING))
    assert eyes.current_look is not None and eyes.current_look.colour is Palette.BLUE


def test_director_app_wiring_explicitly_uses_settings_and_presence_stubs():
    _, _, seen = _build(FakeEyes())
    director = seen["view_callback"].__self__
    assert director._settings is app_module._eyes_settings
    assert director._presence is app_module._eyes_presence
    assert app_module._eyes_settings() == IndicatorSettings()
    assert app_module._eyes_presence() is None


def test_the_stt_scope_drives_the_green_live_cue_through_the_tap():
    eyes = FakeEyes()
    _, _, seen = _build(eyes)
    tap = seen["loop"]["client"]
    tap.start_recording()
    with seen["loop"]["capture_scope"]():
        assert eyes.current_look.colour is Palette.GREEN
    tap.stop_recording()


def test_a_build_without_eyes_still_runs_with_a_null_indicator():
    _, _, seen = _build(NullIndicator())
    assert isinstance(seen["loop"]["client"], LiveCaptureTap)


def test_the_eyes_are_closed_when_the_app_stops():
    eyes = FakeEyes()
    stop = threading.Event()
    _build(eyes, stop)
    seen_off = threading.Event()
    stop.set()
    for _ in range(100):
        if eyes.commands and eyes.commands[-1].kind == "off":
            seen_off.set()
            break
        threading.Event().wait(0.02)
    assert seen_off.is_set()
