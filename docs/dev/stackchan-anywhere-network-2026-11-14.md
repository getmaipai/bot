# StackChan anywhere network: the robot joins the tailnet itself, and keeps a list of Wi-Fi networks

Status: design, owner-approved 2026-11-14, spike measured on the build side, nothing flashed. Item ids: ANYWHERE-01 (robot on the tailnet), ANYWHERE-02 (saved Wi-Fi list and sharing).

## Owner decision and what it replaces

Jesse, 2026-11-14: he is taking the robot to a friend's house and wants it designed "so people can just bring the robot anywhere". He rejected a travel router and rejected an iPhone relay app ("no travel router", a specific iPhone app to join the tailnet "without using hotspot"). In chat he approved starting both parts ("Yes, start both").

## Supersedes

- `docs/dev/design-stackchan-2026-10-14.md`, section 5.2a "Network shape", first two bullets: "The ESP32-S3 cannot run a Tailscale client ... so the device joins the home Wi-Fi and talks to the bot host on the LAN" and "Away from home, the person reaches the robot through the host over Tailscale ... The device itself never needs a public address and has no inbound path from the internet." Decision 5 of 2026-10-15 ("remote reach is over Tailscale, one mechanism for every robot body") stays; what changes is that the StackChan itself becomes a tailnet node so that it works on any Wi-Fi. The no-inbound-path property stays: the robot only makes outbound connections.
- Nothing else. The no-third-party rule of 5.2a is unchanged: Tailscale is already the household's chosen mechanism (the hub and the phone are on it), the control server is the one the household already uses, and a self-hosted Headscale control server stays possible (MicroLink supports it).

## The problem in plain words

At home the robot joins the home Wi-Fi and talks to the hub on the local network. At another house it has internet but no route to the hub. A phone hotspot does not fix that: it gives internet only, and an iPhone does not pass its own Tailscale connection on to a device tethered to it. A relay app on the phone would have to stay open and would make the robot depend on the phone. So the robot needs its own way back to the hub, on any network.

## Part A: the robot joins the tailnet

### Candidate

MicroLink (`github.com/CamM2325/microlink`, MIT licence, reviewed commit `216da3300f0493b0860247d43f7af5ce29df63a5`, 2026-03-17): a Tailscale-compatible client for the ESP32 (control protocol, WireGuard, DERP relay, DISCO, STUN). Tailscale auth key, reusable and ephemeral keys, key-expiry re-registration, Headscale compatible. It is third-party code from one author, not endorsed by Tailscale, so it enters as a pinned, checksummed download (RELEASES-AND-DEPENDENCIES: download, do not vendor), behind a build flag that is OFF until a unit passes the on-device test.

### What the spike measured (build side, 2026-11-14)

Built MicroLink's `basic_connect` example for the ESP32-S3 with our pinned ESP-IDF 5.5.4:

- It configures and builds cleanly on 5.5.4 (the README claims 5.0 and later, tested on 5.3).
- Static RAM is tiny: `libmicrolink.a` 1,468 bytes of `.bss`, `libwireguard_lwip.a` 73 bytes, our `mbedtls` share 248 bytes. Code in flash: about 62 KB (MicroLink) plus 18 KB (WireGuard) plus 27 KB (mbedTLS) plus 9.5 KB (HTTP server component, not needed). The app partitions have room.
- The README figure of "85 to 116 KB SRAM" is therefore not static RAM: it is task stacks plus heap.
- Task stacks, from `microlink_internal.h`: network input and output 8 KB, DERP send 14 KB, coordination 12 KB, WireGuard manager 8 KB (42 KB), plus a 4 KB UDP receive task and an optional 6 KB network-switch task. FreeRTOS creates these stacks in internal RAM.
- Heap: the large buffers (HTTP/2 and JSON, 512 KB each by default, peers, DERP TLS) are plain `malloc`. Our firmware already sets `CONFIG_SPIRAM_USE_MALLOC=y` with `CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=512` and `CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC=y`, so allocations above 512 bytes and all mbedTLS buffers go to PSRAM. PSRAM is not the constraint: the live unit reports about 7.1 MB free of 8 MB.

### The live unit's internal RAM (heap_stats lines in the body log, 2026-11-14)

- free about 76 KB, lowest since boot 53 KB, largest free block 55 KB.
- Internal RAM is the constraint. Adding MicroLink with all four stacks in internal RAM (42 KB, about 52 KB with the optional tasks) would leave about 7 KB at the low-water mark. That does not fit.

### The fit condition

Our sdkconfig has `CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM=y`, so a task can be created with a stack in PSRAM (`xTaskCreateStatic` with a PSRAM buffer). Plan for the spike patch:

- Put the DERP send (14 KB), network I/O (8 KB) and WireGuard manager (8 KB) stacks in PSRAM, 30 KB moved out of internal RAM.
- Keep the coordination task (12 KB) in internal RAM, because it persists keys and peers to NVS and a task with a PSRAM stack must not run flash operations (the cache is off during them).
- Do not start the HTTP config server, the cellular code or the network-switch task (not needed).
- Estimated internal RAM added: about 12 KB (coordination stack) plus 4 KB (UDP receive stack, or fold it into the manager) plus lwIP and WireGuard interface structures, so roughly 20 KB against a low-water margin of 53 KB. That fits with about 30 KB spare.

This is an estimate from the source and the live heap numbers. It is not proven: whether the PSRAM-stack tasks behave (WireGuard crypto speed from PSRAM, any hidden flash access in the network task) is decided only by running it on the unit. Gate: the unit must hold its internal low-water mark above 25 KB for 10 minutes while connected over the tailnet with the voice link up. If it does not, Option 2 or 3 below.

### Options if it does not fit

1. A: MicroLink with PSRAM stacks (recommended, spike first).
2. B: plain WireGuard (the small `wireguard_lwip` part) to a WireGuard endpoint on the Studio. Far less RAM (no control protocol, no DERP, no TLS) but it needs a port forward on the home router or a hosted relay, it is not on the tailnet, and keys are managed by us. Not the first choice because it breaks "just bring it anywhere" if the home router changes.
3. C: a Tailscale Funnel in front of the hub's robot endpoint: public HTTPS with a per-device token. Lowest RAM (one TLS session, mostly PSRAM) and no extra hardware, but it creates a public inbound endpoint for the hub, which the no-inbound-path property rules out unless the owner accepts it.

4. D: a phone bridge (suggested to the owner by ChatGPT, unverified). The robot starts its own Wi-Fi access point, the iPhone joins it with Personal Hotspot off, and an iPhone app that runs a local HTTP or SOCKS proxy (MonoProxy was named) together with the phone's own Tailscale forwards the robot's requests to the Studio. Ranked last, below A, B and C, and not built. Why it ranks last:
   - The robot's firmware would need proxy support (neither the voice link nor the update download speaks through a proxy today), which is new firmware work on its own.
   - iOS background limits: the app itself says it does not guarantee indefinite background operation, so the bridge can stop whenever the phone sleeps or the app is suspended.
   - The robot then depends on the phone being present, and it gives up the friend's Wi-Fi, which is the case Jesse asked for.
   - The combination (robot access point, iPhone joined to it, proxy app, Tailscale on the phone forwarding the proxy's outbound traffic) is untested by anyone we know of.
   What would have to be proven before D could be chosen:
   1. An iPhone on a robot-hosted access point, with Personal Hotspot off, can keep MonoProxy (or an equivalent proxy app) serving the robot for at least 30 minutes with the phone locked and the app in the background, and the voice link stays up.
   2. The phone's Tailscale app really carries the proxy's outbound connections to the Studio's tailnet address (iOS routing, not assumed).
   3. The firmware can send its voice link and its update download through an HTTP or SOCKS proxy within its internal RAM, and the proxy sees only encrypted traffic (the link is plain `ws` today, so the `wss` work comes first).
   4. A second person's phone can do the same without installing anything beyond the app, or Jesse accepts that only his phone can.
   Until all four are shown on real hardware, D is a fallback idea only.

We do not choose B, C or D silently. Option A's gate decides.

### Behaviour once it fits

- LAN first: at the home network the robot keeps using the LAN address of the hub. When that address does not answer (new Wi-Fi), it brings up the tailnet connection and uses the hub's tailnet address for the same link. One link, two addresses, no change in the protocol.
- Credentials: a per-robot Tailscale auth key, tagged `tag:robot`, reusable and ephemeral, created by Home (Tailscale API) or pasted by an admin. It is stored by the firmware in the unit's NVS network-secrets namespace at runtime. No tool of ours writes NVS at flash time, nothing writes at 0x9000, the key is never logged and never shown again after it is saved.
- Access rule: the tailnet policy lets `tag:robot` reach only the hub's robot port. Documented in the user doc with an example policy; Home checks and shows the result on the robot's status row.
- Revocation: the person removes the robot's key in the Tailscale admin page or from the Devices page ("Forget the network key"); the robot then works alone away from home and normally at home.
- Time: WireGuard needs a roughly correct clock. The unit gets time from the hub when it has the link; away it uses the same server time reply. To verify on the unit.
- Away without the tailnet (not yet set up, key expired, no route): the robot keeps working alone (faces, dance, own sounds, offline phrases), as today.

## Part B: saved Wi-Fi networks, with priority and easy sharing

### What the firmware already has

The `esp-wifi-connect` component (`SsidManager`) saves up to 10 networks in the unit's flash. On boot, `WifiStation` scans, keeps the saved networks it can see, sorts them by signal strength and tries them in turn. When none connect it starts its own setup access point with a page at its own address. BluFi (Bluetooth setup) exists in the xiaozhi board code.

### What we add (patch 134, unit side)

- A strict priority order: when several saved networks are in range, the one with the lowest priority number is tried first (home, then the phone hotspot, then the friend's), with signal strength only breaking ties. The order is the saved order and can be changed.
- Device tools (the existing MCP tool channel from the hub): `self.wifi.list` (names and priorities, never passwords), `self.wifi.add` (name, password, optional priority; the password is write-only and never echoed or logged), `self.wifi.remove`, `self.wifi.move`.
- A plain on-screen hint when no saved network connects ("No Wi-Fi: tap to add one").
- QR scan: on the "Add Wi-Fi" screen the camera reads a standard Wi-Fi QR code (`WIFI:T:WPA;S:name;P:password;;`, what an iPhone shows under Settings, Wi-Fi, share). The camera is normally off for privacy; it is turned on only for this scan, with a clear on-screen state, and turned off at once afterwards. The code is read on the unit and never leaves it.

### Home and the hub

- A "Robot Wi-Fi" list on the robot's Devices page: names and order only, add, remove, move. Passwords are write-only: they go from the browser to the hub to the robot in one request, are never stored by Home, never written to a log or a record, and never shown. Only an admin can change the list; a child or teen cannot.
- The link between the hub and the unit is the existing one (a LAN websocket without transport encryption today). A Wi-Fi password sent over it is visible to someone on the same local network. To address that, Home sends passwords only over the tailnet or when the link is encrypted (the `wss` work), and otherwise asks the person to use the QR scan or the setup page. Until `wss` lands the list pushes names and order only, and "add" is QR or the setup page. This is the conservative default and it is stated in the user doc.
- Old firmware: the hub asks the unit for its tools. A unit without the Wi-Fi tools shows "Needs the new firmware" and nothing else changes.

### Fallbacks that already exist

The unit's own setup page and Bluetooth setup stay as the last resort.

## Rules checked

- Rule: no data to a third party we did not choose. Tailscale is the household's existing choice; the unit adds a node to the same tailnet, outbound only.
- No secrets in logs: the auth key, Wi-Fi passwords and tailnet node keys never appear in the body log, the hub log or any record.
- Child and teen robots: only admins change networks and keys.
- Prebuilt over hand-built: MicroLink and the existing `SsidManager` are reused; nothing is rewritten.
- Download, do not vendor: MicroLink is fetched at a pinned commit and checked against a sha256; its licence (MIT) and the x25519 licence file go into `NOTICE`.

## Reuse check

Searched `tailscale`, `wireguard`, `microlink`, `ssid`, `SsidManager`, `blufi` and `wifi` in `bot/body/maipai_body/bodies/stackchan`, the firmware patches and `docs/dev`, and the xiaozhi and `esp-wifi-connect` sources. Reused: `SsidManager` and `WifiStation` (saved list and scan), the existing device tool channel, the existing status rows. New: the priority order, the Wi-Fi tools, the QR scan, MicroLink as a dependency.

## Phases

1. Spike (done on the build side, above): size and fit analysis. Open: the on-device low-water test.
2. Host side, no firmware: Home "Robot Wi-Fi" list and device command, body handler, capability detection (ships over Wi-Fi to the hub).
3. Firmware, combined with the updater (patch 133) and the faces (patch 132): Wi-Fi tools, priority, QR scan, MicroLink behind a flag. One USB visit.
4. On-device test: tailnet up on a second network, low-water gate, voice over the tailnet. Only then the flag defaults to ON and the Devices page offers "Let this robot go anywhere".

## Not verified

Everything on the unit: nothing is flashed. The PSRAM-stack plan, WireGuard speed from PSRAM, the clock, DERP-only voice quality (a third-party test of a different Tailscale stack on a CoreS3 measured about 47 KB/s through a relay, which is enough for voice at about 3 KB/s of audio but not for video), and the QR read quality at room distance are all untested.
