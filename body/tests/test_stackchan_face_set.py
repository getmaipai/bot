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
    used |= {action.face for action in expression_map.PRIMITIVE_BODY_MAP.values() if action.face}
    assert used <= faces | {
        "joy",
        "content",
        "excited",
        "shocked",
        "curious",
        "love",
        "worried",
        "dizzy",
        "silly",
    }


def test_logical_vocabulary_falls_back_until_new_firmware_and_rejects_unknown():
    from maipai_body.bodies.stackchan.face_vocabulary import (
        FACE_VOCABULARY,
        resolve_face,
    )

    assert len(FACE_VOCABULARY) == 19  # the 18 logical faces and the sleeping face
    assert resolve_face("joy", "0.2.86") == "happy"
    assert resolve_face("curious", "0.2.86") == "doubt"
    assert resolve_face("neutral", "0.2.86") == "neutral"
    assert resolve_face("not-a-face", "0.2.86") == "neutral"


def test_upstream_emotion_enum_has_no_joy_face():
    faces = set(json.loads((PACKAGE / "face_set.json").read_text())["faces"])
    assert faces == {
        "neutral",
        "happy",
        "angry",
        "sad",
        "doubt",
        "sleepy",
        "surprised",
        "wink",
        "listening",
        "thinking",
    }
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
    data["faces"].remove("happy")
    (tmp_path / "face_set.json").write_text(json.dumps(data))
    monkeypatch.setenv("MAIPAI_STACKCHAN_FACE_SET", str(tmp_path / "face_set.json"))
    sys.modules.pop("maipai_body.bodies.stackchan.expression_map", None)
    with pytest.raises(ValueError, match="unsupported StackChan face: happy"):
        importlib.import_module("maipai_body.bodies.stackchan.expression_map")
    sys.modules.pop("maipai_body.bodies.stackchan.expression_map", None)
    monkeypatch.delenv("MAIPAI_STACKCHAN_FACE_SET", raising=False)


def test_new_faces_are_native_from_firmware_0_2_93_and_fall_back_before():
    from maipai_body.bodies.stackchan.avatar.server import EXPRESSIONS
    from maipai_body.bodies.stackchan.face_vocabulary import resolve_face
    from maipai_body.bodies.stackchan.xiaozhi.server import FIRMWARE_EMOTIONS

    for name in ("joy", "content", "excited", "shocked", "curious", "love", "worried"):
        assert resolve_face(name, "0.2.93") == name
        assert resolve_face(name, "0.2.92") != name
        assert name in EXPRESSIONS and name in FIRMWARE_EMOTIONS
    # dizzy and silly are not drawn by any firmware yet: they keep their fallbacks.
    assert resolve_face("dizzy", "0.2.93") == "doubt"
    assert resolve_face("silly", "0.2.93") == "wink"
    assert resolve_face("listening", "0.2.61") == "neutral"


def test_patch_132_is_in_the_recipe():
    recipe = (PACKAGE / "firmware" / "recipe.sh").read_text()
    assert 'apply_repo_patch 132-expressive-faces.patch "$SRC"' in recipe
    assert (PACKAGE / "firmware" / "patches" / "132-expressive-faces.patch").is_file()
