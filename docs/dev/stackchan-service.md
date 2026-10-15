# StackChan service

The Bot app starts the xiaozhi and avatar WebSocket services only when `MAIPAI_BODY=stackchan`. Other body configurations do not start them. The xiaozhi service listens on `127.0.0.1:8765`; the avatar service listens on `127.0.0.1:8766`. Set `MAIPAI_XIAOZHI_HOST` to the Bot host's LAN address and `MAIPAI_XIAOZHI_PORT` to select the xiaozhi listener. The avatar listener has separate `MAIPAI_STACKCHAN_AVATAR_HOST` and `MAIPAI_STACKCHAN_AVATAR_PORT` settings. By default, both listeners use loopback; if `MAIPAI_XIAOZHI_HOST` is set, avatar host follows it unless explicitly set. Set both `MAIPAI_XIAOZHI_TLS_CERT` and `MAIPAI_XIAOZHI_TLS_KEY` to enable TLS for both listeners; leave both unset for `ws://`. Firmware verifies `wss://` when built with `--ca-file <pem>`, and the certificate SAN must match each URL host or IP. Use `stackchan-provision --generate-tls <private-dir> --host <bot-lan-host>` to create a local CA and server certificate, then build firmware with the printed `recipe.sh --ca-file` command. TLS resource use on the ESP32-S3 remains unmeasured.

The current provisioned `ws://` connections send the bearer token, audio, and control frames as cleartext to devices on that LAN. Keep the robot and Bot host on a trusted network. Build firmware with `--ca-file <pem>` for `wss://`; the server certificate must include a SAN matching the host or IP in the robot's URL. TLS resource use on the ESP32-S3 remains unmeasured.

The firmware recipe enables its persistent xiaozhi WebSocket by default; `--avatar-server-url ws://192.0.2.10:8766` sets `CONFIG_STACKCHAN_SERVER_URL`. Build the avatar firmware with `--device-id <MAC> --client-id <UUID> --pairing-token <token>` so it uses the same approved identity and token as xiaozhi. The recipe applies patch 011 to add those headers and replace M5's constant avatar token. Pairing uses the existing `PairingStore`; revocation is checked on each received and sent frame. See the [firmware guide](../../body/maipai_body/bodies/stackchan/firmware/README.md) for details.

The protocol implementation is in `body/maipai_body/bodies/stackchan/xiaozhi/`. `XiaozhiServer` checks the device and client identifiers with `PairingStore` before accepting a session, replies to hello, and passes binary audio frames to its async audio callback. The current app wiring does not yet connect that callback to the Home conversation loop.

## Camera

The xiaozhi service also listens for on-demand photos on the vision listener, port `8766` by default. MCP `initialize` advertises `capabilities.vision` with a per-device URL and the paired bearer token. The device posts a multipart JPEG in an `image`, `file`, or `photo` field to that URL, using `Authorization: Bearer <token>`. The receiver caps the full upload at 2 MiB, keeps the latest photo only in process memory, and never writes or forwards the bytes. Set `MAIPAI_VISION_HOST`, `MAIPAI_VISION_PORT`, and `MAIPAI_VISION_URL` for a LAN reachable listener and advertised base URL; use a trusted LAN because the current transport is cleartext. If `MAIPAI_VISION_URL` is a base URL, append the device route `/vision/<Device-Id>`.

All camera captures and avatar stream starts go through the StackChan translator's Robot `camera` part. The xiaozhi `self.camera.take_photo` tool is routed through `Robot.camera.frame`, which lights the full RGB ring red before the request and clears it in `finally`, including capture errors. The fake device refuses capture if red is not lit, so the Bot API cannot capture around this indicator. Stream start is rejected while software estop is engaged. Stream starts also use the red ring and clear it on stop, command error, disconnect, or service shutdown.

The avatar protocol implementation is in `body/maipai_body/bodies/stackchan/avatar/`. The endpoint is `/stackChan/ws?deviceType=StackChan`. M5's binary frame is `[type:1][payload length:4, big endian][payload]`; ControlAvatar is type `0x03` with the M5 nested `leftEye`, `rightEye`, and `mouth` JSON shape. Camera JPEG frames use type `0x01`. The authenticated receiver keeps only the newest bounded frame in process memory, rejects malformed payloads without ending the session, and clears the frame on disconnect. The vision bridge consumes fresh frames with a deadline and brackets decoding/tracking with the camera indicator. The StackChan profile's `expression_map.py` maps listening, thinking, speaking and reply mood cues to this closed face vocabulary. Its primitive table drives bounded yaw/pitch moves, face frames and whole-ring LED states. Breathing and continuous tracking remain unavailable through the general primitive table until hardware behavior is verified.

## Pairing API

The local Bot dashboard exposes:

| Method | Path | Result |
|---|---|---|
| `GET` | `/api/stackchan/pairings/pending` | Pending device and client identifiers with request time |
| `POST` | `/api/stackchan/pairings/approve` | Approves JSON `{ "device_id": "...", "client_id": "..." }` and returns a private token-file path |
| `POST` | `/api/stackchan/pairings/refuse` | Removes one matching pending request without changing approved devices |
| `POST` | `/api/stackchan/pairings/revoke` | Revokes JSON `{ "device_id": "..." }` |

Pairing routes accept requests from the local computer only and require the dashboard's same-origin JSON check. Approval never returns a token in the HTTP response. It writes a one-time token file in a mode-0700 directory with mode 0600, and returns only its path. The provisioning command consumes and removes that file after a successful image build. Revocation removes the allowlist entry; active sessions are closed when their next frame arrives, and audio sending checks the allowlist before every send.

The dashboard links to `/pairing`, which lists pending Device-Id, Client-Id and first-seen time. Its buttons call the same local-only JSON routes. Refusal deletes only the selected pending identity; approval does not expose the token value. Setup uses `body/scripts/stackchan_flash.py`: it checks ESP-IDF 5.5.4, reads a 16 MiB backup before writes, builds the pinned recipe, creates NVS from the approval file, then flashes firmware and NVS. Dry run prints the command sequence and requires a pre-existing backup file. Tests exercise dry run only and never open a serial port.

## Provisioning

Install the Bot package in its managed environment, then generate an NVS image without writing it:

```bash
uv run stackchan-provision --host 192.0.2.10 --version 1 --ota-url http://192.0.2.10:8765/ota --device-id 02:00:00:00:00:15 --client-id 00000000-0000-4000-8000-000000000015 --avatar-server-url ws://192.0.2.10:8766 --firmware-recipe body/maipai_body/bodies/stackchan/firmware/recipe.sh --output stackchan-nvs.bin
```

The command asks for the token without echoing it. With TLS configured on the Bot, the default URL uses `wss://`; otherwise it uses `ws://`. For a token issued by the Pairing API, pass its file path with `--token-file <path>`. The image is created with owner-only permissions because it contains the device token. To write it over USB, add `--write --port <serial-port>`. Without `--write`, the command never calls esptool. Keep the generated image private and remove it when provisioning is complete.

The recipe and pins live in `body/maipai_body/bodies/stackchan/firmware/`. `recipe.sh` fetches the pinned sources, applies the M5 patch and our ordered patches, builds, scans the binary and prints hashes. Build output stays outside the repository. `bump.sh <commit>` checks whether the M5 patch and each MaiPai patch still apply to a proposed upstream commit; inspect the patch changes and host-list changes before accepting new pins.

For a release, use `firmware/release.sh --date YYYY-MM-DD --output <directory>`. It builds in the pinned `espressif/idf:v5.5.4` container when Docker is available, refuses incomplete checksum pins, scans image strings for vendor hosts, and writes a manifest plus `SHA256SUMS`; `firmware/verify.sh <directory>` rejects changed artifacts. The documented fallback is a local ESP-IDF 5.5.4 export followed by `recipe.sh`. Patch 004 leaves the NTP server blank, removing public NTP destinations. A new device starts on provisioned plain `ws://`; a future host OTA reply must set `server_time` as Unix epoch seconds before switching to TLS, since a fresh RTC cannot validate certificates. The existing service does not yet implement that OTA time handoff. Firmware updates remain an explicit, user-approved host-side step and are never offered through an OTA reply.

## Stop behaviour

The xiaozhi service exposes the shared Robot interface. `MAIPAI_BODY=stackchan` selects the StackChan service; `MAIPAI_BODY=fake` selects the same service path for a local fake peer, and other values keep the configured Reachy path. Once an authenticated StackChan session arrives, the app connects the turn bridge's listening, thinking, speaking, reply mood and settle events to the registered StackChan renderer. The presence worker starts the avatar camera stream, performs bounded anonymous face tracking from the newest frame, and stops the stream and worker on shutdown. Listening glances, detected faces are attended, and idle uses the static settle pose because this body has no verified breathing motion. Head targets and expression LEDs use the shared Robot object, retaining lease, profile clamp and software estop checks. The software stop cancels queued moves and best-effort sends the current head angles again to stop an accepted move; if reading those angles fails, the estop stays latched and reports `BodyLost`. This is not a hardware power cut and cannot guarantee the servo has stopped, so use the robot's power switch to cut servo power.

The avatar listener also carries a software estop latch for ControlMotion `0x04` frames. With the latch engaged, incoming motion frames are discarded while the connection remains open. This is host-side filtering and does not cut servo torque.

## Known gaps

The shared expression engine has a registered StackChan renderer and closed face cue tables for listening, thinking, speaking and reply mood. The app now wires those turn events and its idle/presence worker to the renderer after device authentication. It maps listen, glance, tilt, nod, perk, attend, settle and speak; breathe reports an explicit unsupported reason and idle therefore uses settle. Anonymous tracking is bounded to 400 ms corrections and runs only while no turn is active; it stops on service shutdown. Head moves use Robot commands, so profile clamping, lease checks and the estop latch remain in force. Face frames use the authenticated avatar channel. Patch 003 keeps the firmware xiaozhi WebSocket open between listening sessions and retries failed connections; patch 008 adds an optional CA bundle; patch 011 adds shared pairing identity to the avatar channel. The recipe options and CA input are documented in the [firmware guide](../../body/maipai_body/bodies/stackchan/firmware/README.md). Runtime checks use fake peers only; hardware verification remains pending.
- StackChan setup has fake-peer and dry-run coverage only. Hardware has not arrived, so the backup read, flash commands, Wi-Fi onboarding and reboot have not been verified on a unit.

### Idle server pushes

The StackChan Robot adapter exposes `audio.speaker.speak`, `audio.listen_window`,
`alerts.show`, and `reminders.create_reminder`, `get_reminders`, and
`stop_reminder`. Push calls require the Robot control lease. Proactive speech,
alerts, and listen windows also pass through an injected household policy
callable; the default denies them and the caller receives `NotSupported` with a
plain fix line. Reminder create and stop operations are retained in a host
queue when a send fails and can be retried with `flush_reminders()` after
reconnect. The device profile tries the xiaozhi alert operation and falls back
to the face/LED/spoken presentation supported by its client. The pinned base
tool inventory and reminder argument schema still need confirmation on a real
unit. Fake-peer tests cover the host contract only; hardware has not arrived.

Battery is now read through the firmware's read-only `self.battery.get_status` MCP tool, which returns `{ "percent": integer 0..100, "charging": boolean }`. Patch 009 makes failed AXP2101 I2C reads return a safe zero rather than aborting the firmware; a host timeout or malformed tool result maps to `BodyLost`. Touch and IMU remain `NotSupported` because the pinned translator exposes no read-only MCP tools for them. Source-derived chip and register notes are in [the sensor map](stackchan-sensor-map.md); unit measurements are tracked in [the unit-arrival runbook](stackchan-unit-measurements.md). The unit-arrival fixture recorder and host-only egress proof are implemented; real-unit protocol capture and packet-capture results remain pending because hardware has not arrived.

## Tests

The STACKCHAN-30 failure, soak and privacy suite is software-only and uses the
fake xiaozhi and avatar peers. It checks bounded camera buffering with 10,000
frames, pairing refusal and revocation, token rotation, turn dependency errors,
camera indicator bracketing, and a compressed one-day event schedule. These are
host-side checks; no hardware has arrived and no hardware verification is
claimed. Unit measurements remain pending in
[`stackchan-unit-measurements.md`](stackchan-unit-measurements.md).

`body/tests/test_stackchan_xiaozhi.py` exercises a fake device over a local WebSocket. The test covers pairing refusal, approval, hello, audio callback delivery and protocol tool handling without hardware. `body/tests/test_stackchan_avatar.py` uses the independent fake peer in `body/tests/stackchan_sim/`; it covers expression delivery, unpaired refusal, estop motion filtering, malformed-frame isolation, reconnect replacement and codec bounds. These are software fake-peer checks only; no hardware verification is claimed and no test writes to a physical serial port.

`body/tests/test_stackchan_avatar.py` uses the independent fake peer in `body/tests/stackchan_sim/`. It covers expression-frame delivery, unpaired refusal, estop motion filtering, malformed-frame isolation, reconnect replacement and codec bounds. `body/tests/test_stackchan_sensors.py` checks battery tool results and the explicit touch and IMU gaps. These are fake-device protocol checks only; hardware has not arrived, so no unit verification is claimed.

## Host vision bridge

`maipai_body.bodies.stackchan.vision_bridge.StackChanVisionBridge` consumes on-demand JPEG bytes from `robot.camera.frame()` in host memory. Anonymous tracking uses only the detector, returns a `FaceTrackTarget` without identity, and sends small head targets through the Robot API. The StackChan profile in `profile.py` clamps yaw and pitch. Each correction has a deadline; expiry calls `head.hold()`, and a missing face ends the prior correction. Call `close()` when the behavior stops.

Recognition calls the shared `vision.recognize` pipeline and returns the gallery verdict (a tentative person id and confidence, or unknown). The caller must apply household child and teen floors before turn output. A face verdict only selects a turn person and never unlocks adult content. Child and teen print access requires an injected consent check from the print store; absent authorization refuses the operation. The bridge has no implicit upload path. `send_consented_hub_still` sends one JPEG only when passed the explicit still-consent authorization callback.

Frames are decoded directly from bytes and are not written to disk. The measurement runner is `body/maipai_body/bodies/stackchan/measure/vision_run.py`; it reports match and false-accept rates at 0.5, 1.0 and 1.5 m in room and dim conditions for labeled fixtures. The committed frame is a generated geometric image with no person likeness, and its labels are marked placeholders, so the runner reports empty measurements until real labeled trials are supplied. No unit is attached and no range result is claimed.

## Known gaps

- StackChan voice turns accept optional person attribution and pass it to the shared Home turn route as speaker evidence. The hub continues to apply child and teen floors and surface gates. Turn-state expression cues (listening, thinking, speaking, reply mood and settle) reach the injected expression sink; sink failures do not fail speech.
- Opus duration and buffering have only been checked in software; device timing, acoustic echo behavior and abort latency remain unmeasured on hardware.
- The authenticated avatar stream hands its latest JPEG to the host vision bridge through `Robot.camera`; each frame read holds the red ring on during decoding and tracking, then clears it, and disconnect drops the buffered bytes. Hardware camera timing remains unverified.
- The host-side synthetic test proves bounded correction and in-memory handling only. Match rate and false-accept rate remain unmeasured on a physical StackChan unit.
- Print consent must be supplied by the household print-store integration; the bridge defaults to refusing child and teen recognition when that integration is absent.

## Voice turns

The xiaozhi `listen` callback starts one `StackChanTurnBridge` capture per authenticated device session. Incoming binary frames are decoded with PyAV's bundled Opus codec and resampled to mono 16 kHz float32 blocks for the existing `SttStreamClient`. The final transcript goes to the existing turn route; the completed reply is split at sentence punctuation and sent sentence by sentence through `TtsPlaybackClient`. PyAV is pinned by `body/pyproject.toml` and `body/uv.lock` (`av>=14,<17`); its wheels bundle FFmpeg and libopus, so deployment does not depend on a system libopus installation.

StackChan playback resamples the existing TTS PCM to 24 kHz, encodes 60 ms mono Opus frames, and sends them only through the authenticated `XiaozhiServer.send_audio` session. Abort clears pending encoded frames, cancels the active task and sends `tts stop`. The bridge reads the active hub URL and current session cookie from the shared `LinkLifecycle` at each turn. Hub authentication or connection loss uses the verified offline `line.unreachable` clips. A recognition or turn error attempts the plain spoken line “I couldn't understand that. Please try again.” through the hub TTS path, with the offline line as fallback.

The StackChan voice-turn tests use local fake peers and documentation-only addresses. Hardware has not arrived, so these checks do not claim hardware verification.

## Duplex and barge-in

The StackChan turn bridge accepts uplink while its reply is speaking only when the active session reports `features.aec: true`. Without that capability it drops uplink during speech and for a 180 ms post-speech guard. An incoming start/detect event cancels the prior capture and reply before opening the replacement capture, so one session cannot retain two active turns. Abort clears encoded and partial PCM buffers, cancels the turn and emits `tts stop`; playback checks cancellation at frame boundaries. Sentence audio uses a five-frame prebuffer, 60 ms wall-clock frame pacing, and a 420 ms drain before `tts stop`. Clock and sleeper injection support deterministic unit measurement.

The bridge exposes `latency_counters` with `abort_to_silence_ms` and `first_audio_ms`, plus uplink live/drop counts for local diagnostics. These are software measurements; no physical StackChan latency or AEC quality has been verified. The current xiaozhi service does not yet retain device hello features on its session, so its integration must provide the hello AEC flag to the turn bridge before duplex uplink is enabled.
