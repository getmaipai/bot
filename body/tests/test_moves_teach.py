"""MOVES-02: teach it a move by hand, record it, name it, replay it.

The hand is simulated here by a list of state frames; nothing in this file
has touched a physical unit (see ``test_moves_teach_unit.py`` for that).
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
from maipai_body.hal.errors import OutOfEnvelope
from maipai_body.hal.seam import AntennaPositions, HeadPose, StateFrame, Teachable
from maipai_body.moves.player import MovePlayer, MoveRefused
from maipai_body.moves.recorded_move import RecordedMove, pose_to_matrix
from maipai_body.moves.recorder import MoveRecorder, TooShort
from maipai_body.moves.service import MovesService
from maipai_body.moves.store import BadMoveName, MoveStore
from maipai_body.moves.teach import TeachSession
from maipai_body.presence.arbitration import ArbitrationState

_OPEN = ArbitrationState(expression_active=True)
MOVES_DIR = Path(__file__).parent.parent / "maipai_body" / "moves"
NS = 1_000_000_000


def _frames(count: int = 11, dt_s: float = 0.1, yaw_deg: float = 20.0, t0_ns: int = 7 * NS):
    """What a hand sweeping the head yaw and an antenna looks like on the state feed."""
    out = []
    for i in range(count):
        frac = i / (count - 1)
        out.append(
            StateFrame(
                t_received_ns=t0_ns + int(i * dt_s * NS),
                seq=i,
                head_pose=HeadPose(yaw=math.radians(yaw_deg) * frac, pitch=math.radians(4) * frac),
                antennas=AntennaPositions(left=0.3 * frac, right=-0.3 * frac),
                body_yaw=0.0,
            )
        )
    return out


class _Feed:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False

    def __iter__(self):
        return iter(self._frames)

    def close(self):
        self.closed = True


class _TeachBody(FakeReachyMiniClient):
    """The fake with a scripted hand on the state feed."""

    def __init__(self, frames):
        super().__init__(REACHY_MINI_PROFILE)
        self.hand_frames = frames
        self.feed = None

    def state_feed(self, frequency: float = 10.0):
        self.feed = _Feed(self.hand_frames)
        self.requested_frequency = frequency
        return self.feed


# -- the seam --


def test_the_fake_and_the_vendor_client_both_satisfy_the_teachable_seam():
    from maipai_body.bodies.reachy_mini.client import ReachyMiniClient

    assert isinstance(FakeReachyMiniClient(REACHY_MINI_PROFILE), Teachable)
    for name in ("enable_gravity_compensation", "disable_gravity_compensation"):
        assert callable(getattr(ReachyMiniClient, name))


def test_gravity_compensation_is_recorded_by_the_fake_and_refused_after_loss():
    from maipai_body.hal.errors import BodyLost

    body = FakeReachyMiniClient(REACHY_MINI_PROFILE)
    body.enable_gravity_compensation()
    assert body.gravity_compensation is True
    body.disable_gravity_compensation()
    assert body.gravity_compensation is False
    body.simulate_disconnect()
    with pytest.raises(BodyLost):
        body.enable_gravity_compensation()


# -- the format, written --


def test_pose_to_matrix_matches_the_clients_matrix():
    pose = HeadPose(x=0.01, y=-0.02, z=0.03, roll=0.1, pitch=-0.2, yaw=0.3)
    assert np.allclose(pose_to_matrix(pose), _pose_to_matrix(pose), atol=1e-12)


def test_a_recording_is_the_vendor_shape_and_reads_back_as_a_move():
    recorder = MoveRecorder()
    for frame in _frames():
        recorder.add(frame)
    data = recorder.to_json("a wave of the head")
    assert set(data) == {"description", "time", "set_target_data"}
    assert data["description"] == "a wave of the head"
    assert data["time"][0] == 0.0  # rebased to the first frame, not the monotonic clock
    assert data["time"][-1] == pytest.approx(1.0)
    assert set(data["set_target_data"][0]) == {"head", "antennas", "body_yaw"}
    move = RecordedMove.from_json("wave", json.loads(json.dumps(data)))
    assert move.sample(1.0).pose.yaw == pytest.approx(math.radians(20.0), abs=1e-6)
    assert move.sample(1.0).antennas.left == pytest.approx(0.3)


def test_frames_with_no_pose_are_skipped_and_a_stalled_clock_never_repeats_a_time():
    recorder = MoveRecorder()
    frames = _frames(count=4)
    recorder.add(frames[0].model_copy(update={"head_pose": None}))  # a doa-only frame
    for frame in frames:
        recorder.add(frame)
        recorder.add(frame)  # the same instant twice
    data = recorder.to_json("x")
    assert len(data["time"]) == 4
    assert all(b > a for a, b in zip(data["time"], data["time"][1:], strict=False))


def test_a_recording_with_fewer_than_two_poses_is_refused():
    recorder = MoveRecorder()
    recorder.add(_frames(count=2)[0])
    with pytest.raises(TooShort):
        recorder.to_json("x")


def test_a_recording_outside_the_envelope_is_refused_not_clipped():
    recorder = MoveRecorder()
    for frame in _frames(yaw_deg=170.0):  # a hand forcing the head past its yaw limit
        recorder.add(frame)
    with pytest.raises(OutOfEnvelope):
        recorder.to_json("x")


# -- the store --


def test_a_saved_move_round_trips_through_the_store_and_lists_by_name(tmp_path):
    recorder = MoveRecorder()
    for frame in _frames():
        recorder.add(frame)
    store = MoveStore(tmp_path)
    store.save("wave", recorder.to_json("my wave"))
    assert store.names() == ["wave"]
    assert json.loads((tmp_path / "wave.json").read_text())["description"] == "my wave"
    assert store.load("wave").duration_s == pytest.approx(1.0)


@pytest.mark.parametrize(
    "bad", ["", "../escape", "a/b", "Wave Hello", "x" * 41, ".hidden", "wave.json"]
)
def test_a_name_that_is_not_a_plain_slug_is_refused(tmp_path, bad):
    with pytest.raises(BadMoveName):
        MoveStore(tmp_path).save(bad, {"time": [], "set_target_data": []})
    assert list(tmp_path.iterdir()) == []


def test_a_name_in_the_pinned_library_is_refused_so_a_taught_move_never_shadows_one(tmp_path):
    store = MoveStore(tmp_path, reserved={"happy1"})
    with pytest.raises(BadMoveName, match="library"):
        store.save("happy1", {})


def test_saving_over_a_taught_move_needs_an_explicit_replace(tmp_path):
    recorder = MoveRecorder()
    for frame in _frames():
        recorder.add(frame)
    data = recorder.to_json("x")
    store = MoveStore(tmp_path)
    store.save("wave", data)
    with pytest.raises(BadMoveName, match="exists"):
        store.save("wave", data)
    store.save("wave", data, replace=True)


def test_a_malformed_move_is_never_written(tmp_path):
    from maipai_body.moves.recorded_move import InvalidMove

    with pytest.raises(InvalidMove):
        MoveStore(tmp_path).save("wave", {"time": [0.0], "set_target_data": []})
    assert list(tmp_path.iterdir()) == []


def test_a_taught_move_can_be_forgotten(tmp_path):
    recorder = MoveRecorder()
    for frame in _frames():
        recorder.add(frame)
    store = MoveStore(tmp_path)
    store.save("wave", recorder.to_json("x"))
    store.delete("wave")
    assert store.names() == []


# -- the teach session --


def _teach(body, store, *, name="wave", arbitration=_OPEN, muted=False, **kwargs):
    return TeachSession(body, store, **kwargs).teach(name, arbitration, muted=muted)


def test_teaching_turns_gravity_compensation_on_records_then_hands_the_head_back(tmp_path):
    body = _TeachBody(_frames())
    store = MoveStore(tmp_path)
    move = _teach(body, store)
    kinds = [c.kind for c in body.sent_commands]
    assert kinds == ["gravity_on", "gravity_off", "hold"]  # on, then off, then hold the pose
    assert body.gravity_compensation is False
    assert body.feed.closed
    assert move.duration_s == pytest.approx(1.0)
    assert store.names() == ["wave"]


def test_gravity_compensation_is_turned_off_even_when_recording_fails(tmp_path):
    body = _TeachBody(_frames(yaw_deg=170.0))  # out of envelope: saving refuses
    with pytest.raises(OutOfEnvelope):
        _teach(body, MoveStore(tmp_path))
    assert body.gravity_compensation is False
    assert [c.kind for c in body.sent_commands][-1] == "hold"
    assert list(tmp_path.iterdir()) == []


def test_a_muted_body_or_a_higher_priority_owner_refuses_teaching_before_any_motion(tmp_path):
    body = _TeachBody(_frames())
    with pytest.raises(MoveRefused):
        _teach(body, MoveStore(tmp_path), muted=True)
    with pytest.raises(MoveRefused):
        _teach(body, MoveStore(tmp_path), arbitration=ArbitrationState(service_active=True))
    assert body.sent_commands == []


def test_a_stop_ends_the_recording_and_keeps_what_was_taught_so_far(tmp_path):
    body = _TeachBody(_frames(count=50))
    session = TeachSession(body, MoveStore(tmp_path))
    seen = []

    def stop_after_ten(frame):
        seen.append(frame)
        if len(seen) == 10:
            session.stop()

    move = session.teach("wave", _OPEN, on_frame=stop_after_ten)
    assert len(move.times) == 10
    assert body.gravity_compensation is False


def test_the_recording_is_capped_so_a_forgotten_session_ends(tmp_path):
    body = _TeachBody(_frames(count=500, dt_s=0.1))  # 50 s of feed
    move = _teach(body, MoveStore(tmp_path), max_duration_s=5.0)
    assert 4.9 <= move.duration_s <= 5.1


def test_the_session_reads_the_feed_at_the_recording_rate(tmp_path):
    body = _TeachBody(_frames())
    _teach(body, MoveStore(tmp_path))
    assert body.requested_frequency == 50.0  # the rate the player streams back at


# -- replay --


def test_a_taught_move_replays_through_the_player_within_the_envelope(body_client, tmp_path):
    from tests.test_moves import _Clock

    recorder = MoveRecorder()
    for frame in _frames(yaw_deg=25.0):
        recorder.add(frame)
    store = MoveStore(tmp_path)
    store.save("wave", recorder.to_json("my wave"))
    clock = _Clock()
    MovePlayer(body_client, REACHY_MINI_PROFILE, sleep=clock.sleep, monotonic=clock.monotonic).play(
        store.load("wave"), _OPEN
    )
    sent = getattr(body_client, "sent_commands", None)
    if (
        sent is not None
    ):  # the fake records; on the simulator the daemon accepting the stream is the check
        streamed = [c for c in sent if c.kind == "set_target"]
        assert streamed[-1].pose.yaw == pytest.approx(math.radians(25.0), abs=1e-6)
        assert all(abs(c.pose.yaw) <= math.radians(25.0) + 1e-6 for c in streamed)


def test_do_my_wave_plays_the_taught_move_by_name(tmp_path):
    from tests.test_moves import _Clock

    body = FakeReachyMiniClient(REACHY_MINI_PROFILE)
    recorder = MoveRecorder()
    for frame in _frames():
        recorder.add(frame)
    store = MoveStore(tmp_path)
    store.save("wave", recorder.to_json("x"))
    clock = _Clock()
    service = MovesService(
        MovePlayer(body, REACHY_MINI_PROFILE, sleep=clock.sleep, monotonic=clock.monotonic),
        store.load,
        store.names(),
    )
    assert service.ask("please do my wave", _OPEN) == "wave"


# -- the promises --


def test_the_teach_modules_make_no_connection_and_use_no_model():
    banned = {"requests", "urllib", "urllib3", "http", "socket", "httpx", "websockets", "aiohttp"}
    for name in ("recorder.py", "store.py", "teach.py"):
        tree = ast.parse((MOVES_DIR / name).read_text())
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                assert module.split(".")[0] not in banned, f"{name} imports {module}"


def test_nothing_in_the_expression_package_reaches_the_teach_modules():
    expression = Path(__file__).parent.parent / "maipai_body" / "expression"
    for path in expression.glob("*.py"):
        text = path.read_text()
        for word in ("moves.teach", "moves.recorder", "moves.store"):
            assert word not in text
