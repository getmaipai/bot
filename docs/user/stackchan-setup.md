# Set up a StackChan

## What you need

- A StackChan and a USB-C data cable
- A Bot host on the same home network
- A Bot administrator who can use the local setup tools

The first firmware flash and backup need a computer with ESP-IDF 5.5.4. Keep the robot on your home network while you set it up. The service uses `ws://` unless TLS is configured with both `MAIPAI_XIAOZHI_TLS_CERT` and `MAIPAI_XIAOZHI_TLS_KEY`. Create a local CA and server certificate with `stackchan-provision --generate-tls <private-dir> --host <bot-lan-host>`; build firmware with its printed `recipe.sh --ca-file` command so the robot can verify the server certificate.

The firmware recipe enables its persistent WebSocket by default; `--ca-file <pem>` adds a CA bundle and `--no-persistent-websocket` restores session-only behavior. See the [firmware guide](../../body/maipai_body/bodies/stackchan/firmware/README.md) for details.

## Set it up

1. Ask the Bot administrator to save a full backup of the robot's flash before changing it. Keep that file in a private place.
2. Connect the USB-C data cable to the head unit. The administrator flashes the MaiPai firmware built from the pinned recipe in the developer guide.
3. Ask the administrator to make a first NVS image with the Bot host's LAN WebSocket address, using `wss://` when TLS is configured. Use a temporary token for this first connection so the robot can appear as pending.
4. Turn on the robot and connect it to the home Wi-Fi using its setup screen. Wait for it to try the Bot host.
5. On the Bot host, open the Bot dashboard on that same computer. The administrator checks both the pending `Device-Id` and `Client-Id`, then approves that pair through the local Pairing API.
6. The approval response gives the administrator a private token-file path. They use it to make and write the final NVS image over USB. The token file is removed after the image is saved or written successfully.
7. Restart the robot. The administrator confirms that it reconnects as approved, then removes the NVS image after setup.

You'll know setup worked when the device appears as approved in the Bot service. The service exposes the shared Robot interface, but no Bot behavior sends head commands yet, so pairing alone does not move the head. The software stop cancels queued moves and best-effort sends the current head angles again; if it cannot read them, the stop stays latched and reports a lost body. This cannot cut motor power or guarantee the servo has stopped, so use the robot's power switch to cut servo power.

If pairing stays pending, check that the Bot host and robot are on the same home network, then restart the robot. If it still does not appear, ask the Bot administrator to check the local Pairing API.
