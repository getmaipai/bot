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
