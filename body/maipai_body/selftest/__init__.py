"""BOT-SELF-TEST-01: simple per-part checks anyone can run, one pass or fail
per part with a plain "what to do" when it fails. Nothing is kept."""

from maipai_body.selftest.core import (
    Check,
    CheckResult,
    Status,
    format_report,
    overall_ok,
    run_selftest,
)
from maipai_body.selftest.stackchan import StackChanSelfTestContext, stackchan_checks

__all__ = [
    "Check",
    "CheckResult",
    "Status",
    "StackChanSelfTestContext",
    "format_report",
    "overall_ok",
    "run_selftest",
    "stackchan_checks",
]
