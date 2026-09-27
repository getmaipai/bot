"""The reachy_mini_apps entry point resolves to a real ReachyMiniApp.

This is the deterministic half of "the daemon's app list shows the
app": the daemon discovers installed apps purely from this
distribution metadata (verified live: it runs `python -m
maipai_body.app`, the entry point's own module, as a subprocess), so a
correct entry point here is what makes the live daemon see the app at
all.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from reachy_mini import ReachyMiniApp

from maipai_body.app import MaiPaiBody


def test_maipai_bot_entry_point_resolves_to_maipai_body():
    eps = entry_points(group="reachy_mini_apps")
    matches = [ep for ep in eps if ep.name == "maipai_bot"]
    assert matches, "no maipai_bot entry point registered under reachy_mini_apps"
    assert matches[0].load() is MaiPaiBody


def test_maipai_body_is_a_reachy_mini_app():
    assert issubclass(MaiPaiBody, ReachyMiniApp)
