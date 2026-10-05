"""The robot's own settings keys, declared for the ``hello`` (docs/dev.md,
"Robot-only settings keys"): device scope, no hub key, no ``keys.json``
entry. The registry's wire shape lives in commons and is UNVERIFIED from
this repo; nothing here sends it yet, since the bot has no ``hello``
transport.
"""

from __future__ import annotations

from typing import Any

from maipai_body.presence.carry_reaction import DEFAULT_CARRY_REACTION, CarryReaction

CARRY_REACTION_KEY = "robot.motion.carry_reaction"


def settings_declaration() -> list[dict[str, Any]]:
    return [
        {
            "key": CARRY_REACTION_KEY,
            "type": "select",
            "options": [reaction.value for reaction in CarryReaction],
            "default": DEFAULT_CARRY_REACTION.value,
            "scope": "device",
            "label": "When I am picked up",
            "lives_in": "Devices, this robot, Movement",
            "honoured_by": ["bot"],
        }
    ]
