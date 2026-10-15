# StackChan service

The Bot app starts the xiaozhi and avatar WebSocket services only when `MAIPAI_BODY=stackchan`. Other body configurations do not start them. The xiaozhi service listens on `127.0.0.1:8765`; the avatar service listens on `127.0.0.1:8766`. Set `MAIPAI_XIAOZHI_HOST` to the Bot host's LAN address and `MAIPAI_XIAOZHI_PORT` to select the xiaozhi listener. The avatar listener has separate `MAIPAI_STACKCHAN_AVATAR_HOST` and `MAIPAI_STACKCHAN_AVATAR_PORT` settings. By default, both listeners use loopback; if `MAIPAI_XIAOZHI_HOST` is set, avatar host follows it unless explicitly set. Set both `MAIPAI_XIAOZHI_TLS_CERT` and `MAIPAI_XIAOZHI_TLS_KEY` to enable TLS for both listeners; leave both unset for `ws://`. Firmware verifies `wss://` when built with `--ca-file <pem>`, and the certificate SAN must match each URL host or IP. Use `stackchan-provision --generate-tls <private-dir> --host <bot-lan-host>` to create a local CA and server certificate, then build firmware with the printed `recipe.sh --ca-file` command. TLS resource use on the ESP32-S3 remains unmeasured.

The current provisioned `ws://` connections send the bearer token, audio, and control frames as cleartext to devices on that LAN. Keep the robot and Bot host on a trusted network. Build firmware with `--ca-file <pem>` for `wss://`; the server certificate must include a SAN matching the host or IP in the robot's URL. TLS resource use on the ESP32-S3 remains unmeasured.

The firmware recipe enables its persistent xiaozhi WebSocket by default; `--avatar-server-url ws://192.0.2.10:8766` sets `CONFIG_STACKCHAN_SERVER_URL`. Build the avatar firmware with `--device-id <MAC> --client-id <UUID> --pairing-token <token>` so it uses the same approved identity and token as xiaozhi. The recipe applies patch 011 to add those headers and replace M5's constant avatar token. Pairing uses the existing `PairingStore`; revocation is checked on each received and sent frame. See the [firmware guide](../../body/maipai_body/bodies/stackchan/firmware/README.md) for details.

The protocol implementation is in `body/maipai_body/bodies/stackchan/xiaozhi/`. `XiaozhiServer` checks the device and client identifiers with `PairingStore` before accepting a session, replies to hello, and passes binary audio frames to its async audio callback. The current app wiring does not yet connect that callback to the Home conversation loop.

## Camera

The xiaozhi service also listens for on-demand photos on the vision listener, port `8766` by default. MCP `initialize` advertises `capabilities.vision` with a per-device URL and the paired bearer token. The device posts a multipart JPEG in an `image`, `file`, or `photo` field to that URL, using `Authorization: Bearer <token>`. The receiver caps the full upload at 2 MiB, keeps the latest photo only in process memory, and never writes or forwards the bytes. Set `MAIPAI_VISION_HOST`, `MAIPAI_VISION_PORT`, and `MAIPAI_VISION_URL` for a LAN reachable listener and advertised base URL; use a trusted LAN because the current transport is cleartext. If `MAIPAI_VISION_URL` is a base URL, append the device route `/vision/<Device-Id>`.

All camera captures and avatar stream starts go through the StackChan translator's Robot `camera` part. It lights the full RGB ring red before capture or stream start and clears it after a photo, on stream stop, command error, disconnect, or service shutdown. The avatar frame codec is isolated in `body/maipai_body/bodies/stackchan/avatar_frames.py`; the small handler hook is `XiaozhiServer.send_avatar_frame(bytes)`. StartCameraStream uses command `0x05`; an empty payload starts and `00` stops. Stream start is rejected while software estop is engaged.

The avatar protocol implementation is in `body/maipai_body/bodies/stackchan/avatar/`. The endpoint is `/stackChan/ws?deviceType=StackChan`. M5's binary frame is `[type:1][payload length:4, big endian][payload]`; ControlAvatar is type `0x03` with the M5 nested `leftEye`, `rightEye`, and `mouth` JSON shape. The closed expression map translates to M5's eye weight/rotation ranges; eyes and mouth are Robot capabilities. No camera frames are handled in the avatar channel.

## Pairing API

The local Bot dashboard exposes:

| Method | Path | Result |
|---|---|---|
| `GET` | `/api/stackchan/pairings/pending` | Pending device and client identifiers with request time |
| `POST` | `/api/stackchan/pairings/approve` | Approves JSON `{ "device_id": "...", "client_id": "..." }` and returns a private token-file path |
| `POST` | `/api/stackchan/pairings/revoke` | Revokes JSON `{ "device_id": "..." }` |

Pairing routes accept requests from the local computer only and require the dashboard's same-origin JSON check. Approval never returns a token in the HTTP response. It writes a one-time token file in a mode-0700 directory with mode 0600, and returns only its path. The provisioning command consumes and removes that file after a successful image build. Revocation removes the allowlist entry; active sessions are closed when their next frame arrives, and audio sending checks the allowlist before every send.

## Provisioning

Install the Bot package in its managed environment, then generate an NVS image without writing it:

```bash
uv run stackchan-provision --host 192.0.2.10 --version 1 --ota-url http://192.0.2.10:8765/ota --device-id 02:00:00:00:00:15 --client-id 00000000-0000-4000-8000-000000000015 --avatar-server-url ws://192.0.2.10:8766 --firmware-recipe body/maipai_body/bodies/stackchan/firmware/recipe.sh --output stackchan-nvs.bin
```

The command asks for the token without echoing it. With TLS configured on the Bot, the default URL uses `wss://`; otherwise it uses `ws://`. For a token issued by the Pairing API, pass its file path with `--token-file <path>`. The image is created with owner-only permissions because it contains the device token. To write it over USB, add `--write --port <serial-port>`. Without `--write`, the command never calls esptool. Keep the generated image private and remove it when provisioning is complete.

The recipe and pins live in `body/maipai_body/bodies/stackchan/firmware/`. `recipe.sh` fetches the pinned sources, applies the M5 patch and our ordered patches, builds, scans the binary and prints hashes. Build output stays outside the repository. `bump.sh <commit>` checks whether the M5 patch and each MaiPai patch still apply to a proposed upstream commit; inspect the patch changes and host-list changes before accepting new pins.

## Stop behaviour

The xiaozhi service exposes the shared Robot interface, but no Bot behavior sends head commands yet. The software stop cancels queued moves and best-effort sends the current head angles again to stop an accepted move; if reading those angles fails, the estop stays latched and reports `BodyLost`. This is not a hardware power cut and cannot guarantee the servo has stopped, so use the robot's power switch to cut servo power.

The avatar listener also carries a software estop latch for ControlMotion `0x04` frames. With the latch engaged, incoming motion frames are discarded while the connection remains open. This is host-side filtering and does not cut servo torque.

## Known gaps

The Bot service is not wired to a Bot behavior that issues head commands or expression cues automatically. Patch 003 keeps the firmware xiaozhi WebSocket open between listening sessions and retries failed connections; patch 008 adds an optional CA bundle; patch 011 adds shared pairing identity to the avatar channel. The recipe options and CA input are documented in the [firmware guide](../../body/maipai_body/bodies/stackchan/firmware/README.md).

Battery, touch and IMU remain `NotSupported` at the shared robot API because the pinned xiaozhi translator exposes no verified read path for them. Source-derived chip and register notes are in [the sensor map](stackchan-sensor-map.md); unit measurements are tracked in [the unit-arrival runbook](stackchan-unit-measurements.md). Patch 009 protects AXP2101 charging-state reads from an I2C timeout abort, but does not add battery reporting to the Bot API.

## Tests

`body/tests/test_stackchan_xiaozhi.py` exercises a fake device over a local WebSocket. The test covers pairing refusal, approval, hello, audio callback delivery and protocol tool handling without hardware. `body/tests/test_stackchan_avatar.py` uses the independent fake peer in `body/tests/stackchan_sim/`; it covers expression delivery, unpaired refusal, estop motion filtering, malformed-frame isolation, reconnect replacement and codec bounds. These are software fake-peer checks only; no hardware verification is claimed and no test writes to a physical serial port.

`body/tests/test_stackchan_avatar.py` uses the independent fake peer in `body/tests/stackchan_sim/`. It covers expression-frame delivery, unpaired refusal, estop motion filtering, malformed-frame isolation, reconnect replacement and codec bounds. These are fake-device protocol checks only; hardware has not arrived, so no unit verification is claimed.
