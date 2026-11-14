"""The no-NVS flash script never writes the NVS partition and skips an unchanged bootloader."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "stackchan_flash_nonvs",
    Path(__file__).resolve().parents[1] / "scripts/stackchan_flash_nonvs.py",
)
flash = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flash)


def make_image(tmp_path: Path) -> Path:
    image = tmp_path / "image"
    image.mkdir(parents=True)
    for name, _offset in flash.PARTS:
        (image / name).write_bytes(name.encode() * 10)
    return image


def test_nothing_overlaps_the_nvs_partition(tmp_path):
    parts = flash.parts_to_write(make_image(tmp_path), None)
    assert [off for off, _ in parts] == [0x0, 0x8000, 0xD000, 0x20000, 0xA00000]
    for off, path in parts:
        assert off + path.stat().st_size <= flash.NVS_START or off >= flash.NVS_END


def test_an_unchanged_bootloader_and_partition_table_are_not_rewritten(tmp_path):
    image = make_image(tmp_path)
    backup = bytearray(b"\xff" * flash.FLASH_SIZE)
    for name, offset in flash.PARTS[:2]:
        data = (image / name).read_bytes()
        backup[offset : offset + len(data)] = data
    parts = flash.parts_to_write(image, bytes(backup))
    assert [off for off, _ in parts] == [0xD000, 0x20000, 0xA00000]


def test_a_changed_bootloader_is_written_and_the_command_never_names_nvs(tmp_path):
    image = make_image(tmp_path)
    parts = flash.parts_to_write(image, b"\xff" * flash.FLASH_SIZE)
    command = flash.write_command("/dev/cu.usbmodem1", parts)
    assert "0x9000" not in command
    assert command.count("write_flash") == 1
    assert "0x0" in command


def test_a_missing_part_or_an_overlap_is_refused(tmp_path):
    image = make_image(tmp_path)
    (image / "maipai-stackchan.bin").unlink()
    with pytest.raises(flash.FlashPlanError):
        flash.parts_to_write(image, None)
    big = make_image(tmp_path / "second")
    (big / "partition-table.bin").write_bytes(
        b"x" * 0x2000
    )  # 0x8000 + 0x2000 runs into NVS at 0x9000
    with pytest.raises(flash.FlashPlanError):
        flash.parts_to_write(big, None)
