"""Record a paired StackChan's hello, MCP tools and OTA exchanges.

Run from ``body/`` after pairing the unit. The required ``--unit`` address
must be the WebSocket endpoint of the local StackChan service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "stackchan"
REDACTED = "<REDACTED>"
SENSITIVE_KEY = re.compile(
    r"token|authorization|password|secret|credential|api[_-]?key|serial(?:[_-]?number)?|session[_-]?id",
    re.I,
)
MAC = re.compile(r"(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}")
UUID = re.compile(r"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")


def redact(value: Any, key: str = "") -> Any:
    """Remove credentials and stable hardware identifiers recursively."""
    if SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {name: redact(child, str(name)) for name, child in value.items()}
    if isinstance(value, list):
        return [redact(child) for child in value]
    if isinstance(value, str):
        value = MAC.sub("<REDACTED_MAC>", value)
        value = UUID.sub("<REDACTED_UUID>", value)
        serial = re.search(r"(?i)\b(?:serial(?:\s+number)?|s/n)\s*[:=]\s*[^\s,;]+", value)
        if serial:
            marker = re.match(r"(?i)(?:serial(?:\s+number)?|s/n)\s*[:=]", serial.group())
            value = (
                value[: serial.start()]
                + marker.group()
                + " <REDACTED_SERIAL>"
                + value[serial.end() :]
            )
        return value
    return value


async def record_ws(args: argparse.Namespace) -> dict[str, Any]:
    headers = {"Protocol-Version": "1"}
    if args.device_id:
        headers["Device-Id"] = args.device_id
    if args.client_id:
        headers["Client-Id"] = args.client_id
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    async with connect(args.unit, additional_headers=headers, open_timeout=args.timeout) as ws:
        client_hello = {
            "type": "hello",
            "version": 1,
            "features": {"mcp": True},
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60,
            },
        }
        await ws.send(json.dumps(client_hello))
        server_hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=args.timeout))
        request_id = 241
        await ws.send(
            json.dumps(
                {
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/list",
                        "params": {},
                    },
                }
            )
        )
        tools_list = await read_mcp_response(ws, request_id, args.timeout)
    return {"hello": {"request": client_hello, "response": server_hello}, "tools_list": tools_list}


async def read_mcp_response(ws: Any, request_id: int, timeout: float) -> dict[str, Any]:
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        payload = message.get("payload", {}) if isinstance(message, dict) else {}
        if message.get("type") == "mcp" and payload.get("id") == request_id:
            return payload


def record_ota(url: str, timeout: float) -> dict[str, Any]:
    body = json.dumps({"version": 1, "language": "en-US", "flash_size": 0}).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(256 * 1024).decode("utf-8", errors="replace")
            try:
                response_body: Any = json.loads(raw)
            except json.JSONDecodeError:
                response_body = raw
            return {
                "request": {"method": "POST", "url": "<REDACTED_URL>", "body": json.loads(body)},
                "response": {"status": response.status, "body": response_body},
            }
    except URLError as exc:
        raise RuntimeError(f"OTA exchange failed: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, help="paired unit service WebSocket URL")
    parser.add_argument("--token", help="pairing bearer token; never stored")
    parser.add_argument("--device-id", help="paired device identifier")
    parser.add_argument("--client-id", help="paired client identifier")
    parser.add_argument("--ota-url", required=True, help="local host OTA endpoint to query")
    parser.add_argument("--output", type=Path, default=FIXTURES / "unit-arrival.json")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if not args.unit.startswith(("ws://", "wss://")):
        parser.error("--unit must be a ws:// or wss:// service address")
    if not args.ota_url.startswith(("http://", "https://")):
        parser.error("--ota-url must be an http:// or https:// host endpoint")
    try:
        capture = asyncio.run(record_ws(args))
        capture["ota"] = record_ota(args.ota_url, args.timeout)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(redact(capture), indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(f"Wrote redacted StackChan fixtures to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
