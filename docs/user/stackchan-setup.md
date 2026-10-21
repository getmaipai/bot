# Set up a StackChan

After setup, see [Your StackChan](stackchan.md) for what it can do.

You need a StackChan, a USB-C data cable, a Bot host, a phone, and a computer with ESP-IDF 5.5.4.

Setup never uses the M5 app or an M5 account. Your Wi-Fi password goes from your phone straight to the robot.

## Steps

1. Connect the StackChan to the setup computer with the USB-C data cable.

   You will see the robot charge or turn on.

2. Pair the robot with the Bot.

   The robot's Device-Id is its MAC address. The setup tool prints it when it connects over USB. Pick any new UUID as its Client-Id. Pairing gives you a private token file path. The token itself is not shown.

   Today this step needs a developer command. See [the unit runbook](../dev/stackchan-unit-measurements.md).

3. Run `body/scripts/stackchan_flash.py` with the USB port, backup path, token file, both IDs, and the Bot addresses.

   Replace the sample port, IDs, and token path with the values for your robot:

   ```sh
   python body/scripts/stackchan_flash.py --port /dev/ttyUSB0 \
     --backup "$HOME/stackchan-backup.bin" --token-file /path/from/approval \
     --device-id 02:00:00:00:00:28 \
     --client-id 00000000-0000-4000-8000-000000000028 \
     --xiaozhi-url ws://192.0.2.10:8765 --avatar-url ws://192.0.2.10:8766
   ```

   You will see each setup step printed. The tool saves a full flash backup before it writes firmware. This takes a few minutes.

4. Wait for the tool to finish.

   You will see a completion message with the backup and image paths. The robot restarts and shows a welcome screen with **Skip** and **Start** buttons.

5. Tap **Skip** on the robot's screen. Do not tap **Start**: it asks for the M5 app.

   You will see the app list.

6. Open **AI Agent**.

   You will see a Wi-Fi setup message with a hotspot name that starts with `Xiaozhi-` and the address `http://192.168.4.1`.

7. On your phone, join that hotspot, then open `http://192.168.4.1`.

   You will see a list of Wi-Fi networks.

8. Pick the network the Bot host uses, type its password, and save.

   You will see the robot leave the hotspot, join your network, and connect to the Bot. Your phone goes back to its usual network.

## Fix a problem

- **The robot says "Waiting for response timeout" again and again:** The Bot does not know this robot. Check that you paired the same Device-Id and Client-Id you gave the setup tool, then restart the robot.
- **No hotspot appears:** The robot already has a saved network. If that network is wrong, run the setup tool again, then repeat steps 5 to 8.
- **The token file is missing:** Pair the robot again and use the new file path.
- **The backup is missing:** Choose a new backup path and run the setup again. The tool will make a backup before writing.
- **The robot will not connect by USB:** Try another data cable. Hold the reset button for about three seconds, then retry.
- **The setup stops on the ESP-IDF check:** Install ESP-IDF 5.5.4 and retry.

Keep the robot on your home network. It talks to the Bot over the local network only. The software stop cannot cut motor power. Use the robot's power switch to stop its servos.
