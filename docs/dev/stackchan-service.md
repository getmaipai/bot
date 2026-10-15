# StackChan service

The Bot app starts the xiaozhi WebSocket service only when `MAIPAI_BODY=stackchan`. Other body configurations do not start it. The service listens on `127.0.0.1:8765` by default; set `MAIPAI_XIAOZHI_HOST` to the Bot host's LAN address and `MAIPAI_XIAOZHI_PORT` to select another port. The current provisioned `ws://` connection sends the bearer token, audio, and control frames as cleartext to devices on that LAN. Keep the robot and Bot host on a trusted network. The firmware accepts `wss://`, but the pinned build does not include the CA certificate patch needed to trust a self-signed Bot certificate, so secure WebSocket provisioning is not ready yet. A CA injection patch and a `wss://` default remain future firmware work.

The protocol implementation is in `body/maipai_body/bodies/stackchan/xiaozhi/`. `XiaozhiServer` checks the device and client identifiers with `PairingStore` before accepting a session, replies to hello, and passes binary audio frames to its async audio callback. The current app wiring does not yet connect that callback to the Home conversation loop.

## Pairing API

The local Bot dashboard exposes:

| Method | Path | Result |
|---|---|---|
| `GET` | `/api/stackchan/pairings/pending` | Pending device and client identifiers with request time |
| `POST` | `/api/stackchan/pairings/approve` | Approves JSON `{ "device_id": "..." }` and returns a private token-file path |
| `POST` | `/api/stackchan/pairings/revoke` | Revokes JSON `{ "device_id": "..." }` |

Pairing routes accept requests from the local computer only and require the dashboard's same-origin JSON check. Approval never returns a token in the HTTP response. It writes a one-time token file in a mode-0700 directory with mode 0600, and returns only its path. The provisioning command consumes and removes that file after a successful image build. Revocation removes the allowlist entry; active sessions are closed when their next frame arrives, and audio sending checks the allowlist before every send.

## Provisioning

Install the Bot package in its managed environment, then generate an NVS image without writing it:

```bash
uv run stackchan-provision --url ws://192.0.2.10:8765 --version 1 --ota-url http://192.0.2.10:8765/ota --output stackchan-nvs.bin
```

The command asks for the token without echoing it. For a token issued by the Pairing API, pass its file path with `--token-file <path>`. The image is created with owner-only permissions because it contains the device token. To write it over USB, add `--write --port <serial-port>`. Without `--write`, the command never calls esptool. Keep the generated image private and remove it when provisioning is complete.

The recipe and pins live in `body/maipai_body/bodies/stackchan/firmware/`. `recipe.sh` fetches the pinned sources, applies the M5 patch and our ordered patches, builds, scans the binary and prints hashes. Build output stays outside the repository. `bump.sh <commit>` checks whether the M5 patch and each MaiPai patch still apply to a proposed upstream commit; inspect the patch changes and host-list changes before accepting new pins.

## Stop behaviour

The StackChan profile and xiaozhi service expose head motion. The software stop cancels queued moves and blocks new ones, but it cannot cancel a move the servo has already accepted or stop the servo after the network link is lost. Use the robot's power switch to cut servo power.

## Known gaps

The firmware closes its WebSocket session between turns, so host-initiated head moves fail while the robot is idle. Patch 003, a persistent WebSocket connection with retry and backoff, is deferred until it can be built and checked from a clean firmware tree.

## Tests

`body/tests/test_stackchan_xiaozhi.py` exercises a fake device over a local WebSocket. The test covers pairing refusal, approval, hello, audio callback delivery and protocol tool handling without hardware. No test writes to a physical serial port.
