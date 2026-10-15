"""Errors the HAL seam raises.

A body-specific client (``maipai_body.bodies.<id>.client``) never raises
anything across the seam except these three and ``KeyError`` from
``BodyProfile.axis``. Anything above the seam catches these, never a
vendor's own exception type.
"""

from __future__ import annotations


class BodyLost(Exception):
    """The connection to the body's hardware backend was lost.

    Raised once, on the command or read that discovers the loss. The
    client that raises it refuses every further command until a fresh
    connection is established (AGENTS.md, RM-01: "nothing is retried
    silently").
    """


class OutOfEnvelope(Exception):
    """A requested actuator target falls outside the profile's declared axis limits.

    Raised by the body before anything reaches the backend; the
    backend's own clamp (a vendor daemon, a driver board) is the second
    line, never the first.
    """


class NotSupported(Exception):
    """The profile does not declare a capability a caller asked for.

    ``part``, ``capability``, ``message`` and ``fix`` match the shared
    ``NotSupported`` shape in spec ``vocab/robot-api.json``. Positional
    ``message`` remains accepted for existing seam callers.
    """

    def __init__(
        self,
        message: str,
        *,
        part: str = "",
        capability: str = "",
        fix: str = "",
    ) -> None:
        self.part = part
        self.capability = capability
        self.message = message
        self.fix = fix
        detail = f"{message} Fix: {fix}" if fix else message
        super().__init__(detail)


class NotPermitted(Exception):
    """A command was refused because its caller does not hold the robot lease."""


class EstopEngaged(Exception):
    """Motion is refused while the emergency stop is engaged."""


class Busy(Exception):
    """A command cannot interrupt a timed operation already in progress."""


class DeadlineExpired(Exception):
    """A continuous command's deadline has passed; the body must stop."""
