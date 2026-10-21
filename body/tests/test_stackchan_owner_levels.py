import json
import logging

from maipai_body.bodies.stackchan.owner_levels import OwnerLevels


def test_defaults_and_round_trip(tmp_path):
    path = tmp_path / "owner_levels.json"
    levels = OwnerLevels(path)
    levels.load()
    assert (levels.volume, levels.brightness) == (70, 100)
    levels.set_volume(42)
    levels.set_brightness(73)
    restored = OwnerLevels(path)
    restored.load()
    assert (restored.volume, restored.brightness) == (42, 73)
    assert json.loads(path.read_text()) == {"volume": 42, "brightness": 73}


def test_missing_or_corrupt_file_uses_defaults(tmp_path):
    path = tmp_path / "owner_levels.json"
    levels = OwnerLevels(path)
    levels.load()
    assert (levels.volume, levels.brightness) == (70, 100)
    path.write_text("not json")
    levels.load()
    assert (levels.volume, levels.brightness) == (70, 100)


def test_unwritable_path_warns_once_and_does_not_raise(tmp_path, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file")
    path = blocker / "owner_levels.json"
    levels = OwnerLevels(path)
    with caplog.at_level(logging.WARNING):
        levels.set_volume(40)
    assert len(caplog.records) == 1
    assert str(path) in caplog.text
    assert "permission" in caplog.text.lower() or "writable" in caplog.text.lower()


def test_setters_clamp_and_save_only_on_change(tmp_path, monkeypatch):
    path = tmp_path / "owner_levels.json"
    levels = OwnerLevels(path)
    saves = []
    original = levels.save
    monkeypatch.setattr(levels, "save", lambda: (saves.append(1), original())[1])
    levels.set_volume(-5)
    levels.set_volume(-1)
    levels.set_brightness(80)
    levels.set_brightness(120)
    levels.set_brightness(101)
    assert (levels.volume, levels.brightness) == (0, 100)
    assert len(saves) == 3
