# StackChan: pieces we have, gaps, and verdicts (2026-10-14)

Status: DRAFT, research only. Nothing flashed or run; every claim is read from source. Hardware has not arrived.
Companion to `design-stackchan-2026-10-14.md` (the body design) and `design-robot-api-2026-10-14.md` (the robot object).
Where this note and section 3 or 5.2a of the body design differ, this note wins.

## 1. The headline

The stock StackChan firmware cannot meet the "no live third party" rule. It speaks two protocols and has vendor defaults compiled in:

| Channel | Protocol | Default destination | Runtime override |
|---|---|---|---|
| Voice and tools | xiaozhi WebSocket plus MCP | OTA host `api.tenclass.net` (third party) | Yes: NVS key `wifi:ota_url`, set from the Wi-Fi AP page or by serial NVS patch |
| Avatar, camera stream, motion, text, dance | M5 binary frames at `/stackChan/ws?deviceType=StackChan` | `47.113.125.164:12800` (M5Stack) | No: compile-time `CONFIG_STACKCHAN_SERVER_URL` only |
| Device registry and MQTT | HTTP and MQTT | `ezdata2.m5stack.com`, `uiflow2.m5stack.com:1883` | Unknown |
| Time | SNTP | `pool.ntp.org`, `time.google.com`, `cn.pool.ntp.org` | The OTA reply's `server_time` can replace it |

Consequence: we build our own firmware, once, reproducibly (ESP-IDF 5.5.4, pinned and checksummed, per "download, don't vendor"),
with our URLs compiled in and the persistent-channel patch. Until then, firewall the four vendor hosts above.

## 2. Pieces we have, by robot-API part

| Robot part | Native ability | Piece we have | Source and license | Status |
|---|---|---|---|---|
| connection | Wi-Fi, BLE and AP provisioning | AP page "Custom OTA URL"; serial NVS patch tool | esp-wifi-connect; warble `nvs-tool` (MIT) | Have |
| connection (always on) | WS only opens per session | Firmware patch holding the WS open from boot, backoff 5 to 60 s | kisaragi `stackchan-mcp` firmware (MIT) | Have, to port |
| voice in | 16 kHz Opus, 60 ms, dual mics, wake word "HiStackChan" | Opus decode, hello handshake, listen modes | xiaozhi docs; xinnan-tech, kisaragi, warble | Have |
| voice out | 24 kHz Opus accepted via server hello | Pacing recipe: 5-frame prebuffer, wall-clock pacing, 420 ms drain before `tts stop` | warble (Go, MIT) | Have |
| Opus in Python | none | `opuslib` (BSD-3) over system libopus | PyPI | Have |
| tools | on-device MCP server | Hand-rolled JSON-RPC session: id map, 10 to 30 s timeouts, cursor loop | kisaragi `esp32_client.py`, xinnan `mcp_handler.py` | Have, to rebuild |
| head | 2 servos, yaw -128..128, pitch 0..90 | `self.robot.get_head_angles`, `set_head_angles` | M5 `hal_mcp.cpp` (MIT) | Have, with a bug (section 4) |
| leds | 12 RGB, 0..168 | `self.robot.set_led_color` (left and right neon lights, one color) | M5 `hal_mcp.cpp` | Have |
| reminders | on-device timers | `create_reminder`, `get_reminders`, `stop_reminder` | M5 `hal_mcp.cpp` | Have |
| eyes, mouth | avatar face | ControlAvatar 0x03 on the avatar channel; `llm {emotion,text}` on the xiaozhi channel | M5 `hal_ws_avatar.cpp`; xiaozhi | Have (two routes) |
| camera, on demand | GC0308 320x240 | `self.camera.take_photo`: server gives `capabilities.vision {url, token}` in `initialize`, device POSTs multipart JPEG | xiaozhi `esp32_camera.cc`; xinnan `vision_handler.py` | Have, see section 4 |
| camera, continuous | JPEG frames, quality 20, 350 or 700 ms cadence (about 2.9 fps ceiling) | StartCameraStream 0x05 on the avatar channel | M5 `hal_ws_avatar.cpp` | Have, rate unmeasured |
| identity and pairing | `Device-Id` (MAC), `Client-Id`, bearer token | Per-device token issued in the OTA reply, allowlist on `Device-Id`, admin approval | xinnan `core/auth.py`; xiaozhi `ota.cc` | Have |
| attention without speech | `alert {status,message,emotion}` | Built-in vibration sound plus text | xiaozhi | Have, version unverified |
| speaker identity | none in protocol | Bot does voiceprint on uplink audio itself | xinnan pattern | Build |
| face recognition | none on device | Ship without it (ruled); tracking and voice identity | n/a | Ruled |
| battery, power | AXP2101 PMIC | Not exposed over MCP in anything read | none found | Gap |
| touch, NFC, IR, IMU | 3-zone touch, NFC, IR | Base xiaozhi tools exist; not read (v2.2.4 source fetched at build time) | xiaozhi 78 | Gap, unverified |
| reference server | M5's own avatar server | Go server, database, admin UI | M5 `server/` (MIT) | Read for the protocol; not our runtime |

## 3. Gap research verdicts

| Gap | Verdict | What we do |
|---|---|---|
| A. Server pushes an action with no user turn | PARTIAL | Stock firmware opens the WS only per session. Port kisaragi's one-function patch so the WS stays open; then `tts`, `listen`, MCP and `alert` all work from idle. |
| B. Full duplex and barge-in | PARTIAL | Protocol pieces exist (`abort`, `listen` realtime, hello `features.aec`). No server we read does echo-free duplex. Honor `abort`, stop pacing at once, send `tts stop`, treat uplink during Speaking as live only when `aec` is true. AEC quality unmeasured. |
| C. Python Opus | SOLVED | `opuslib` plus pinned system libopus, documented in the installer. |
| D. Transport security | PARTIAL | Device trusts public CAs only and is not a tailnet client, so MagicDNS names do not resolve for it. Use `ws://` on a trusted LAN or VLAN with a per-device token. Private-CA `wss://` is a later firmware feature. Audio and camera are unencrypted on the LAN; say so in the docs. |
| E. Identity and pairing | SOLVED | Server-issued tokens through the OTA reply, `Device-Id` allowlist, admin approval in the bot UI. M5's constant token `hi-stack-chan` is replaced. |
| F. Camera | PARTIAL | `take_photo` for on-demand sight; the avatar stream for tracking. Real fps and latency unmeasured. |
| G. MCP client | SOLVED | Hand-roll the JSON-RPC session. |
| H. Provisioning | PARTIAL | OTA URL needs no rebuild. The avatar server URL does. One custom build covers both. |
| I. Other message types | SOLVED | Hello, framing versions, message list and timeouts are in source. Risk is version drift: our research source is newer than M5's v2.2.4 base. |

## 4. Defects and traps found

- `set_head_angles`: `yaw` and `pitch` use -9999 as "unchanged", so the declared minimum is -9999, not the documented -128 or 0.
  The tool accepts out-of-envelope values down to -9999 and the clamp is only the description's advice. Our translator clamps
  itself to the measured envelope and never relies on the tool to refuse.
- `take_photo` needs the vision URL in `initialize`. The avatar-channel firmware never appears to set one, so the explain route may
  not work on StackChan. Settle on the unit; the avatar camera stream is the fallback.
- LED tool sets all lights one color. A per-LED ring needs a different route (the avatar channel or a firmware tool).
- The camera-on indicator is the RGB LEDs, lit by the translator, per the ruling. That means the indicator is software: a stream
  started by any other path would not light it. The translator is the only code allowed to start a stream.
- Time: until NTP is blocked and replaced by `server_time`, the device reaches public NTP hosts. Treat as a vendor-contact leak.

## 5. Unmeasured, needs the unit

Servo limits and speed under load (pitch recommended 5..85 degrees); whether M5's build enables AEC; real camera fps, latency and
quality at 320x240; battery runtime and how to read charge; whether `notify`, `alert` and `glyph_push` exist in the v2.2.4 base;
base tool list and parameters; whether BLE can set `ota_url`; TLS clock behavior.

## 6. Design consequences

1. A `bodies/stackchan/` profile and a bot-repo service: the translator speaks xiaozhi (voice, MCP) and, in step two, the avatar
   channel (camera stream, face). Home pairs with the service; Home never speaks either protocol.
2. A firmware build recipe in the bot repo: pinned toolchain, our URLs, the persistent-channel patch, per-device token, NTP removed.
   Fetched and checksummed, not vendored. This is a new work item the body design did not list.
3. Robot API parts that StackChan cannot fill yet (battery, touch events, IMU) stay `NotSupported` until the unit is measured.
4. The fake body for tests replays recorded xiaozhi and avatar frames, so the whole translator is testable without hardware.

## 7. Decisions

Settled by Jesse, 2026-10-14:
1. Custom firmware build first; the stock firmware is not run against our server.
2. Step one is voice and tools only (xiaozhi side); the avatar channel and camera stream come in step two.

Settled by Jesse, 2026-10-15: StackChan estop is a software latch that rejects new motion and cancels host-queued targets. The firmware releases servo torque when idle but offers no remote torque cut; the physical stop is the power switch or unplugging the robot.

Open: which unit measurements to run first once it arrives (section 5 lists them).

## 8. Prior art and official docs (added after a second research pass)

Evidence is read from source and docs, not run. Full report: session scratchpad `gap-research/PRIOR-ART.md`.

### Closes or narrows a gap

| Gap | Finding | Use |
|---|---|---|
| H, zero tenclass contact | The `i41-eu/i41eu-StackChan` fork (branch `embody`) adds a build switch `STACKCHAN_XIAOZHI_OTA_CHECK`, default off, through a ~20 line patch to xiaozhi. Off means no call to the third-party OTA host. | Port the patch. |
| H, no OTA call at all | xiaozhi reads `websocket` `url`, `token`, `version` from NVS when it opens the channel. A pre-seeded NVS (`nvs_partition_gen`) gives a full session without any OTA request. | Use. |
| H, server address | M5 documents `CONFIG_STACKCHAN_SERVER_URL` and the override file `sdkconfig.defaults.local`. | Use. |
| D, private-CA `wss://` | ESP-IDF 5.5.4 `CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH` adds our CA to the bundle at build time. The TLS layer already uses that bundle, so no code change. | Use, later step. |
| B, duplex | One K151 build reports device-side AEC with continuous uplink working at 60% speaker volume, failing at 80%. The i41 fork uplinks the speaker reference channel, so server-side AEC is physically possible. Both are single-unit anecdotes. | Measure on our unit. |
| F, camera | Measured about 5 fps at 320x240 and 2.3 fps at 640x480 over a WebSocket (i41 author). Upstream avatar stream is slower. | Target 5 fps, confirm. |
| S5, sensors | i41 `HARDWARE.md` lists the drivers and registers: AXP2101 battery, INA226 current, BMI270 IMU, 3-zone touch, NFC, light and proximity, RTC. | Copy facts into our sensor map. |
| A, idle announcements | xiaozhi `notify {audio_url}` plays while idle with no mic. Newer than M5's pinned v2.2.4. | Needs a base bump. |
| Reproducible build | i41 `container.sh`, `release.sh`, `scan_secrets.py` and a pinned `espressif/idf:v5.5.4` image with SHA256SUMS. | Model for our recipe. |

Build and flash, from the upstream README and the i41 fork: ESP-IDF v5.5.4 only (6.x fails), `python3 fetch_repos.py`, `idf.py build`,
`idf.py -p <port> flash` on the head USB-C port; hold RST about 3 s until the green LED lights if it will not enter download mode.
Back up the whole flash before the first write. Partitions: 16 MB, two 4.94 MB OTA slots, 4 MB assets at 0xA00000.

### New gaps

- J. The three SNTP hosts are hardcoded in `hal_network.cpp` with no config. Patch to our server, or drop SNTP and use the OTA `server_time` plus the on-board RTC.
- K. Every stock boot posts the MAC, UUID, serial and chip info to the third-party OTA host. Block at the router until the patch is in.
- L. A battery read can abort the firmware: `Axp2101::IsCharging` calls `ESP_ERROR_CHECK` on an I2C timeout (reproduced on one K151 build). Any battery polling we add must be wrapped.
- M. Licence (corrected): `m5stack/StackChan` has no root LICENSE file, but `firmware/` and `server/` carry MIT licences and MIT file headers, so code from them may be reused with the notice kept. `app/` and `remote/` not checked beyond `remote/code/LICENSE`. Not a blocker.
- N. Version drift: M5 pins xiaozhi v2.2.4. Notify remains opt-in and is sent only when the connected device advertises `features.notify`; otherwise idle alerts retain the STACKCHAN-26 face/LED/spoken fallback. A downloaded and SHA256-checked v2.3.0 archive (`1b48ebd7863695bf80d384c6c09af6299a6d7d0e`, `51ab9575b6df400c88eeb3eff61255965229e40fd6c8b4807cd7c24603e42a53`) did not contain a `notify` handler or `audio_url`, so the pin is unchanged. Future bump tooling must verify source and archive checksum before any pin update. No hardware verification.
- O. Internal RAM is tight (about 35 KB free in the i41 build); TLS failed there when LVGL held internal RAM. `wss://` on our build is unmeasured.
- P. Private-CA verification needs a valid clock. The RTC is unset on a new unit, so first boot needs plain `ws://`, `server_time`, or a build-time epoch.
- Q. The i41 "Embody" path skips xiaozhi entirely: raw 24 kHz PCM and sensor events over our own WebSocket. We chose xiaozhi first; revisit once the unit is measured, since it removes the OTA flow and gives the AEC reference.

### Other projects worth reading

`a237821375/stackchan-xiaozhi` (MIT: servo protection, barge-in notes), `alexeyzel/chan-home-assistant` (ESPHome on the unit),
`andymai/stackchan-kai` (clean-slate Rust, LAN-only; long-horizon alternative), `dr-funchal/stackchan-kids` (MIT on its own changes).
Reddit, Hackaday and forum coverage returned nothing usable; non-GitHub community sources are not covered.

## Sources

COMMS.md and FIRMWARE.md research files (session scratchpad, not committed); m5stack/StackChan (MIT); 78/xiaozhi-esp32;
kisaragi-mochi/stackchan-mcp (MIT); xinnan-tech/xiaozhi-esp32-server; rebelthor/warble; BrettKinny/dotty-stackchan.
