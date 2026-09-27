"""The renderer registry: one column per body, looked up by profile id."""

from __future__ import annotations

import pytest

import maipai_body.expression  # noqa: F401  (registers "reachy_mini" on import)
from maipai_body.expression.reachy_mini_renderer import render as reachy_mini_render
from maipai_body.expression.renderers import register_renderer, renderer_for
from maipai_body.hal.errors import NotSupported


def test_reachy_mini_is_registered_on_import():
    assert renderer_for("reachy_mini") is reachy_mini_render


def test_an_unregistered_body_raises_not_supported():
    with pytest.raises(NotSupported):
        renderer_for("some_future_maipai_build")


def test_a_registered_renderer_can_be_looked_up_by_its_id():
    def fake_renderer(primitive, client, profile, *, doa_angle_rad=0.0):
        pass

    register_renderer("test_only_body", fake_renderer)
    try:
        assert renderer_for("test_only_body") is fake_renderer
    finally:
        # do not leak a fake registration into other tests' lookups
        from maipai_body.expression.renderers import _RENDERERS

        del _RENDERERS["test_only_body"]
