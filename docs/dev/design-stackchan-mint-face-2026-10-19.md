# StackChan: the mint face (2026-10-19)

Status: VERIFIED on the first unit (2026-10-20). Raised by Jesse on the first unit bench: "face needs to be cuter".

## Verdict

Replace the upstream face on the voice screen with a new skin, `MintAvatar`, drawn by firmware patch 013. Keep the upstream
`DefaultAvatar` untouched, because the dance, ESP-NOW and setup apps still create it. Add two faces, surprised and wink.

The bot repo has no `docs/design/RULES.md`, so the architect gate does not apply to this change.

## How we chose it

1. Jesse sent a reference grid of a minimal face on a pale mint screen with "more like this".
2. We drew two original sets in that style as SVG mockups (D: mint pal, E: mint pal with blush). The reference character is not
   copied: the shapes are plain dots, arcs and filled caps.
3. The first mockup was too small on a 320x240 screen; every feature was scaled 1.35 times around the face center.
4. Jesse picked D and asked for both new faces.
5. The real skin code was rendered in a host build of LVGL 9.4 (the firmware's version) before any flash, eight faces plus a
   blink frame and three lip sync frames. The render matched the approved mockup.

## The look

| Part | Value |
|---|---|
| Screen | `#C4F0DA` mint |
| Lines and dots | `#18241F` ink, 7 px rounded stroke |
| Mouth fill | `#3E9E6B` green, tongue `#8ED6A4` |
| Eyes | 22 px dots (30 px when surprised) at 78 px either side of center, 23 px above it |
| Mouth | 39 px below center |

| Face | Eyes | Mouth |
|---|---|---|
| neutral | dots | thin smile |
| happy | "^" arcs | open green cap with tongue |
| angry | ">" "<" | white teeth box |
| sad | dots with inner-raised brows | small green frown cap |
| doubt | one dot, one flat line with a brow | wavy line |
| sleepy | "u" arcs | small "o" |
| surprised | big dots | tall green oval with tongue |
| wink | left dot, right "^" | smile with tongue tip |

## Contracts kept

- **Blink:** the blink modifier drops eye weight to 25 for 200 ms. Any eye with weight below 50 draws a flat line, so every face
  blinks. Setting an emotion resets eye weight to 100, so the blink modifier's resync reads an open eye.
- **Lip sync:** the speaking modifier sets mouth weight 40 to 80 (open) or 0 to 20 (closed). Above 20 the mouth draws an open
  green cap whose height follows the weight; at or below 20 it draws the face's own mouth.
- **Idle drift:** eye and mouth position and eye size follow the idle modifier (position moves up to 16 px). Mouth rotation is
  stored but not drawn, because a rotated filled cap looks broken.
- **No speech bubble:** Jesse asked for no text under the face. The skin creates no bubble; the avatar's speech calls check for a
  missing bubble and do nothing, so `stackchan_display.cc` works unchanged. Sleepy loses the upstream "Zzz" text with it.
- **Tap:** the panel stays clickable.

## How a face is selected

Faces travel over the voice channel: the bot service sends an `llm` message with an `emotion` string, and the display's
`SetEmotion` maps it. Patch 013 adds `surprised` (also `shocked`) and `winking`. The host maps `wink` to `winking` in
`xiaozhi/server.py`. The avatar socket's JSON control sets weight, rotation and size only, so it cannot pick the new shapes; the
bench page already sends faces over the voice channel.

The reply mood `fear` now shows `surprised` instead of `doubt`.

## Files

- `body/maipai_body/bodies/stackchan/firmware/patches/013-mint-face-skin.patch`: adds `skins/mint/mint.{h,cpp}`, the two enum
  values, the include, the two `SetEmotion` names, and creates `MintAvatar` in `SetupUI`.
- `body/maipai_body/bodies/stackchan/firmware/patches/014-wifi-awake-while-speaking.patch`: Wi-Fi power while speaking.
- `face_set.json` regenerated from the patched enum (eight faces).
- `avatar/server.py`, `xiaozhi/server.py`, `expression_map.py` and their tests know the two new faces.

## On the unit (2026-10-20)

Jesse watched the mint face idle, blink, drift and talk on the first unit. The lip sync mouth closes when the audio ends
(commit 8986b10 fixed a mouth that stopped 1.4 s early).

**App-only flash keeps pairing.** Flashing the five images from `build/flash_args` with `esptool write_flash` leaves NVS alone,
so the unit keeps its Wi-Fi and pairing. After the flash, tap Skip, then AI Agent.

**Speech stutter was Wi-Fi power save, not the face.** Speech stuttered after the first mint flash. Two face changes cut the
work but not the stutter:

| Change | Result |
|---|---|
| Original mint skin | Each lip sync tick repainted 17,600 px; a breathing step 30,720 px |
| Redraw fix: skip unchanged hide, align and line calls; size line objects to their stroke | Lip sync 4,357 px, an unchanged mouth 10 px, breathing 16,168 px (the old face: 3,158, 874 and 3,069) |
| Free internal SRAM low point | 43 KB, the same as the old face (44.6 KB), so memory was not the cause |

Then the old face, rebuilt without patch 013, stuttered "bad" with the same ping (1.4 s average during speech, 9 of 40
lost). The serial log showed the cause: after activation the firmware sets Wi-Fi to `MAX_MODEM` power save and raises it only
when the robot opens its own audio channel. The host speaks over the persistent socket without that, so the radio slept
through speech. Patch 014 sets `PERFORMANCE` when the robot enters speaking and `LOW_POWER` when it returns to idle. With it,
ping during speech averaged 0.57 s (5 of 40 lost) and Jesse heard only a little stutter at the start and end.

**Left open:** the stutter at the start. Measured on 2026-10-20 (unit measurements, "Speech edges"): entering speaking
clears the decode queue about 100 ms after `tts start`, cutting the first 6 to 12 frames. Gaps mid-line and at the end
were Wi-Fi stalls from a 30-frame burst; the host now spaces its lead. Patch 016 fixes the start in firmware; it is built
and waits for a flash and a listening test.

**No speech bubble.** The text under the face is gone, as Jesse asked.
