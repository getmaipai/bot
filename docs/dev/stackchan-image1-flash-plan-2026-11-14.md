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
| 146 | The fallback works on any subnet and never hands the token to a stranger's network. The fallback host is the unit's current Wi-Fi gateway first (the laptop on its own Internet Sharing network, whatever address macOS picked), then 192.168.2.1, chosen at each attempt. The fallback only runs on a Wi-Fi network whose name starts with `maipai` (case-insensitive): name the laptop's sharing network `maipai-trip`. A friend's router or a hotel gets nothing. |

Not in image 1: a robot and a laptop on the SAME Wi-Fi that is not the laptop's own (a friend's network). That needs the unit to know the laptop's address and to trust it, which is a separate design (see `stackchan-away-trip-and-permanent-2026-11-14.md`). Not in image 1 either (images 2 to 4, over the air): strict Wi-Fi priority, the QR scan, MicroLink, the settings page.

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
4. Away from home: the laptop relay on the laptop's sharing address (found by the script) (`body/scripts/trip_relay.py`; a copy is in `data-scratch/bin/trip-relay.py`; ports 62923 and 62924 as the hub uses) and the unit joined to the
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

## Rehearsal at home (before leaving, about 15 minutes)

The laptop plays the friend's house. You need: the iPhone and its USB cable, the laptop, the robot.

1. On the iPhone: Settings > Personal Hotspot is on ("Allow Others to Join" can stay off; the USB cable is enough).
2. Plug the iPhone into the laptop by USB. Trust the computer if asked. The laptop gets internet through it.
3. On the laptop: System Settings > General > Sharing > Internet Sharing. Share from the iPhone USB connection, to Wi-Fi. Open the
   Wi-Fi options: Network Name `maipai-trip`, Security WPA2 Personal, a password you will remember. Turn Internet Sharing on.
   The laptop's Wi-Fi is now its own network. (The laptop can no longer be on your home or your friend's Wi-Fi at the same time:
   that is why its address stays the same everywhere.)
4. Turn Tailscale on in the laptop's menu bar. In Terminal: `python3 ~/Downloads/trip-relay.py --doctor` (the file from this chat;
   the same program is `body/scripts/trip_relay.py` in the bot repo). It prints the laptop's addresses, the address the robot will
   see, a reminder about the network name, and OK for both Studio ports.
5. Start the relay: `python3 ~/Downloads/trip-relay.py` and leave that window open. It prints `waiting for the robot`.
6. Teach the robot the laptop's network (once). The robot opens its own setup page only at power-up, and only when it has no saved
   network or none of them is reachable within 60 seconds (read from the firmware: `TryWifiConnect`, `CONNECT_TIMEOUT_SEC` 60; the
   StackChan has no gesture that opens it). So, at home: in Home open the Robot Wi-Fi card on the Devices page and Forget your
   home network (the robot stays connected until it restarts), then switch the robot off and on. With no saved network it opens its
   setup hotspot at once (the face says to connect to a hotspot named `Xiaozhi-...`). Join that hotspot with your own phone (not the
   iPhone that is plugged in), open `http://192.168.4.1`, and add TWO networks: `maipai-trip` (the password from step 3) and your
   home Wi-Fi again (the list holds up to 10 and the robot joins the strongest one it can see). Finish with the page's exit button.
   The robot joins your home Wi-Fi (stronger) and now knows both. (At the friend's house you can skip all of this if it was done:
   the robot does not see your home Wi-Fi there, sees `maipai-trip`, and joins it.)
   Not verified on this unit: adding two networks in one setup-page session, and the page's exit button; if the page only takes one
   network per visit, repeat the power-cycle for the second.
7. Make the robot use the laptop's network now (at home it prefers the stronger home Wi-Fi): swipe up on the robot's face for the
   quick-settings panel and pick `maipai-trip` under the saved Wi-Fi (per the firmware notes; not verified on this unit), or switch
   your home Wi-Fi off for a minute so the robot loses it and picks `maipai-trip`. Home address unreachable now, so after two tries the
   robot uses the laptop. Watch the relay window: `robot connected from 192.168.x.y to port 62923`, then port 62924. Ask the robot a question: it answers.
   Say the wake word, set a timer, play a song and watch the title.
8. Back at home: stop the relay, turn Internet Sharing off. The robot loses `maipai-trip` and rejoins your home Wi-Fi by itself (the
   home address is also retried once a minute while it is on the fallback).

If step 7 does not connect: the relay window says why (the Studio did not answer: Tailscale is off; no robot connection at all:
the robot is not on `maipai-trip`, or its name does not start with `maipai`). The robot at the trip still works alone (faces, timers,
music dance, phrases) without chat.

## At the friend's house

Repeat steps 1 to 3 and 5: iPhone USB, Internet Sharing from the iPhone to the Wi-Fi network `maipai-trip`, Tailscale on, the relay
running. The friend's Wi-Fi is never used: no address of his network can clash with the laptop's own network. The robot joins
`maipai-trip` (saved once, in step 6).

## Is the token safe on the fallback?

The robot sends its pairing token to the gateway of the network it is on. The fallback therefore only runs on a network named
`maipai...`, which the unit joins only with the password you set; a lookalike network cannot complete the WPA2 handshake without it.
On any other network the log says `fallback not used` and no connection is made to that network's gateway. The relay never reads or
prints the stream. Rotate the robot's pairing (re-pair in Home) if the laptop network's password is ever shared.
