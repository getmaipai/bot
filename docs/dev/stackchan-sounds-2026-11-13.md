# StackChan sounds: the earcon family and the local offline phrases (2026-11-13)

Built from sections 14 and 17 of `stackchan-lights-audit-and-plan-2026-11-13.md` after the owner approved the plans ("build the
rest out"). Firmware patches 115 to 118; host module `bodies/stackchan/sounds.py`. Nothing here has run on a unit: the firmware was
built with `recipe.sh` (all four patches apply and compile), the logic is tested on the host. The listening test is the owner's.

## What was built

**One earcon family** (`firmware/assets/sounds/snd_*.ogg`, rendered by `body/scripts/render_unit_sounds.py`, deterministic): a soft
bell (a sine with a quiet second and third harmonic, 10 ms attack, exponential decay), rising for good news and falling for bad.
Ogg Opus, mono, 16 kHz, 24 kbps, 60 ms frames (the encoder settings of the shipped tones; every packet reads as 0x58 like theirs).

| Name | Shape | Length | Bytes | Played by | Night |
|---|---|---|---|---|---|
| `needs_you` | two notes rising, insistent | 0.80 s | 2.4 KB | firmware: Wi-Fi setup (first use) at once and each minute; refused, once | first setup only |
| `plug_in` | two notes rising, quick | 0.46 s | 1.3 KB | firmware: charger in | no |
| `charged` | three notes rising | 0.88 s | 2.7 KB | firmware: charging stopped with the cable in | no |
| `unplug` | one note falling | 0.48 s | 1.4 KB | firmware: cable out | no |
| `offline` | two notes falling | 0.72 s | 1.9 KB | firmware: link down 10 s (once per outage) | no |
| `goodbye` | three notes falling, slow | 0.98 s | 3.0 KB | the power key work calls `maipai_sounds_goodbye()` | yes |
| `shutter` | a short double click | 0.42 s | 0.5 KB | host: the camera cue goes up | yes (privacy) |

The five shipped tones stay as they were and are playable by name: `success` (back online, dance start), `popup`, `vibration`,
`exclamation` (error), `low_battery`. The pop tone was kept as it is: it is already a short rising tone and re-rendering it would
change a sound the household knows without a clear gain.

**Where they live.** The seven new earcons are embedded in the app image (`main/CMakeLists.txt` lists them, `recipe.sh` copies them
into `assets/sfx`), not in the assets partition: the first-setup cue must play before the assets are applied (they are applied in the
activation task, which never runs while the unit waits for Wi-Fi), and a file in the image cannot be missing at run time. The sixteen
offline phrases are in the assets image (memory mapped, `ph_<group>_<n>.ogg`), because the wake word itself needs the assets.

**The tool** `self.audio.play_sound {name, urgent, test}` plays one of the twelve fixed names. It follows the speaker volume the host
already sets, and refuses (answering `{ok:false,error}`) when muted, switched off, or at night unless the cue is a safety or privacy
cue. `self.audio.set_sound_policy {enabled, night_ok, muted, dark, quiet_from, quiet_to}` stores the policy in the unit's own NVS
namespace `mp_sounds` (only on a real change; `dark` is never saved), so quiet hours still hold with Home down because the unit
judges them on its own clock. `self.audio.sound_info` reports the policy, the link state, how many of the sixteen clips are in the
assets and the play counts. A weak `maipai_mute_active()` returns false today; the hard mute work overrides it (or sets `muted`
through the policy).

**Tier 2, the local offline phrases.** When the wake word or a tap fires with no socket to the body (the 400 ms path of patch 075),
the unit plays a clip chosen by what it knows: no Wi-Fi, connecting (under 10 s), no host (10 s or more), refused (the host accepted
the connection and closed it before the hello, twice in a row), and "I'm back" after an outage over a minute. Sixteen clips in five
groups (4, 4, 3, 3, 2), a round robin so none repeats in a row, at most one per 10 s and three in any minute, then the old tone; at
night or with sounds off the tone only; muted, nothing. A clip missing from the assets falls back to the tone and is counted.

**Tier 1 is untouched** (`turn.py _offline_line`, the body is up and Home is down). The two tiers never both speak: tier 2 is called
only from `ShowCantReachHome`, which patch 075 reaches only when the unit has no open channel to the body, and tier 1 speaks only on
a turn the body is running. A test reads patch 075 to keep that true.

**Host** (`sounds.py`): pushes the policy (on a settings change, on connect, when the sensor night flips, and every 5 minutes as a
repair), plays the host-owned cues from a worker thread (a camera cue never waits on the unit): the low battery earcon then the line
"My battery is low. Please plug me in." once per crossing (the line by day only), the shutter, the error earcon before the apology,
the success chime at a dance start; and answers the hub's `sound_test` command (starts a background test that plays all twelve in
turn, skipping "off" and the night rule but never the mute, and answers at once).

## When it may chime (owner, 2026-11-14)

"This is not something to chime for." A chime is for something a person must notice, or that just changed because of them. It is never for something the robot chose to do by itself.

May chime (`CHIME_ALLOWED` in `sounds.py`): `needs_you` (a person must act or decide), `plug_in`, `unplug` and `charged` (power events a person caused), `low_battery`, `shutter` (a picture was taken), `goodbye` (shutdown), `exclamation` (a failure after an action they asked for). A timer or alarm they set rings through the alarm controller, not through this list.

Never chimes: dancing and the music session (no dance start chime), song naming and its retries, face changes and idle looks, reconnects, retries, update checks and anything else routine. `success`, `popup`, `vibration` and `offline` are not asked from the host.

Rules, enforced by one gate in `SoundService.play` (every host-initiated sound goes through it; a test checks that nothing else asks the unit to play a sound):
- a cue on the allowed list only;
- at least 60 s between two chimes of one cue (the shutter: 2 s), so a state that flaps makes at most one chime per gap;
- at most 20 chimes of one cue in 24 hours (the shutter: 500);
- the volume setting, mute, quiet hours and the night rules apply as before;
- the Settings sound test bypasses the gate on purpose (it plays every sound in turn).

Firmware-originated cues (the unit's own policy, `self.audio.set_sound_policy`): the unit plays the vibration tone when a tap finds no hub link (a person tapped it: allowed), the offline earcon after three minutes without the hub (patch 120) and the success chime when the link returns after an outage that sounded offline (patch 116). Those last two are not asked from the host and cannot be gated there; a hub install that takes the hub away for three minutes or more can sound them. A firmware change would be needed to remove them (not done).

### Quiet during a dance (owner 2026-11-14)

"Make those beeps go away": while a music session runs, and for 30 s after it, the host pushes the sound policy with `enabled` false (`SoundService._dance_silenced`, read from the music session's state every second). The unit then refuses its event sounds (plug, charged, unplug, offline, success, popup, vibration and so on) and keeps only the safety cues (a picture, the urgent setup cue). The unit's own cues that exist for routine things, found in the firmware source: the success chime on boot after activation (stock xiaozhi), the popup tone when the wake word or a tap opens listening, the offline earcon and the "I'm back" chime after an outage (patches 116 and 120), plug, unplug and charged from the power poll (patch 116), the vibration tone for a tap with no hub link. No firmware cue is tied to a dance move or a face change. The host log cannot show which cue sounded (the unit sends no event for it); the next firmware image should add a `sound_played` diagnostic event with the cue name so the log can name it.

## The voice and its licence

The phrases use the household's default voice, the Stack's Chatterbox Turbo preset (`chatterbox-turbo-voice-default`), Apache-2.0
by the Stack's pinned catalog record (`stack/docs/components.md`, `models/manifests/chatterbox-turbo-fp16.json`, revision
`b2d0a13a`). They are machine-made speech, no real person. They were rendered with the Stack's own engine script
(`mlx_tts_server.py`, started on a free local port with the models read offline; the running hub was not touched) by
`body/scripts/render_unit_phrases.py`. The check is recorded in `assets/phrases/phrases.json` (`voice.licence_checked`), in
`NOTICE` and in the user guide. The tier 1 bundle manifest (`speech/offline_clips.json`, `pocket-tts-english`, CC-BY-4.0, which
requires attribution) now has `licence_checked: true` for the same reason and carries its credit line in the manifest, `NOTICE` and
the user guide. Speech synthesis is not bit-exact between runs, so the committed files and their checksums are the record.

## In the robot's own voice

For a household build, render the sixteen tier 2 phrases on the hub with the voice bound to the robot (`robot.voice.id`). Use
`body/scripts/render_unit_phrases.py --tts http://127.0.0.1:18791 --voice-id voice-… --out /path/outside/the/repo`. The renderer
posts each phrase to the hub's `/api/tts` route with that voice id, applies the same streamed WAV normalizer as robot speech,
then writes the Ogg clips, a per-clip manifest, and `voice.sha256`. The hash changes with either the selected voice or phrase
text. The output directory must be outside the git work tree: cloned or designed voices may represent a real person, so these
household clips must stay in hub data and never enter a commit or release. If the voice is unavailable, the renderer reports
that and leaves no output. Running without `--voice-id` retains the committed default voice render path.

## Sizes (a real `recipe.sh` build of patches 001 to 099 plus 115 to 118, ESP-IDF 5.5.4)

| Image | Before the strip note's numbers | With the sounds | Limit | Free |
|---|---|---|---|---|
| App image (`stack-chan-maipai.bin`) | 3,176,864 | 3,238,000 | 5,177,344 | 1,939,344 |
| Assets image (`generated_assets.bin`) | 2,492,840 | 2,625,313 | 6,225,920 | 3,600,607 |

The seven earcons are 13,176 bytes of the app image (all seven `_binary_snd_*_ogg_start` symbols are in the linked ELF); the sixteen
phrases are 76,003 bytes of Ogg data (0.74 to 1.99 s each) in the assets image, all sixteen names found in it. The rest of the growth
is the sound module and the other builders' work since the strip note's measurement.

## What needs a unit

Everything audible. In the order to listen: (1) Settings, Lights and Sounds, Test the sounds (or the `sound_test` command), all twelve
in turn: do the seven new ones sound like one family with the old five, and are rising and falling obvious; (2) plug the charger in
by day (`plug_in`), wait until full (`charged`), unplug (`unplug`); (3) stop the hub for 15 s (`offline` at 10 s, then the success
chime and no phrase on return, since under a minute); (4) say the wake word with the hub off: a `no_host` phrase, again 10 s later a
different one; (5) switch the router off: `no_wifi`; (6) an unapproved unit: `refused`; (7) the camera: the shutter click with the pink
flash; (8) at night: none of the above except the shutter, the tone for the wake word, and the low battery tone. Also check the
unknowns: that `IsCharging()` falls when the AXP2101 finishes the charge (otherwise `charged` never plays), and that the hello failure
marks a refusal (otherwise `refused` reads as `no_host`).

## What is not done

- `goodbye` has no caller. The power key hold cuts power in hardware with no warning the firmware can use (plan section 6 asks for
  the unit check that decides); the function exists for the power key work.
- The pop tone is not re-rendered.
- The home side: see "What Home needs" below.

## What Home needs

| Key | Type, default | Label (plain words) |
|---|---|---|
| `robot.sounds.enabled` | boolean, true | "Sounds from the robot" |
| `robot.sounds.night` | boolean, false | "Sounds at night too" |

Both are device scope and read from the settings frame; a missing key keeps the default. `robot.muted` and `robot.quiet` (when sent)
silence every sound. New device command `sound_test {}`: the ack state is `{"sound_test": "started", "sounds": [...]}` or
`{"sound_test": "refused", "why": "muted"}`; the Settings, Lights and Sounds page gets a "Test the sounds" button that sends it.
