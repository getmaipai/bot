# StackChan firmware images: proposal (2026-11-14, revised after the independent security review)

Status: proposal. Nothing here is built into an image beyond the spike, and nothing is flashed. Related: `stackchan-anywhere-network-2026-11-14.md` (design, Parts A to C), `stackchan-faces-2026-11-14.md`, patch 133 (wireless update). This replaces the earlier single combined image: it is now FOUR images, one over USB and three over the air.

## Why split

The unit is on battery and not on USB. Its current firmware (0.2.86) has no updater, so the first image is flashed once over USB. A USB-written image resets the OTA data, so it has no previous slot to roll back to. That is why it must be minimal and why the updater has to be proven on the bench before anyone unplugs the cable. Everything riskier then arrives over the air, where a bad image rolls back by itself.

## The images

| Image | Delivered | Patches | Notes |
|---|---|---|---|
| 1 | USB, once | current `main` through 132 (faces) and 133 (updater) | No MicroLink, no priority change. Minimal on purpose. |
| 2 | over the air | 134 strict priority, 135 QR scan and setup hint | Then the priority tests at home. |
| 3 | over the air | 136 MicroLink (OFF until a unit passes its test) | Boot-loop guard; RAM re-measured after any mbedTLS change. |
| 4 | over the air | 137 to 139 Part C (the settings window and page) | After the Part C redesign is reviewed. |

The earlier notes disagreed on whether MicroLink is in the first image. Resolved: it is not. It is off until a unit passes its on-device test and arrives in image 3.

## Image 1 bench proof (before unplugging)

1. Flash image 1 over USB with `esptool` over the five app images only (bootloader and partition table only if their bytes differ from a full-flash backup taken first; never the NVS partition, never 0x9000). Pairing and saved networks stay.
2. A version-bump image delivered over the air installs and the unit reports the new version.
3. A deliberately bad image (it must not reach the hub link) is delivered: the unit rolls back to the previous slot by itself and reports the old version.
4. A good image is delivered again and installs.
5. Only then is the unit unplugged.

## Strict priority (patch 134, image 2): the decision

Goal: with two saved networks both in range, the higher-priority one is joined even when it is weaker (home first, then the hotspot, then a friend's).

The connect order is decided in `WifiStation::HandleScanResult` (sorts the visible saved networks by signal strength), and a new network is inserted at the FRONT of the saved list by `SsidManager::AddSsid`. Both are in the registry component `esp-wifi-connect` (pinned by `dependencies.lock`, commit `a7b34167750f0188486b489240268d0f7c306caf`), downloaded at build time, so the recipe's usual patch targets cannot reach it.

Choice: a project-local override of the component. The recipe downloads the exact pinned version into `firmware/components/esp-wifi-connect`, checks it against the lock's `component_hash`, applies patch 134, and a small patch to the xiaozhi `main/idf_component.yml` points the dependency at it (`override_path`). Changes: order the connect queue by saved-order index first with signal strength only as the tie-break and a floor (a network weaker than -85 dBm goes after the others); `AddSsid` appends at the END (lowest priority), because under strict priority a new hotspot or a friend's Wi-Fi at the front would beat the home Wi-Fi. A future component bump re-checks the patch like the others. Rejected: our own chooser in the board path (it would fight the component's reconnect state machine).

Host-side proof first: a header-only ordering function (`maipai_wifi_order.h`) with a C unit test covering priority over signal, the weak floor, ties, unseen networks and append-at-end, in the style of `maipai_beat.h`.

On-device priority tests (two access points of ours, for example the home router and a phone hotspot, both saved, home first):
1. Both visible, the hotspot clearly stronger: after a reboot the unit joins home.
2. Reorder (hotspot first): after a reboot the unit joins the hotspot even though home is stronger.
3. Top network switched off: the unit joins the second within one minute; switched back on, it stays on the second until the next reconnect (no flapping) and returns to the first after a reboot or a disconnect.
4. A top-priority network weaker than -85 dBm with a usable second: the second is joined.
5. A newly added network lands at the end of the list, not the front.
6. A unit with existing saved networks keeps all of them and their order after the flash.

## RAM rules (all images)

- Any task that writes NVS (or does any flash operation) has an internal-RAM stack. ESP-IDF asserts on flash operations from a PSRAM stack. NVS writes from PSRAM-stack tasks go to one internal-stack worker.
- The gate is measured with everything running at once: the voice link up, camera face watching on, MicroLink connected, and (from image 4) a setup page request in flight. Internal low-water mark at or above 25 KB for 10 minutes AND the largest free internal block at or above 16 KB (proposed; set from a measurement of the voice link's biggest reconnect allocation). Re-measure after any mbedTLS change.

## Image 3 safety

MicroLink starts only when a key is present and the flag is on; a boot-loop guard turns the tailnet client off by itself after 3 resets within 2 minutes of starting, and reports it. The robot never tries the hub's home LAN address on an unknown network (the unit sends its pairing token to whatever `ws://` address it holds): LAN only on the network marked as home, otherwise the tailnet only.

## Gates before any image is built beyond the spike

- `code-review` at medium on each patch, one at a time.
- The architect has looked at the design note (Parts A to C) after this revision.
- Images are built only into my own build directory, never over another session's, and are not flashed.

## On-device acceptance after image 1

1. Boots, shows the new faces, reports the new firmware version to the hub, pairing and saved networks intact.
2. The bench proof above (bump, bad image rolls back, good image).

Later images have their own acceptance lists: priority (image 2), QR scan with the vision-off switch honored and the pink light on (image 2), tailnet and RAM gate (image 3), the Part C checks (image 4).

## Not verified

Everything on the unit. The component override and the ordering function are designed, not written. MicroLink's behaviour with PSRAM stacks, the access point and page RAM, and QR read quality are unmeasured.


## Patch 140: the song title bar (added 2026-11-14)

A small display-only patch (`140-song-title-bar.patch`, after 133): the song title as white, bolder, slightly larger text on a solid black bar at the bottom edge (owner's words, 2026-11-14). It applies cleanly in the recipe's patch check and has a preview sheet; it changes no logic of patch 123 (same show, hide and 60 s deadline). Proposed image: the first over-the-air image (image 2, with 134 and 135), not image 1: image 1 stays minimal (132 and 133 only) because a USB-written image has no slot to roll back to. If the owner wants the title look sooner, it can join image 1 once a full firmware compile has passed.


## Beeping findings and firmware items (2026-11-14)

The robot made short beeps while idle and during a stuck dance. The host logged no sound requests, so the sounds are unit-originated: its own earcon list (patches 115 to 118, gated by `self.audio.set_sound_policy`, which now always says muted) or the stock voice-engine tones (`Application::PlaySound(Lang::Sounds::OGG_*)` on connect, activation, wake, listening and errors, plus patch 075 and 118's `OGG_VIBRATION` for the offline tone), which the policy does not gate. Signs in the log: the unit's music analysis reports a block of about 235 skipped windows (about 5 s) once or twice a minute, and the unit reconnects after each hub restart.

Next firmware image, in this order:

1. **A `sound_played` event** naming every sound the unit plays, from both its own list and the stock `PlaySound` calls (a wrapper at the one `Application::PlaySound` entry), so the host log names the cue. The host side already logs `robot activity:` lines and polls `self.audio.sound_info`.
2. **Stock tones gated by the same policy.** Route `Application::PlaySound` through `ms_decide` (muted and disabled refuse it; safety cues pass), so one setting silences stock tones too.
3. **No tone on reconnect or activation.** Remove the stock connect, activation and success tones, and the offline `OGG_VIBRATION` fallback when the link only blinked.
4. **Remove the host's temporary silence** (`SILENCE_UNIT_SOUNDS`) once 1 to 3 are proven on the unit.
