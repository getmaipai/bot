# StackChan firmware

`recipe.sh` builds the pinned StackChan source with the MaiPai firmware patches. It requires the pinned ESP-IDF version in `pins.toml` and the tools installed by ESP-IDF.

Patch 009 makes a failed common I2C register read log a warning and return zero. This covers the AXP2101 charge-direction read at register `0x01`, so `Axp2101::IsCharging()` returns false on an I2C timeout instead of aborting the firmware. It also makes other common register reads return zero on failure, so callers must treat zero as an unavailable reading where appropriate.

Run `STACKCHAN_CHECK_ONLY=1 firmware/recipe.sh` to fetch the pinned source and verify patch application plus Kconfig. A normal recipe run performs a full build when the pinned ESP-IDF toolchain is installed.

The recipe enables a persistent Xiaozhi websocket by default. It opens the connection during protocol startup, keeps it available between listening sessions, and retries a failed connection with exponential delays and jitter, capped at 60 seconds. Pass `--no-persistent-websocket` to the recipe to use the upstream session-only connection behavior. The Kconfig switch defaults to enabled for this profile.

For a Bot using a private HTTPS certificate, provide its CA certificate to the build:

```sh
firmware/recipe.sh --ca-file /path/to/bot-ca.pem
```

The file must be a readable X.509 certificate in PEM format. The recipe writes its path to `CONFIG_STACKCHAN_CA_PEM` as a build setting, then sets ESP-IDF's `CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH` to the same file and enables the custom certificate bundle. ESP-IDF appends that certificate to the built-in roots used for `wss://`. Firmware C code does not read `CONFIG_STACKCHAN_CA_PEM`; ESP-IDF uses the custom bundle settings at build time. When `--ca-file` is omitted, the recipe leaves `CONFIG_STACKCHAN_CA_PEM` empty and disables the custom bundle. The certificate file path is build input and must exist on the machine running the recipe.

The default server URL remains unchanged. Provisioning selects the server URL and websocket scheme for the installed hub.

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
