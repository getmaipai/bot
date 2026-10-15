# StackChan custom firmware: build recipe design (2026-10-14)

Status: DRAFT, design only. Nothing built or flashed; the unit has not arrived. Every step marked UNVERIFIED is settled on the unit.
Inputs: `design-stackchan-pieces-and-gaps-2026-10-14.md` (gaps A to Q, section 8) and the research behind it.
Decided by Jesse, 2026-10-14: custom firmware first; step one is voice and tools (xiaozhi side) only.

## 1. Goal

One reproducible build that produces a firmware image which, from first boot, contacts only our bot service on the home network:
no M5Stack server, no third-party OTA host, no public NTP, no registry or MQTT host. Anyone can rebuild it and get the same checksum.

## 2. Licence and why the recipe fetches instead of vendoring

Corrected after Jesse's check: `m5stack/StackChan` is open source. It has no root LICENSE file, but `firmware/LICENSE` and
`server/LICENSE` are MIT (M5Stack, 2026), the firmware files carry MIT SPDX headers, and `remote/code/` has its own LICENSE.
The firmware pulls in xiaozhi-esp32 (MIT) and some BLE sample code under Unlicense OR CC0. MIT is compatible with our AGPL-3.0:
we may copy and patch with the copyright and permission notice kept.

The recipe still fetches upstream at a pinned commit and applies patch files, for a different reason: "download, don't vendor"
(dependencies come by lockfile and checksum, not copied in) and a small, reviewable diff against a moving upstream. Patch files that
derive from MIT work keep the source's notice in their header. Run the licence check (`docs/LICENSING.md`) once on the final
dependency list, including the `remote/` and `app/` folders if we ever use them (their licences were not read).

## 3. Layout in the bot repo

```
bodies/stackchan/firmware/
  recipe.sh              fetch, verify, patch, build, checksum (runs inside the container)
  pins.toml              upstream commit, xiaozhi v2.2.4 commit, IDF image digest, expected SHA256 of each fetched archive
  patches/               ordered *.patch, one change each, header says what and why
  config/sdkconfig.defaults.local.tmpl   our URLs and switches, filled from the install
  provision/             NVS template and the pairing tool (section 6)
  README.md              user-grade steps: backup, flash, restore
```

## 4. The build

- Toolchain: `espressif/idf:v5.5.4` container, pinned by digest. ESP-IDF 6.x is known to fail (missing `mqtt` component), so the pin is hard.
- Fetch: upstream firmware at one commit, then upstream's `fetch_repos.py` for its dependencies, which pins xiaozhi-esp32 v2.2.4 and
  the other components by commit. Our `pins.toml` records the top commit and we verify the result by a tree hash.
- Output: `stackchan-<our version>.bin` plus `SHA256SUMS`. Local build only, no push-triggered CI.
- Secrets: the build bakes in no token. Per-device tokens arrive through NVS at provisioning (section 6). A secrets scan runs on the
  output tree.
- Network during build is allowed for fetching pinned sources; the resulting image is checked by section 7.

## 5. Patch set

| # | Patch | Closes | Source idea | Size |
|---|---|---|---|---|
| 1 | Server URL from our config (`CONFIG_STACKCHAN_SERVER_URL`), default empty so an unprovisioned unit contacts nothing | H | M5's own override file | config only |
| 2 | Skip the xiaozhi OTA check (`STACKCHAN_XIAOZHI_OTA_CHECK` off); use the NVS `websocket` url, token, version | H, K | i41 fork | about 20 lines |
| 3 | Keep the voice WebSocket open from boot, reconnect with 5 to 60 s backoff | A | kisaragi | one function |
| 4 | Replace the three hardcoded SNTP hosts: ours, or none (use RTC plus our `server_time`) | J | ours, about 3 lines | tiny |
| 5 | Remove or stub M5 registry and MQTT start (`hal_ezdata.cpp`) so nothing dials those hosts | vendor hosts | ours | small |
| 6 | Wrap battery and PMIC reads so an I2C timeout returns an error instead of `abort()` | L | ours | small |
| 7 | Unique firmware identity so a stock OTA can never be offered | OTA safety | xiaozhi custom-board guide | config |
| 8 | Optional, later: custom CA in the certificate bundle (`CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH`) for `wss://` | D | ESP-IDF | config, needs RAM and clock tests |

Order of work: patches 1, 2, 4, 5, 7 first (they remove vendor contact and are small); 3 next (it enables idle pushes); 6 with the
battery part; 8 is a separate step after measurement (gaps O and P).

The avatar channel (`/stackChan/ws`) is not served in step one. With the server URL empty, the firmware must not dial it; patch 1
makes that explicit and the check in section 7 proves it. This is UNVERIFIED in source: confirm that an empty URL does not retry.

## 6. Provisioning, no rebuild per device

- Wi-Fi: the unit's own AP or BLE page, as stock.
- Our server and token: written to NVS, namespaces `websocket` (`url`, `token`, `version`) and `wifi` (`ota_url`), by a small tool that
  runs on the install host and writes the NVS partition over USB. The method (esptool plus the NVS generator) is the one warble's
  `nvs-tool` shows. Whether BLE can set these is UNVERIFIED.
- Pairing: the bot UI shows a pairing request keyed by the unit's `Device-Id` (MAC); an admin approves; the service issues a random
  per-device token and stores it. Revoking removes the token and the allowlist entry.
- First boot clock: the on-board RTC is unset on a new unit and the first connection is plain `ws://`, so it works without a valid clock.
  Our server supplies time through the first reply. UNVERIFIED which message the firmware reads (`server_time` is in the OTA reply,
  which patch 2 skips); settle on the unit, with a build-time epoch as the fallback (gap P).

## 7. Proving "no third party"

A build is not accepted until these pass, on a captured trace from the unit on an isolated network:

1. Static: grep the image and config for the vendor hosts and IPs found in the research (M5 server IP, the third-party OTA host,
   `ezdata2` and `uiflow2` M5 hosts, the three NTP names, `raw.githubusercontent.com`). None present, or present only in dead strings the trace shows never used.
2. Dynamic: boot, provision, run a voice turn, idle 30 minutes. Every packet's destination is our bot service or the access point's
   DHCP and DNS. DNS queries are listed and each name is justified.
3. Router rule: block the vendor hosts as defence in depth. The test is run once with the block off to prove the firmware itself behaves.

## 8. Flash, backup and restore (from the upstream docs and the i41 fork)

1. Dump the whole 16 MB flash first and keep it (`esptool` read). Restore writes it back at 0x0.
2. Flash the build over the head USB-C port. If it does not enter download mode, hold RST about 3 s until the green LED lights.
3. Official restore: M5Burner, "Only Official". The README states the stock restore path; keep it as the fallback.
4. Partitions are stock: nvs, otadata, two 4.94 MB OTA slots, 4 MB assets at 0xA00000, coredump. An update replaces the inactive slot
   only; updates come from our service (the OTA reply carries `firmware {version, url}`) once an update path is designed.
   Until then, updates are by USB.

## 9. Unknowns that block or change the recipe

- Whether an empty server URL stops the avatar channel cleanly (patch 1).
- Whether M5's build reads xiaozhi settings from NVS the same way as upstream xiaozhi when the OTA check is off.
- RAM headroom with TLS and AEC on (gap O); decides whether patch 8 is viable.
- Whether the v2.2.4 base has `notify`, `alert` and `glyph_push` (gap N).
- AEC enabled in M5's build, and its quality (gap B).
- `app/` (Flutter) and `remote/` licences, if we ever use them: not read.

## 10. Order of work

1. Pin the upstream commit and write `pins.toml`; reproduce an unmodified build in the container (needs only a PC).
2. Patches 1, 2, 4, 5, 7; build; run the static check of section 7.
3. When the unit arrives: backup, flash, provisioning tool, dynamic trace.
4. Patch 3, then 6; then measure gaps B, F, O, P and decide patch 8.

Step 1 and the static half of step 2 need no hardware.

## Sources

`design-stackchan-pieces-and-gaps-2026-10-14.md` section 8; m5stack/StackChan README and Kconfig; xiaozhi-esp32 docs (websocket, custom board);
ESP-IDF 5.5.4 docs (certificate bundle); i41-eu/i41eu-StackChan; kisaragi-mochi/stackchan-mcp; rebelthor/warble `nvs-tool`.
