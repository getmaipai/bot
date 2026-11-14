# StackChan combined firmware image: proposal for the one USB flash (2026-11-14)

Status: proposal. Nothing in this list is built into an image yet, and nothing is flashed. Related: `stackchan-anywhere-network-2026-11-14.md` (design, Parts A to C), `stackchan-faces-2026-11-14.md`, patch 133 (wireless update).

## Why one image

The unit is on battery and not on USB. Its current firmware (0.2.86) has no updater, so the next image has to be flashed once over USB. After that, patch 133 lets later images arrive over Wi-Fi. So that one image should carry everything that needs the bootloader or a first install: the updater, the new faces, the saved-network priority, the QR scan, the tailnet client (compiled in, off), and the on-robot settings page.

## Contents

| Patch | What | State |
|---|---|---|
| 132 | the new face shapes (joy, content, excited, shocked, curious, love, worried) | on bot `main` |
| 133 | wireless firmware update and the update icon | on bot `main` |
| 134 | strict saved-network priority (see the decision below) | to write |
| 135 | the "Add Wi-Fi" QR scan screen | to write |
| 136 | MicroLink tailnet client: three stacks in PSRAM, Google STUN fallback removed, build flag compiled IN but off at runtime until a key is pasted | to write |
| 137 to 139 | the settings page on the robot (Part C): setup window, HTTPS server and sessions, pages | to write after the architect has looked |

The sleep "z" overlay and the unbuilt faces (dizzy, silly) are not in this list.

## Strict priority: the decision

Goal: with two saved networks both in range, the higher-priority one is joined even when it is weaker (home first, then the hotspot, then a friend's).

The connect order is decided in `WifiStation::HandleScanResult` (sorts the visible saved networks by signal strength and pushes them into `connect_queue_`). That file is in the registry component `esp-wifi-connect` (pinned by `dependencies.lock`, commit `a7b34167750f0188486b489240268d0f7c306caf`), downloaded at build time, so our recipe's usual patch targets cannot reach it.

Options:
1. Project-local override of the component. The recipe downloads the exact pinned version into `firmware/components/esp-wifi-connect`, checks it against the lock's `component_hash`, applies patch 134 to `wifi_station.cc`, and a small patch to the xiaozhi `main/idf_component.yml` points the dependency at it (`override_path`). The change is one function: order the queue by saved-order index first, signal strength only as the tie-break and as a floor (a network weaker than -85 dBm goes after the others, so a barely visible top-priority network does not block a usable one). If joining fails, the next entry in the queue is tried, as today.
2. Our own connect-order logic in the board's start path. Rejected: the component owns the station state machine (it reconnects and rescans on its own events), and a second chooser that disconnects and joins by hand would fight it. That is the less safe path.

Choice: option 1. It is smaller (one function), keeps the component's state machine, and is deterministic. Cost: the recipe must fetch and verify one more pinned download, and a future component bump must re-check the patch (same discipline as the other patches).

On-device acceptance test (needs two access points of ours, for example the home router and a phone hotspot, both saved, home first in the list):
1. Both visible, the hotspot clearly stronger: after a reboot the unit joins home. Serial log shows both in range and home chosen.
2. Move the saved order (hotspot first): after a reboot the unit joins the hotspot even though home is stronger.
3. Switch the top network off: the unit joins the second within one minute; switch it back on: the unit stays on the second until the next reconnect (no flapping) and returns to the first after a reboot or a disconnect.
4. A top-priority network weaker than -85 dBm with a usable second: the second is joined.
5. Saved-network migration: a unit with existing saved networks keeps all of them and their current order after the flash.

Host-side proof before the flash: a header-only ordering function (`maipai_wifi_order.h`) with a C unit test covering priority over signal, the weak floor, ties and unseen networks, in the same style as `maipai_beat.h`.

## Gates before any image is built beyond the spike

- `code-review` at medium on patches 134 to 139, one at a time.
- The architect has looked at the design note (Parts A to C).
- A combined image is built only into my own build directory, never over another session's, and is not flashed.

## On-device acceptance gates (after the USB flash)

1. Boots, shows the new faces, reports firmware `0.2.9x` to the hub, pairing and saved networks intact (the flash never writes the NVS partition).
2. Priority tests 1 to 5 above.
3. QR scan: with the vision-off switch off, a Wi-Fi QR code from an iPhone is read and saved with the pink light on; with the switch on, the screen says so and nothing is read.
4. Tailnet: with a pasted ephemeral tagged key, the unit joins the tailnet on a second Wi-Fi network, reaches the hub's robot port and the voice link works. Internal RAM low-water mark stays at or above 25 KB for 10 minutes while connected with the voice link up. If it does not, the tailnet flag stays off and the options in the design note (B, C, D) are reopened.
5. Updater: a later image delivered over Wi-Fi installs, and a deliberately bad image rolls back.
6. Part C (when built): the checks listed in its section.

## Flash steps (when approved)

`esptool` write of the five app images only (bootloader, partition table, otadata, app, assets), at the offsets in `build/flash_args`. Never the NVS partition, never 0x9000. The unit is connected to the Studio by USB for this one time. Pairing, saved networks and settings stay.

## Not verified

Everything on the unit. The component override and the ordering function are designed, not written. MicroLink's behaviour with PSRAM stacks, the HTTPS server's RAM, and QR read quality are unmeasured.
