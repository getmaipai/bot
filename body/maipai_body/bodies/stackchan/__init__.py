"""StackChan body profile and xiaozhi adapters."""

from .adapter import StackChanRobotAdapter, create_stackchan_robot
from .profile import STACKCHAN_PROFILE

__all__ = ["STACKCHAN_PROFILE", "StackChanRobotAdapter", "create_stackchan_robot"]
