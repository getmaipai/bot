# StackChan face vocabulary, 2026-11-14

The host uses a logical face vocabulary independent of the currently flashed face renderer. Every host face request goes through `StackChanBehavior.show_face`, including reactions, idle changes, orientation reactions, music dance cues, and meeting reactions. Turn expressions use the same `resolve_face` vocabulary in the StackChan renderer. The existing turn, rest, mute, camera cue, link strip, and tap-zone guards remain authoritative.

## Vocabulary and current fallback

| Logical name | Firmware face after release | Current firmware fallback |
| --- | --- | --- |
| neutral | neutral | neutral |
| happy | happy | happy |
| joy | joy | happy |
| content | content | happy |
| wink | wink | wink |
| excited | excited | happy |
| surprised | surprised | surprised |
| shocked | shocked | surprised |
| curious | curious | doubt |
| thinking | thinking | thinking |
| listening | listening | listening |
| love | love | happy |
| sad | sad | sad |
| worried | worried | doubt |
| angry | angry | angry |
| sleepy | sleepy | sleepy |
| dizzy | dizzy | doubt |
| silly | silly | wink |

Firmware 0.2.86 draws only the ten names in `face_set.json`; no new faces are enabled yet. `NEW_FACES_FIRMWARE` is `None`, so the nine new shapes always use their listed fallbacks. Setting the minimum version after a firmware release makes those logical names resolve to native faces. `face_set.json` remains generated upstream data and is not changed here.

## Event mapping

- Reply moods: happiness maps to happy by default, joy when the cue also carries excitement; joy to joy; excitement to excited; surprise to shocked; love, affection and adoration to love; contentment to content; playful to silly; anger to angry; sadness to sad; fear to worried; doubt to curious; sleepiness to sleepy; wry to wink; unknown moods to neutral.
- Orientation: left or right side maps to worried, upside down to shocked, face down or on back to sleepy.
- Touch: shake maps to dizzy. A pet, stroke or confirmed tap keeps the heart (the unit's heart symbol, or the love face when the unit has no symbol tool), as the owner ruled on 2026-10-21 that a touch always gets one reaction. A surprised-then-wink poke and a content stroke are not wired yet: they would replace the heart the owner asked for, so they wait for a decision on which reaction wins.
- Music dance face rotation uses joy, happy, wink, and excited. `mood_for_genre` maps aggressive, metal, punk or hard to angry; ballad, love or soul to love; pop, dance or EDM to excited; ambient, chill or lofi to sleepy. The song identification result is wired conditionally for a `genre` string, but Home's current result does not promise or currently provide that field.
- Idle faces are weighted across happy, content, curious, thinking, sleepy, wink, silly, and rare surprised. Existing wait timing and no-repeat behavior are retained.
- Meeting decisions: arrived is surprised then happy; recognised is happy; child is excited; stranger is curious; left is briefly sad; returned after a long absence is excited. The existing camera greeting edge after a long absence is wired as `returned_after_long`. No explicit arrived, left, recognised, child, or stranger events are currently emitted by `presence_watch.py` or `person_tracker.py`, so those kinds have no event wiring yet.
- Rest stages send the existing rest faces and request sleep-Z stages 1, 2 and 0 for drowsy, asleep and awake. `SLEEP_Z_FIRMWARE` is `None` until firmware exposes the tool, so it is currently a no-op.

## Current and future firmware

On firmware 0.2.86, new logical names render their current fallbacks: joy/content/excited/love use happy, shocked uses surprised, curious/worried/dizzy use doubt, and silly uses wink. The ten existing faces retain their native names. After the firmware release adds the new shapes, setting `NEW_FACES_FIRMWARE` enables their native rendering automatically. Sleep-Z remains independently version gated.
