"""The robot's own settings keys, declared for the ``hello`` (docs/dev.md,
"Robot-only settings keys"): device scope, no hub key, no ``keys.json``
entry. The registry's wire shape lives in commons and is UNVERIFIED from
this repo; nothing here sends it yet, since the bot has no ``hello``
transport.
"""

from __future__ import annotations

from typing import Any

from maipai_body.indicator.settings import ROBOT_DEVICE_PAGE, eyes_settings_declaration
from maipai_body.presence.carry_reaction import DEFAULT_CARRY_REACTION, CarryReaction

CARRY_REACTION_KEY = "robot.motion.carry_reaction"


def settings_declaration(eyes_capability: str = "eyes") -> list[dict[str, Any]]:
    """Every robot-only key. ``eyes_capability`` is the body's id for its eyes:
    ``eyes`` on Reachy, ``light_ring`` on the MaiPai build (the keys' ``needs``)."""
    return [
        {
            "key": CARRY_REACTION_KEY,
            "type": "select",
            "options": [reaction.value for reaction in CarryReaction],
            "default": DEFAULT_CARRY_REACTION.value,
            "scope": "device",
            "label": "When I am picked up",
            "lives_in": f"{ROBOT_DEVICE_PAGE}, Movement",
            "honoured_by": ["bot"],
        },
        *eyes_settings_declaration(eyes_capability),
    ]
