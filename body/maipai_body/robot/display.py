"""Body-neutral routing of content to surfaces (BOT-SC-SCREEN-01).

An empty placement list means "this body cannot show it"; the caller falls
back to speech. Hold times are UNMEASURED defaults: the router only caps
them, it never measures how long a surface actually needs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

SurfaceKind = Literal["face", "dial", "lcd"]
ContentKind = Literal["photo", "weather", "camera_feed", "alert", "status", "camera_active"]

_IMAGE_KINDS: frozenset[ContentKind] = frozenset({"photo", "weather", "camera_feed"})
_FACE_IMAGE_CAP_S = {"photo": 15.0, "weather": 15.0, "camera_feed": 30.0}
_ALERT_FACE_CAP_S = 8.0


@dataclass(frozen=True)
class Surface:
    name: str
    kind: SurfaceKind
    shows_images: bool
    shows_text: bool
    shows_icon: bool
    # True when showing content hides the animated face: the face itself is
    # the screen (StackChan's whole face is a display).
    shared_with_face: bool


@dataclass(frozen=True)
class Content:
    kind: ContentKind
    has_image: bool
    has_text: bool
    has_icon: bool
    hold_s: float


@dataclass(frozen=True)
class Placement:
    surface: str
    takes_over_face: bool
    hold_s: float


def choose_placements(content: Content, surfaces: Sequence[Surface]) -> list[Placement]:
    """Pick at most one placement per surface, in the order of `surfaces`."""
    if content.kind == "camera_active":
        chosen: dict[str, Placement] = {}
        if content.has_icon:
            for surface in surfaces:
                if surface.kind == "dial" and surface.shows_icon:
                    chosen[surface.name] = Placement(surface.name, False, content.hold_s)
                    break
        return _ordered(chosen, surfaces)

    if content.kind in _IMAGE_KINDS:
        if not content.has_image:
            return []
        for surface in surfaces:
            if surface.kind == "lcd" and surface.shows_images:
                return [Placement(surface.name, False, content.hold_s)]
        for surface in surfaces:
            if surface.kind == "face" and surface.shows_images:
                cap = _FACE_IMAGE_CAP_S[content.kind]
                return [Placement(surface.name, True, min(content.hold_s, cap))]
        return []

    if content.kind in ("alert", "status"):
        chosen = {}
        for surface in surfaces:
            if surface.kind == "dial" and surface.shows_icon and content.has_icon:
                chosen[surface.name] = Placement(surface.name, False, content.hold_s)
                break
        for surface in surfaces:
            if surface.kind == "lcd" and surface.shows_text and content.has_text:
                chosen[surface.name] = Placement(surface.name, False, content.hold_s)
                break
        # Only an alert may fall back to the face, and only when nothing
        # else can show it; a status never hides the face.
        if content.kind == "alert" and not chosen:
            for surface in surfaces:
                if surface.kind == "face" and (
                    (surface.shows_text and content.has_text)
                    or (surface.shows_icon and content.has_icon)
                ):
                    chosen[surface.name] = Placement(
                        surface.name, True, min(content.hold_s, _ALERT_FACE_CAP_S)
                    )
                    break
        return _ordered(chosen, surfaces)

    return []


def _ordered(chosen: dict[str, Placement], surfaces: Sequence[Surface]) -> list[Placement]:
    return [chosen[surface.name] for surface in surfaces if surface.name in chosen]
