"""EXPR-05: a body-agnostic web dashboard.

Shows a body's live head pose, antennas, body yaw, direction of arrival
and presence/arbitration state, and triggers any expression primitive by
name. Everything here goes through the HAL seam (``state_feed``,
``read_presence``) and ``ExpressionEngine``; no vendor module is imported
by this package, so the same page serves every body profile.
"""

from .server import DashboardServer

__all__ = ["DashboardServer"]
