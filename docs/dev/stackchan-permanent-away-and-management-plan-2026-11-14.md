# StackChan: the permanent away-from-home experience and bot management, stage plan (2026-11-14)

Owner (Jesse, 2026-11-14): "fully build this out because this could be our final design. Register it to a tailscale network and then just give it any WiFi",
then: no relay focus; focus on Tailscale, easy Wi-Fi connections and bot management; a setup screen with a QR code like professional products; an iPhone
first flow (no NFC); a setup window that also works while the robot is connected to Wi-Fi but not working. This note is the plan and the facts it rests on.
It extends `stackchan-away-trip-and-permanent-2026-11-14.md` (decisions, MicroLink choice) and `stackchan-anywhere-network-2026-11-14.md` (security design).

## What exists now (built in this stage, verified on the build side only)

- Patches 147 (the tailnet client module, Kconfig, CMake hook, `self.tailnet.status` and `self.tailnet.set`, a boot-loop guard that switches the client off
  after 3 crashed boots in a row), 148 (connection order: home address, then the hub's tailnet address, then the Wi-Fi gateway on a network named `maipai*`)
  and 149 (a library patch for the pinned MicroLink: four task stacks in PSRAM, wg_mgr internal because it writes NVS, Tailscale's own STUN host).
- `recipe.sh --tailnet` fetches MicroLink at the commit pinned in `pins.toml` (`Csontikka/microlink`, MIT) into the build root, outside the StackChan tree;
  `--tailnet-authkey-file` makes a PRIVATE first-enrolment image from a key kept in a mode 600 file (never committed, never printed).
- Verified: the recipe applies all patches, the firmware compiles and links (app 3,421,920 bytes, 34 percent of the 0x4f0000 slot free; static internal RAM
  +2.2 KB over image 1; PSRAM +131 KB), host tests for the guard, the address helpers and the host choice pass. NOT verified: anything on a unit.
- Internal RAM budget estimate (not measured): wg_mgr stack 8 KB + the client's start task 5 KB + about 4 KB of queues and lwIP structures + 2 KB static is about
  20 KB against about 76 KB free (low-water 53 KB), so the 25 KB gate is plausible but thin. The first on-device test measures it.

## Facts found in the firmware and the library (2026-11-14)

- MicroLink has NO interactive login: a first registration needs a Tailscale auth key (it logs "AuthURL ... approve at" but does not poll for approval). Once
  registered it keeps its node keys in NVS (`microlink`, `ml_peers`; no collision with our namespaces) and later images carry no key. The key must be a
  one-off, tagged (`tag:robot`), non-ephemeral, pre-approved key with key expiry disabled for the node.
- lwIP routes any destination in 100.64.0.0/10 to the WireGuard interface (netmask /10), so the existing socket code connects to `100.113.4.61:62923`
  unchanged once the client is up. The first packet starts the WireGuard handshake (a few seconds): patch 148 gives a tailnet address an 8 s first probe.
- esp-wifi-connect already runs the setup AP in `WIFI_MODE_APSTA` (AP and STA at the same time), with an open AP, 4 clients, a DNS catch-all and a web
  server that answers the Apple (`/hotspot-detect.html`), Android (`/generate_204*`) and Windows (`/ncsi.txt`) captive portal probes with a redirect and
  serves a JSON scan list. So the setup window can run while the robot stays on Wi-Fi: the AP shares the STA's channel. If the STA must drop
  (a channel change when the home network moves), the robot is offline for the length of the window; the page says so.
- sdkconfig has `CONFIG_ESP_WIFI_SOFTAP_SAE_SUPPORT=y` and WPA3 SAE: a WPA3 setup hotspot is supported. `CONFIG_LV_USE_QRCODE=y`: the screen can draw a QR.
- Only the setup AP is open today (`WIFI_AUTH_OPEN`): the redesign (WPA3-SAE, a fresh single-use passphrase per window, nothing listening otherwise) needs a
  project-local override of the component (the same override patch 134 needs for strict priority).

## The iPhone-first setup flow (professional pattern, no custom app)

Pattern: the robot shows a QR code and a short code; the phone camera scans a standard Wi-Fi QR (`WIFI:T:SAE;S:<hotspot>;P:<passphrase>;;`), the phone joins the
robot's own protected hotspot in one tap, iOS opens the Captive Network Assistant sheet by itself, and a short page lists nearby networks. Why it is the best
fit without an app: it is what ESP SoftAP provisioning, Matter commissioning QR codes and Sonos/Chromecast code screens converge on; Web Bluetooth does not work in
iOS Safari, NFC on iPhone only opens URLs and cannot join Wi-Fi (and the CoreS3 has no NFC), and a camera plus a captive page needs nothing installed.

1. ENTRY (owner principle 2026-11-14: the hotspot and its page exist only while a setup window is open, opened deliberately; never an always-on access point).
   The primary, discoverable route is INSIDE the existing swipe-up quick-settings panel (volume, brightness, saved Wi-Fi, Done): it gets two entries, `Setup` and
   `Status`. Swipe left and right stay volume (the owner's habit; moving volume into the panel would add a step to something used daily, so the tradeoff is decided
   against a left/right swipe). Child safety: `Setup` needs a deliberate 2 s press-and-hold on a `Start setup` button, with the countdown and a single-use code,
   and the window closes by itself (10 minutes, or when setup succeeds, or a saved network returns). Automatic screens: with NO saved network reachable for 30 to 60 s the
   robot shows the Setup screen by itself (nothing opens a hotspot until the person starts one); with Wi-Fi up but no hub (home or tailnet) for 5 minutes the robot only
   OFFERS Setup (the same press-and-hold confirm). A Home command `show setup code` (robot reachable) shows the same offer. No update runs during a window and no window
   opens during an update; the page never changes the hub address and never accepts firmware.
1a. THREE WAYS TO ADD A WI-FI, in this order on the Setup screen: (1) ON THE ROBOT, no phone and no hotspot (the thermostat pattern): a scan list to tap, then an on-screen
   LVGL keyboard for the password with a show/hide toggle, a Join button and a clear tick or plain error; saved into the list of 10. (2) For a phone: the QR and short code
   below (the WPA3 hotspot opens only now). (3) Scan a Wi-Fi QR the phone made, with the robot's camera (patch 135). Option 1 is the smallest to build and test: it needs
   only the scan call (esp_wifi_scan in STA mode, with the AP closed) and an LVGL keyboard, and works with nothing else in place.
2. THE SCREEN: a large QR, a 6-character pairing code, one line ("Scan with your phone camera"), the countdown, and below it in order: "Or scan a Wi-Fi QR from your
   phone" (robot camera, patch 135, vision-off aware, pink light) and "Or add it from Home" (shown once the robot is on the tailnet).
3. THE PAGE (one short page, iOS CNA sheet safe: no window.open, no downloads, no reliance on persisted JavaScript state or multiple tabs): nearby networks to tap,
   a password field with a Show toggle, a Join button, progress, then a clear result ("Saved, you can close this" with a tick on the robot's screen too, or "Wrong
   password, try again"). iOS leaves a Wi-Fi network that has no internet, so: keep the hotspot up for 15 s after Join so the result shows, say plainly when it is done,
   and answer the Apple probes (`hotspot-detect.html`, `captive.apple.com` style, `success.txt`) with the portal redirect until setup is done, then with the real
   success body so iOS drops the sheet. Test the page in a narrow WebKit viewport (375 px, no address bar).
4. DIAGNOSTICS PANEL (same page): green and red steps with a plain next action: Wi-Fi joined and signal (rssi), got an address, DNS works, internet reachable,
   tailnet client state and last handshake, hub reachable over home and over the tailnet, the last error in plain words, firmware and host versions,
   buttons: Restart Wi-Fi, Restart robot, Forget the tailnet key (re-register), Forget all networks, add / forget / reorder Wi-Fi.
5. OFFLINE REASON ON THE SCREEN (replaces the bare word "Offline" after 45 s): "No known Wi-Fi in range" (setup window offered), "Wi-Fi connected, can't reach
   home" (tailnet state shown), "Hub not answering" with the recovery in one line.

### iPhone steps to put in the setup screen help and the trip card (verified by search 2026-11-14)

- A Wi-Fi QR for a network the iPhone knows (including a friend's network the iPhone has joined): iOS 18 Passwords app, Wi-Fi, tap the network, Show Network QR Code
  ([MacRumors guide](https://www.macrumors.com/how-to/share-wi-fi-passwords-with-qr-code-ios)); point the robot's camera at it (patch 135).
- The iPhone's own Personal Hotspot as a saved network: the CoreS3 is 2.4 GHz only. On iPhone 12 and later turn on Settings, Personal Hotspot, Maximize
  Compatibility (2.4 GHz); earlier iPhones already use 2.4 GHz ([Apple Platform Support](https://support.apple.com/guide/platform-support/sup025284ac0)). Keep the Personal Hotspot
  screen open while the robot joins.

## Stage plan (sizes: S under half a day, M about a day, L several days)

| Stage | What | Size | Local test without the tailnet |
|---|---|---|---|
| 0 | Spike build: patches 147 to 149, recipe flag, pin, tests (done) | S | host tests, compile |
| 1b | EARLY, LOCAL: the Setup entry in the swipe-up panel, the press-and-hold confirm, and option 1: join a Wi-Fi from the touchscreen (scan list, LVGL keyboard with show/hide, Join, tick or error). Smallest on-device test: forget the home network in Home, open Setup from the panel, tap the network, type the password on the robot, see the tick and the robot rejoin | M | yes (needs only the robot) |
| 1 | FIRST ON-DEVICE TEST: private first-enrolment image, register, connect from a phone hotspot, RAM gate, 10 minute soak, same identity after reboot and Wi-Fi switch | S | no |
| 2 | Home: tailnet connections count as an encrypted link (`link_encrypted` true, peer 100.64/10), add Wi-Fi from Home over it (wifi_add, existing route and card), reorder, status "Connected through your tailnet (away)", tailnet address and last seen | M | host and Home tests |
| 3 | Strict Wi-Fi priority: project-local override of esp-wifi-connect (saved order first, -85 dBm floor, append at end), host-tested ordering | M | host tests |
| 4 | Setup window for a phone: WPA3 hotspot plus APSTA, single-use passphrase, QR screen, captive page (iPhone-first), the offers, diagnostics panel, offline reasons | L | yes (all local) |
| 5 | Robot camera scan of a Wi-Fi QR (patch 135) | M | yes |
| 6 | Bot management in Home (Devices, kit parts): path and quality, versions, Update button through the updater (idle, battery or charger rules), restart connection / robot, rename, forget the tailnet key; unit self-healing (Wi-Fi up but no hub for 10 minutes: restart Wi-Fi, then reboot) | M to L | host tests |
| 7 | Production enrolment without a private build: an admin pastes the key in Home over the encrypted link, expiry shown, one-click forget (ANYWHERE-03 tail) | M | no |

Smallest path to Jesse's whole flow (register the robot, add a Wi-Fi from Home, see it connect through the tailnet away from home): stages 1, 2 and the
tailnet part of stage 3 (add order). Stage 4 can start at once in parallel: it does not need the tailnet.

## The first on-device test Jesse would be asked to approve (stage 1)

Before it: Jesse creates one Tailscale auth key (admin console, Settings, Keys: reusable off, ephemeral OFF, pre-approved ON, tag `tag:robot`; the tag owner and a grant limiting
the tag to the Studio's two robot ports, and key expiry disabled for the node), saves it with nano into `~/.config/maipai/tailnet-robot-authkey` (mode 600); it is
never pasted in chat or git. Then one USB connection and one go: I flash the private image (full-flash backup first, no NVS write), the unit registers as
`maipai-robot`, and I check from the Studio: `self.tailnet.status` ready, the 100.x address in the machine list, internal RAM at or above 25 KB with voice and avatar
running, a chat turn over the tailnet from a phone hotspot, the same machine entry after a reboot and a Wi-Fi switch, a 10 minute soak. Rollback: flash the saved image 1
(`~/esp/stackchan-build/image1/image1-0.2.102`) with `stackchan_flash_nonvs.py`.

## Risks and open items

- Internal RAM is the real risk (estimate above). If the gate fails: trim the client's peer and buffer settings first, then the diagnostics page, then consider the
  plain WireGuard endpoint option from the earlier note.
- A relay-only tailnet path is slow for large transfers (one measured OTA took 498 s against 26 s direct) but fine for voice; the updater should prefer the home path.
- Owner decisions (2026-11-14): a WPA3-SAE hotspot with a single-use passphrase counts as an encrypted channel for CREDENTIALS.md; NVS encryption is NOT done now (an eFuse that
  cannot be undone). The robot's own tailnet connection also counts as an encrypted channel (WireGuard): the check-in reports `link_encrypted` when the connection comes from
  the unit's own tailnet address while its tailnet client says connected (bot 0.2.104).
- Connection order of the trip firmware (the end-state design): the home address first, then the Studio over the tailnet, then the `maipai*` gateway fallback (the laptop relay,
  compiled in with `STACKCHAN_FALLBACK_GATEWAY`, off in the end state with `--no-gateway-fallback`). The gateway fallback costs about 1 byte of static RAM; the setup window
  (access point and page) is an estimated 20 to 30 KB of internal RAM only while it is open and nothing when closed (not measured).
- Away test without moving the robot (ANYWHERE-08): `wifi_use` (patch 154, memory-only hold with an automatic return after 3 minutes without the hub) and `prefer_tailnet`
  (patch 153); see `docs/dev/robot-wifi-command.md` in Home.
- The Tailscale policy cannot be read from here: the grant JSON and the allow-all check are for Jesse's account (`tag:robot` to the Studio's two ports only).
