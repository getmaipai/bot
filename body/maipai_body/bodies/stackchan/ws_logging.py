"""Quiet logging for the StackChan websocket listeners.

Home's port health check opens a TCP connection and closes it without sending
a byte. websockets logs that as an ERROR with a traceback ("opening handshake
failed": InvalidMessage / EOFError), thousands of times a day. A connection
that sends no bytes is not a fault, so those records are dropped; every other
handshake failure (a bad request, a TLS error) still logs normally.
"""

from __future__ import annotations

import logging

from websockets.exceptions import InvalidMessage

_NAME = "maipai_body.stackchan.websockets"


class _DropEmptyConnections(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != "opening handshake failed" or not record.exc_info:
            return True
        error = record.exc_info[1]
        if isinstance(error, (EOFError, ConnectionResetError)):
            return False
        if isinstance(error, InvalidMessage):
            cause = error.__cause__ or error.__context__
            return not isinstance(cause, (EOFError, ConnectionResetError))
        return True


def listener_logger(name: str = _NAME) -> logging.Logger:
    """The logger to pass as ``serve(logger=...)``; created once, filter attached once."""
    logger = logging.getLogger(name)
    if not any(isinstance(item, _DropEmptyConnections) for item in logger.filters):
        logger.addFilter(_DropEmptyConnections())
    return logger
