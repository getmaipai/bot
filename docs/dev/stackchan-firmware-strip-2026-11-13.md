# StackChan firmware strip (2026-11-13)

The owner uses the unit for the voice agent and its settings only, and wants no Bluetooth. This note records the
six strip patches (095 to 099), what each one measured, what each one risks and what to check on the unit. The
audit that proposed them is `firmware-strip-audit-2026-11-13` (read-only, linker map of the 2026-11-12 build). Step 1
of that audit (core dump to flash) and step 8 (new clips) are other changes.

Nothing here has run on a unit. Every number below is from a real recipe build (ESP-IDF 5.5.4, pinned tree plus
patches 001 to 081), measured with `idf.py size` and the file sizes. The full `recipe.sh` run of all six patches
passed (all six `PATCH-OK`, `BUILD-OK`, tree clean after the reverse apply) and gave a byte-identical image to the
step-by-step builds: `stack-chan-maipai.bin` 3,176,864 bytes, `generated_assets.bin` 2,492,840 bytes.

## Sizes, step by step

Each row is one more patch on top of the rows above it, in the order built. "DIRAM" is the static internal RAM the
image holds (IRAM code, data, bss); what it gives up becomes internal heap, so `heap_stats` `int_free` on the unit
should rise by about that much (not yet measured on the unit).

| Step | Patch | App image (bytes) | Assets image (bytes) | Flash code / rodata | DIRAM used (bytes) |
|---|---|---|---|---|---|
| Baseline (patches 001 to 081) | | 3,812,368 | 3,794,083 | 2,497,732 / 1,138,856 | 211,583 (code 137,735, data 36,612, bss 36,208) |
| 2 assets partition grown | 095 | 3,812,368 (0) | 3,794,083 (0) | same | same |
| 3 CJK font and emoji out | 096 | 3,812,992 (+624) | 2,492,840 (-1,301,243) | 2,498,208 / 1,139,004 | 211,583 (0) |
| 4 Mooncake apps out | 097 | 3,264,944 (-548,048) | 2,492,840 | 2,104,628 / 1,004,204 | 187,331 (-24,252) |
| 5 Bluetooth off | 098 (needs 097) | 3,254,832 (-10,112) | 2,492,840 | 2,099,448 / 1,000,296 | 186,543 (-788) |
| 6 Wi-Fi only boards, fewer sounds | 099-wifi-only-and-fewer-sounds | 3,240,832 (-14,000) | 2,492,840 | 2,099,448 / 986,288 | 186,543 (0) |
| 7 JPEG decoder out | 099-no-jpeg-decoder | 3,176,864 (-63,968) | 2,492,840 | 2,057,256 / 982,756 | 168,291 (-18,252) |
| Total | | -635,504 (-16.7%) | -1,301,243 | | -43,292 |

Partition room, from the partition table built in step 2 (`gen_esp32part.py` on the built `partition-table.bin`):

| | Before | After |
|---|---|---|
| assets partition | 0xA00000, 4,194,304 bytes | 0xA00000, 6,225,920 bytes (0x5F0000, 6,080 KB) |
| assets free | 400,221 | 3,733,080 (with the step 3 image) |
| app slot (ota_0 / ota_1, 5,177,344 each) free | 1,364,976 | 2,000,480 |
| coredump (64 KB) | 0xE00000 | 0xFF0000 (last 64 KB of the 16 MB chip) |

Steps 4 and 5 interact: once the Mooncake apps were gone nothing referenced the Bluetooth controller any more, so the
linker had already dropped most of it in step 4. Step 5 then adds only 10 KB of flash and 788 bytes of RAM, but it
makes the result certain (the controller cannot come back through a stale default) and removes the BLE server source
from the build. Read steps 4 and 5 as one saving of about 25 KB of internal RAM and 558 KB of flash.

## The six patches

All are in `body/maipai_body/bodies/stackchan/firmware/patches/` and applied by `recipe.sh` after patch 081 (and after
the other builders' 083 to 094 once those land). Each header holds the intent, upstream file and the check list.

### 095 grow the assets partition (step 2)

`partitions.csv`: assets keeps its offset 0xA00000 and grows from 4 MB to 0x5F0000; the coredump partition moves from
0xE00000 to 0xFF0000 (it was the only thing in the way; it is unused until the core dump is on). Offsets of nvs 0x9000
(0x4000), otadata, phy_init, ota_0 and ota_1 are unchanged, so the pairing and Wi-Fi in NVS are untouched by the flash.
The recipe's assets size check moved from 4,194,304 to 6,225,920. The flash manifest, `release.sh` and `verify.sh` read
offsets from ESP-IDF's `flasher_args.json`, so they pick up the new `partition-table.bin` (written at 0x8000) with no
edit; the only hard-coded offset in the repo is a test fixture (0xa00000, still right).

Risk: the table is rewritten, so this change needs `partition-table.bin`, the app and the assets image flashed
together; an app flashed alone keeps the old table and the old 4 MB size. The partition is memory mapped whole, so
the larger size costs no RAM. A reader of the core dump by flash offset must use the new offset (the IDF reader
finds the partition by type).

Unit check: boot log "The partition size is 6080 KB" (Assets), `wake_stats` `armed=1` (wake word and stop word still
load), "unit boot" with the same device id (pairing kept), Wi-Fi joins without re-provisioning.

### 096 drop the Chinese font and the emoji (step 3)

The assets script is no longer given the text font or emoji collection, so `index.json` has no `text_font` or
`emoji_collection` key; the theme keeps the compiled-in `font_puhui_basic_20_4` (800 glyphs: ASCII, Latin-1, Latin
Extended). Nothing reads the emoji files (the avatar display overrides SetEmotion).

Strings the firmware draws that need glyphs, and the font that covers them:

- Every value in the en-US `language.json` (52 strings, including the Wi-Fi setup screen text "Wi-Fi Configuration Mode",
  "Hotspot: ", "Entering Wi-Fi configuration mode...", "Scanning Wi-Fi..."): all characters covered (checked by script
  against the font's character map).
- Literals in `stackchan_display.cc` ("Connecting to Wi-Fi...", "Connecting to Home...", "Quick settings", "Volume N",
  "Switching Wi-Fi", the brightness and Wi-Fi rows), `stackchan.cc` ("Offline"), `application.cc` ("Can't reach Home",
  "Please bind and set up in the mobile app.", "Upgrade successful, rebooting..."): all ASCII.
- The hotspot name `Xiaozhi-XXXX` and its address: ASCII. The Wi-Fi setup portal itself is a web page in the phone's
  browser and is not drawn by the unit.
- The one non-ASCII literal, the ellipsis in the sleeping face's "Zzz", is now three dots.
- Text from the host (the speech bubble) can hold typographic punctuation the basic font lacks. `SetChatMessage` now maps
  curly quotes, en and em dashes, the ellipsis, the bullet and the no-break space to ASCII.
- Not covered, and drawn as nothing (no placeholder box): Chinese characters (206 are in the font, the rest are not),
  emoji, and any symbol outside Latin. A saved Wi-Fi name in Chinese would show blank in the quick settings list.

Unit check: no "The font file ... is not found" line; an English reply with a curly apostrophe, an em dash and an
ellipsis shows them as ASCII; the sleeping face shows "Zzz..."; the quick settings and the Wi-Fi setup screen read
normally.

### 097 remove the Mooncake apps (step 4)

`main.cpp` no longer installs apps or runs the Mooncake loop: it initialises the HAL and calls `startXiaozhi()`, which
is what the unit did already whenever `startAiAgentOnBoot` was true (the default). The launcher, setup (servo
calibration, about, account, display, connectivity workers), app center, ESP-NOW controller, EzData, the vendor dance
app, the avatar phone-call app and the template are filtered out of the build, with the home indicator and the four hal
files only they used. The source files stay in the tree. Kept: the status bar, toast and reminder (`apps/common`), all
HAL services, the avatar websocket worker from patch 054, the dance keyframes in `stackchan/modifiers/dance.h` that
`self.robot.dance` plays, the quick settings panel and the Wi-Fi setup captive flow (esp-wifi-connect, softap, DNS and
HTTP server and the portal page are in the map).

Risk: the home indicator was the only way from the face to the launcher, and so to the vendor Setup app (servo
calibration, vendor Wi-Fi page). That way is gone. Anything that stored `startAiAgentOnBoot=false` no longer has a
launcher to land in. Servo calibration from the vendor app is no longer on the unit.

Unit check: "unit boot" with the firmware version; the face appears; `wake_stats` `armed=1`; a spoken reply; the status
bar appears after the first show; a swipe opens the quick settings (volume, brightness, Wi-Fi switch); a head pet
reacts; `stack_stats` and `heap_stats` lines appear (`int_free` about 24 KB above the baseline); camera stream lines when
the host asks; the Wi-Fi setup screen with the hotspot name when no saved network is in range; a dance tool call.

### 098 Bluetooth off (step 5, needs 097)

The recipe sets `CONFIG_BT_ENABLED=n` and checks it in the finished `sdkconfig`; the patch drops `hal_ble.cpp` and the
`bleprph` helper tree from the build. Nothing in agent mode started Bluetooth: the BLE server was called only from the
vendor dance app (`app_dance.cpp:48`) and the setup app's connectivity worker, both removed by 097. `hal_ble.cpp` has no
other caller, which is why this step needs 097.

Risk: phones cannot reach the unit over Bluetooth any more (the vendor app and its BLE setup page).

Unit check: nothing about Bluetooth or NimBLE in the boot log; `int_free` and `int_min` in `heap_stats` higher than
before steps 4 and 5; everything else as for 097.

### 099 Wi-Fi only boards and fewer sounds (step 6)

The 4G modem boards (`ml307_board`, `nt26_board`, `dual_network_board`) and the USB RNDIS board are not built, and the
ten sounds the disabled activation flow used (digits 0 to 9, `activation.ogg`, 25,953 bytes) are not embedded; all their
call sites were already commented out. The esp-ml307 library stays linked because its network classes are what the Wi-Fi
board and the websocket protocol use; only its modem code left, and that code was already unreferenced after step 4 (flash code did not change in this step; the saving is the sounds and some strings). The audit
also listed `err_pin`, `err_reg` and `upgrade`; they are kept because `application.cc` still names them and dropping
them needs a source patch there (14.7 KB, not worth a merge conflict). `welcome`, `wificonfig`, `camera_shutter` and
`new_notification` are kept as well: the unit plays them.

Risk: low. A missing sound would be a link error, and the build links.

Unit check: the popup, exclamation, success and low_battery tones still play; the wificonfig tone on the Wi-Fi setup
screen; the camera shutter on a photo request; the websocket connects as before.

### 099 JPEG decoder out (step 7)

Proof that the decoder is unused: its only caller of the wrapper (`jpeg_dec::decode_to_lvgl`) is the avatar websocket's
`DataType::Jpeg` case, which decoded phone-call video frames for the vendor video window (removed by 097; nothing
subscribes to `onWsVideoFrame`); the host's avatar server never sends type 0x02 to the unit, only receives it
(`avatar/server.py` sends 0x03, 0x04, 0x05 and the hello); xiaozhi's `jpeg_to_image()` is reachable only under
`CONFIG_XIAOZHI_CAMERA_ALLOW_JPEG_INPUT`, which is off for the GC0308 camera. The case now ignores such a frame, and
`jpeg_decoder.cpp` and `jpeg_to_image.c` are not built. The encoder (camera stream, snapshots) is linked as before: its
objects are in the map and its IRAM (9,799 bytes) is untouched. The decoder's IRAM (about 18 KB: color convert, scale,
IDCT) is gone.

Risk: a future feature that shows host-sent video on the unit would need the decoder back (drop this patch).

Unit check: camera frames still reach the host (stats lines with frames and no encode failures; "what do you see" gets
an answer); `int_free` about 18 KB higher.

## Dropping one step

Remove its `apply_repo_patch` line in `recipe.sh`. Steps 095, 096, 097, 099 (either file) are independent of each
other (each applied alone and each left out, in a clean tree, with `git apply --unidiff-zero --check`). 098 needs 097.
For 098 also remove the two lines tagged "patch 098" in `recipe.sh` (`CONFIG_BT_ENABLED=n` and its check).

## Flash order and what is not verified

Not verified: everything on the unit. Not measured: the real `int_free` gain, boot time, the glyph rendering (checked
against the font table, not on the screen), the bubble text with the normalizer, the Wi-Fi setup screen, the camera
stream after the decoder is gone, the larger assets mapping at boot.

Suggested order (three flashes, a boot test after each; flash the partition table with the app and assets in flash A):

1. A: 095 + 096 (+ the 099 sounds). Assets side only; checks above for 095 and 096.
2. B: 097 + 098. The big code removal and Bluetooth; the check list for 097 and 098.
3. C: 099-no-jpeg-decoder. Camera path; check frames and `int_free`.

One flash of everything is possible (the recipe builds all six), but a fault would then not say which step caused it.
