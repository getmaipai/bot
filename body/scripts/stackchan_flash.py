"""Back up, build, provision, and flash a pinned StackChan setup."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "maipai_body/bodies/stackchan/firmware"
RECIPE = FIRMWARE / "recipe.sh"
PINS = FIRMWARE / "pins.toml"
FLASH_SIZE = 0x1000000
NVS_OFFSET = 0x9000
BUILD_ROOT = Path(
    os.environ.get(
        "STACKCHAN_BUILD_ROOT",
        str(Path.home() / "esp/stackchan-build/stackchan-02-run/build"),
    )
)


def _run(command: list[str], *, dry_run: bool) -> None:
    shown = command.copy()
    if "--pairing-token" in shown:
        index = shown.index("--pairing-token") + 1
        if index < len(shown):
            shown[index] = "<private-token>"
    stage = "FLASH" if "flash" in " ".join(command).lower() else "STEP"
    print(stage + ": " + " ".join(shown))
    if not dry_run:
        subprocess.run(command, check=True)


def _idf_version() -> str:
    import tomllib

    with PINS.open("rb") as stream:
        return tomllib.load(stream)["toolchain"]["esp_idf"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="USB serial port for the StackChan")
    parser.add_argument(
        "--backup", required=True, type=Path, help="Private whole-flash backup path"
    )
    parser.add_argument(
        "--token-file", required=True, type=Path, help="Private approval token file"
    )
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--xiaozhi-url", required=True)
    parser.add_argument("--avatar-url", required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print steps without invoking tools or serial"
    )
    args = parser.parse_args(argv)

    try:
        export = shlex.quote(str(Path.home() / "esp/esp-idf/export.sh"))
        if args.dry_run and (not args.backup.is_file() or args.backup.stat().st_size != FLASH_SIZE):
            raise ValueError(
                "Dry run needs an existing complete 16 MiB flash backup file. Save one first."
            )
        if not args.token_file.is_file():
            raise ValueError("Approval token file is missing. Approve this device and retry.")
        if not args.dry_run:
            version = subprocess.check_output(
                ["bash", "-lc", f"source {export} >/dev/null && idf.py --version"],
                text=True,
            ).strip()
            expected = _idf_version()
            if expected not in version:
                raise ValueError(f"ESP-IDF {expected} is required. Found: {version}")
            if not args.backup.is_file():
                args.backup.parent.mkdir(parents=True, exist_ok=True)
                _run(
                    [
                        "esptool.py",
                        "--port",
                        args.port,
                        "read_flash",
                        "0x0",
                        hex(FLASH_SIZE),
                        str(args.backup),
                    ],
                    dry_run=False,
                )
            if not args.backup.is_file() or args.backup.stat().st_size != FLASH_SIZE:
                raise ValueError(
                    "Full-flash backup is missing or incomplete. No flash write was started."
                )
        else:
            print(f"CHECK: ESP-IDF {_idf_version()} (dry run, no serial access)")
            print(f"BACKUP: {args.backup} ({FLASH_SIZE} bytes present)")

        # Backup verification is complete before the first firmware or NVS write.
        token = args.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("Approval token file is empty. Approve the device again.")
        _run(
            [
                str(RECIPE),
                "--avatar-server-url",
                args.avatar_url,
                "--device-id",
                args.device_id,
                "--client-id",
                args.client_id,
                "--pairing-token",
                token,
            ],
            dry_run=args.dry_run,
        )
        output = BUILD_ROOT / "output"
        image = output / "stack-chan-maipai.bin"
        nvs_image = output / "stackchan-nvs.bin"
        provision = [
            sys.executable,
            "-m",
            "maipai_body.bodies.stackchan.xiaozhi.provision",
            "--url",
            args.xiaozhi_url,
            "--token-file",
            str(args.token_file),
            "--device-id",
            args.device_id,
            "--client-id",
            args.client_id,
            "--avatar-server-url",
            args.avatar_url,
            "--version",
            "1",
            "--output",
            str(nvs_image),
        ]
        _run(provision, dry_run=args.dry_run)
        flash_command = (
            f"source {export} >/dev/null && "
            f"idf.py -C {shlex.quote(str(BUILD_ROOT / 'StackChan/firmware'))} "
            f"-p {shlex.quote(args.port)} flash"
        )
        _run(
            [
                "bash",
                "-lc",
                flash_command,
            ],
            dry_run=args.dry_run,
        )
        _run(
            ["esptool.py", "--port", args.port, "write_flash", hex(NVS_OFFSET), str(nvs_image)],
            dry_run=args.dry_run,
        )
        print(f"DONE: backup saved at {args.backup}; firmware image: {image}; NVS: {nvs_image}")
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Setup stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
