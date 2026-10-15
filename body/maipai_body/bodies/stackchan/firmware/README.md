# StackChan firmware

`recipe.sh` builds the pinned StackChan source with the MaiPai firmware patches. It requires the pinned ESP-IDF version in `pins.toml` and the tools installed by ESP-IDF.

The recipe enables a persistent Xiaozhi websocket by default. It opens the connection during protocol startup, keeps it available between listening sessions, and retries a failed connection with exponential delays and jitter, capped at 60 seconds. Pass `--no-persistent-websocket` to the recipe to use the upstream session-only connection behavior. The Kconfig switch defaults to enabled for this profile.

For a Bot using a private HTTPS certificate, provide its CA certificate to the build:

```sh
firmware/recipe.sh --ca-file /path/to/bot-ca.pem
```

The file must be a readable X.509 certificate in PEM format. ESP-IDF adds it to the built-in certificate bundle used for `wss://`; the built-in roots remain trusted. When `--ca-file` is omitted, the recipe leaves `CONFIG_STACKCHAN_CA_PEM` empty and disables the custom bundle. The certificate file path is build input and must exist on the machine running the recipe.

The default server URL remains unchanged. Provisioning selects the server URL and websocket scheme for the installed hub.
