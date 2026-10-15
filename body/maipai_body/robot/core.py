"""One capability-checked robot object over body-specific command adapters."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from maipai_body.hal.errors import (
    BodyLost,
    Busy,
    DeadlineExpired,
    EstopEngaged,
    NotPermitted,
    NotSupported,
)
from maipai_body.hal.seam import BodyProfile, HeadPose

from .api import PartContract, RobotApi, load_robot_api

_PRIORITY = {"safety": 0, "person": 1, "expression": 2, "idle": 3}
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lease:
    holder: str
    priority: str


class Robot:
    """Vendor-neutral robot parts backed by one body profile and its adapters.

    ``drivers`` maps the part ids in the shared robot API vocabulary to
    body-specific adapters. The vocabulary is loaded from the pinned commons
    source and is never copied into the Bot package.
    """

    def __init__(
        self,
        profile: BodyProfile,
        drivers: Mapping[str, object],
        api: RobotApi | None = None,
    ) -> None:
        self.profile = profile
        self._api = api or load_robot_api()
        self._drivers = dict(drivers)
        self._capabilities = frozenset(profile.capabilities)
        for part_id, verbs in profile.leased_motion.items():
            contract = self._api.parts.get(part_id)
            if contract is None or set(verbs) - contract.verbs:
                raise ValueError(
                    f"body profile '{profile.id}' declares invalid leased motion for {part_id!r}"
                )
        for part_id, verb in profile.safe_stop.items():
            contract = self._api.parts.get(part_id)
            if contract is None or verb not in contract.verbs:
                raise ValueError(
                    f"body profile '{profile.id}' declares invalid safe stop {part_id}.{verb}"
                )
        for axis_name in profile.axis_map.values():
            try:
                profile.axis(axis_name)
            except KeyError as exc:
                raise ValueError(
                    f"body profile '{profile.id}' maps to missing axis {axis_name!r}"
                ) from exc
        has_leased_actuator = any(
            part_id in self._api.parts
            and any(
                capability in self._capabilities
                for capability in self._api.parts[part_id].capabilities
            )
            for part_id, verbs in profile.leased_motion.items()
            if verbs
        )
        if has_leased_actuator:
            missing = {"lease", "estop"} - self._capabilities
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(
                    f"body profile '{profile.id}' declares motion but lacks {names}; "
                    "add both safety capabilities before enabling robot motion"
                )
        self._parts: dict[str, RobotPart] = {}
        self._lease: Lease | None = None
        self._estop_engaged = False
        self._last_safe_stop: tuple[str, ...] = ()

    @property
    def capabilities(self) -> frozenset[str]:
        """The read-only capability ids declared by this body's profile."""
        return self._capabilities

    @property
    def lease_holder(self) -> str | None:
        return self._lease.holder if self._lease else None

    @property
    def estop_engaged(self) -> bool:
        return self._estop_engaged

    @property
    def last_safe_stop(self) -> tuple[str, ...]:
        """Names of supported safety-stop commands that failed most recently."""
        return self._last_safe_stop

    def __getattr__(self, name: str) -> Any:
        if name in self._api.whole_robot_verbs:
            return partial(self._whole_robot_command, name)
        contract = self._api.parts.get(name)
        if contract is None:
            raise AttributeError(f"{type(self).__name__} has no attribute {name!r}")
        self._check_part(contract)
        if name not in self._parts:
            self._parts[name] = RobotPart(self, contract)
        return self._parts[name]

    def _whole_robot_command(self, verb: str, *args: Any, **kwargs: Any) -> Any:
        if verb in {"connect", "disconnect"}:
            return self._invoke_part("connection", verb, *args, **kwargs)
        if verb in {"wake", "sleep", "power_on", "shutdown"}:
            return self._invoke_part("power", verb, *args, **kwargs)
        if verb == "emergency_stop":
            return self._invoke_part("estop", "engage", *args, **kwargs)
        raise AttributeError(f"unknown whole-robot verb {verb!r}")

    def _check_part(self, contract: PartContract) -> None:
        missing = [cap for cap in contract.capabilities if cap not in self._capabilities]
        supported = (
            not missing
            if contract.capability_mode == "all"
            else len(missing) < len(contract.capabilities)
        )
        if supported:
            return
        capability = missing[0] if missing else contract.capabilities[0]
        expected = " or ".join(contract.capabilities)
        message = (
            f"robot part '{contract.id}' is not present in body profile "
            f"'{self.profile.id}', which does not declare {expected}"
        )
        fix = getattr(
            self,
            "_unsupported_fixes",
            {},
        ).get(
            contract.id,
            f"Use a body profile that declares {capability} before calling {contract.id}.",
        )
        raise NotSupported(message, part=contract.id, capability=capability, fix=fix)

    def _driver(self, part: str) -> object:
        driver = self._drivers.get(part)
        if driver is None:
            contract = self._api.part(part)
            capability = contract.capabilities[0]
            message = (
                f"robot part '{part}' is declared by profile '{self.profile.id}' "
                "but has no body adapter"
            )
            fix = f"Add the {part} adapter to the body profile implementation for {capability}."
            raise NotSupported(message, part=part, capability=capability, fix=fix)
        return driver

    def _read_part_state(self, contract: PartContract, field: str) -> Any:
        self._check_part(contract)
        driver = self._driver(contract.id)
        reader = getattr(driver, "read", None)
        if callable(reader):
            return reader(field)
        try:
            return getattr(driver, field)
        except AttributeError as exc:
            raise NotSupported(
                f"robot part '{contract.id}' does not report '{field}'",
                part=contract.id,
                capability=contract.capabilities[0],
                fix=f"Read a state field supported by the {contract.id} adapter.",
            ) from exc

    def _invoke_part(self, part: str, verb: str, *args: Any, **kwargs: Any) -> Any:
        contract = self._api.part(part)
        self._check_part(contract)
        if verb not in contract.verbs:
            raise AttributeError(f"robot part '{part}' has no verb {verb!r}")
        if part == "lease" and verb == "acquire":
            return self._acquire_lease(*args, **kwargs)
        if part == "lease" and verb == "release":
            return self._release_lease(*args, **kwargs)
        if part == "estop" and verb == "engage":
            return self._engage_estop(*args, **kwargs)
        if part == "estop" and verb == "release":
            result = self._dispatch(part, verb, *args, **kwargs)
            self._estop_engaged = False
            return result
        if part == "base" and verb == "drive":
            self._check_deadline(args, kwargs)
        if verb in self.profile.leased_motion.get(part, ()):
            if self._estop_engaged:
                raise EstopEngaged(
                    f"robot part '{part}' is stopped; release the emergency stop first"
                )
            self._require_lease(part, verb)

        applied_args, applied_kwargs = self._clamp(part, args, kwargs)
        try:
            result = self._dispatch(part, verb, *applied_args, **applied_kwargs)
        except BodyLost:
            self._estop_engaged = True
            self._safe_stop(include_estop=True)
            raise
        if result is not None:
            return result
        if applied_kwargs:
            return dict(applied_kwargs)
        if len(applied_args) == 1:
            return applied_args[0]
        if applied_args:
            return applied_args
        return True

    def _dispatch(self, part: str, verb: str, *args: Any, **kwargs: Any) -> Any:
        driver = self._driver(part)
        command = getattr(driver, "command", None)
        if callable(command):
            return command(verb, *args, **kwargs)
        method = getattr(driver, verb, None)
        if not callable(method):
            contract = self._api.part(part)
            capability = contract.capabilities[0]
            raise NotSupported(
                f"robot part '{part}' has capability '{capability}' but adapter lacks '{verb}'",
                part=part,
                capability=capability,
                fix=f"Implement {part}.{verb} on the selected body adapter.",
            )
        return method(*args, **kwargs)

    def _acquire_lease(self, priority: str = "idle", holder: str = "controller") -> Lease:
        if priority not in _PRIORITY:
            raise ValueError(
                f"unknown lease priority {priority!r}; use safety, person, expression or idle"
            )
        requested = Lease(holder=holder, priority=priority)
        if self._lease is not None:
            current_rank = _PRIORITY[self._lease.priority]
            requested_rank = _PRIORITY[priority]
            if requested_rank > current_rank:
                raise NotPermitted(
                    f"robot lease is held by {self._lease.holder!r} "
                    f"at {self._lease.priority} priority; "
                    f"{holder!r} at {priority} priority cannot take control"
                )
            if requested.holder == self._lease.holder:
                self._lease = requested
                return requested
            if requested_rank == current_rank:
                raise Busy(f"robot lease is already held by {self._lease.holder!r}")
        self._lease = requested
        return requested

    def _release_lease(self, holder: str | None = None) -> bool:
        if self._lease is None:
            return False
        if holder is not None and holder != self._lease.holder:
            raise NotPermitted(f"robot lease belongs to {self._lease.holder!r}, not {holder!r}")
        self._lease = None
        return True

    def _require_lease(self, part: str, verb: str) -> None:
        if self._lease is None:
            raise NotPermitted(
                f"robot part '{part}.{verb}' needs a control lease; "
                "acquire one before moving the body"
            )

    def _engage_estop(self) -> Any:
        self._estop_engaged = True
        try:
            result = self._dispatch("estop", "engage")
        except BodyLost:
            self._safe_stop(include_estop=True, raise_body_lost=True)
            raise
        self._safe_stop(raise_body_lost=True)
        return result if result is not None else True

    def _safe_stop(self, *, include_estop: bool = False, raise_body_lost: bool = False) -> None:
        commands = list(self.profile.safe_stop.items())
        if include_estop:
            commands.insert(0, ("estop", "engage"))
        failed: list[str] = []
        body_lost: BodyLost | None = None
        for part, verb in commands:
            contract = self._api.parts.get(part)
            if contract is None or part not in self._drivers or verb not in contract.verbs:
                continue
            try:
                self._dispatch(part, verb)
            except Exception as exc:
                failed.append(f"{part}.{verb}")
                if isinstance(exc, BodyLost) and body_lost is None:
                    body_lost = exc
                if isinstance(exc, NotSupported):
                    detail = exc.fix
                else:
                    detail = str(exc) or type(exc).__name__
                LOG.warning("Robot safe-stop command %s.%s failed: %s", part, verb, detail)
                continue
        self._last_safe_stop = tuple(failed)
        if raise_body_lost and body_lost is not None:
            raise body_lost

    def _check_deadline(self, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> None:
        deadline = kwargs.get("deadline", args[3] if len(args) > 3 else None)
        if deadline is None:
            raise ValueError(
                "base.drive needs a monotonic deadline; provide the time when motion must stop"
            )
        if not isinstance(deadline, (int, float)):
            raise TypeError("base.drive deadline must be a monotonic timestamp in seconds")
        if deadline <= time.monotonic():
            try:
                self._dispatch("base", "stop")
            except BodyLost:
                self._estop_engaged = True
                self._safe_stop(include_estop=True)
                raise
            raise DeadlineExpired("base.drive deadline has passed; the base was told to stop")

    def _clamp(
        self, part: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        if not self.profile.leased_motion.get(part):
            return args, kwargs
        cooked_args = list(args)
        cooked_kwargs = dict(kwargs)
        target_key = (
            "pose" if "pose" in cooked_kwargs else "target" if "target" in cooked_kwargs else None
        )
        if target_key is not None:
            cooked_kwargs[target_key] = self._clamp_pose(part, cooked_kwargs[target_key])
        elif cooked_args and isinstance(cooked_args[0], (HeadPose, Mapping)) and part == "head":
            cooked_args[0] = self._clamp_pose(part, cooked_args[0])

        if part == "head":
            for field in ("pitch", "roll", "yaw", "speed"):
                if field in cooked_kwargs:
                    cooked_kwargs[field] = self._clamp_axis(
                        f"head_{field}", cooked_kwargs[field], radians=field != "speed"
                    )
        elif part == "appendages" and "angle" in cooked_kwargs:
            name = str(cooked_kwargs.get("name", cooked_args[0] if cooked_args else ""))
            axis = self.profile.axis_map.get(f"appendages.{name}", name)
            cooked_kwargs["angle"] = self._clamp_axis(axis, cooked_kwargs["angle"], radians=True)
        elif part == "appendages" and len(cooked_args) > 1:
            name = str(cooked_args[0])
            axis = self.profile.axis_map.get(f"appendages.{name}", name)
            cooked_args[1] = self._clamp_axis(axis, cooked_args[1], radians=True)
        elif part == "base":
            for field in ("vx", "vy", "wz"):
                if field in cooked_kwargs:
                    cooked_kwargs[field] = self._clamp_axis(f"base_{field}", cooked_kwargs[field])
            for index, field in enumerate(("vx", "vy", "wz")):
                if len(cooked_args) > index:
                    cooked_args[index] = self._clamp_axis(f"base_{field}", cooked_args[index])
        return tuple(cooked_args), cooked_kwargs

    def _clamp_pose(self, part: str, pose: Any) -> Any:
        if part != "head":
            return pose
        fields = {"pitch": "head_pitch", "roll": "head_roll", "yaw": "head_yaw"}
        if isinstance(pose, HeadPose):
            return pose.model_copy(
                update={
                    field: self._clamp_axis(axis, getattr(pose, field), radians=True)
                    for field, axis in fields.items()
                }
            )
        if isinstance(pose, Mapping):
            result = dict(pose)
            for field, axis in fields.items():
                if field in result:
                    result[field] = self._clamp_axis(axis, result[field], radians=True)
            return result
        return pose

    def _clamp_axis(self, axis_name: str, value: Any, *, radians: bool = False) -> Any:
        if not isinstance(value, (int, float)):
            return value
        axis = next(
            (candidate for candidate in self.profile.axes if candidate.name == axis_name), None
        )
        if axis is None:
            return value
        low, high = axis.min, axis.max
        if radians and axis.unit == "deg":
            low, high = math.radians(low), math.radians(high)
        return min(max(value, low), high)


class RobotPart:
    """One profile-checked part; its names and verbs come from commons."""

    def __init__(self, robot: Robot, contract: PartContract) -> None:
        self._robot = robot
        self._contract = contract

    def __getattr__(self, name: str) -> Any:
        if name in self._contract.verbs:
            return partial(self._robot._invoke_part, self._contract.id, name)
        if name in self._contract.state:
            if self._contract.id == "estop" and name == "engaged":
                return self._robot.estop_engaged
            if self._contract.id == "lease" and name == "holder":
                return self._robot.lease_holder
            return self._robot._read_part_state(self._contract, name)
        prefix = f"{name}."
        if any(verb.startswith(prefix) for verb in self._contract.verbs):
            return RobotFacet(self, name)
        raise AttributeError(f"robot part '{self._contract.id}' has no attribute {name!r}")

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """Return this part's stream using the same vocabulary-backed command path."""
        if "stream" not in self._contract.verbs:
            raise AttributeError(f"robot part '{self._contract.id}' has no stream verb")
        return self._robot._invoke_part(self._contract.id, "stream", *args, **kwargs)


class RobotFacet:
    """One nested vocabulary prefix, such as ``audio.speaker``."""

    def __init__(self, part: RobotPart, prefix: str) -> None:
        self._part = part
        self._prefix = prefix

    def __getattr__(self, name: str) -> Any:
        verb = f"{self._prefix}.{name}"
        if verb in self._part._contract.verbs:
            return partial(
                self._part._robot._invoke_part,
                self._part._contract.id,
                verb,
            )
        raise AttributeError(
            f"robot part '{self._part._contract.id}' has no attribute '{self._prefix}.{name}'"
        )
