"""The plan's ``react`` slot entry point, behind a flag that is off by default.

``ConversationLoop`` calls a hook with the move name a reply plan named and
whether that plan's ``react`` is allowed; this module is the hook. With the
flag off it plays nothing, and a plan that forbids ``react`` plays nothing
either way. It never reads a cue, an emotion or a sentiment.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import HeadActuator
from maipai_body.model_assets import AssetUnavailable
from maipai_body.presence.arbitration import ArbitrationState

from .library import PINS_PATH, ensure_move, load_pins
from .player import MovePlayer, MoveRefused
from .recorded_move import RecordedMove
from .service import MovesService

REACT_FLAG = "MAIPAI_BOT_REACT_MOVES"
_TRUE = {"1", "true", "yes", "on"}


def react_moves_enabled(environ: Mapping[str, str]) -> bool:
    return environ.get(REACT_FLAG, "").strip().lower() in _TRUE


class ReactHook:
    def __init__(self, service: MovesService, *, enabled: bool) -> None:
        self._service = service
        self._enabled = enabled

    def __call__(
        self,
        move: str,
        arbitration: ArbitrationState,
        *,
        react_allowed: bool,
        muted: bool = False,
    ) -> bool:
        """Play ``move`` if the flag is on and the plan allows it; say whether it played."""
        if not self._enabled:
            return False
        try:
            self._service.react(move, arbitration, react_allowed=react_allowed, muted=muted)
        except MoveRefused:
            return False
        return True


def build_react_hook(
    client: HeadActuator,
    cache_dir: Path,
    environ: Mapping[str, str],
    pins_path: Path = PINS_PATH,
) -> ReactHook | None:
    """The hook over the pinned emotions library, or ``None`` when the flag is off.

    Nothing is fetched here: a move file is downloaded (and verified against
    its pin) only when the plan first names it.
    """
    if not react_moves_enabled(environ):
        return None
    pins = load_pins(pins_path)

    def load(name: str) -> RecordedMove:
        for pin in pins:
            if name in pin.files:
                path = ensure_move(pin, name, cache_dir)
                return RecordedMove.from_json(name, json.loads(path.read_text()))
        raise AssetUnavailable(f"{name} is not in the pinned move libraries")

    names = sorted(name for pin in pins for name in pin.files)
    player = MovePlayer(client, REACHY_MINI_PROFILE)
    return ReactHook(MovesService(player, load, names), enabled=True)
