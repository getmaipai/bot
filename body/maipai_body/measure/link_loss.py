"""M-R5: Wi-Fi loss mid-turn and mid-sentence, driven through a real ``ConversationLoop``.

The bench is the production wiring with the hub swapped for
``StandInHub``: the real STT, turn and tts clients, the real expression
engine, the real ``StateReporter`` (its interval is the reconnection
clock, because it is the one thing in the body that keeps trying a hub
nobody is asking anything of). A trial arms one fault, wakes the robot,
and reads off what the body did: when the cancel was raised, whether the
pose settled, when the link was next used successfully, and whether the
one line was spoken once.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.hal.seam import BodyProfile
from maipai_body.link.state import StateReporter
from maipai_body.measure.loop_bench import NullAudioIO, TriggerableWakeEngine
from maipai_body.measure.motion import FeedRecorder, time_to_still
from maipai_body.measure.stand_in_hub import StandInHub
from maipai_body.measure.stats import summarize
from maipai_body.run_loop import LINK_RESTORED_LINE, ConversationLoop, FunnelState
from maipai_body.speech.capture import AudioCapture
from maipai_body.speech.playback import AudioPlayback
from maipai_body.speech.stt_stream import SttStreamClient
from maipai_body.speech.tts_playback import TtsPlaybackClient
from maipai_body.speech.turn_client import TurnClient
from maipai_body.speech.wake import WakeScorer

SCENARIOS = ("listening", "mid_turn", "mid_sentence")
# Where in the stand-in's script each scenario's fault lands: before the stt
# stream is ready; after the signal event; after the third 1 KiB audio chunk.
_FAULTS = {
    "listening": ("stt", 0),
    "mid_turn": ("turn", 1),
    "mid_sentence": ("tts", 3),
}


class _TimedEngine(ExpressionEngine):
    """An ``ExpressionEngine`` that stamps every cue it handles."""

    def __init__(self, client, profile, sink: list[tuple[Phase, int]]) -> None:
        super().__init__(client, profile)
        self._sink = sink

    def handle(self, cue: Cue, context, **kwargs):
        self._sink.append((cue.phase, time.monotonic_ns()))
        return super().handle(cue, context, **kwargs)


def _wait_for(predicate: Callable[[], bool], timeout_s: float, interval_s: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return predicate()


class LinkLossBench:
    def __init__(
        self,
        body,
        profile: BodyProfile,
        hub: StandInHub,
        *,
        report_interval_s: float = 15.0,
    ) -> None:
        self.hub = hub
        self.audio_io = NullAudioIO(body)
        self.rendered: list[tuple[Phase, int]] = []
        playback = AudioPlayback(self.audio_io)
        self._wake_engine = TriggerableWakeEngine()
        changed = threading.Event()
        self.loop = ConversationLoop(
            client=self.audio_io,
            expression_engine=_TimedEngine(self.audio_io, profile, self.rendered),
            audio_capture=AudioCapture(self.audio_io),
            audio_playback=playback,
            wake_scorer=WakeScorer(self._wake_engine, self.audio_io, threshold=0.5),
            stt_client=SttStreamClient(hub.stt_url, "bench-cookie"),
            turn_client=TurnClient(hub.http_url, "bench-cookie"),
            tts_client=TtsPlaybackClient(hub.http_url, "bench-cookie", playback),
            on_change=changed.set,
        )
        self._stop = threading.Event()
        self._reporter = StateReporter(
            lambda: ("bench-cookie", hub.http_url),
            self._stop,
            self.loop.snapshot,
            changed,
            interval_s=report_interval_s,
        )
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for target, args in ((self.loop.run, (self._stop,)), (self._reporter.run, ())):
            thread = threading.Thread(target=target, args=args, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        self.hub.restore()  # lets any held connection go so the threads can end
        for thread in self._threads:
            thread.join(timeout=5.0)

    def wait_idle(self, timeout_s: float = 10.0) -> bool:
        return _wait_for(lambda: self.loop.state.funnel is FunnelState.IDLE, timeout_s)

    def run_turn(self, timeout_s: float = 10.0) -> bool:
        """Wake the robot and wait for the turn to run its course."""
        before = len(self.loop.state.trace)
        self._wake_engine.trigger()
        return _wait_for(
            lambda: (
                len(self.loop.state.trace) > before and self.loop.state.funnel is FunnelState.IDLE
            ),
            timeout_s,
        )

    def start_turn(self) -> None:
        self._wake_engine.trigger()


def stratified_outages(count: int, *, interval_s: float) -> list[float]:
    """``count`` outage lengths spread evenly across one report interval.

    The reconnect clock is the state reporter's interval, so how long the
    link stays down decides where in that interval it returns. Restoring
    at the same moment every trial would measure one phase of it; spreading
    the outages makes p50 and p95 describe the whole interval.
    """
    return [(i + 0.5) / count * interval_s for i in range(count)]


def run_trial(
    bench: LinkLossBench,
    scenario: str,
    mode: str,
    *,
    cancel_timeout_s: float,
    settle_window_s: float = 1.0,
    recover_timeout_s: float = 30.0,
    outage_s: float = 0.0,
) -> dict[str, Any]:
    """One loss and one recovery: the cancel, the pose, the reconnect, the line.

    The link stays down for at least ``outage_s`` from the moment it was lost.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}, not {scenario!r}")
    hub = bench.hub
    bench.wait_idle()
    rendered_before = len(bench.rendered)
    tts_before = len(hub.tts_requests)
    hub.loss_at = None
    route, after = _FAULTS[scenario]

    recorder = FeedRecorder()
    feed_thread = threading.Thread(target=recorder.run, args=(bench.audio_io,), daemon=True)
    feed_thread.start()
    time.sleep(0.2)  # a baseline before the loss

    hub.fail_next(route, after=after, mode=mode)
    bench.start_turn()

    def _cancel_ns() -> int | None:
        for phase, stamp in bench.rendered[rendered_before:]:
            if phase is Phase.CANCEL:
                return stamp
        return None

    row: dict[str, Any] = {"scenario": scenario, "mode": mode, "outage_s": outage_s}
    if not _wait_for(lambda: _cancel_ns() is not None, cancel_timeout_s):
        # The link stays down until the harness lifts it, so the loop is
        # still waiting; lift it and let the turn end before reporting.
        recorder.stop()
        hub.restore()
        bench.wait_idle(recover_timeout_s)
        row.update(
            cancel_ms=None,
            cancels=0,
            error=f"no cancel within {cancel_timeout_s:g} s",
        )
        return row

    cancel_ns = _cancel_ns()
    assert cancel_ns is not None
    time.sleep(settle_window_s)
    recorder.stop()
    feed_thread.join(timeout=2.0)
    phases = [phase for phase, _ in bench.rendered[rendered_before:]]
    row.update(
        phases=[phase.value for phase in phases],
        cancels=phases.count(Phase.CANCEL),
        cancel_ms=(cancel_ns - hub.loss_at * 1e9) / 1e6 if hub.loss_at is not None else None,
        pose_still_after_cancel_ms=time_to_still(recorder.samples, cancel_ns),
    )

    bench.wait_idle(recover_timeout_s)
    if hub.loss_at is not None:
        time.sleep(max(0.0, outage_s - (time.monotonic() - hub.loss_at)))
    hub.restore()
    restored = hub.restored_at
    assert restored is not None
    if _wait_for(lambda: any(t >= restored for t in hub.state_reports), recover_timeout_s):
        first = min(t for t in hub.state_reports if t >= restored)
        row["reconnect_ms"] = (first - restored) * 1e3
    else:
        row["reconnect_ms"] = None

    bench.run_turn(recover_timeout_s)
    spoken = hub.tts_requests[tts_before:]
    row["line_on_next_turn"] = bool(spoken) and spoken[-1].startswith(LINK_RESTORED_LINE)
    bench.run_turn(recover_timeout_s)
    spoken = hub.tts_requests[tts_before:]
    row["line_on_turn_after"] = len(spoken) >= 2 and spoken[-1].startswith(LINK_RESTORED_LINE)
    return row


def summarize_trials(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """p50 and p95 per figure; a trial with no cancel is counted, never averaged in."""
    good = [row for row in rows if row.get("error") is None]
    return {
        "trials": len(rows),
        "errors": len(rows) - len(good),
        "cancel_ms": summarize([r["cancel_ms"] for r in good if r["cancel_ms"] is not None]),
        "pose_still_after_cancel_ms": summarize(
            [
                r["pose_still_after_cancel_ms"]
                for r in good
                if r["pose_still_after_cancel_ms"] is not None
            ]
        ),
        "reconnect_ms": summarize(
            [r["reconnect_ms"] for r in good if r["reconnect_ms"] is not None]
        ),
        "max_cancels_per_turn": max((r["cancels"] for r in good), default=0),
        "line_on_next_turn": sum(1 for r in good if r["line_on_next_turn"]),
        "line_on_turn_after": sum(1 for r in good if r["line_on_turn_after"]),
    }
