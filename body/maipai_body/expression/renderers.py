"""The renderer registry: one primitive vocabulary, one column per body.

``dev.md`` section 5's own title. Every body registers its own renderer
under its profile id (a plain function matching ``PrimitiveRenderer``'s
shape); ``ExpressionEngine`` picks the right one by the profile it is
given, so adding a second body (the MaiPai build, once its own HAL
profile exists) never means editing the engine, only registering a new
column here.
"""

from __future__ import annotations

from typing import Protocol

from maipai_body.hal.errors import NotSupported
from maipai_body.hal.seam import BodyProfile, HeadActuator


class PrimitiveRenderer(Protocol):
    """One body's column: renders a primitive through its own HeadActuator."""

    def __call__(
        self,
        primitive: str,
        client: HeadActuator,
        profile: BodyProfile,
        *,
        doa_angle_rad: float = 0.0,
        real_time: bool = False,
    ) -> None: ...


_RENDERERS: dict[str, PrimitiveRenderer] = {}


def register_renderer(profile_id: str, renderer: PrimitiveRenderer) -> None:
    """Register ``renderer`` as the column for the body profile named ``profile_id``."""
    _RENDERERS[profile_id] = renderer


def renderer_for(profile_id: str) -> PrimitiveRenderer:
    """Return the registered renderer for ``profile_id``, or raise if this body has none."""
    try:
        return _RENDERERS[profile_id]
    except KeyError:
        raise NotSupported(f"no expression renderer registered for body {profile_id!r}") from None


def registered_profile_ids() -> tuple[str, ...]:
    """Every body id with a registered renderer, for tests and diagnostics."""
    return tuple(_RENDERERS.keys())
