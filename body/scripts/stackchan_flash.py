"""Back up, build, provision, and flash a pinned StackChan setup."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "maipai_body/bodies/stackchan/firmware"
RECIPE = FIRMWARE / "recipe.sh"
PINS = FIRMWARE / "pins.toml"
FLASH_SIZE = 0x1000000
NVS_OFFSET = 0x9000
# Bootloader, partition table and the first app slot.
FIRMWARE_OFFSETS = (0x0, 0x8000, 0x20000)
BUILD_ROOT = Path(
    os.environ.get(
        "STACKCHAN_BUILD_ROOT",
        str(Path.home() / "esp/stackchan-build/stackchan-02-run/build"),
    )
)


IDF_EXPORT = Path.home() / "esp/esp-idf/export.sh"
# ESP-IDF 5.5 refuses newer Pythons; recipe.sh uses the same Homebrew 3.12 first.
IDF_PYTHON_PATH = "/opt/homebrew/opt/python@3.12/libexec/bin"


def _idf_env() -> dict[str, str]:
    """Return the environment ESP-IDF's export.sh sets up, for every IDF tool call."""
    script = (
        f'export PATH={shlex.quote(IDF_PYTHON_PATH)}:"$PATH"; '
        f"source {shlex.quote(str(IDF_EXPORT))} >/dev/null 2>&1 && env -0"
    )
    # The Bot's own virtualenv (uv run) must not leak in: ESP-IDF then checks the
    # Bot's packages against its pins and export.sh fails while returning 0.
    base = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
    }
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        base["PATH"] = os.pathsep.join(
            p for p in base.get("PATH", "").split(os.pathsep) if not p.startswith(venv)
        )
    result = subprocess.run(["bash", "-c", script], capture_output=True, check=False, env=base)
    pairs = (item.split("=", 1) for item in result.stdout.decode().split("\0") if "=" in item)
    env = dict(pairs)
    if result.returncode or not env.get("IDF_PATH"):
        raise ValueError(
            f"ESP-IDF did not load from {IDF_EXPORT}. Install ESP-IDF {_idf_version()} "
            "with Python 3.12 and retry."
        )
    return env


def _run(command: list[str], *, dry_run: bool, env: dict[str, str] | None = None) -> None:
    shown = command.copy()
    if "--pairing-token" in shown:
        index = shown.index("--pairing-token") + 1
        if index < len(shown):
            shown[index] = "<private-token>"
    stage = "FLASH" if command[-1] == "flash" or "write_flash" in command else "STEP"
    print(stage + ": " + " ".join(shown))
    if not dry_run:
        result = subprocess.run(command, check=False, env=env)
        if result.returncode:
            # Never let CalledProcessError print the raw command: it holds the token.
            raise ValueError(
                f"This step failed with exit code {result.returncode}: {' '.join(shown)}. "
                "Read the output above, fix the cause and run setup again."
            )


def _write_flash_command(
    port: str, build_dir: Path, nvs_image: Path, *, dry_run: bool = False
) -> list[str]:
    """One esptool write of the built images plus the NVS image.

    idf.py flash would reconfigure the project, and recipe.sh deletes the
    private sdkconfig.defaults.local after the build, so that reconfigure fails.
    """
    flash_args = build_dir / "flash_args"
    command = ["esptool.py", "--chip", "esp32s3", "--port", port, "-b", "460800"]
    command += ["--before", "default_reset", "--after", "hard_reset", "write_flash"]
    if dry_run and not flash_args.is_file():
        return command + [f"@{flash_args}", hex(NVS_OFFSET), str(nvs_image)]
    if not flash_args.is_file():
        raise ValueError(
            f"Build output is missing {flash_args}. Run setup again so the firmware builds first."
        )
    lines = flash_args.read_text().split("\n")
    command += lines[0].split()
    images: dict[int, Path] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise ValueError(
                f"{flash_args} has an unreadable line: {line!r}. Run setup again to rebuild."
            )
        image = build_dir / fields[1]
        if not image.is_file():
            raise ValueError(f"Build output is missing {image}. Run setup again to rebuild.")
        images[int(fields[0], 0)] = image
        command += [fields[0], str(image)]
    # Without these three the write would change NVS and leave old or no firmware.
    missing = [hex(offset) for offset in FIRMWARE_OFFSETS if offset not in images]
    if missing:
        raise ValueError(
            f"{flash_args} lists no image at {', '.join(missing)}. Run setup again to rebuild."
        )
    return command + [hex(NVS_OFFSET), str(nvs_image)]


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
        env: dict[str, str] | None = None
        if args.dry_run and (not args.backup.is_file() or args.backup.stat().st_size != FLASH_SIZE):
            raise ValueError(
                "Dry run needs an existing complete 16 MiB flash backup file. Save one first."
            )
        if not args.token_file.is_file():
            raise ValueError("Approval token file is missing. Approve this device and retry.")
        if not args.dry_run:
            env = _idf_env()
            version = subprocess.check_output(["idf.py", "--version"], text=True, env=env).strip()
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
                        # 2 Mbaud reads the 16 MiB backup about 8x faster than the default.
                        "-b",
                        "2000000",
                        "read_flash",
                        "0x0",
                        hex(FLASH_SIZE),
                        str(args.backup),
                    ],
                    dry_run=False,
                    env=env,
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
            env=env,
        )
        output = BUILD_ROOT / "output"
        image = output / "stack-chan-maipai.bin"
        nvs_image = output / "stackchan-nvs.bin"
        # provision.py deletes the token file it reads. Hand it a private copy so a
        # failed flash can be retried; the approved file goes only after the write.
        scratch = tempfile.TemporaryDirectory(prefix="stackchan-token-")
        token_copy = Path(scratch.name) / "approved.token"
        token_copy.write_text(token + "\n", encoding="utf-8")
        token_copy.chmod(0o600)
        provision = [
            sys.executable,
            "-m",
            "maipai_body.bodies.stackchan.xiaozhi.provision",
            "--url",
            args.xiaozhi_url,
            "--token-file",
            str(token_copy),
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
            "--generator",
            str(
                IDF_EXPORT.parent
                / "components/nvs_flash/nvs_partition_generator/nvs_partition_gen.py"
            ),
        ]
        try:
            _run(provision, dry_run=args.dry_run, env=env)
        finally:
            scratch.cleanup()
        _run(
            _write_flash_command(
                args.port,
                BUILD_ROOT / "StackChan/firmware/build",
                nvs_image,
                dry_run=args.dry_run,
            ),
            dry_run=args.dry_run,
            env=env,
        )
        if not args.dry_run:
            try:
                args.token_file.unlink(missing_ok=True)
            except OSError as error:
                print(f"Flash finished, but delete {args.token_file} by hand: {error}")
        print(f"DONE: backup saved at {args.backup}; firmware image: {image}; NVS: {nvs_image}")
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Setup stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
