"""EYES-02: the seven robot-only settings keys the eyes honour.

Robot-only: declared on the ``hello``, no spec record, no ``keys.json``
entry. Every key carries the schema-required ``label`` and ``lives_in``
(the robot's device page, shared with its other robot-only keys), scope
``device``, ``honoured_by: [bot]`` and ``needs`` set to the body's
capability: ``eyes`` on Reachy, ``light_ring`` on the MaiPai build.

Field and type names (``boolean``, ``number``, ``time``, ``select``,
``range``) follow the one declaration already in the repo; they are
UNVERIFIED against spec-v0.1.74's ``settings-key.schema.json``, which this
clone cannot reach (``tests/test_indicator_settings.py`` validates against
it when ``MAIPAI_SPEC_SETTINGS_KEY_SCHEMA`` points at the file).

Quiet hours are owned by Home and this bot has no settings transport yet.
The robot-only time keys are ``night_from`` and ``night_to`` pending that
transport; retire them if Home later supplies a shared quiet-hours setting.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from maipai_body.indicator import looks

ROBOT_DEVICE_PAGE = "Devices, this robot"
_LIVES_IN = f"{ROBOT_DEVICE_PAGE}, Lights"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
SLEEP_EYES_OPTIONS = ["off", "dim"]

KEY_ENABLED = "robot.indicator.enabled"
KEY_BRIGHTNESS = "robot.indicator.brightness"
KEY_NIGHT_BRIGHTNESS = "robot.indicator.night_brightness"
KEY_NIGHT_FROM = "robot.indicator.night_from"
KEY_NIGHT_TO = "robot.indicator.night_to"
KEY_SLEEP_EYES = "robot.indicator.sleep_eyes"
KEY_ALARM = "robot.indicator.alarm"


@dataclass(frozen=True)
class IndicatorSettings:
    enabled: bool = True
    brightness: float = looks.DAY_LEVEL_DEFAULT
    night_brightness: float = looks.NIGHT_LEVEL_DEFAULT
    night_from: int = 21 * 60  # minute of the local day
    night_to: int = 7 * 60
    sleep_eyes: str = "dim"
    alarm: bool = True


def _time_text(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_time(value: object, default: int) -> int:
    match = _TIME_RE.match(value) if isinstance(value, str) else None
    return int(match.group(1)) * 60 + int(match.group(2)) if match else default


def _parse_level(value: object, bounds: tuple[float, float], default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value) if bounds[0] <= value <= bounds[1] else default


def parse_settings(values: Mapping[str, object]) -> IndicatorSettings:
    """Settings from the stored key values; a missing, malformed or out of range
    value is the default, never an error."""
    d = IndicatorSettings()
    enabled = values.get(KEY_ENABLED, d.enabled)
    alarm = values.get(KEY_ALARM, d.alarm)
    sleep = values.get(KEY_SLEEP_EYES, d.sleep_eyes)
    return IndicatorSettings(
        enabled=enabled if isinstance(enabled, bool) else d.enabled,
        brightness=_parse_level(values.get(KEY_BRIGHTNESS), looks.DAY_LEVEL_RANGE, d.brightness),
        night_brightness=_parse_level(
            values.get(KEY_NIGHT_BRIGHTNESS), looks.NIGHT_LEVEL_RANGE, d.night_brightness
        ),
        night_from=_parse_time(values.get(KEY_NIGHT_FROM), d.night_from),
        night_to=_parse_time(values.get(KEY_NIGHT_TO), d.night_to),
        sleep_eyes=sleep if sleep in SLEEP_EYES_OPTIONS else d.sleep_eyes,
        alarm=alarm if isinstance(alarm, bool) else d.alarm,
    )


def _spec(key: str, type_: str, default: Any, label: str, range_: Any = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"key": key, "type": type_, "default": default}
    if range_ is not None:
        entry["range"] = range_
    entry.update(scope="device", label=label, lives_in=_LIVES_IN, honoured_by=["bot"])
    return entry


def _specs() -> list[dict[str, Any]]:
    d = IndicatorSettings()
    return [
        _spec(KEY_ENABLED, "boolean", d.enabled, "Show what I am doing with my eyes"),
        _spec(
            KEY_BRIGHTNESS,
            "number",
            d.brightness,
            "Eye brightness by day",
            list(looks.DAY_LEVEL_RANGE),
        ),
        _spec(
            KEY_NIGHT_BRIGHTNESS,
            "number",
            d.night_brightness,
            "Eye brightness at night",
            list(looks.NIGHT_LEVEL_RANGE),
        ),
        _spec(KEY_NIGHT_FROM, "time", _time_text(d.night_from), "Night starts at"),
        _spec(KEY_NIGHT_TO, "time", _time_text(d.night_to), "Night ends at"),
        _spec(
            KEY_SLEEP_EYES,
            "select",
            d.sleep_eyes,
            "My eyes at night when idle",
            list(SLEEP_EYES_OPTIONS),
        ),
        _spec(KEY_ALARM, "boolean", d.alarm, "Blink amber when I tip or fall"),
    ]


INDICATOR_KEYS: tuple[str, ...] = tuple(spec["key"] for spec in _specs())


def eyes_settings_declaration(needs: str) -> list[dict[str, Any]]:
    """The seven declarations for a body whose capability id is ``needs``."""
    return [{**spec, "needs": [needs]} for spec in _specs()]
