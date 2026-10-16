import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "maipai_body" / "bodies" / "stackchan"
SCRIPT = ROOT / "scripts" / "stackchan_face_set.py"


def test_fixture_source_regenerates_checked_in_face_set_byte_for_byte(tmp_path):
    source = tmp_path / "avatar"
    source.mkdir()
    (source / "avatar.cpp").write_text(
        "enum class Expression { Neutral, Happy, Sad };\n"
        'const char* names[] = {"neutral", "happy", "sad"};\n'
    )
    output = tmp_path / "faces.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--commit", "abc123", "--output", str(output)],
        check=True,
    )
    data = json.loads(output.read_text())
    assert data["source_file"] == "avatar.cpp"
    assert data["upstream_commit"] == "abc123"
    assert data["faces"] == ["happy", "neutral", "sad"]
    expected = (
        b'{\n  "source_file": "avatar.cpp",\n  "upstream_commit": "abc123",\n'
        b'  "faces": [\n    "happy",\n    "neutral",\n    "sad"\n  ]\n}\n'
    )
    assert output.read_bytes() == expected


def test_checked_in_map_faces_exist_in_face_set():
    faces = set(json.loads((PACKAGE / "face_set.json").read_text())["faces"])
    import maipai_body.bodies.stackchan.expression_map as expression_map

    used = {frame.expression for frame in expression_map.CUE_FACE_MAP.values()}
    used |= set(expression_map.REPLY_MOOD_FACE_MAP.values())
    used |= {action.face for action in expression_map.PRIMITIVE_BODY_MAP.values()}
    assert used <= faces


def test_upstream_emotion_enum_has_no_joy_face():
    faces = set(json.loads((PACKAGE / "face_set.json").read_text())["faces"])
    assert faces == {"neutral", "happy", "angry", "sad", "doubt", "sleepy"}
    from maipai_body.bodies.stackchan.avatar_frames import encode_face

    with pytest.raises(ValueError, match="unsupported StackChan face: joy"):
        encode_face("joy")


def test_firmware_patch_series_has_valid_hunk_counts():
    patches = PACKAGE / "firmware" / "patches"
    for patch in sorted(patches.glob("*.patch")):
        result = subprocess.run(
            ["git", "apply", "--stat", str(patch)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{patch.name}: {result.stderr}"


def test_expression_map_names_missing_face_in_plain_import_error(tmp_path, monkeypatch):
    data = json.loads((PACKAGE / "face_set.json").read_text())
    data["faces"].remove("doubt")
    (tmp_path / "face_set.json").write_text(json.dumps(data))
    monkeypatch.setenv("MAIPAI_STACKCHAN_FACE_SET", str(tmp_path / "face_set.json"))
    sys.modules.pop("maipai_body.bodies.stackchan.expression_map", None)
    with pytest.raises(ValueError, match="unsupported StackChan face: doubt"):
        importlib.import_module("maipai_body.bodies.stackchan.expression_map")
    sys.modules.pop("maipai_body.bodies.stackchan.expression_map", None)
    monkeypatch.delenv("MAIPAI_STACKCHAN_FACE_SET", raising=False)
