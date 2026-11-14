# StackChan firmware image 1: what is in it and how it is flashed (2026-11-14)

Image 1 is the single USB flash. After it the unit has the updater (patch 133), so later firmware goes over Wi-Fi.
Nothing in this plan writes NVS: the saved pairing and the saved Wi-Fi networks stay.

## What is in it

Everything in the 0.2.86 firmware (patches up to 131) plus:

| Patch | What |
|---|---|
| 132 | Expressive faces (joy, content, excited, shocked, curious, love, worried). |
| 133 | The firmware updater (pull, verify, write the inactive slot, roll back by itself) and its icon. |
| 140 | Song title: white text on a solid black bar at the bottom edge, bolder and slightly larger. |
| 141 | Beep root cause. The charger sounds used the battery current direction, which flips with the servo load and with a weak USB supply, so plug-in and unplug cues played every minute or two. Now the AXP2101 VBUS-good bit, a change must hold 10 s (an unplug 20 s), every cue has a minimum gap (plug-in 30 s, low battery 10 min, shutter 1.5 s, ...), and the unit reports `sound_played` (name and source) and `power_poll` (reading and flap count, once a minute). |
| 142 | The stock tones that bypassed the sound gate: the "ready" chime is gone; an alert's sound, the low battery popup and the photo shutter go through the gate. The wake word answer, the timer tone and the offline wake tone are untouched. |
| 143 | The word "Offline" in the upper left shows after 45 s without the hub (was 10 s). |
| 144 | Fallback hub endpoint. The voice and avatar channels try the saved home address; after two failed attempts (or a 2 s TCP probe with no answer) they try `ws://192.168.2.1:<same port>` with the same saved pairing token, and retry home about once a minute (and probe it while connected on the fallback). 192.168.2.1 is the fixed address macOS Internet Sharing gives the laptop on its own Wi-Fi. A third (public wss) entry is one more row in `main/hal/maipai_fallback.cc` and one more state in the two connect loops. |

Not in image 1 (images 2 to 4, over the air): strict Wi-Fi priority, the QR scan, MicroLink, the settings page.

## The image

Built with `MAIPAI_FIRMWARE_VERSION=0.2.102` from the tree under `~/esp/stackchan-build/image1/build`.
Folder: `~/esp/stackchan-build/image1/image1-0.2.102/` with `bootloader.bin`, `partition-table.bin`, `ota_data_initial.bin`,
`maipai-stackchan.bin` (the app, 3,282,144 bytes = 0x3214e0; the app slot is 0x4f0000 = 5,177,344 bytes, 37 percent free),
`generated_assets.bin`, `flash_args` and `SHA256SUMS`.

## USB flash steps

Needs a physical step: the unit connected to the Studio by a USB-C data cable (the same port and cable as the 0.2.86 flash;
the port shows as `/dev/cu.usbmodem*`).

1. Plug the unit into the Studio and leave it on. `ls /dev/cu.usbmodem*` names the port (one line).
2. Dry run (shows the plan, writes nothing; the first run reads the whole flash as the backup):

   ```bash
   cd ~/Developer/github.com/getmaipai/bot/body
   uv run --frozen python scripts/stackchan_flash_nonvs.py --port /dev/cu.usbmodemXXXX \
     --image ~/esp/stackchan-build/image1/image1-0.2.102 \
     --backup ~/stackchan-backups/stackchan-full-2026-11-14.bin --dry-run
   ```

3. The real run (reads the 16 MB backup first, about 5 minutes at 921600 baud, then writes only the parts that need writing):

   ```bash
   uv run --frozen python scripts/stackchan_flash_nonvs.py --port /dev/cu.usbmodemXXXX \
     --image ~/esp/stackchan-build/image1/image1-0.2.102 \
     --backup ~/stackchan-backups/stackchan-full-2026-11-14.bin
   ```

   It refuses to write if the backup is not exactly 16 MB, if a part is missing, or if any part would overlap the NVS partition
   (0x9000 to 0xd000). It writes the bootloader and the partition table only when their bytes differ from the backup, then the OTA
   data (0xd000), the app (0x20000) and the assets (0xa00000). The unit resets by itself.
4. Unplug. The unit boots on the old pairing and joins its saved Wi-Fi.

To restore: `esptool write_flash 0x0 <the backup>` brings back the exact 0.2.86 flash, NVS included.

## After the boot, check

1. The host log (`/usr/local/maipai-home/data/logs/launchd.err.log`) shows `unit firmware: fw version=0.2.102`. From that moment the host stops
   forcing the unit muted and pushes the normal sound policy (`robot activity: sound policy follows the firmware ... forced_mute=off`).
2. The new faces draw, the song title is a white bold line on a black bar, no tone on connect, no "Offline" for a hub restart under 45 s.
3. No plug-in or unplug beeps: `robot activity: unit played a sound name=... src=...` lines appear only for real events; `unit power`
   lines (once a minute) show `vbus`, `charging`, `ext` and `flaps`.
4. Away from home: the laptop relay on 192.168.2.1 (`data-scratch/bin/trip-relay.py`, ports as the hub uses) and the unit joined to the
   laptop's Wi-Fi: the serial log and the host log show the fallback line and the voice and avatar channels connect; back on the home
   network the unit returns home within about a minute. The laptop's Wi-Fi must be one of the unit's saved networks first (add it before
   leaving; Home refuses to send a password over the plain link today, so use the unit's own setup page or quick settings panel).

## Bench proof of the updater (before unplugging, per the combined-image proposal)

1. A version-bump image (0.2.103, same tree) is delivered over the air: the unit reports 0.2.103.
2. A deliberately bad image (built with `recipe.sh --dev-voice-url ws://192.0.2.1:9`, a hub address that never answers, version
   0.2.104-bad) is delivered: it never reaches the hub link, so it never marks itself valid and the 5 minute watchdog rolls back;
   the unit reports 0.2.103 again.
3. A good image (0.2.105) is delivered and installs.

Not yet verified: how the three bench images reach the unit without a signed release each time. The normal path is a signed release
the hub installs (a hub restart per image, and each restart is a reconnect). A direct path is the unit tool `self.firmware.update`
(url, sha256, size, version) called with a one-time URL for a file served from the Studio; it needs a small harness through the body's
tool channel. Decide before the bench which one is used.

## What is not verified

Nothing has run on a unit: the image compiled and the new strings are in the binary (`sound_played`, `power_poll`, `Home address failed
twice`, `Hub reached through the fallback endpoint`, `stock_alert`, `stock_low_battery`, `camera_photo`). The VBUS-good bit
(register 0x00, bit 5) is the XPowersLib `isVbusGood` bit; confirm on the unit that `unit power` shows `vbus=1` on the cable and `vbus=0`
on battery. The free internal RAM with both channels open is not measured (the fallback adds no second session: only one of the two
addresses is connected at a time per channel).
