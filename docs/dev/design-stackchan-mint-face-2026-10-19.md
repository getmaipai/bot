# StackChan: the mint face (2026-10-19)

Status: BUILT, flash pending. Raised by Jesse on the first unit bench: "face needs to be cuter".

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
| sleepy | "u" arcs | small "o", plus the upstream "Zzz" bubble |
| surprised | big dots | tall green oval with tongue |
| wink | left dot, right "^" | smile with tongue tip |

## Contracts kept

- **Blink:** the blink modifier drops eye weight to 25 for 200 ms. Any eye with weight below 50 draws a flat line, so every face
  blinks. Setting an emotion resets eye weight to 100, so the blink modifier's resync reads an open eye.
- **Lip sync:** the speaking modifier sets mouth weight 40 to 80 (open) or 0 to 20 (closed). Above 20 the mouth draws an open
  green cap whose height follows the weight; at or below 20 it draws the face's own mouth.
- **Idle drift:** eye and mouth position and eye size follow the idle modifier (position moves up to 16 px). Mouth rotation is
  stored but not drawn, because a rotated filled cap looks broken.
- **Speech bubble and tap:** the skin keeps the upstream bubble and a clickable panel, so `stackchan_display.cc` works unchanged.

## How a face is selected

Faces travel over the voice channel: the bot service sends an `llm` message with an `emotion` string, and the display's
`SetEmotion` maps it. Patch 013 adds `surprised` (also `shocked`) and `winking`. The host maps `wink` to `winking` in
`xiaozhi/server.py`. The avatar socket's JSON control sets weight, rotation and size only, so it cannot pick the new shapes; the
bench page already sends faces over the voice channel.

The reply mood `fear` now shows `surprised` instead of `doubt`.

## Files

- `body/maipai_body/bodies/stackchan/firmware/patches/013-mint-face-skin.patch`: adds `skins/mint/mint.{h,cpp}`, the two enum
  values, the include, the two `SetEmotion` names, and creates `MintAvatar` in `SetupUI`.
- `face_set.json` regenerated from the patched enum (eight faces).
- `avatar/server.py`, `xiaozhi/server.py`, `expression_map.py` and their tests know the two new faces.

## Not verified yet

The face on the real unit. Steps: build with `recipe.sh`, flash with `body/scripts/stackchan_flash.py`, then step through the
eight faces and a spoken line from the bench page with Jesse watching.
