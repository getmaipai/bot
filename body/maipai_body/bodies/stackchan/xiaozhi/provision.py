"""Generate and optionally write the StackChan Wi-Fi NVS partition."""

from __future__ import annotations

import argparse
import csv
import getpass
import ipaddress
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .tls import generate_local_ca


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(
            f"Required tool {name} was not found. Install ESP-IDF 5.5.4 tools and retry."
        )
    return found


def _tool_python(tool: str) -> str:
    """Use ESP-IDF's Python environment (set by export.sh) or one beside the tool."""
    idf_env = os.environ.get("IDF_PYTHON_ENV_PATH")
    if idf_env and (Path(idf_env) / "bin" / "python").is_file():
        return str(Path(idf_env) / "bin" / "python")
    tool_path = Path(tool).resolve()
    for parent in tool_path.parents:
        candidate = parent / "bin" / "python"
        if candidate.is_file() and candidate != Path(sys.executable):
            return str(candidate)
    return sys.executable


def _service_url(host: str, port: int, tls: bool) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        formatted_host = host
    else:
        formatted_host = f"[{address}]" if address.version == 6 else str(address)
    return f"{'wss' if tls else 'ws'}://{formatted_host}:{port}"


def generate_image(
    output: Path,
    *,
    websocket_url: str,
    token: str,
    version: str,
    ota_url: str,
    client_id: str = "",
    partition_size: int = 0x4000,
    generator: str | None = None,
) -> Path:
    """Generate an NVS binary using ESP-IDF's nvs_partition_gen.py.

    The image replaces the whole NVS partition, so these keys preserve pairing and make
    the robot boot straight into the AI Agent.
    """
    if not websocket_url.startswith("ws://") and not websocket_url.startswith("wss://"):
        raise ValueError(
            "WebSocket URL must start with ws:// or wss://. Use the bot host's LAN address."
        )
    if not token or not version:
        raise ValueError("Token and firmware version are required. Supply both values and retry.")
    generator_path = generator or _tool("nvs_partition_gen.py")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stackchan-nvs-") as temp_dir:
        temp = Path(temp_dir)
        csv_path = temp / "provision.csv"
        with csv_path.open("w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            rows = [
                ["key", "type", "encoding", "value"],
                ["websocket", "namespace", "", ""],
                ["url", "data", "string", websocket_url],
                ["token", "data", "string", token],
                ["version", "data", "i32", version],
            ]
            if ota_url:
                rows.extend([["wifi", "namespace", "", ""], ["ota_url", "data", "string", ota_url]])
            if client_id:
                rows.extend([["board", "namespace", "", ""], ["uuid", "data", "string", client_id]])
            rows.extend(
                [
                    ["xiaozhi", "namespace", "", ""],
                    ["boot_ai", "data", "u8", "1"],
                    ["app_config", "namespace", "", ""],
                    ["is_configed", "data", "u8", "1"],
                ]
            )
            writer.writerows(rows)
        result = subprocess.run(
            [
                _tool_python(generator_path),
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
    output.chmod(0o600)
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
        "--url", help="LAN WebSocket URL; defaults from --host and configured TLS mode"
    )
    parser.add_argument("--host", help="Bot host LAN hostname or IP for the default URL")
    parser.add_argument(
        "--service-port", type=int, default=None, help="Bot WebSocket port for the default URL"
    )
    parser.add_argument(
        "--generate-tls",
        type=Path,
        metavar="DIR",
        help="Generate a local CA and server certificate in this private directory",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        help="Read the one-time per-device token from a file instead of the hidden prompt",
    )
    parser.add_argument("--device-id", help="StackChan MAC address for the avatar channel")
    parser.add_argument("--client-id", help="Stable UUID for this StackChan firmware identity")
    parser.add_argument(
        "--avatar-server-url",
        help="Avatar WebSocket URL, for example ws://192.0.2.10:8766",
    )
    parser.add_argument(
        "--firmware-recipe",
        type=Path,
        help="Optional firmware recipe to build with the same device identity and token",
    )
    parser.add_argument("--version", required=True, help="Server protocol version")
    parser.add_argument(
        "--ota-url",
        default="",
        help="Optional LAN OTA check URL; leave empty while firmware OTA checks are disabled",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=lambda value: int(value, 0), default=0x4000)
    parser.add_argument("--generator", help="Path to ESP-IDF nvs_partition_gen.py")
    parser.add_argument("--write", action="store_true", help="Write the NVS image over USB")
    parser.add_argument("--port", help="USB serial port, required with --write")
    parser.add_argument("--esptool", help="Path to esptool.py")
    args = parser.parse_args(argv)
    try:
        if bool(args.device_id) != bool(args.client_id):
            raise ValueError("--device-id and --client-id must be provided together.")
        if args.firmware_recipe and not args.device_id:
            raise ValueError("--firmware-recipe requires --device-id and --client-id.")
        if args.write and not args.port:
            raise ValueError("--write needs --port. Add the USB serial port and retry.")
        if not args.write and args.port:
            raise ValueError("--port only works with --write. Add --write to write over USB.")
        if args.token_file:
            if not args.token_file.is_file():
                raise ValueError(
                    "Token file is missing. Use the private file path from the pairing approval "
                    "response and retry."
                )
            if stat.S_IMODE(args.token_file.stat().st_mode) & 0o077:
                raise ValueError(
                    "Token file can be read by other users. Restrict it to your account and retry."
                )
            token = args.token_file.read_text().strip()
        else:
            token = getpass.getpass("One-time StackChan token: ")
        tls_configured = bool(
            os.environ.get("MAIPAI_XIAOZHI_TLS_CERT") and os.environ.get("MAIPAI_XIAOZHI_TLS_KEY")
        )
        if args.generate_tls:
            host = args.host or os.environ.get("MAIPAI_XIAOZHI_HOST")
            if not host:
                raise ValueError(
                    "--generate-tls needs --host or MAIPAI_XIAOZHI_HOST. "
                    "Set the Bot LAN host and retry."
                )
            ca_cert, server_cert, server_key = generate_local_ca(args.generate_tls, host)
            print(f"CA certificate: {ca_cert}")
            print(f"Server certificate: {server_cert}")
            print(f"Server key: {server_key}")
            print(
                "Configure Bot with MAIPAI_XIAOZHI_TLS_CERT="
                f"{server_cert} MAIPAI_XIAOZHI_TLS_KEY={server_key}"
            )
            print(f"Firmware recipe: recipe.sh --ca-file {ca_cert}")
            tls_configured = True
        websocket_url = args.url
        if not websocket_url:
            host = args.host or os.environ.get("MAIPAI_XIAOZHI_HOST")
            if not host:
                raise ValueError("--url or --host is required. Set the Bot LAN host and retry.")
            port = args.service_port or int(os.environ.get("MAIPAI_XIAOZHI_PORT", "8765"))
            websocket_url = _service_url(host, port, tls_configured)
        elif tls_configured:
            parsed_url = urlsplit(websocket_url)
            if parsed_url.scheme == "ws":
                websocket_url = urlunsplit(parsed_url._replace(scheme="wss"))
        if websocket_url.startswith("wss://") and not tls_configured and not args.generate_tls:
            raise ValueError(
                "A wss:// URL needs MAIPAI_XIAOZHI_TLS_CERT and MAIPAI_XIAOZHI_TLS_KEY. "
                "Configure both Bot certificate paths or use ws://."
            )
        image = generate_image(
            args.output,
            websocket_url=websocket_url,
            token=token,
            version=args.version,
            ota_url=args.ota_url,
            client_id=args.client_id or "",
            partition_size=args.size,
            generator=args.generator,
        )
        if args.token_file and args.firmware_recipe:
            args.token_file.unlink()
        if args.firmware_recipe:
            recipe_args = [
                str(args.firmware_recipe),
                "--device-id",
                args.device_id,
                "--client-id",
                args.client_id,
                "--pairing-token",
                token,
            ]
            if args.avatar_server_url:
                recipe_args.extend(["--avatar-server-url", args.avatar_server_url])
            result = subprocess.run(
                recipe_args,
                check=False,
            )
            if result.returncode:
                raise RuntimeError("Firmware recipe failed. Keep the token file and retry.")
        print(json.dumps({"image": str(image), "bytes": image.stat().st_size}))
        print("Steps: 1. Keep the robot connected by its USB-C data port.")
        print("2. Back up the existing flash before changing partitions.")
        if args.write:
            write_image(image, port=args.port, esptool=args.esptool)
            print(f"3. Wrote the NVS image at 0x9000 on {args.port}.")
        else:
            print(f"3. Image is ready at {image}; no USB write was requested.")
        if args.token_file:
            args.token_file.unlink()
        print("4. Reboot the robot and approve its Device-Id in the Bot pairing API.")
        return 0
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
