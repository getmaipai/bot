# StackChan wireless firmware update (design, 2026-11-14)

Owner ask: the robot runs on battery and is no longer connected to the Studio, so a firmware change must reach it over Wi-Fi,
with a clear animated "updating" icon on its screen. One last USB flash may be needed to give the unit an updater.

## What exists today (read from the 0.2.86 build tree)

- Partitions: `ota_0` and `ota_1` (0x4f0000 each), `otadata` at 0xd000, `assets` (4 MB) at 0xa00000, `nvs` at 0x9000 (never written
  by an update).
- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y` is already set in the build's sdkconfig, so the bootloader flashed with 0.2.86 already
  rolls an unvalidated new image back. No bootloader change is needed.
- `CONFIG_STACKCHAN_XIAOZHI_OTA_CHECK` is off (patch 002 and 003 era): the stock check never runs. M5's `Hal::updateFirmware`
  (menu "About") uses xiaozhi `Ota::CheckVersion` plus `Ota::Upgrade(url)`; it is a manual menu path, has no hash check and talks to
  `ota_url` in NVS, which we leave empty.
- The unit already downloads audio over plain HTTP from the body (notification audio URL), so an HTTP pull from the body host is the
  same trust as every command today. The hub verifies the release signature (ed25519, `verifiedStackChanManifest`); the unit cannot
  verify ed25519, so integrity on the unit is a SHA-256 of the image supplied in the same authenticated MCP call.
- Residual risk, stated plainly: an attacker who can alter traffic on the home LAN can already issue any command to the unit. The
  update adds no new trust. TLS with a pinned hub certificate (wss later, see the Tailscale decision) closes it for commands and
  updates together; it is a follow-up, not part of this item.

## Design

1. **Home** (`GET /api/devices/me/firmware-update`, body token): returns `{ available, version, sha256, size, url_token }` for the
   newest verified StackChan firmware (manifest verified with the release signing keys, the app part's hash from the signed manifest),
   or `available: false` when the unit's reported version is the same or newer. Also `GET /api/devices/me/firmware-update/app.bin`
   streams the verified file (hash re-checked while streaming) to the body only.
2. **Body** (`firmware_update.py`, one controller): every 10 minutes and on connect asks Home; decides with a pure function
   `should_update(...)`: unit version older, idle (no turn, no timer or alarm, not asleep in a call), not muted, battery at or above 40
   percent or charging, last attempt for this version older than 6 hours after a failure, unit link healthy, `robot.firmware.auto`
   setting not off (default on). It fetches the file from Home into a temp file, checks size and hash, serves it once to the unit
   from its own HTTP port under a random one-time path, and calls the unit tool `self.firmware.update`.
3. **Unit** (patch 133, new file `maipai_update.cpp`): tool `self.firmware.update {url, sha256, size, version}`. Refuses unless
   idle and battery or charger conditions hold. Downloads with `esp_http_client`, writes the INACTIVE slot with `esp_ota_begin`,
   `esp_ota_write`, streams SHA-256 (mbedtls) and compares with the given hash and size before `esp_ota_end` and
   `esp_ota_set_boot_partition`. Any mismatch, timeout (120 s without data) or write error aborts, leaves the running slot alone and
   reports `firmware_update_failed` with a reason. Success reports `firmware_update_done` and reboots.
4. **Rollback**: the new image stays pending-verify. It calls `esp_ota_mark_app_valid_cancel_rollback` only after the hub link is up
   and the first face is drawn. A 5 minute watchdog without that mark calls `esp_ota_mark_app_invalid_rollback_and_reboot`, and a
   crash or reset before the mark makes the bootloader return to the old slot by itself.
5. **Icon**: while downloading and while rebooting, the face skin overlay shows a small spinner ring (arc rotating, drawn with the same
   primitives as the song title overlay of patch 123, palette tokens only) with a thin progress bar under it. It yields only to the
   mute mark (which stays visible). It clears on failure at once, and on success by the reboot. Home shows "Robot is updating" on
   the existing robot status row (reuse the status mechanism, no new surface) from the `firmware_update_started` event.
6. **Assets**: the 4 MB assets partition changes only when generated assets change (sounds, phrases, wake words). It is not
   part of this item. When it must change, that release says so and the unit needs USB (or the xiaozhi assets download) once; the
   update controller skips an app update whose manifest asset hash differs from what the unit reports unless the release marks the
   app image compatible with the older assets (`assets_compatible: true`).

## One-time step

The 0.2.86 to 0.2.93 firmware has no updater tool, so ONE USB flash of the first updater firmware is needed. After that, every
app-only firmware release is Wi-Fi. Flash only the app image and otadata as before (never NVS).

## Tests

- Python: `should_update` truth table (battery, charging, muted, in turn, timers, version, backoff, setting), manifest and hash
  verification, one-time URL, failure backoff.
- TypeScript (Home): route returns nothing for an unverified manifest, a same or newer unit version, or a missing file; hash check.
- Firmware: host-compiled unit test of the pure parts (version compare, the accept/refuse rule, SHA-256 compare); the slot logic
  is reviewed against the ESP-IDF OTA sequence line by line (documented in the patch header).
