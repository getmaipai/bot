# StackChan anywhere network: the robot joins the tailnet itself, and keeps a list of Wi-Fi networks

Status: design, owner-approved 2026-11-14, spike measured on the build side, nothing flashed. Item ids: ANYWHERE-01 (robot on the tailnet), ANYWHERE-02 (saved Wi-Fi list and sharing).

## Owner decision and what it replaces

Jesse, 2026-11-14: he is taking the robot to a friend's house and wants it designed "so people can just bring the robot anywhere". He rejected a travel router and rejected an iPhone relay app ("no travel router", a specific iPhone app to join the tailnet "without using hotspot"). In chat he approved starting both parts ("Yes, start both").

## Supersedes

- `docs/dev/design-stackchan-2026-10-14.md`, section 5.2a "Network shape", first two bullets: "The ESP32-S3 cannot run a Tailscale client ... so the device joins the home Wi-Fi and talks to the bot host on the LAN" and "Away from home, the person reaches the robot through the host over Tailscale ... The device itself never needs a public address and has no inbound path from the internet." Decision 5 of 2026-10-15 ("remote reach is over Tailscale, one mechanism for every robot body") stays; what changes is that the StackChan itself becomes a tailnet node so that it works on any Wi-Fi. The no-inbound-path property stays: the robot only makes outbound connections.
- Bot `docs/BACKLOG.md` ROBOT-TAILSCALE-01 (bot half, amended), two statements: "A body that cannot run Tailscale (StackChan's ESP32-S3) stays on the LAN and the bot host that runs its translator is the tailnet node", and, in its out-of-scope line, "a relay or proxy for a robot that is not a tailnet member". The first is superseded for the StackChan by this note (the unit becomes a tailnet node itself); the second stays true (we build no relay or proxy; option D below is a fallback idea only). The hub auto-provisioning half stays dropped (OWNER-ANSWERS 1): keys are pasted by an admin, never minted by Home.
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
- Credentials: the Tailscale auth key is PASTE-ONLY by an admin. Home does NOT mint keys through the Tailscale API: that was dropped by the owner on 2026-10-15 (OWNER-ANSWERS 1: a third-party account credential in the hub; bot `docs/BACKLOG.md` amendment table and the ROBOT-TAILSCALE-01 hub half). The admin creates the key in the Tailscale admin page and pastes it on the robot's Devices page. The key must be tagged `tag:robot` and EPHEMERAL, and preferably single-use or short-lived (an expiry of days, not months). Home shows the key's expiry to the person (the admin pastes the expiry date with the key, or reads it from the Tailscale admin page; Home never calls the Tailscale API to find out) and a one-click "Forget the network key" that wipes it from the robot.
- Key transport: the key (like a Wi-Fi password) is a secret and must travel encrypted, never over the plain `ws` link between the body and the unit. The allowed paths are: `wss` once it lands on the unit link; the setup page served by the unit's own access point (the phone joins the robot's access point, no router is in the path); or Bluetooth setup with encryption on. Until `wss` lands, Home refuses to send a key or a Wi-Fi password over the plain link and says why and which of the other paths to use. The key is held only in memory on the hub for the one request and is never stored in a Home record or written to a log.
- Key at rest, and the stolen-robot risk: the unit's NVS is not encrypted (no NVS encryption in `sdkconfig`), so the key sits in plain flash. Someone who steals the robot and reads its flash gets the key. What limits the damage: the key is tagged `tag:robot`, and the tailnet policy lets that tag reach only the hub's robot port (the example policy goes in the user doc); the key is ephemeral and expires on its own; and "Forget the network key" plus removing the node in the Tailscale admin page ends access at once. A reusable key is acceptable only because of the tag policy; a single-use or short-lived key is preferred. Flash encryption would remove the risk but is a bootloader change that cannot be done over Wi-Fi: out of scope, named here as the known gap.
- What happens on expiry: the unit's client detects the expired key (MicroLink reports key expiry), stops trying the tailnet, shows no error to a child, and tells the admin on the Devices page ("This robot's network key has expired. Paste a new one."). The robot keeps working alone away from home and normally at home. The hub never retries with an old key.
- Access rule: the tailnet policy lets `tag:robot` reach only the hub's robot port. Documented in the user doc with an example policy using placeholder addresses; Home shows the robot's tailnet status through the existing status rows. Home cannot read the policy (no API access), so the doc and the status row say "check your policy" and the robot's connection test shows whether the hub answers.
- Time: WireGuard needs a roughly correct clock. The unit gets time from the hub when it has the link; away it uses the same server time reply. To verify on the unit.
- Away without the tailnet (not yet set up, key expired, no route): the robot keeps working alone (faces, dance, own sounds, offline phrases), as today.

## Part B: saved Wi-Fi networks, with priority and easy sharing

### What the firmware already has (checked against the pinned tree, patches 1 to 133)

- The `esp-wifi-connect` registry component (`SsidManager`, pinned to 3.1.x by `dependencies.lock`) saves up to 10 networks in flash. A new network goes to the FRONT of the saved list. When the list is full it silently drops the last entry. List order is only the saved order: `WifiStation` scans, sorts the saved networks it can see by signal strength and tries them in that order. On a network that cannot be joined, the unit starts its own setup access point with a page at its own address; Bluetooth setup (BluFi) also exists.
- Patch 023 already adds unit tools on the MCP channel: `self.wifi.list_saved` (names, never passwords), `self.wifi.add`, `self.wifi.forget` (by index) and `self.wifi.switch` (moves a saved network to the front). Patch 044 makes the unit join the strongest access point of a saved network.
- So the unit side needs no new tools. What is missing is the hub and Home side that uses them, and a true priority order.

### What is new, and the constraint on it

- Strict priority (home first, then the hotspot, then the friend's, with signal only breaking ties) is not possible by patching the recipe's usual targets: the connect order lives in `WifiStation::HandleScanResult` inside a registry component that is downloaded at build time. Two ways, to be chosen when it is built: (a) a local override of `esp-wifi-connect` under `firmware/components` with a one-function change, pinned and checksummed, or (b) a chooser in our own `hal.cpp` that watches which saved networks are in range and, when a lower-priority one is joined while a higher one is visible, rejoins the higher one. Until then "preferred" means "tried first when the signals are close", which is what `self.wifi.switch` gives today. At a friend's house only that house's network and the hotspot are in range, so the common trip case works without it.
- The silent drop of the last entry when the list is full must be replaced by a refusal that says what to do ("Forget one network first"), in the Home list.
- QR scan: on the "Add Wi-Fi" screen the camera reads a standard Wi-Fi QR code (`WIFI:T:WPA;S:name;P:password;;`, what an iPhone shows under Settings, Wi-Fi, share). It follows the existing camera rules, not a special case: the camera's normal state is the watch mode set by `robot.camera.watch_level` (default on, `continual` frame delivery; household can set off, presence or identify), and the unit's hard vision-off switch (patch 106, saved in the `maipai_priv` NVS namespace) turns the camera off at the unit. The scan only runs when the vision-off switch is not set. While it runs the pink camera light is on and no setting can dim it (owner rule 2026-10-20), and the scan stays inside the leak check (the frame is decoded on the unit, only the Wi-Fi name and password are kept, nothing is sent). If vision is off, the screen says so in plain words ("The camera is off, so I can't read a QR code. Use the setup page: join my Wi-Fi name and open the address shown.") and the setup page is the way. Decision recorded: the scan is a person-started action and honors the vision-off switch; it does not depend on `robot.camera.watch_level`, which only governs idle face watching.
- A plain on-screen hint when no saved network connects, reusing the existing setup-hint text in the board code: "Add a Wi-Fi network in Home, or scan its QR code".

### Home and the hub

- A "Robot Wi-Fi" list on the robot's Devices page: names and order only, add, remove, move. Passwords are write-only: they go from the browser to the hub to the robot in one request, are never stored by Home, never written to a log or a record, and never shown. Only an admin can change the list; a child or teen cannot.
- The link between the body and the unit is the existing one (a LAN websocket without transport encryption today). A Wi-Fi password or a tailnet key sent over it could be read by someone on the same local network. Same rule as the key transport above: Home sends secrets only over an encrypted path (`wss`, or the unit's own access point setup page, or encrypted Bluetooth setup), and until `wss` lands the "add" action in Home refuses with a plain message that names those paths. The hub also does not persist a Wi-Fi password: the `wifi_add` command is delivered over the live connection only and is never written to the command table, a record or a log.
- Physical presence is trusted. Anyone who holds the robot, a child included, can add a network by QR or by the setup page, exactly as the setup page assumes today. Decision recorded: this is not gated (the robot's own setup has always worked this way, a child cannot reach other people's data through it, and a child-proof gate would stop the household from using it). What a child cannot do is change networks from Home: only an admin can add or forget a network or a key there.
- Old firmware: the hub asks the unit for its tools. A unit without the Wi-Fi tools shows "Needs the new firmware" and nothing else changes.

### Fallbacks that already exist

The unit's own setup page and Bluetooth setup stay as the last resort.

## Hard-coded hosts in MicroLink (read from source, pinned commit 216da33)

Read `components/microlink/include/microlink_internal.h` and the sources at the pinned commit in a temporary directory (downloaded, not vendored):

- Control server `controlplane.tailscale.com` and DERP default `derp9e.tailscale.com`: Tailscale's own services, the same ones the household's hub and phone already use. A Headscale control host is configurable. These are third-party hosts and get privacy rows (below).
- STUN: primary `derp9.tailscale.com`, and a HARD-CODED FALLBACK `stun.l.google.com`. The Google host is not acceptable (a public third party outside the household's tailnet choice; the capture check in `netcapture.py` has deny rows for exactly this kind of host). The build patch removes the fallback (set it empty and make the STUN code skip an empty host) so the only STUN hosts are Tailscale's DERP hosts delivered by the tailnet's own map. The patch is part of the MicroLink firmware patch and the `netcapture.py` deny list gets the Google STUN name added.
- NTP: MicroLink starts no SNTP client and names no NTP host (its only mention is a comment about key expiry). The unit's time comes from the hub's reply, as today, and no public NTP host is added.

## Privacy page rows (added with the feature, flag off until proven)

When the MicroLink flag ships, the privacy manifest in Home and the user page `what-home-looks-up.md` get two rows, listed only while the robot's tailnet setting is on:

- Tailscale control server (`controlplane.tailscale.com`, or the household's Headscale host): the robot registers and fetches the tailnet map; Tailscale sees the robot's node name, public key and addresses, never audio or messages.
- Tailscale DERP relays (for example `derp9e.tailscale.com`) and DERP-hosted STUN: used only when no direct path exists; traffic is end-to-end encrypted by WireGuard, the relay sees only sizes and timing.

## Review gate before any firmware build beyond the spike

Run `code-review` at medium on every firmware patch (MicroLink, the Google STUN removal, the QR scan screen, the priority chooser) before building an image from them. The spike so far is a build of MicroLink's own example, not our firmware.

## Backlog

Rows added to bot `docs/BACKLOG.md` with this commit: ANYWHERE-01 (robot on the tailnet), ANYWHERE-02 (saved Wi-Fi list and sharing), and an amendment row for ROBOT-TAILSCALE-01 in the supersede table.

## Rules checked

- Rule: no data to a third party we did not choose. Tailscale is the household's existing choice; the unit adds a node to the same tailnet, outbound only.
- No secrets in logs: the auth key, Wi-Fi passwords and tailnet node keys never appear in the body log, the hub log or any record.
- Child and teen robots: only admins change networks and keys.
- Prebuilt over hand-built: MicroLink and the existing `SsidManager` are reused; nothing is rewritten.
- Download, do not vendor: MicroLink is fetched at a pinned commit and checked against a sha256; its licence (MIT) and the x25519 licence file go into `NOTICE`.

## Reuse check

Searched `tailscale`, `wireguard`, `microlink`, `ssid`, `SsidManager`, `blufi` and `wifi` in `bot/body/maipai_body/bodies/stackchan`, the firmware patches (found patches 023 and 044) and `docs/dev`, and the xiaozhi and `esp-wifi-connect` sources. Reused: `SsidManager` and `WifiStation` (saved list and scan), the patch 023 Wi-Fi tools, the existing device tool channel, the existing status rows. New: the strict priority order, the QR scan, the hub and Home side, MicroLink as a dependency.

## Phases

1. Spike (done on the build side, above): size and fit analysis. Open: the on-device low-water test.
2. Host side, no firmware (the unit tools exist): a spec command kind for the Wi-Fi actions (add, forget, switch), the Home "Robot Wi-Fi" list on the Devices page (admin only), the body handler that calls the existing `self.wifi.*` tools, and a way to show the saved names. Showing the names needs the body to report them to Home; the robot check-in path that carries state returns HTTP 500 today (open bug, branch `cloud/checkin-500` not reviewed), so that bug is fixed first or the list is read through a command result. Ships over Wi-Fi to the hub.
3. Firmware, combined with the updater (patch 133) and the faces (patch 132): strict priority, the QR scan, the setup hint and MicroLink behind a flag. One USB visit.
4. On-device test: tailnet up on a second network, low-water gate, voice over the tailnet. Only then the flag defaults to ON and the Devices page offers "Let this robot go anywhere".

## Not verified

Everything on the unit: nothing is flashed. The PSRAM-stack plan, WireGuard speed from PSRAM, the clock, DERP-only voice quality (a third-party test of a different Tailscale stack on a CoreS3 measured about 47 KB/s through a relay, which is enough for voice at about 3 KB/s of audio but not for video), and the QR read quality at room distance are all untested.
