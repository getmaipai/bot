# StackChan: listening and thinking faces, the shared link screen, the offline look, the power key (2026-11-13)

Status: BUILT (firmware patches 110 to 114 compile and link; host side tested). Patch 109 is intentionally unused; the recipe proceeds from 108 to 110. NOT flashed and NOT seen on a unit. Source:
`docs/dev/stackchan-lights-audit-and-plan-2026-11-13.md` (master table rows 1 to 5, 11, 13, 33, 35, 39 to 41; sections 11, 16, 18) and the
owner's answers the same day: the face carries thinking and speaking, the ring is dark by default, "build the rest out".

## What was built

| Patch | What | Files |
|---|---|---|
| 110 | Two new faces in the mint skin: `listening` (eyes a little wider and rounder, mouth a short closed line) and `thinking` (eyes up and to the right, a small level mouth nudged to that side). Two new `Emotion` values, two names in `SetEmotion`. | `emotion.h`, `skins/mint/mint.cpp`, `stackchan_display.cc` |
| 111 | The shared link screen: one black cover with a glyph slot (the shipped Wi-Fi icons at 1.5 times) and a text slot, used for "Connecting to Wi-Fi...", "Wi-Fi setup needed" (with the hotspot name and address from the setup flow, on their own lines), "Connecting to Home..." and "Waiting for Home to approve me" (slash glyph plus a key drawn from shapes). The ring is dark at boot; only Wi-Fi setup and approval blink it cyan. The old boot cover, boot ring blink and the dim white at the first Standby are removed. | `stackchan_display.cc/.h` |
| 112 | The standing offline look once the face is up: the muted `offline` palette (grey-blue, eyes 5 px lower), a corner strip with the slash glyph and "Offline" instead of a speech bubble (the mint skin has no bubble, so the old "Offline" and "Can't reach Home" text never showed), a connecting strip (glyph cycling, no words) after 3 s down, restored when the session opens. The offline palette is reserved: the host's palette tool cannot pick it and it is never saved. | `mint.cpp`, `stackchan_display.cc/.h`, `hal_bridge.cc/.h`, `stackchan.cc`, `application.cc`, `websocket_protocol.cc` |
| 113 | The "refused / waiting for approval" state: the unit counts connects that were accepted and then closed before the hub's hello; two in a row show the approval look (full screen at boot, the strip with the muted palette and a cyan ring after). | `websocket_protocol.cc/.h`, `stackchan.cc`, `stackchan_display.cc` |
| 114 | The power key: a handler that blanks the ring and shows the sleeping face when the key has been held about a second, before the PMIC's own cut about three seconds later. | `stackchan.cc`, `hal_io_expander.cpp`, `hal_bridge.h` |

Host side (bot, no release yet): `listening` and `thinking` are in `face_set.json`, `CUE_FACE_MAP` (replacing `neutral` for those two cues), the
avatar and xiaozhi expression tables, and the renderer. A unit older than `FACES_MIN_FIRMWARE` (0.2.66) is still sent `neutral`
(`face_for_firmware`). The head moves that go with the cues (`perk` for listening, `attend` for thinking, and `speak`) no longer send a face
of their own: each one sent `neutral` right after the cue and would have painted over the new face.

## Preview stills (owner approval, decision D6)

`docs/dev/stackchan-faces-preview-2026-11-13/sheet.png` (`gen.py <icon folder> sheet.html` redraws it and writes one SVG per still): the neutral reference, `listening`,
`thinking`, the offline look, the connecting strip, the approval strip and the three link screens. They are drawn by `gen.py` in the same
folder from the numbers in `mint.cpp` (320x240 panel, 1.35 scale, the unit's own Wi-Fi icon data), not rendered by LVGL, so the font and edge
smoothing differ from the screen. Draw parameters:

| Face | Eyes (mockup units, times 1.35 for pixels) | Mouth |
|---|---|---|
| neutral | dot radius 8 | quadratic from (-26,-4) through (0,14) to (26,-4) |
| listening | dot radius 10 (neutral 8, surprised 11) | quadratic from (-16,0) through (0,7) to (16,0) |
| thinking | dot radius 8, offset (+6,-8) from the eye centre | straight line from (-4,3) to (12,3) |
| offline palette | background 0xBBC6CE, ink 0x26303A, fill 0x62788A, tongue 0xA5B6C3, eyes 5 px lower | unchanged |

## How the link looks are decided

`ApplyLink()` in `stackchan_display.cc` is the one place. Inputs: the boot status (`boot_look_`, from `SetStatus`), whether the first Standby
has passed (`boot_done_`), the Wi-Fi setup hint, and three flags the websocket task sets through `hal_bridge::hub_link_set(connecting,
offline, refused)`: connecting after 3 s down, offline after 10 s down (also the dim amber ring, unchanged from patch 075), refused after two
accept-then-close connects. Before `boot_done_` the full screen shows; after it the strip shows, with precedence refused, offline,
connecting. `hal_bridge::link_note(text)` puts a short line on the strip (the tap that finds no Home: "Can't reach Home" for 3 s). Wi-Fi setup
always shows the full screen, also when asked later.

## What is known only from the build

- Compiles and links with the other patches (`recipe.sh`), size in the release note; the strip, the link screen and the palette were not
  drawn on a screen by LVGL. Layout numbers (strip at 6,6 with a 236 px text width, glyph at 1.5 times, label top at y 96) come from the
  panel size, not from looking at it.
- The approval state is inferred, not read: the hub accepts the socket and then closes it with code 1008 and a reason text, but the
  firmware's websocket class does not hand the close code to the caller. Two accepted-then-closed connects in a row count as refused. A hub
  that is simply restarting closes sockets too, but it does not accept the handshake first, so it reads as offline. The check is a unit
  that Home has not approved: it must show the key look within a minute.
- Patch 114 (the power key): see the next section.

## The power key: what the code says and what only the unit can

Facts from the code (the pinned M5 tree and patch 050): `stackchan.cc` writes AXP2101 register 0x27 to 0x00, which by the AXP2101 register
map is the key's "long press" threshold of about 1 s and the PMIC's own power-off after about 4 s (the shortest settings; the bit meanings
are from the register map, not yet checked on a unit). Nothing in the firmware reads the key. `Axp2101::PowerOff` (register 0x10 bit 0) is
used only by the idle shutdown, which already blanks the ring first (patch 050). The ring is 12 pixels held by the PY32 expander on the
base; the audit's reading, still unmeasured, is that the base keeps its last colours when the CoreS3 loses power.

What patch 114 does: at boot it sets bit 2 of register 0x41 (so the PMIC keeps the long-press flag) and clears register 0x49. Every 100 ms
the touch timer reads register 0x49; when bit 2 is set it clears it, blanks the ring (`leds_blank(true)`, which keeps the host's colours in
the shadow) and sets the `sleeping` face. If the unit is still running 6 s later the key was let go: the ring (only if this handler
blanked it) and the neutral face come back. Boot already writes the ring black twice (`hal_io_expander.cpp`), and the dim white at the first
Standby is gone (patch 111).

What cannot be decided without the unit (10 minutes, power button on USB and on battery):

1. Does the long-press flag really appear in register 0x49 bit 2 at about 1 s (watch the log line "power key held")?
2. Does the PMIC cut at about 4 s, and does the unit with USB attached power off or restart (a new "unit boot" line in the host log)?
3. After the cut, is the ring dark? If the base keeps its last colours, the blank written before the cut is what keeps it dark. If a
   unit that is off on USB still lights the ring, the base rail is fed from USB and only a blank can help, which this patch does.
4. A press shorter than 1 s must do nothing visible.
5. Let go at 2 s: the face and the ring return about 6 s after the flag.

Not done: a "goodbye" tone before the cut (the sound patches own the earcons), and a ring that stays dark if the unit is switched off with
something else writing the ring in its last second (the host cannot write while the unit is leaving).

## Tests

Host: `tests/test_stackchan_listening_thinking_faces.py` (new), and the updated expression, face set and live-fix tests. Firmware: the patch
series applies in order (`recipe.sh`), the images build, and `STACKCHAN_CHECK_ONLY=1 recipe.sh` configures; nothing runs on a unit.
