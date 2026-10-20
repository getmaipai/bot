# StackChan firmware

`recipe.sh` builds the pinned StackChan source with the MaiPai firmware patches. It requires the pinned ESP-IDF version in `pins.toml` and the tools installed by ESP-IDF.

## Reproducible release

Use `release.sh --date YYYY-MM-DD [--version 1.0.0] --signing-key <Ed25519-private-key.pem> --output <directory>` to build with `espressif/idf:v5.5.4`. Along with the existing release metadata, it ships the bootloader and partition table plus `flash-manifest.json`; offsets come from ESP-IDF's `flasher_args.json`, and the manifest is validated and signed with the supplied key. `verify.sh <directory>` checks every listed checksum, manifest layout, and part size and SHA256. A release refuses to start if any source, dependency, or container pin is missing a SHA256. Container builds require Docker or a compatible engine. If no container engine is installed, the documented fallback is to export a local ESP-IDF 5.5.4 toolchain and run `recipe.sh` directly; it still enforces the pinned version.

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

## Household setup tool

From the repository root, run `body/scripts/stackchan_flash.py` with `--port`, `--backup`, `--token-file`, `--device-id`, `--client-id`, `--xiaozhi-url`, and `--avatar-url`. The tool checks for the pinned ESP-IDF 5.5.4, saves the full 16 MiB flash before writing, builds the pinned firmware, creates the NVS image from the approval token file, then flashes firmware and NVS. It stops if the backup is missing or incomplete. Use `--dry-run` to print the steps without using a serial port; dry run needs an existing full-flash backup file. Example addresses should use the Bot host, such as `ws://192.0.2.10:8765` and `ws://192.0.2.10:8766`. The tool writes the built images and the NVS image in one esptool pass from `build/flash_args`, and the NVS image carries `board:uuid` so the unit keeps its paired Client-Id. The robot boots straight into the AI Agent; on first boot with no Wi-Fi it opens its setup hotspot to join Wi-Fi.


## Source verification

The patch series was checked against the pinned M5 StackChan commit `1b5765599fba8aaad1811d9a79358ccc7051f5f3` using `STACKCHAN_CHECK_ONLY=1 recipe.sh`; patches 009 and 012 apply and Kconfig reconfigures successfully. Patch 009's hunk was regenerated from an edit to the pinned xiaozhi-esp32 source. The upstream avatar enum is in `firmware/main/stackchan/avatar/avatar/elements/emotion.h` and defines six faces: neutral, happy, angry, sad, doubt and sleepy; patch 013 adds surprised and wink. Patch 014 keeps Wi-Fi out of power save while the robot speaks. Patch 015 logs audio frames lost at the start and end of a spoken line. Patch 016 accepts a line's audio from `tts start`, so entering the speaking state no longer clears its first frames. Patch 017 adds `self.screen.set_face_background` (seven palettes plus a black night face, the palette saved in NVS key `face_pal`), `self.robot.set_idle_motion` (a runtime gate on idle head movement) and `self.screen.get_ambient_light` (LTR-553 sensor, lux). `face_set.json` is generated from the patched enum (eight faces). The ESP-IDF 5.5.4 recipe build completed and the host egress scan passed. This confirms a firmware build only; no hardware behavior is verified.
