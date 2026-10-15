"""Generate and optionally write the StackChan Wi-Fi NVS partition."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(
            f"Required tool {name} was not found. Install ESP-IDF 5.5.4 tools and retry."
        )
    return found


def generate_image(
    output: Path,
    *,
    websocket_url: str,
    token: str,
    version: str,
    ota_url: str,
    partition_size: int = 0x4000,
    generator: str | None = None,
) -> Path:
    """Generate an NVS binary using ESP-IDF's nvs_partition_gen.py."""
    if not websocket_url.startswith("ws://") and not websocket_url.startswith("wss://"):
        raise ValueError(
            "WebSocket URL must start with ws:// or wss://. Use the bot host's LAN address."
        )
    if not token or any(not value for value in (version, ota_url)):
        raise ValueError(
            "Token, firmware version, and OTA URL are required. Supply all values and retry."
        )
    generator_path = generator or _tool("nvs_partition_gen.py")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stackchan-nvs-") as temp_dir:
        temp = Path(temp_dir)
        csv_path = temp / "provision.csv"
        csv_path.write_text(
            "key,type,encoding,value\n"
            f"url,data,string,{websocket_url}\n"
            f"token,data,string,{token}\n"
            f"version,data,string,{version}\n"
            f"ota_url,data,string,{ota_url}\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                generator_path,
                "generate",
                str(csv_path),
                str(output),
                hex(partition_size),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(
                "NVS image generation failed. Check ESP-IDF NVS CSV values and retry. "
                f"{result.stderr.strip()}"
            )
    if not output.is_file() or output.stat().st_size != partition_size:
        raise RuntimeError(
            "NVS image has the wrong size. Check the partition size and generator output, "
            "then retry."
        )
    return output


def write_image(
    image: Path, *, port: str, address: int = 0x9000, esptool: str | None = None
) -> None:
    """Write the generated partition over USB. Never called by generation."""
    tool = esptool or _tool("esptool.py")
    result = subprocess.run(
        [sys.executable, tool, "--port", port, "write_flash", hex(address), str(image)], check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"USB NVS write failed on {port}. Check the cable and boot mode, then retry."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", required=True, help="LAN WebSocket URL, for example ws://192.0.2.10:8765"
    )
    parser.add_argument(
        "--token", required=True, help="Per-device token from administrator approval"
    )
    parser.add_argument("--version", required=True, help="Server protocol version")
    parser.add_argument("--ota-url", required=True, help="LAN OTA check URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=lambda value: int(value, 0), default=0x4000)
    parser.add_argument("--generator", help="Path to ESP-IDF nvs_partition_gen.py")
    parser.add_argument(
        "--write-port", help="Optional USB serial port; writes only when explicitly supplied"
    )
    parser.add_argument("--esptool", help="Path to esptool.py")
    args = parser.parse_args(argv)
    try:
        image = generate_image(
            args.output,
            websocket_url=args.url,
            token=args.token,
            version=args.version,
            ota_url=args.ota_url,
            partition_size=args.size,
            generator=args.generator,
        )
        print(json.dumps({"image": str(image), "bytes": image.stat().st_size}))
        if args.write_port:
            write_image(image, port=args.write_port, esptool=args.esptool)
        return 0
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
