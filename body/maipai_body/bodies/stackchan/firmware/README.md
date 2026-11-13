# StackChan firmware

`recipe.sh` builds the pinned StackChan source with the MaiPai firmware patches. It requires the pinned ESP-IDF version in `pins.toml` and the tools installed by ESP-IDF.

## Reproducible release

Use `release.sh --date YYYY-MM-DD [--version 1.0.0] --signing-key PATH|keychain:ITEM --output <directory>` to build with `espressif/idf:v5.5.4`; `keychain:ITEM` reads the private key from the macOS Keychain into a private temporary directory. Along with the existing release metadata, it ships the bootloader and partition table plus `flash-manifest.json`; offsets come from ESP-IDF's `flasher_args.json`, and the manifest is validated and signed with the supplied key. `verify.sh [--public-key PATH] <directory>` requires the release's Ed25519 public key PEM and checks every listed checksum, manifest signature and layout, and part size and SHA256. A release refuses to start unless StackChan and every dependency are pinned by full git commit, `repos.json` and `dependencies.lock` by SHA256, and, for a container build, the image by digest. Container builds require Docker or a compatible engine. If no container engine is installed, the documented fallback is to export a local ESP-IDF 5.5.4 toolchain and run `recipe.sh` directly; it still enforces the pinned version.

Patch 004 removes public NTP host strings from firmware source when `CONFIG_STACKCHAN_NTP_SERVER` is empty, as set by the recipe. At first boot, the device uses plain `ws://` to reach the provisioned host. The host must supply `server_time` (Unix epoch seconds) in its first OTA reply so the firmware can set its clock before a later TLS connection. Until a valid clock is established, provision `ws://`; a device must not attempt `wss://` with an unset RTC. The current Bot xiaozhi service does not implement the OTA exchange yet, so this host-side time handoff and TLS transition remain unverified and must be completed before private-CA TLS is enabled.

Firmware updates are a deliberate host-side operation: an administrator reviews and approves an image, verifies its checksums, and provisions it through the supported local process. The service OTA response never advertises `firmware.url`.

Patch 009 makes a failed common I2C register read log a warning and return zero. This covers the AXP2101 charge-direction read at register `0x01`, so `Axp2101::IsCharging()` returns false on an I2C timeout instead of aborting the firmware. It also makes other common register reads return zero on failure, so callers must treat zero as an unavailable reading where appropriate.

Run `STACKCHAN_CHECK_ONLY=1 firmware/recipe.sh` to fetch the pinned source and verify patch application plus Kconfig. A normal recipe run performs a full build when the pinned ESP-IDF toolchain is installed.

The recipe enables a persistent Xiaozhi websocket by default. It opens the connection during protocol startup, keeps it available between listening sessions, and retries a failed connection with exponential delays and jitter, capped at 60 seconds. Pass `--no-persistent-websocket` to the recipe to use the upstream session-only connection behavior. The Kconfig switch defaults to enabled for this profile.

For a Bot using a private HTTPS certificate, provide its CA certificate to the build:

```sh
firmware/recipe.sh --ca-file /path/to/bot-ca.pem
```

The file must be a readable X.509 certificate in PEM format. The recipe writes its path to `CONFIG_STACKCHAN_CA_PEM` as a build setting, then sets ESP-IDF's `CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH` to the same file and enables the custom certificate bundle. ESP-IDF appends that certificate to the built-in roots used for `wss://`. Firmware C code does not read `CONFIG_STACKCHAN_CA_PEM`; ESP-IDF uses the custom bundle settings at build time. When `--ca-file` is omitted, the recipe leaves `CONFIG_STACKCHAN_CA_PEM` empty and disables the custom bundle. The certificate file path is build input and must exist on the machine running the recipe.

The default server URL remains unchanged. Provisioning selects the server URL and websocket scheme for the installed hub.

Patch 013 replaces the voice screen's face with the mint skin (`skins/mint/`) and adds two faces, `surprised` and `wink` (display names `surprised` and `winking`). The upstream default face stays for the other apps. Design and contracts: [the mint face note](../../../../../docs/dev/design-stackchan-mint-face-2026-10-19.md).

Patch 010 adds the `self.battery.get_status` MCP tool. It returns the PMIC battery level as `percent` and charging state as `charging`, using StackChan's existing HAL power-management methods.

The default avatar server URL is empty. Pass `--avatar-server-url ws://192.0.2.10:8766` to build with `CONFIG_STACKCHAN_SERVER_URL` pointing to the Bot host. Use the Bot host's LAN address, not loopback, from the robot.

The avatar channel uses the same per-device pairing token and allowlist as xiaozhi. Patch 011 adds the `Device-Id` and `Client-Id` request headers and reads the configured token rather than M5's `hi-stack-chan` constant. Supply these values to the recipe for the approved identity:

```sh
firmware/recipe.sh --avatar-server-url ws://192.0.2.10:8766 \
  --device-id 02:00:00:00:00:15 \
  --client-id 00000000-0000-4000-8000-000000000015 \
  --pairing-token <private-per-device-token>
```

Treat the token and build directory as private. The recipe does not print the token, and `sdkconfig.defaults.local` is restored after the build. Keep it out of logs and shared build artifacts.

### Development builds against another Bot app (patch 079)

A paired unit keeps its voice address, avatar address and token in NVS, so a normal build always talks to the live Bot app. To test a worktree body (on other ports, paired with a dev Home) on the real unit without rewriting NVS, build with the development overrides; they win over the saved values only when set, and every release build leaves them empty:

```sh
firmware/recipe.sh --dev-voice-url ws://192.0.2.10:61155 \
  --dev-avatar-url ws://192.0.2.10:61156 \
  --dev-token <token the dev Bot app has approved for this unit>
```

The recipe prints `DEV-OVERRIDE: ...` for each value, so a build with them can never be mistaken for a release. Flash only the app image (and `ota_data_initial.bin`), never NVS, and approve the unit's Device-Id and Client-Id with that token in the dev Bot app's `stackchan-pairing.json`; the Bot app logs both ids when an unknown unit connects ("StackChan pairing request: Device-Id ... Client-Id ..."). Flash the normal build back when done (2026-11-12: used for the vision work).

### Head tap with the motion sensor (patch 081)

The head touch strip (Si12T, three pads under the big plain grey area at the back of the head top; nothing is visible) reads 0 to 3. A light tap reads 1, the same level as the strip's idle noise (200 to 400 samples a minute on a noisy day, none on a quiet one), so patches 076 to 080 could only choose between phantom pets and lost taps. Patch 081 reads the BMI270 every 10 ms (it was 100 ms) and marks a jolt: a change of at least 1.0 m/s^2 between two samples after 150 ms of stillness, and not within 0.6 s of a servo command (the unit's own head moves can start with a jerk of 3 to 5). A strip contact at any level with a jolt within 100 ms before or 150 ms after its first touched sample is a press with `strong=1`, `tap=1`, `strip=1`, the jolt size (`jolt`, m/s^2 times 100) and its distance (`gap`, ms); the shake, orientation and stall checks keep their 100 ms rhythm. Measured on the unit on 2026-11-12: idle floor 0.1 m/s^2 (one 0.46 blip in ten minutes), light taps on the strip 1.1 to 4.6, desk slaps beside the unit 2.3 to 4.4, typing under 0.5, a pick-up starts under 0.5. A tap by the motion sensor alone (`kFrontTapEnabled`) is built but off: a desk slap is the size of a light tap on the shell, and the shape (head rotation, front-back axis) separated 4 of 5 shell taps from 0 of 5 slaps on too few recordings. Known residual: on a noisy day a hard knock on the desk that lands inside a noise run's 250 ms window counts as a tap. `imu_stats` gains `jolts`, `jolt_max`, `blanked` (jolts inside a servo blank) and `front_taps`; `head_touch_stats` gains `taps`. For the first half hour after boot the USB serial console prints a trace (`I` moving samples with the gyro, `IS` per second, `J` jolts, `T` touched strip samples, `P` presses); `tests/test_stackchan_head_tap_replay.py` models the rule and replays a recorded noisy idle period. Opening the serial port resets the unit.

## Household setup tool

From the repository root, run `body/scripts/stackchan_flash.py` with `--port`, `--backup`, `--token-file`, `--device-id`, `--client-id`, `--xiaozhi-url`, and `--avatar-url`. The tool checks for the pinned ESP-IDF 5.5.4, saves the full 16 MiB flash before writing, builds the pinned firmware, creates the NVS image from the approval token file, then flashes firmware and NVS. It stops if the backup is missing or incomplete. Use `--dry-run` to print the steps without using a serial port; dry run needs an existing full-flash backup file. Example addresses should use the Bot host, such as `ws://192.0.2.10:8765` and `ws://192.0.2.10:8766`. The tool writes the built images and the NVS image in one esptool pass from `build/flash_args`, and the NVS image carries `board:uuid` so the unit keeps its paired Client-Id. The robot boots straight into the AI Agent; on first boot with no Wi-Fi it opens its setup hotspot to join Wi-Fi.


## Source verification

The patch series was checked against the pinned M5 StackChan commit `1b5765599fba8aaad1811d9a79358ccc7051f5f3` using `STACKCHAN_CHECK_ONLY=1 recipe.sh`; patches 009 and 012 apply and Kconfig reconfigures successfully. Patch 009's hunk was regenerated from an edit to the pinned xiaozhi-esp32 source. The upstream avatar enum is in `firmware/main/stackchan/avatar/avatar/elements/emotion.h` and defines six faces: neutral, happy, angry, sad, doubt and sleepy; patch 013 adds surprised and wink. Patch 014 keeps Wi-Fi out of power save while the robot speaks. Patch 015 logs audio frames lost at the start and end of a spoken line. Patch 016 accepts a line's audio from `tts start`, so entering the speaking state no longer clears its first frames. Patch 017 adds `self.screen.set_face_background` (seven palettes plus a black night face, the palette saved in NVS key `face_pal`), `self.robot.set_idle_motion` (a runtime gate on idle head movement) and `self.screen.get_ambient_light` (LTR-553 sensor, lux). `face_set.json` is generated from the patched enum (eight faces). The ESP-IDF 5.5.4 recipe build completed and the host egress scan passed. This confirms a firmware build only; no hardware behavior is verified.

Patches 018 and 019: patch 018 saves the hub's `maipai_token` from hello in NVS key `websocket/token` and reconnects with it; the avatar channel reads its token from `websocket/token` and its address from `websocket/avatar_url`.
