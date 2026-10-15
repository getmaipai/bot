# Set up a StackChan

## What you need

- A StackChan and a USB-C data cable
- A Bot host on the same home network
- A Bot administrator who can use the local setup tools

The first firmware flash and backup need a computer with ESP-IDF 5.5.4. Keep the robot on your home network while you set it up. The current `ws://` connection sends the token, audio, and control frames without encryption. Use a trusted home network and bind the Bot service to its LAN address. The firmware does not yet have the CA certificate patch needed for secure `wss://` connections to a self-signed Bot certificate.

## Set it up

1. Ask the Bot administrator to save a full backup of the robot's flash before changing it. Keep that file in a private place.
2. Connect the USB-C data cable to the head unit. The administrator flashes the MaiPai firmware built from the pinned recipe in the developer guide.
3. Ask the administrator to make a first NVS image with the Bot host's LAN WebSocket address. Use a temporary token for this first connection so the robot can appear as pending.
4. Turn on the robot and connect it to the home Wi-Fi using its setup screen. Wait for it to try the Bot host.
5. On the Bot host, open the Bot dashboard on that same computer. The administrator checks the pending `Device-Id` and approves it through the local Pairing API.
6. The approval response gives the administrator a private token-file path. They use it to make and write the final NVS image over USB. The token file is removed after the image is saved or written successfully.
7. Restart the robot. The administrator confirms that it reconnects as approved, then removes the NVS image after setup.

You'll know setup worked when the device appears as approved in the Bot service. The service can move the head. Its software stop blocks new moves and cancels queued moves, but cannot stop a move the servo has accepted. Use the robot's power switch to cut servo power.

If pairing stays pending, check that the Bot host and robot are on the same home network, then restart the robot. If it still does not appear, ask the Bot administrator to check the local Pairing API.
