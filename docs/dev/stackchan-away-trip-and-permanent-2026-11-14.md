# StackChan away from home: the trip stopgap and the permanent design (2026-11-14)

Status: the stopgap is decided and in progress; the permanent design is a backlog item (ANYWHERE-05). This note saves what two
independent design consults (Fable, 2026-11-14) found, so none of it is lost. It extends
`stackchan-anywhere-network-2026-11-14.md` (the on-robot Tailscale design, ANYWHERE-01 to 04).

## Owner decisions (2026-11-14, Jesse)

- He leaves for a friend's house within hours and needs the whole robot to work there, chat and voice with Home included, with only
  the robot, his iPhone and his laptop: no travel router, no extra hardware.
- Wanted: "the permanent solution", not a stopgap. For the trip: "relay to get working today and then backlog a full design".
- Not wanted: a public address for the hub as the default design. The Tailscale Funnel option was reviewed and is **not turned on**.

## The stopgap for the trip (decided)

The robot's firmware tries the saved home address first, then a fallback address, `ws://192.168.2.1:<voice port>` and
`ws://192.168.2.1:<avatar port>` (the Mac's Internet Sharing address). At the trip: the laptop joins the iPhone by USB tethering,
turns on Internet Sharing to Wi-Fi, the robot joins the laptop's own Wi-Fi, and `data-scratch/bin/trip-relay.py` on the laptop
forwards the two connections over Tailscale to the Studio (the hub log says the voice and avatar services listen on
`ws://0.0.0.0:62923` and `:62924`). No public inbound endpoint anywhere. The relay's check ran from the laptop on 2026-11-14:
both Studio ports answered over Tailscale. Not yet verified: the robot-side fallback (a firmware patch in image 1, one USB flash).
If it fails, the robot at the trip runs offline mode (patch 075: faces, timers, music dance, phrases) without chat.

## Fable's findings on the options (saved for the permanent design)

1. **Funnel plus a firmware fallback URL is the fastest path (about 90 minutes to prove at home), but not the permanent answer.**
   - The hub's userspace tailscaled already carries the `funnel` and `https` capabilities (ports 443, 8443, 10000); Home stays private
     on 443, so the robot path would use 8443, with a secret in the path.
   - The unit's wss uses `esp_crt_bundle_attach` (Mozilla roots, Let's Encrypt included) with SNI; no CA change needed.
   - `CONFIG_MBEDTLS_HAVE_TIME_DATE` is unset, so certificate dates are not checked and the missing wall clock does not break TLS
     (verify in the built sdkconfig).
   - The unit re-reads `websocket/url` on each reconnect. A whole-NVS flash drops the saved Wi-Fi list (the hub's enroll-image and
     provision.py write url, token and version only), so never write NVS; patch 079's build-time URL override changes only the app image.
   - The hub's boot reply cannot redirect today (the OTA exchange is compiled out, patch 002; `ota_url` is unused).
   - A stranger with the URL gets nothing: `server.py` closes anything without an approved Device-Id, Client-Id and Bearer (1008).
   - Opus 24 kHz at 60 ms frames is 3 to 4 KiB/s each way; the measured DERP-relay throughput of about 47 KiB/s leaves 10x headroom.
   - Why it is not the permanent design: it contradicts "nothing comes in from the internet", Funnel has bandwidth limits and depends
     on Tailscale's service, and it exposes the robot servers publicly.
2. **Riskiest assumption for any TLS-on-robot path:** the unit's internal RAM (about 76 KB free, low-water 53 KB) surviving TLS plus
   AEC plus opus. `MBEDTLS_EXTERNAL_MEM_ALLOC=y` helps. Only a test on the unit proves it.
3. **Phone relay apps (MonoProxy, NetBridge, MQTT BLE Bridge, Speedify, PairVPN):** none is verified for a robot, none keeps working
   with the phone locked, none carries Tailscale for a non-client device. iOS cannot act as a subnet router. Ranked below on-robot
   Tailscale, a direct WireGuard endpoint and Funnel.
4. **Tailscale's answer for devices that cannot run it** is a subnet router (Layer 3 routes advertised by one machine on the far
   network), not MAC addressing. That is the travel-router idea Jesse rejected for the product.
5. **Second flash avoided later:** patch 133 (`self.firmware.update`, https pull through the same bundle) lets later images arrive over
   whatever link the unit has, once the host hands it a reachable URL.

## Permanent design (backlog, ANYWHERE-05)

The robot joins the household tailnet itself (MicroLink, ANYWHERE-01), with no public endpoint:

- Fit: MicroLink with its task stacks in PSRAM except the NVS-writing worker (estimate about 20 KB internal, about 30 KB spare); gate
  at least 25 KB internal free for 10 minutes with everything running, and the largest free internal block at least 16 KB.
- Auth: a per-robot reusable, ephemeral, tagged `tag:robot` key pasted by an admin (never minted by Home, OWNER-ANSWERS 1),
  expiry shown with a one-click "Forget the network key"; the access rule lets the robot reach only the hub's robot ports.
- Connection order in the firmware: home address, then the tailnet address, never a public one; LAN only on the network marked as home.
- Wi-Fi list with strict priority (patch 134), QR sharing (135), the password-protected settings window on the robot's own WPA3 access
  point (137 to 139), all over the air after the updater is proven on the bench.
- Fallbacks if MicroLink does not fit: a plain WireGuard endpoint on the Studio, then Funnel as an opt-in, off-by-default "Trip mode"
  that turns itself off after a set time and shows a notice in Home.
- Open owner decisions: WPA3-SAE as an encrypted channel for CREDENTIALS.md; NVS encryption (an eFuse that cannot be undone).

## Decided for the trip: the robot only uses the relay on the laptop's own network (2026-11-14, patch 146)

Jesse's requirement: it must work whatever the friend's Wi-Fi is. The relay path now is independent of the friend's network:

- The robot joins the laptop's own Wi-Fi (macOS Internet Sharing from the iPhone's USB tether), named `maipai-trip` or anything
  starting with `maipai`. The fallback host is the unit's current Wi-Fi gateway (the laptop, any subnet macOS picks), then 192.168.2.1.
- The fallback runs only on a network whose name starts with `maipai` (CONFIG_STACKCHAN_FALLBACK_SSID_PREFIX). The robot sends its
  saved pairing token to the fallback host, so a friend's router, a hotel or an evil twin (which cannot complete the WPA2 handshake
  without the password) must never be one. Patch 146 has a host-tested core (`maipai_fallback_core.h`, `fallback_core_test.c`).
- The friend's Wi-Fi is never used, so its subnet cannot clash (for example a friend's router on 192.168.2.1 and the laptop on 192.168.2.2).

Not built: a robot and the laptop on the SAME Wi-Fi that is not the laptop's own. The unit would need the laptop's address and a
reason to trust it. Options weighed:

- (a) A UDP beacon from the laptop that the unit listens for. Rejected without authentication: any device on a friend's network could
  send a fake beacon and receive the robot's pairing token.
- (b) Challenge before token: the unit sends a random nonce first and sends the token only after the real Studio answers through the
  relay with a signature it can verify. Needs a protocol change on the voice and avatar servers (today the bearer token travels in
  the first request) and a signing key on the unit that is not baked into a public image. Backlog under ANYWHERE-05.
- (c) The relay asks the Studio over Tailscale for a short-lived HMAC of a nonce the unit sends. Same key problem.

Also noted in the review of patch 133 (the updater): the unit checks size, SHA-256 and the version in the written slot, and rolls back
unless a healthy hub link is held, but the SHA-256 arrives over the same (plain ws) link as the update command, so anything that can
speak the protocol to the unit can push firmware. A signed image (ed25519, public key in the app image) is a backlog item; for the
trip the exposure is the laptop relay path, protected by the `maipai` network gate and the WPA2 password.

## Which MicroLink to pin (owner's find, 2026-11-14)

Jesse pointed at `github.com/Csontikka/esphome-tailscale`. It is an ESPHome external component, so it cannot be dropped into this xiaozhi
ESP-IDF firmware, but it carries a maintained copy of the MicroLink client (`Csontikka/microlink`, MIT) with fixes the dormant upstream
(`CamM2325/microlink`, described there as dormant since March 2026) lacks. Facts read from its README and changelog (2026-11-14):

- Latest changelog entry 0.5.31 on 2026-11-09; 192 stars, 309 commits. The only verified chip is an ESP32-S3 with PSRAM (the unit's chip).
- Memory: the netmap buffer defaults to 512 KB (range 64 to 2048), about 1 KB per peer slot, 16 peers by default. A no-PSRAM mode exists for a
  C3 (32 to 74 KB free internal heap) and is experimental. Our budget (about 76 KB free internal, gate 25 KB) still decides.
- Speed: WireGuard about 2 to 5 Mbit/s on the S3; DERP relay adds 50 to 150 ms; one measured relay-only OTA took 498 s against 26 s direct, so
  large downloads over a relay are slow while opus voice (3 to 4 KiB/s each way) is fine. The default DERP home region and `netcheck_override`
  matter for latency.
- Keys: the auth key is used at first boot; the node key lives in NVS and expires after 180 days on the hosted service unless key expiry is
  disabled for that node; no private-CA control plane; it cannot advertise subnet routes or be an exit node (we only need a client).
- Other maintained ESP-IDF options named there: `Asimmimx/tailtiny` (a plain ESP-IDF fork, tested on a C3), `fugo101/microlink` (ESP-IDF 6).

Decision for ANYWHERE-01 and ANYWHERE-05: pin the maintained `Csontikka/microlink` fork (checksummed, downloaded, not vendored) as the
base, compare with `tailtiny` at the spike, and re-measure our internal RAM and the voice latency over a DERP relay before anything ships.
Still a later step; the trip uses the laptop relay.

### Two corrections from a second opinion (2026-11-14)

An independent outline of the same plan (MicroLink in the firmware, prove it on the board first) agreed with this design and added two points we adopt:

- **Key type:** use a one-off, reusable, NON-ephemeral, pre-approved auth key with key expiry disabled for the robot node. An ephemeral key makes the
  robot vanish from the machine list whenever it is offline, and a robot is offline often. This replaces the earlier "ephemeral" wording in
  `stackchan-anywhere-network-2026-11-14.md` (the key stays paste-only by an admin, tagged `tag:robot`, never in Git).
- **Narrow access rule:** the tag may reach only the Studio's two robot ports (the hub log shows `ws://0.0.0.0:62923` and `:62924`); check the tailnet
  policy for an existing allow-all rule, because a narrow grant does not override it.

Proof order for the spike: identify the build framework (ESP-IDF 5.5.4 here, above the 5.3 floor), test on the unit with a spare image kept for restore (the
full-flash backup `~/stackchan-backups/stackchan-full-2026-11-14.bin` exists), enroll on a phone hotspot, one outbound TCP connection to a tailnet
address, one authenticated robot connection through the normal code path, reboot and switch Wi-Fi to confirm the same machine entry returns without a new key.

## Self-healing for the trip: what exists and the gaps (2026-11-14)

Asked by the owner: "any self healing on the script and the robot to connect, fix, anything to give me feedback on connection."

What heals itself today:

- **Relay v2 (laptop):** waits for Internet Sharing, binds on the sharing address whatever it is, restarts its listeners if they stop or the address
  changes, retries the Studio every few seconds, notices a long sleep and starts again, never exits on an internal error; macOS notifications
  (rate limited) for robot connected or lost, Studio unreachable, Tailscale off, Internet Sharing off; a local status page
  (http://127.0.0.1:8899) and a log file without tokens.
- **Robot (firmware 0.2.102):** retries the hub with growing pauses (up to about a minute), tries the Wi-Fi gateway after two failures on a
  `maipai...` network, retries the home address about once a minute, shows "Offline" after 45 s without the hub, rolls a bad update back after 5 minutes without a hub link.
- **Home (bot 0.2.103 and Home AWAY-LINK-01):** the Connection row says "Connected at home", "Connected away from home (through your laptop)" or
  "Offline since 14:10" and what the unit says about its hub link (reconnecting, trying the laptop relay).

Gaps, for the next over-the-air firmware image (none is built; the first USB flash is done):

1. **Wi-Fi up, no hub for a long time:** if the unit stays on Wi-Fi but reaches no hub address for 10 minutes, it should restart its Wi-Fi, and
   after 30 minutes reboot. Today it only keeps retrying.
2. **On-screen cause:** the face says only "Offline". It should say why in one line ("Looking for your laptop", "No network in reach: join Xiaozhi-...").
3. **The setup page opens only at power-up.** After N minutes without any saved network in reach it should open by itself, without a power cycle, and
   a quick-settings entry should open it on purpose.
4. **Switching saved Wi-Fi networks** by priority (patch 134) so a stronger friend's Wi-Fi never wins over `maipai-trip` on purpose.
5. **A robot and a laptop on the same Wi-Fi** (not the laptop's own): needs the signed discovery beacon described above.
6. **Relay on login:** not built (the owner runs it by hand); a launch-agent file would make it start by itself.
