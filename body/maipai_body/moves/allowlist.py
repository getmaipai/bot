"""The age allow-list: which moves a child, a teen or an unknown speaker may be shown.

Age and surface gates outrank everything, so an unstated band is treated
as restricted. The seven stems below are the owner's ruling (MOVES-01
amendment); a move file ``rage1`` or ``go_away2`` is matched by its stem.
Adults may ask for any move.
"""

from __future__ import annotations

import re

CHILD_TEEN_EXCLUDED = frozenset(
    {"rage", "furious", "dying", "contempt", "disgusted", "go_away", "reprimand"}
)
UNRESTRICTED_BANDS = frozenset({"adult"})


def move_stem(name: str) -> str:
    return re.sub(r"[\d_]+$", "", name)


def is_allowed(name: str, band: str) -> bool:
    if band in UNRESTRICTED_BANDS:
        return True
    return move_stem(name) not in CHILD_TEEN_EXCLUDED


def allowed_names(names: list[str], band: str) -> list[str]:
    return [name for name in names if is_allowed(name, band)]
