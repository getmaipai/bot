"""The face touch classifier (firmware patch 105) is plain C: compile and run its test on the host.
Also checks that the mute patch series is wired into the recipe in order and carries its guards."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent / "maipai_body/bodies/stackchan/firmware"
PATCHES = FIRMWARE / "patches"
TOUCH_PATCH = PATCHES / "105-face-touch-toggles.patch"
C_TEST = HERE / "firmware" / "touch_core_test.c"
SERIES = [
    "105-face-touch-toggles.patch",
    "106-privacy-core.patch",
    "107-mic-guards.patch",
    "108-mint-muted-and-lidded.patch",
]


def _added_file(patch: Path, path: str) -> str:
    text = patch.read_text()
    block = text.split(f"+++ b/{path}\n", 1)[1]
    body = block.split("\n", 1)[1]  # drop the @@ line
    lines = []
    for line in body.splitlines():
        if line.startswith("diff --git"):
            break
        if line.startswith("+"):
            lines.append(line[1:])
    return "\n".join(lines) + "\n"


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler on this machine")
def test_touch_core_c_tests_pass(tmp_path):
    (tmp_path / "maipai_touch_core.h").write_text(
        _added_file(TOUCH_PATCH, "firmware/main/hal/maipai_touch_core.h")
    )
    binary = tmp_path / "touch_test"
    build = subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{tmp_path}",
            str(C_TEST),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all passed" in run.stdout


def test_the_series_is_wired_into_the_recipe_in_order():
    recipe = (FIRMWARE / "recipe.sh").read_text()
    order = [
        m.group(1)
        for m in re.finditer(r"^apply_repo_patch (10[5-9]-[\w-]+\.patch) ", recipe, re.MULTILINE)
    ]
    assert order == SERIES
    for name in SERIES:
        text = (PATCHES / name).read_text()
        assert text.startswith("# Intent: ") and "\n# Upstream: " in text
        assert "\n# Check after a flash: " in text
        assert chr(0x2014) not in text.split("\ndiff --git", 1)[0]  # no em dash in the prose header


def test_the_xiaozhi_guards_target_the_xiaozhi_repo():
    recipe = (FIRMWARE / "recipe.sh").read_text()
    assert 'apply_repo_patch 107-mic-guards.patch "$FW/xiaozhi-esp32"' in recipe
    assert 'apply_repo_patch 106-privacy-core.patch "$SRC"' in recipe


def _added(name: str) -> str:
    return "\n".join(
        line[1:] for line in (PATCHES / name).read_text().splitlines() if line.startswith("+")
    )


def test_the_microphone_guard_sits_inside_the_codec_class_and_below_the_audio_task():
    codec = _added("106-privacy-core.patch")
    # EnableInput(true) refuses, Read hands back silence, and nothing but the guard reopens it.
    assert "if (enable && maipai_mic_blocked())" in codec
    assert "if (maipai_mic_blocked()) {\n        // Never touch the device while muted" in codec
    assert "bool CoreS3AudioCodec::MaipaiMicOff" in codec
    # The chip is powered down in the constructor when the saved state says muted.
    assert "if (maipai_mic_blocked()) {\n        // The unit boots muted" in codec
    # The ES7210 power registers are read back and a mismatch is not "verified".
    for register in ("0x47", "0x4C", "0x06"):
        assert register in codec
    assert "mic_off_verified" in codec


def test_every_way_into_listening_is_guarded():
    xiaozhi = _added("107-mic-guards.patch")
    for needle in (
        "if (maipai_mic_blocked()) {\n        // Muted or in full quiet (patch 107): nothing",
        'if (enable && maipai_mic_blocked()) {\n        ESP_LOGW(TAG, "wake word stays off',
        'if (enable && maipai_mic_blocked()) {\n        ESP_LOGW(TAG, "voice processing stays off',
        "if (armed && maipai_mic_blocked())",
        "listening refused: muted or in full quiet",
        "if (!protocol_ || maipai_mic_blocked())",
    ):
        assert needle in xiaozhi, needle
    # The refusal sits at the top of SetListeningMode, the one way into the listening state.
    assert (
        "void Application::SetListeningMode(ListeningMode mode) {\n+    if (maipai_mic_blocked())"
        in (PATCHES / "107-mic-guards.patch").read_text().replace("\n \n", "\n")
    )


def test_full_quiet_silences_the_speaker_and_the_servos_and_vision_off_the_camera():
    core = _added("106-privacy-core.patch")
    assert "if (maipai_quiet()) {\n        return samples;  // full quiet" in core
    assert (
        "if (maipai_quiet()) {\n        return;  // full quiet (patch 106): the head holds" in core
    )
    assert "stop_motion_at_angle(getCurrentAngle())" in core
    assert (
        core.count("if (maipai_vision_off())") >= 3
    )  # Capture, StreamCaptures and the avatar loop
    assert "vision_skipped" in core


def test_the_toggle_places_never_start_a_listen_and_a_hold_acts_while_the_finger_is_down():
    display = _added("105-face-touch-toggles.patch")
    assert "if (!mtc_region_listens(s_last_region))" in display
    assert "case LV_EVENT_PRESSING:" in display and "mtc_action_while_down" in display
    assert "case LV_EVENT_RELEASED:" in display and "mtc_action_on_release" in display
    # The toggle makes no sound: nothing in the series plays a tone.
    assert "PlaySound" not in display and "PlaySound" not in _added("106-privacy-core.patch")


def test_the_series_uses_its_own_nvs_namespace_and_never_the_websocket_one():
    core = _added("106-privacy-core.patch")
    assert 'kNamespace = "maipai_priv"' in core
    assert '"websocket"' not in core
