"""MOVES-01 (amended): both datasets, the clip index, the age allow-list, the envelope report."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from maipai_body.bodies.reachy_mini.client import _pose_to_matrix
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE
from maipai_body.hal.seam import HeadPose
from maipai_body.model_assets import AssetUnavailable
from maipai_body.moves.allowlist import CHILD_TEEN_EXCLUDED, allowed_names, is_allowed
from maipai_body.moves.library import LibraryPin, ensure_move, installed_names, load_pins
from maipai_body.moves.pinning import build_pin, parse_clip_index
from maipai_body.moves.player import MovePlayer, MoveRefused
from maipai_body.moves.recorded_move import RecordedMove
from maipai_body.moves.service import MovesService
from maipai_body.presence.arbitration import ArbitrationState

ROOT = Path(__file__).parent.parent
_OPEN = ArbitrationState(expression_active=True)


def _move(pitch_deg: float = 5.0) -> dict:
    samples = []
    for i in range(4):
        pose = HeadPose(pitch=math.radians(pitch_deg) * i / 3)
        samples.append(
            {"head": _pose_to_matrix(pose).tolist(), "antennas": [0.0, 0.0], "body_yaw": 0}
        )
    return {"description": "d", "time": [0.0, 0.1, 0.2, 0.3], "set_target_data": samples}


def _blob(data: dict) -> bytes:
    return json.dumps(data).encode()


REV = "d" * 40


def test_the_dances_library_pins_like_any_apache_library():
    pin = LibraryPin(
        library="dances",
        repo="o/r",
        revision=REV,
        license="Apache-2.0",
        files={"simple_nod": "a" * 64},
    )
    assert pin.library == "dances"


def test_the_shipped_pins_cover_both_libraries_with_a_clip_index():
    pins = {pin.library: pin for pin in load_pins()}
    assert set(pins) == {"emotions", "dances"}
    for pin in pins.values():
        assert pin.license == "Apache-2.0"
        assert pin.files, f"{pin.library} has no pinned clips"
        assert set(pin.clips) <= set(pin.files) | set(pin.excluded)
        assert not set(pin.files) & set(pin.excluded)


def test_the_clip_index_comes_from_metadata_jsonl():
    text = (
        '{"file_name": "amazed1.ogg", "title": "amazed1", "description": "Wow.", '
        '"motion_file": "amazed1.json"}\n'
        '{"file_name": "x.ogg", "title": "x", "description": "Other.", "motion_file": "x.json"}\n'
    )
    assert parse_clip_index(text) == {"amazed1": "Wow.", "x": "Other."}


def test_an_over_envelope_clip_is_excluded_not_clipped():
    blobs = {"calm1": _blob(_move(5.0)), "wild1": _blob(_move(80.0))}
    pin = build_pin("emotions", "o/r", REV, "Apache-2.0", blobs, "", REACHY_MINI_PROFILE)
    assert set(pin["files"]) == {"calm1"}
    assert "wild1" in pin["excluded"]
    assert "head_pitch" in pin["excluded"]["wild1"]
    assert pin["files"]["calm1"] == hashlib.sha256(blobs["calm1"]).hexdigest()


def test_a_malformed_clip_is_excluded_with_its_reason():
    pin = build_pin(
        "emotions", "o/r", REV, "Apache-2.0", {"bad1": b'{"time": []}'}, "", REACHY_MINI_PROFILE
    )
    assert pin["files"] == {} and "bad1" in pin["excluded"]


def test_an_excluded_clip_is_never_installed(tmp_path):
    pin = LibraryPin(
        library="emotions",
        repo="o/r",
        revision=REV,
        license="Apache-2.0",
        files={"calm1": "a" * 64},
        excluded={"wild1": "head_pitch outside the envelope"},
    )
    with pytest.raises(AssetUnavailable, match="envelope"):
        ensure_move(pin, "wild1", tmp_path)


@pytest.mark.parametrize("stem", sorted(CHILD_TEEN_EXCLUDED))
@pytest.mark.parametrize("band", ["child", "teen", "unknown"])
def test_restricted_bands_never_get_the_harsh_moves(stem, band):
    assert not is_allowed(f"{stem}1", band)
    assert is_allowed(f"{stem}1", "adult")


def test_the_exclusion_list_is_exactly_the_ruled_seven():
    assert CHILD_TEEN_EXCLUDED == {
        "rage",
        "furious",
        "dying",
        "contempt",
        "disgusted",
        "go_away",
        "reprimand",
    }


def test_allowed_names_per_band():
    names = ["happy1", "rage1", "go_away1", "reprimand3", "simple_nod"]
    assert allowed_names(names, "adult") == names
    assert allowed_names(names, "child") == ["happy1", "simple_nod"]
    assert allowed_names(names, "teen") == ["happy1", "simple_nod"]


def _service():
    client = FakeReachyMiniClient()
    player = MovePlayer(client, REACHY_MINI_PROFILE, sleep=lambda s: None)
    moves = {n: RecordedMove.from_json(n, _move()) for n in ("rage1", "happy1")}
    return MovesService(player, moves.__getitem__, sorted(moves)), client


def test_a_child_asking_for_rage_gets_nothing_and_the_body_stays_still():
    service, client = _service()
    assert service.ask("do the rage dance", _OPEN, band="child") is None
    assert client.sent_commands == []


def test_an_adult_can_ask_for_rage():
    service, _ = _service()
    assert service.ask("do the rage dance", _OPEN, band="adult") == "rage1"


def test_the_react_slot_obeys_the_allow_list():
    service, client = _service()
    with pytest.raises(MoveRefused):
        service.react("rage1", _OPEN, react_allowed=True, band="teen")
    assert client.sent_commands == []


def test_an_unstated_band_is_treated_as_restricted():
    service, _ = _service()
    assert service.ask("do the rage dance", _OPEN) is None


def test_with_no_pack_installed_there_is_no_clip_library(tmp_path):
    pin = load_pins()[0]
    assert installed_names(pin, tmp_path) == []
    assert installed_names(pin, tmp_path / "missing") == []


def test_the_base_robot_assets_carry_no_moves_entry():
    for path in ROOT.parents[0].rglob("robot-assets.json"):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        text = path.read_text().lower()
        assert "reachy-mini-emotions" not in text and "reachy-mini-dances" not in text


def test_the_notice_carries_the_licence_attribution_and_tag():
    notice = (ROOT.parent / "NOTICE").read_text()
    assert "Apache-2.0" in notice
    assert "Pollen Robotics" in notice
    assert "reachy_mini_community_moves" in notice


def test_the_moves_package_imports_no_network_library():
    import ast

    banned = {"requests", "httpx", "urllib", "urllib3", "aiohttp", "socket", "http"}
    for path in (ROOT / "maipai_body" / "moves").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            assert not banned & set(names), f"{path.name} imports {names}"


# -- MOVES-02: the spoken "teach you a move" trigger --


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("let me teach you a move called wave", "wave"),
        ("Teach you a new move named Big Hello", "big_hello"),
        ("I want to teach you a move, call it nod yes", "nod_yes"),
        ("learn a new move called shrug", "shrug"),
    ],
)
def test_a_teach_request_names_the_move(text, name):
    from maipai_body.moves.service import parse_teach_request

    assert parse_teach_request(text) == name


@pytest.mark.parametrize(
    "text",
    [
        "do the happy dance",
        "what is a move in chess",
        "teach me a move",
        "let me teach you a move",
    ],
)
def test_other_speech_is_not_a_teach_request(text):
    from maipai_body.moves.service import parse_teach_request

    assert parse_teach_request(text) is None
