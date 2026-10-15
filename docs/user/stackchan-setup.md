# Set up a StackChan

## What you need

- A StackChan and a USB-C data cable
- A Bot host on the same home network
- A Bot administrator who can use the local setup tools

The first firmware flash and backup need a computer with ESP-IDF 5.5.4. Keep the robot on your home network while you set it up. Both services use `ws://` unless TLS is configured with `MAIPAI_XIAOZHI_TLS_CERT` and `MAIPAI_XIAOZHI_TLS_KEY`. Set `MAIPAI_XIAOZHI_HOST` and `MAIPAI_STACKCHAN_AVATAR_HOST` to the Bot host's LAN address so both services can accept the robot; by default they listen on loopback. Create a local CA and server certificate with `stackchan-provision --generate-tls <private-dir> --host <bot-lan-host>`; build firmware with its printed `recipe.sh --ca-file` command so the robot can verify the server certificate. The certificate SAN must match the host or IP in both robot URLs.

The firmware recipe enables its persistent xiaozhi WebSocket by default. Set the avatar channel URL with `--avatar-server-url ws://192.0.2.10:8766`; also pass `--device-id`, `--client-id`, and `--pairing-token` so the avatar connection uses the approved per-device credentials. `--ca-file <pem>` adds a CA bundle and `--no-persistent-websocket` restores session-only voice behavior. See the [firmware guide](../../body/maipai_body/bodies/stackchan/firmware/README.md) for details.

## Set it up

1. Ask the Bot administrator to save a full backup of the robot's flash before changing it. Keep that file in a private place.
2. Connect the USB-C data cable to the head unit. The administrator flashes the MaiPai firmware built from the pinned recipe in the developer guide.
3. Ask the administrator to build firmware with the avatar URL set to the Bot host's LAN address and a stable `Device-Id`/`Client-Id`. Have them provision xiaozhi with a temporary token, using `wss://` when TLS is configured, so the robot can appear as pending.
4. Turn on the robot and connect it to the home Wi-Fi using its setup screen. Wait for either channel to appear as pending.
5. On the Bot host, open the Bot dashboard on that same computer. The administrator checks both the pending `Device-Id` and `Client-Id`, then approves that pair through the local Pairing API.
6. The approval response gives the administrator a private token-file path. They use it with `stackchan-provision --token-file <path> --device-id <MAC> --client-id <UUID> --avatar-server-url ws://192.0.2.10:8766 --firmware-recipe <recipe>` to generate the final xiaozhi NVS image and rebuild the avatar firmware with the same token and identity. Keep generated images private, then remove them after setup.
7. Restart the robot. The administrator confirms both channels reconnect as approved. The avatar path is `/stackChan/ws?deviceType=StackChan`; it carries binary frames and keeps its connection open.

You'll know setup worked when the device appears as approved in the Bot service. The service exposes the shared Robot interface, but no Bot behavior sends head commands yet, so pairing alone does not move the head. The software stop cancels queued moves and best-effort sends the current head angles again; if it cannot read them, the stop stays latched and reports a lost body. This cannot cut motor power or guarantee the servo has stopped, so use the robot's power switch to cut servo power.

If pairing stays pending, check that the Bot host and robot are on the same home network, then restart the robot. If it still does not appear, ask the Bot administrator to check the local Pairing API.
