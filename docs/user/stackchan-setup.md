# Set up a StackChan

You need a StackChan, a USB-C data cable, a Bot host, and a computer with ESP-IDF 5.5.4.

## Steps

1. Connect the StackChan to the setup computer with the USB-C data cable.

   You will see the robot charge or turn on.

2. Open the Bot dashboard on the setup computer and choose **Pairing**.

   You will see the pairing page. It only works on the computer running the browser.

3. Turn on the StackChan and connect it to your home Wi-Fi.

   You will see its Device-Id and Client-Id appear in the pending list.

4. Select **Approve** beside the matching device.

   You will see a private token file path. The token itself is not shown.

5. Run `body/scripts/stackchan_flash.py` with the USB port, backup path, token file, both IDs, and the Bot addresses.

   Replace the sample port, IDs, and token path with the values for your robot:

   ```sh
   python body/scripts/stackchan_flash.py --port /dev/ttyUSB0 \
     --backup "$HOME/stackchan-backup.bin" --token-file /path/from/approval \
     --device-id 02:00:00:00:00:28 \
     --client-id 00000000-0000-4000-8000-000000000028 \
     --xiaozhi-url ws://192.0.2.10:8765 --avatar-url ws://192.0.2.10:8766
   ```

   You will see each setup step printed. The tool saves a full flash backup before it writes firmware.

6. Wait for the tool to finish.

   You will see a completion message with the backup and image paths. The robot restarts with the Bot firmware.

## Fix a problem

- **No device appears:** Check that the robot and Bot host use the same Wi-Fi. Restart the robot and wait a minute.
- **The page says to open it locally:** Open the page in a browser on the Bot computer.
- **The token file is missing:** Approve the pending device again and use the new file path.
- **The backup is missing:** Choose a new backup path and run the setup again. The tool will make a backup before writing.
- **The robot will not connect by USB:** Try another data cable. Hold the reset button for about three seconds, then retry.
- **The setup stops on the ESP-IDF check:** Install ESP-IDF 5.5.4 and retry.

Keep the robot on your home network during setup. The device connects to the Bot over the local network. The software stop cannot cut motor power. Use the robot's power switch to stop its servos.
