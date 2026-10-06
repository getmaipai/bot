"""MOVES-01: the recorded moves package.

The move JSON shape is Pollen's (``{description, time, set_target_data}``);
the moves used here are synthetic, built in the test, never copies of
Pollen's library.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.client import _pose_to_matrix
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.expression.cue import Cue, Phase, map_cue_to_primitive
from maipai_body.expression.engine import ExpressionEngine
from maipai_body.expression.primitives import PRIMITIVE_NAMES
from maipai_body.expression.suppression import SuppressionContext
from maipai_body.hal.seam import HeadPose
from maipai_body.model_assets import AssetUnavailable, ChecksumMismatch
from maipai_body.moves.library import (
    EXCLUDED_LIBRARIES,
    LibraryPin,
    ensure_move,
    load_pins,
    move_url,
)
from maipai_body.moves.player import MovePlayer, MoveRefused
from maipai_body.moves.recorded_move import InvalidMove, RecordedMove, matrix_to_pose
from maipai_body.moves.service import MovesService, parse_move_request
from maipai_body.presence.arbitration import ArbitrationState

# Expression owns the head: nothing of higher priority is active.
_OPEN = ArbitrationState(expression_active=True)
EXPRESSION_DIR = Path(__file__).parent.parent / "maipai_body" / "expression"


def _matrix(pose: HeadPose) -> list[list[float]]:
    return _pose_to_matrix(pose).tolist()


def _move_json(samples: int = 5, dt: float = 0.1, yaw_deg: float = 10.0) -> dict:
    """A synthetic nod-and-sway move in the vendor shape."""
    data = []
    for i in range(samples):
        frac = i / (samples - 1)
        pose = HeadPose(yaw=math.radians(yaw_deg) * frac, pitch=math.radians(5.0) * frac)
        data.append({"head": _matrix(pose), "antennas": [0.2 * frac, -0.2 * frac], "body_yaw": 0.0})
    return {
        "description": "synthetic test move",
        "time": [round(i * dt, 6) for i in range(samples)],
        "set_target_data": data,
    }


class _Clock:
    """A fake clock so playback is deterministic and instant."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# -- the format --


def test_a_move_parses_from_the_vendor_json_shape():
    move = RecordedMove.from_json("happy1", _move_json())
    assert move.name == "happy1"
    assert move.duration_s == pytest.approx(0.4)
    assert move.description == "synthetic test move"


def test_matrix_to_pose_inverts_the_clients_pose_to_matrix():
    pose = HeadPose(x=0.01, y=-0.02, z=0.03, roll=0.1, pitch=-0.2, yaw=0.3)
    back = matrix_to_pose(np.array(_matrix(pose)))
    for field in ("x", "y", "z", "roll", "pitch", "yaw"):
        assert getattr(back, field) == pytest.approx(getattr(pose, field), abs=1e-9)


def test_sampling_interpolates_between_the_bracketing_samples():
    move = RecordedMove.from_json("m", _move_json(samples=3, dt=1.0, yaw_deg=20.0))
    mid = move.sample(0.5)
    assert mid.pose.yaw == pytest.approx(math.radians(20.0) * 0.25, abs=1e-6)
    assert mid.antennas.left == pytest.approx(0.05, abs=1e-9)


def test_sampling_clamps_to_the_ends():
    move = RecordedMove.from_json("m", _move_json())
    assert move.sample(-1.0).pose.yaw == pytest.approx(0.0, abs=1e-9)
    assert move.sample(99.0).pose.yaw == pytest.approx(math.radians(10.0), abs=1e-6)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("time"),
        lambda d: d.update(time=d["time"][:-1]),
        lambda d: d.update(time=[0.0]),
        lambda d: d.update(time=[0.0, 0.2, 0.1, 0.3, 0.4]),
        lambda d: d["set_target_data"][0].update(head=[[1, 0], [0, 1]]),
        lambda d: d["set_target_data"][0].update(antennas=[0.1]),
    ],
)
def test_a_malformed_move_is_refused(mutate):
    data = _move_json()
    mutate(data)
    with pytest.raises(InvalidMove):
        RecordedMove.from_json("bad", data)


# -- fetching: pinned, checksummed, never vendored --


def _pin(tmp_path: Path, payload: bytes, *, revision: str = "a" * 40) -> LibraryPin:
    import hashlib

    return LibraryPin(
        library="emotions",
        repo="pollen-robotics/reachy-mini-emotions-library",
        revision=revision,
        license="Apache-2.0",
        files={"happy1": hashlib.sha256(payload).hexdigest()},
    )


def test_the_move_url_is_pinned_to_the_revision():
    pin = LibraryPin(
        library="emotions",
        repo="o/r",
        revision="b" * 40,
        license="Apache-2.0",
        files={"happy1": "0" * 64},
    )
    assert (
        move_url(pin, "happy1")
        == f"https://huggingface.co/datasets/o/r/resolve/{'b' * 40}/happy1.json"
    )


def test_a_pin_without_a_full_revision_is_rejected():
    with pytest.raises(ValueError):
        LibraryPin(library="emotions", repo="o/r", revision="main", license="Apache-2.0", files={})


def test_ensure_move_downloads_verifies_and_caches(tmp_path, monkeypatch):
    payload = json.dumps(_move_json()).encode()
    pin = _pin(tmp_path, payload)
    calls: list[str] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield payload

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr("maipai_body.model_assets.requests.get", fake_get)
    path = ensure_move(pin, "happy1", tmp_path)
    assert path.read_bytes() == payload
    ensure_move(pin, "happy1", tmp_path)
    assert len(calls) == 1  # the second call is served from the cache


def test_a_checksum_mismatch_is_refused_and_leaves_nothing_behind(tmp_path, monkeypatch):
    payload = b'{"tampered": true}'
    pin = _pin(tmp_path, b"something else")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield payload

    monkeypatch.setattr("maipai_body.model_assets.requests.get", lambda *a, **k: _Response())
    with pytest.raises(ChecksumMismatch):
        ensure_move(pin, "happy1", tmp_path)
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.parametrize("bad_sum", ["", "abc123", "Z" * 64, "A" * 64])
def test_ensure_move_refuses_an_unpinned_checksum_before_any_request(
    tmp_path, monkeypatch, bad_sum
):
    pin = LibraryPin(
        library="emotions",
        repo="o/r",
        revision="a" * 40,
        license="Apache-2.0",
        files={"happy1": bad_sum},
    )
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        raise AssertionError("no request may be made for an unpinned file")

    monkeypatch.setattr("maipai_body.model_assets.requests.get", fake_get)
    with pytest.raises(AssetUnavailable):
        ensure_move(pin, "happy1", tmp_path)
    assert calls == []


def test_a_move_the_pin_does_not_list_is_unavailable(tmp_path):
    pin = _pin(tmp_path, b"x")
    with pytest.raises(AssetUnavailable):
        ensure_move(pin, "not_in_the_pin", tmp_path)


def test_the_dances_library_is_excluded_until_its_licence_is_stated():
    assert "dances" in EXCLUDED_LIBRARIES
    assert all(pin.library != "dances" for pin in load_pins())
    with pytest.raises(ValueError):
        LibraryPin(library="dances", repo="o/r", revision="c" * 40, license="", files={})


def test_the_shipped_pins_hold_only_apache_licensed_libraries():
    for pin in load_pins():
        assert pin.license == "Apache-2.0"


def test_no_library_content_is_vendored_in_the_repo():
    root = Path(__file__).parent.parent
    for path in (root / "maipai_body" / "moves").rglob("*.json"):
        data = json.loads(path.read_text())
        assert "set_target_data" not in data, f"{path} looks like a vendored move"


# -- playing --


def _service(tmp_path, client=None, clock=None):
    client = client or FakeReachyMiniClient()
    clock = clock or _Clock()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=clock.sleep, monotonic=clock.monotonic)
    moves = {"happy1": RecordedMove.from_json("happy1", _move_json())}
    return MovesService(player, lambda name: moves[name], sorted(moves)), client, clock


def test_playing_a_move_streams_its_samples_through_the_seam():
    client = FakeReachyMiniClient()
    clock = _Clock()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=clock.sleep, monotonic=clock.monotonic)
    player.play(RecordedMove.from_json("m", _move_json()), _OPEN)
    kinds = [c.kind for c in client.sent_commands]
    assert kinds[0] == "goto"  # ease to the first sample, no jump
    assert kinds.count("set_target") >= 5
    assert client.sent_commands[-1].kind == "set_target"
    last = client.sent_commands[-1]
    assert last.pose.yaw == pytest.approx(math.radians(10.0), abs=1e-6)
    assert clock.now >= 0.4  # paced at the recording's own timing


def test_a_move_outside_the_envelope_is_refused_before_any_motion():
    from maipai_body.hal.errors import OutOfEnvelope

    data = _move_json()
    data["set_target_data"][-1]["head"] = _matrix(HeadPose(pitch=math.radians(80.0)))
    client = FakeReachyMiniClient()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=lambda s: None)
    with pytest.raises(OutOfEnvelope):
        player.play(RecordedMove.from_json("wild", data), _OPEN)
    assert client.sent_commands == []


@pytest.mark.parametrize(
    "state",
    [
        ArbitrationState(stop_active=True, expression_active=True),
        ArbitrationState(service_active=True, expression_active=True),
        ArbitrationState(tracking_active=True, expression_active=True),
    ],
)
def test_a_higher_priority_owner_blocks_playback(state):
    client = FakeReachyMiniClient()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=lambda s: None)
    with pytest.raises(MoveRefused):
        player.play(RecordedMove.from_json("m", _move_json()), state)
    assert client.sent_commands == []


def test_a_muted_body_plays_nothing():
    client = FakeReachyMiniClient()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=lambda s: None)
    with pytest.raises(MoveRefused):
        player.play(RecordedMove.from_json("m", _move_json()), _OPEN, muted=True)
    assert client.sent_commands == []


def test_stop_ends_playback_with_a_hold():
    client = FakeReachyMiniClient()
    clock = _Clock()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=clock.sleep, monotonic=clock.monotonic)

    def sleep_then_stop(seconds: float) -> None:
        clock.sleep(seconds)
        player.stop()

    player = MovePlayer(
        client, REACHY_MINI_PROFILE, sleep=sleep_then_stop, monotonic=clock.monotonic
    )
    player.play(RecordedMove.from_json("m", _move_json(samples=50)), _OPEN)
    assert client.sent_commands[-1].kind == "hold"
    assert len([c for c in client.sent_commands if c.kind == "set_target"]) < 5


# -- asking --


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("do the happy dance", "happy1"),
        ("Play the happy move", "happy1"),
        ("show me happy", "happy1"),
        ("do the sad dance", None),
        ("I am so happy today", None),  # a mood is not an ask
        ("the happy robot is nice", None),
    ],
)
def test_parse_move_request(text, expected):
    assert parse_move_request(text, ["happy1", "curious2"]) == expected


def test_asking_for_a_move_plays_it(tmp_path):
    service, client, _ = _service(tmp_path)
    assert service.ask("do the happy dance", _OPEN) == "happy1"
    assert any(c.kind == "set_target" for c in client.sent_commands)


def test_asking_for_an_unknown_move_plays_nothing(tmp_path):
    service, client, _ = _service(tmp_path)
    assert service.ask("do the sad dance", _OPEN) is None
    assert client.sent_commands == []


def test_the_react_slot_plays_only_when_the_plan_allows_it(tmp_path):
    service, client, _ = _service(tmp_path)
    with pytest.raises(MoveRefused):
        service.react("happy1", _OPEN, react_allowed=False)
    assert client.sent_commands == []
    service.react("happy1", _OPEN, react_allowed=True)
    assert any(c.kind == "set_target" for c in client.sent_commands)


# -- never from a cue --


def test_no_cue_maps_to_a_move():
    for phase in Phase:
        for emotion in (None, "happy", "sad", "joy", "excited"):
            for intensity in (None, "high", "low"):
                cue = Cue(
                    phase=phase,
                    cue_seq=1,
                    primary_act="inform",
                    expressed_emotion=emotion,
                    emotion_intensity=intensity,
                )
                primitive = map_cue_to_primitive(cue)
                assert primitive is None or primitive in PRIMITIVE_NAMES


def test_no_move_plays_when_the_expression_engine_handles_every_cue():
    client = FakeReachyMiniClient()
    engine = ExpressionEngine(client, REACHY_MINI_PROFILE)
    for seq, phase in enumerate(Phase):
        cue = Cue(phase=phase, cue_seq=seq, expressed_emotion="happy", emotion_intensity="high")
        engine.handle(cue, SuppressionContext())
    assert all(c.kind == "set_target" for c in client.sent_commands)


def test_the_expression_package_never_imports_the_moves_package():
    for path in EXPRESSION_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any("moves" in n.split(".") for n in names), f"{path.name} imports moves"
