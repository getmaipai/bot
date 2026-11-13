"""StackChan mute, vision off and full quiet, the host side (firmware patches 105 to 108,
design note docs/dev/stackchan-mute-2026-11-13.md).

Three independent states live on the unit and are saved in its own flash:

* ``muted``: no listening. The unit powers the microphone chip down and reads it back
  (``mic_off_verified``); the host never says "muted" until the unit has said so.
* ``vision_off``: the camera is not read. The host stops asking for frames, drops any that arrive,
  analyses nothing and refuses a picture question.
* ``quiet`` (full quiet): no movement, no sound out, no listening. Vision keeps whatever it was.

The unit is the authority. A person can change each from the unit's face (tap the eyes, hold the
mouth, hold the forehead) with no host at all; the host reads the state back from the ``privacy``
event and the minute ``wake_stats`` and never "resets" it on connect. Home's settings
(``robot.muted``, ``robot.vision_off``, ``robot.quiet``, ``robot.mute.local_unmute``) are a request:
a changed value is pushed to the unit and confirmed from its read-back.

Four small pieces with no sockets of their own, driven by their callers:

* ``PrivacyState``: the newest facts, the leak check and ``muted_reason()``.
* ``PrivacyController``: pushing a request to the unit and the hub's ``mute`` / ``unmute`` commands.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from maipai_body.settings_keys import (
    LOCAL_UNMUTE_KEY,
    MUTED_KEY,
    QUIET_KEY,
    VISION_OFF_KEY,
)

LOG = logging.getLogger("maipai_body.bodies.stackchan.privacy")

# How long a request the unit has not confirmed may stand before the mismatch line.
MISMATCH_AFTER_S = 60.0
# A state must have held this long before a minute report is read for a leak (counters since last
# report begin before a change), and this long before a late camera frame counts (frames in flight).
SETTLE_S = 75.0
FRAME_SETTLE_S = 5.0
# The unit's own reports tell the state; these event kinds carry it.
_STATE_KINDS = frozenset({"wake_stats", "privacy"})


def _flag(value: object) -> bool:
    return value is True or (isinstance(value, int) and not isinstance(value, bool) and value != 0)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class PrivacyState:
    """What the unit says about its mute, vision and quiet, and the leak check on top of it."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_change: Callable[[PrivacyState], object] | None = None,
        on_leak: Callable[[str, str], object] | None = None,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.listeners: list[Callable[[PrivacyState], object]] = (
            [on_change] if on_change is not None else []
        )
        self.on_leak = on_leak
        self.known = False  # True once the unit has reported at least once
        self.muted = False
        self.vision_off = False
        self.quiet = False
        self.mic_off_verified = False
        self.mute_source: str | None = None
        self.local_unmute: bool | None = None
        self.leaks = 0
        self._leak_logged: dict[str, float] = {}
        self._unverified_since: float | None = None
        self._unverified_logged = False
        # When listening and looking went off, so a minute report that spans the change is not
        # read as a leak.
        self._mic_off_since: float | None = None
        self._vision_off_since: float | None = None

    # ---- what the rest of the host asks ----

    def muted_reason(self) -> str | None:
        """The plain word for why the robot says and hears nothing, or None. The named hook for the
        announcement, repeat and dance code: ``"muted"`` or ``"full quiet"``."""
        if self.muted:
            return "muted"
        if self.quiet:
            return "full quiet"
        return None

    def silent(self) -> bool:
        return self.muted_reason() is not None

    def head_blocked(self) -> str | None:
        """Why the head must not move (full quiet), else None."""
        return "full quiet" if self.quiet else None

    def facts(self) -> dict[str, Any]:
        """The check-in members; every value is None until the unit has reported."""
        if not self.known:
            return {
                "muted": None,
                "vision_off": None,
                "quiet": None,
                "mic_off_verified": None,
                "mute_source": None,
            }
        return {
            "muted": self.muted,
            "vision_off": self.vision_off,
            "quiet": self.quiet,
            "mic_off_verified": self.mic_off_verified,
            "mute_source": self.mute_source,
        }

    # ---- what the unit reports ----

    def observe(self, kind: str, extra: Mapping[str, object] | None) -> None:
        extra = extra or {}
        if kind in _STATE_KINDS and "muted" in extra:
            self._take_state(kind, extra)
        elif kind == "camera":
            self._check_camera(extra)
        elif kind == "boot":
            # A restart: what the unit reports next is its saved state; forget the unverified timer.
            self._unverified_since = None
            self._unverified_logged = False
        if kind == "wake_stats" and "muted" in extra:
            self._check_wake(extra)

    def _take_state(self, kind: str, extra: Mapping[str, object]) -> None:
        with self._lock:
            before = (self.muted, self.vision_off, self.quiet, self.mic_off_verified, self.known)
            self.muted = _flag(extra.get("muted"))
            if "vision_off" in extra:
                self.vision_off = _flag(extra.get("vision_off"))
            if "quiet" in extra:
                self.quiet = _flag(extra.get("quiet"))
            if "mic_off_verified" in extra:
                self.mic_off_verified = _flag(extra.get("mic_off_verified"))
            source = extra.get("mute_source")
            if isinstance(source, str) and source:
                self.mute_source = source
            if "local_unmute" in extra:
                self.local_unmute = _flag(extra.get("local_unmute"))
            self.known = True
            after = (self.muted, self.vision_off, self.quiet, self.mic_off_verified, self.known)
            mic_off = self.muted or self.quiet
            now = self._clock()
            if mic_off:
                if self._mic_off_since is None:
                    self._mic_off_since = now
            else:
                self._mic_off_since = None
            if self.vision_off:
                if self._vision_off_since is None:
                    self._vision_off_since = now
            else:
                self._vision_off_since = None
            if mic_off and not self.mic_off_verified:
                if self._unverified_since is None:
                    self._unverified_since = self._clock()
            else:
                self._unverified_since = None
                self._unverified_logged = False
        if after != before:
            LOG.info(
                "StackChan privacy: muted=%s vision_off=%s quiet=%s (microphone chip %s)%s",
                self.muted,
                self.vision_off,
                self.quiet,
                "verified off" if self.mic_off_verified else "not verified off",
                f", changed from the {self.mute_source}"
                if kind == "privacy" and self.mute_source
                else "",
            )
            for listener in list(self.listeners):
                try:
                    listener(self)
                except Exception:
                    LOG.warning("StackChan privacy change hook failed", exc_info=True)

    # ---- the leak check: a mute that hears anything, a vision-off that sees anything ----

    def _check_wake(self, extra: Mapping[str, object]) -> None:
        if not _flag(extra.get("muted")) and not _flag(extra.get("quiet")):
            return
        if self._mic_off_since is None or self._clock() - self._mic_off_since < SETTLE_S:
            return  # the minute's counters began before the mute
        fetches = _count(extra.get("fetches"))
        detections = _count(extra.get("detections"))
        speech = _count(extra.get("vad_speech"))
        armed = _flag(extra.get("armed"))
        if fetches or detections or speech or armed:
            self._leak(
                "microphone",
                f"the unit says muted but its wake engine shows armed={int(armed)} "
                f"fetches={fetches} detections={detections} vad_speech={speech}",
            )

    def _check_camera(self, extra: Mapping[str, object]) -> None:
        if not _flag(extra.get("vision_off")):
            return
        if self._vision_off_since is None or self._clock() - self._vision_off_since < SETTLE_S:
            return
        captured = _count(extra.get("captured"))
        sent = _count(extra.get("sent"))
        if captured or sent:
            self._leak(
                "camera",
                f"vision is off but the unit captured {captured} and sent {sent} frames",
            )

    def frame_arrived(self) -> None:
        """A camera frame reached the host while vision is off: always a leak."""
        since = self._vision_off_since
        if self.vision_off and since is not None and self._clock() - since >= FRAME_SETTLE_S:
            self._leak("camera", "a camera frame arrived while vision is off")

    def _leak(self, what: str, detail: str) -> None:
        now = self._clock()
        with self._lock:
            self.leaks += 1
            last = self._leak_logged.get(what, float("-inf"))
            quiet = now - last < 60.0
            if not quiet:
                self._leak_logged[what] = now
        if not quiet:
            LOG.error("StackChan privacy LEAK (%s): %s", what, detail)
            if self.on_leak is not None:
                try:
                    self.on_leak(what, detail)
                except Exception:
                    LOG.warning("StackChan privacy leak hook failed", exc_info=True)

    def tick(self) -> None:
        """Call about once a second: a mic that stays unverified after the mute is said once."""
        with self._lock:
            since = self._unverified_since
            logged = self._unverified_logged
            if since is None or logged or self._clock() - since < MISMATCH_AFTER_S:
                return
            self._unverified_logged = True
        LOG.warning(
            "StackChan privacy: muted for over %d s but the unit has not confirmed the microphone "
            "chip is powered down; Home keeps saying it has not confirmed",
            int(MISMATCH_AFTER_S),
        )


def _parse(result: object) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    if isinstance(result, str):
        try:
            value = json.loads(result)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


class PrivacyController:
    """Asks the unit to change a state, reads back what it did, and answers the hub's commands.

    ``call(tool, arguments)`` is the unit's tool call. Nothing here changes the unit's state on its
    own initiative except pushing what Home's settings ask for."""

    def __init__(
        self,
        call: Callable[[str, dict[str, object]], object],
        state: PrivacyState,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._call = call
        self.state = state
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: dict[str, bool] = {}  # the last value of each Home setting this host saw
        self._pending: dict[str, bool] = {}  # asked of the unit but not yet confirmed
        self._asked_at: dict[str, float] = {}
        self._policy_sent: bool | None = None
        self._mismatch_logged: set[str] = set()

    # ---- talking to the unit ----

    def read(self) -> bool:
        """Ask the unit for its state (on connect). True when it answered."""
        try:
            reply = _parse(self._call("self.privacy.get", {}))
        except Exception:
            LOG.debug("StackChan privacy state could not be read", exc_info=True)
            return False
        if "muted" not in reply:
            return False
        self.state.observe("privacy", reply)
        return True

    def push(
        self, *, mute: bool | None = None, vision_off: bool | None = None, quiet: bool | None = None
    ) -> dict[str, Any]:
        """Ask the unit to set the given states. Returns {"confirmed": bool, ...state}."""
        arguments: dict[str, object] = {}
        for name, value in (("mute", mute), ("vision_off", vision_off), ("quiet", quiet)):
            if value is not None:
                arguments[name] = 1 if value else 0
        if not arguments:
            return {"confirmed": True, **self.state.facts()}
        try:
            reply = _parse(self._call("self.privacy.set", arguments))
        except Exception as exc:
            LOG.warning(
                "StackChan privacy request failed (%s); it stays pending", type(exc).__name__
            )
            with self._lock:
                for name, value in (("mute", mute), ("vision_off", vision_off), ("quiet", quiet)):
                    if value is not None:
                        self._pending[name] = value
                        self._asked_at.setdefault(name, self._clock())
            return {"confirmed": False, **self.state.facts()}
        if "muted" in reply:
            self.state.observe("privacy", {**reply, "mute_source": "home"})
        confirmed = self._matches(mute, vision_off, quiet)
        with self._lock:
            for name, value in (("mute", mute), ("vision_off", vision_off), ("quiet", quiet)):
                if value is None:
                    continue
                if confirmed:
                    self._pending.pop(name, None)
                    self._asked_at.pop(name, None)
                else:
                    self._pending[name] = value
                    self._asked_at.setdefault(name, self._clock())
        return {"confirmed": confirmed, **self.state.facts()}

    def _matches(self, mute: bool | None, vision_off: bool | None, quiet: bool | None) -> bool:
        state = self.state
        if mute is not None and state.muted != mute:
            return False
        if vision_off is not None and state.vision_off != vision_off:
            return False
        if quiet is not None and state.quiet != quiet:
            return False
        # A listening-off state counts only once the unit has read the microphone chip back.
        if (mute or quiet) and not state.mic_off_verified:
            return False
        return True

    def on_connect(self) -> None:
        """A unit connected: learn its state, send the unmute policy, retry what was pending. Never
        sends an unmute or resets anything the unit holds."""
        self.read()
        with self._lock:
            policy = self._seen.get(LOCAL_UNMUTE_KEY)
            pending = dict(self._pending)
        if policy is not None:
            self._send_policy(policy, force=True)
        if pending:
            self.push(
                mute=pending.get("mute"),
                vision_off=pending.get("vision_off"),
                quiet=pending.get("quiet"),
            )

    def _send_policy(self, allowed: bool, *, force: bool = False) -> None:
        if not force and self._policy_sent == allowed:
            return
        try:
            self._call("self.privacy.set_policy", {"local_unmute": allowed})
            self._policy_sent = allowed
        except Exception:
            LOG.debug("StackChan privacy policy could not be sent", exc_info=True)

    # ---- Home's settings ----

    def apply_settings(self, values: Mapping[str, Any]) -> None:
        """Home's request. A first sighting only ever restricts (a mute is never lost); after that a
        changed value is pushed, an unmute included (the admin confirmed it in Home)."""
        want: dict[str, bool] = {}
        for key, name in (
            (MUTED_KEY, "mute"),
            (VISION_OFF_KEY, "vision_off"),
            (QUIET_KEY, "quiet"),
        ):
            value = values.get(key)
            if not isinstance(value, bool):
                continue
            previous = self._seen.get(key)
            self._seen[key] = value
            current = {
                "mute": self.state.muted,
                "vision_off": self.state.vision_off,
                "quiet": self.state.quiet,
            }[name]
            if previous is None:
                if value and not current:
                    want[name] = True
            elif previous != value and value != current:
                want[name] = value
        policy = values.get(LOCAL_UNMUTE_KEY)
        if isinstance(policy, bool):
            self._seen[LOCAL_UNMUTE_KEY] = policy
            self._send_policy(policy)
        if want:
            self.push(
                mute=want.get("mute"),
                vision_off=want.get("vision_off"),
                quiet=want.get("quiet"),
            )

    # ---- the hub's mute and unmute commands ----

    def command(self, mute: bool, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """The hub's ``mute`` or ``unmute``. An unmute needs ``confirm: true`` in the payload: the
        admin must have confirmed it in Home, because a remote unmute turns a microphone on."""
        payload = payload or {}
        if not mute and payload.get("confirm") is not True:
            return {
                "muted": self.state.muted,
                "status": "needs_confirm",
                "error": "Turning listening back on from Home needs a confirmation. Confirm in "
                "Home that the robot should listen again, then send the unmute again.",
            }
        reply = self.push(mute=mute)
        return {
            "muted": bool(self.state.muted),
            "status": "confirmed" if reply["confirmed"] else "unconfirmed",
            "mic_off_verified": bool(self.state.mic_off_verified),
        }

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        return {
            "mute": lambda payload: self.command(True, payload),
            "unmute": lambda payload: self.command(False, payload),
        }

    def tick(self) -> None:
        """Once a second: a request the unit has not confirmed for a minute is said once."""
        now = self._clock()
        with self._lock:
            stale = [
                name
                for name, at in self._asked_at.items()
                if now - at >= MISMATCH_AFTER_S and name not in self._mismatch_logged
            ]
            self._mismatch_logged.update(stale)
            for name in list(self._mismatch_logged):
                if name not in self._asked_at:
                    self._mismatch_logged.discard(name)
        for name in stale:
            LOG.warning(
                "StackChan privacy: Home asked for %s %s over a minute ago and the unit has not "
                "confirmed it; the robot card keeps saying it has not confirmed",
                name,
                "on" if self._pending.get(name) else "off",
            )
