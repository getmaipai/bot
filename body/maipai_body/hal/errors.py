"""Errors every body profile raises through the HAL seam."""


class BodyError(Exception):
    """Base for every error the seam defines."""


class BodyLost(BodyError):
    """The connection to the body's daemon was lost.

    Raised once per loss. The client that raises it refuses every further
    command until something calls its `reconnect`.
    """


class OutOfEnvelope(BodyError):
    """A commanded target falls outside the profile's declared axis limits.

    Raised by the body before anything reaches the daemon; the daemon's own
    clamp is the second line, never the first.
    """


class NotSupported(BodyError):
    """The body's profile does not declare the capability a caller asked for."""
