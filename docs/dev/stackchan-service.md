# StackChan service

The Bot app starts the xiaozhi WebSocket service only when `MAIPAI_BODY=stackchan`. Other body configurations do not start it. The service binds to `0.0.0.0:8765` by default; `MAIPAI_XIAOZHI_HOST` and `MAIPAI_XIAOZHI_PORT` select another bind address and port. It stores the per-device token digest in `stackchan-pairing.json` under the Bot data directory. The dashboard process opens the same file for local pairing operations.

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

## Motion limit

StackChan's current firmware offers head angle commands but no remote torque-disable command. The shared `Robot` API requires a lease and a working emergency stop for every body with actuators. Its head-only stop contract means disabling torque. The StackChan profile therefore does not expose head motion, and the xiaozhi service advertises no robot tools until the firmware can implement a real stop. A software lock cannot stop an in-flight servo command or stop the servo after the network link is lost.

## Tests

`body/tests/test_stackchan_xiaozhi.py` exercises a fake device over a local WebSocket. The test covers pairing refusal, approval, hello, audio callback delivery and protocol tool handling without hardware. No test writes to a physical serial port.
