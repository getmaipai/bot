"""Flash a built StackChan image over USB WITHOUT touching NVS (the saved pairing and Wi-Fi stay).

Steps: (1) back up the whole 16 MB flash, (2) compare the image's bootloader and partition table
with the backup and write them only when their bytes differ, (3) write the app (0x20000), the OTA
data (0xd000) and the assets (0xa00000). Nothing here ever writes 0x9000 to 0xd000 (the NVS
partition). `--dry-run` prints the commands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

FLASH_SIZE = 0x1000000
NVS_START = 0x9000
NVS_END = 0xD000  # the NVS partition is 0x9000..0xd000 (16 KB); the OTA data starts right after it
PARTS = (
    ("bootloader.bin", 0x0),
    ("partition-table.bin", 0x8000),
    ("ota_data_initial.bin", 0xD000),
    ("maipai-stackchan.bin", 0x20000),
    ("generated_assets.bin", 0xA00000),
)
IDF_PYTHON = Path.home() / ".espressif/python_env/idf5.5_py3.12_env/bin/python"


class FlashPlanError(ValueError):
    """The plan would touch NVS or the image is incomplete."""


def parts_to_write(image: Path, backup: bytes | None) -> list[tuple[int, Path]]:
    """The (offset, file) pairs to write.

    The bootloader and the partition table are written only when they differ from the backup."""
    out: list[tuple[int, Path]] = []
    for name, offset in PARTS:
        path = image / name
        if not path.is_file():
            raise FlashPlanError(f"{path} is missing: the image is incomplete")
        data = path.read_bytes()
        if offset + len(data) > FLASH_SIZE:
            raise FlashPlanError(f"{name} does not fit in the 16 MB flash")
        if offset < NVS_END and offset + len(data) > NVS_START:
            raise FlashPlanError(f"{name} at {hex(offset)} would overlap the NVS partition")
        if name in ("bootloader.bin", "partition-table.bin") and backup is not None:
            if backup[offset : offset + len(data)] == data:
                continue
        out.append((offset, path))
    return out


def write_command(port: str, parts: list[tuple[int, Path]]) -> list[str]:
    command = [
        str(IDF_PYTHON), "-m", "esptool", "--chip", "esp32s3", "-p", port, "-b", "921600",
        "--before", "default_reset", "--after", "hard_reset", "write_flash",
        "--flash_mode", "dio", "--flash_freq", "80m", "--flash_size", "16MB",
    ]  # fmt: skip
    for offset, path in parts:
        command += [hex(offset), str(path)]
    return command


def backup_command(port: str, backup: Path) -> list[str]:
    return [
        str(IDF_PYTHON), "-m", "esptool", "--chip", "esp32s3", "-p", port, "-b", "921600",
        "read_flash", "0x0", hex(FLASH_SIZE), str(backup),
    ]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument(
        "--image", required=True, type=Path, help="the image folder (five .bin files)"
    )
    parser.add_argument(
        "--backup", required=True, type=Path, help="where the full-flash backup goes"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.backup.exists() and args.backup.stat().st_size == FLASH_SIZE:
        print(f"using the existing backup {args.backup}")
        have_backup = True
    else:
        have_backup = False
    steps: list[list[str]] = []
    if not have_backup:
        steps.append(backup_command(args.port, args.backup))
    if args.dry_run and not have_backup:
        parts = parts_to_write(args.image, None)
    else:
        if not have_backup:
            for step in steps:
                print("+", " ".join(step))
                subprocess.run(step, check=True)
            steps = []
        if args.backup.stat().st_size != FLASH_SIZE:
            raise FlashPlanError("the backup is not 16 MB: stop, do not flash")
        parts = parts_to_write(args.image, args.backup.read_bytes())
    steps.append(write_command(args.port, parts))
    for step in steps:
        print("+", " ".join(step))
        if not args.dry_run:
            subprocess.run(step, check=True)
    assert all(not (NVS_START <= off < NVS_END) for off, _ in parts)
    print(
        "DONE: the image is written; NVS (the saved pairing and Wi-Fi) was not touched."
        if not args.dry_run
        else "DRY RUN: nothing written."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
