# StackChan companion behaviors (2026-10-20)

Owner request, seven behaviors. Each is a bot verb or service first (vendor-neutral, `NotSupported` on a body that lacks it) with
a StackChan translation underneath that calls a firmware MCP tool or an avatar frame. Firmware work is a numbered patch under
`body/maipai_body/bodies/stackchan/firmware/patches/` (next free number: 020). Host work is Python under
`body/maipai_body/` with a fake-peer test. Nothing here claims hardware verification; flashing a unit is Jesse's call.

Built by the local coding lane (`local-lane dispatch`), one writer per file set; the dispatcher reads every diff and runs the
tests and `scripts/check.sh --pre`. Claude only designs, maps and reviews.

## Existing parts to reuse (do not rebuild)

- `presence/night.py` (`NightController`, `set_face_background`, volume, brightness), `presence/sleep_auto.py` (quiet hours, luma).
- `presence/attention.py` and `presence/doa.py` (gaze, point at sound), `vision/watch.py`, `vision_bridge.py`, `robot.camera.frame()`.
- `moves/` (recorded moves, `MovesService`, age allow-list), `expression/` and `bodies/stackchan/expression_map.py`, `renderer.py`.
- Firmware tools `self.robot.set_idle_motion`, `self.screen.set_face_background`, `self.screen.get_ambient_light`, `set_led_colors`.
- The avatar channel (`avatar/`, `avatar_frames.py`) already streams frames to the face.

## Items

| Id | Behavior | Host (bot) | Firmware patch | Hub |
|---|---|---|---|---|
| BOT-SC-WIFI-01 | Swipe the face to switch or edit Wi-Fi; saved networks, hotspot | `network` part: `wifi.list_saved`, `wifi.switch`, `wifi.add`, `wifi.forget`; credentials never logged | 020: NVS list of up to 8 networks, MCP tools `self.wifi.list/switch/add/forget`, swipe opens a list screen, new networks reuse the xiaozhi Wi-Fi config AP page | none (networks stay on the robot) |
| BOT-SC-ANIM-01 | Drowsy, asleep and waking routines; no frozen smile for hours | `expression/rest.py` policy and `stackchan/routines.py` renderer (built); wiring into the idle worker and quiet hours next | 021 only if a new pose is needed; first use existing faces and head poses | none |
| BOT-SC-GAZE-01 | Look at the speaker, gently, setting on/off | `attention` has gaze and DoA; add a StackChan sink limited to small yaw/pitch steps, at most one move per second, never scans; setting `robot.look_at_speaker` | none (`set_head_angles`) | setting in the hub registry |
| BOT-SC-DANCE-01 | Dance on command; auto-dance when music is heard, about 10 s then settle | `dance` service: verb `dance(name)`, music detector on the existing mic blocks (spectral flux plus beat periodicity, no audio kept); start after 3 s of music, stop 10 s later, cooldown until 10 s of silence; setting `robot.auto_dance` | 022: `self.robot.dance(name)` mapped to the firmware's built-in dances (read the pinned source for the real names first; if none, fall back to `moves/` recordings) | song id: BOT-SC-DANCE-02, a feature fingerprint (never raw audio) to a hub endpoint, after a design note |
| BOT-SC-VISION-01 | Silent ambient vision, setting on/off, plus a visible "take a picture" mode | `ambient_vision` worker: only when the funnel has been idle 60 s and no turn is active, one `camera.frame()` held in memory, hub describes it, frame dropped, only a text scene note kept; "let me take a look" bypasses the idle gate; visible mode keeps today's ring and shutter | 023: a `silent` flag on the photo tool that suppresses ring, shutter sound and screen flash; honored only when the host sets it and the setting is on | `vision.describe` exists; the scene note is a Memory record with provenance |
| BOT-SC-NIGHT-01 | Alexa-style night: whisper in, whisper out | loudness classifier on the mic block (RMS and spectral tilt); a whispered request sets the reply to whisper level for that turn and asks the hub for a quiet TTS style; ties into `NightController` | none | hub TTS accepts a `style: whisper` hint (separate hub item) |
| BOT-SC-SCREEN-01 | What goes on which screen; hub-made pictures | `display` router: `show(kind, payload)` picks the surface from the body profile (StackChan: the whole face; the dial-and-LCD robot: dial for status icons, chest LCD for pictures); kinds `photo`, `weather`, `camera_feed`, `alert`, `status` | 024 only if the face needs a new full-screen image frame; first reuse the avatar image frame photos already use | hub renders the weather card and Frigate snapshot as a still image and streams it (Frigate later) |

## Settings (registered once, hub registry)

`robot.ambient_vision` (default off), `robot.look_at_speaker` (default on), `robot.auto_dance` (default off), `robot.night_whisper`
(default on), `robot.wifi_auto_switch` (default on). Each is a plain on/off with a one-line description.

## Rules for every item

- Ambient vision keeps no frame, thumbnail or pixel log; only a text note. A test proves nothing is written to disk and the frame is dropped.
- Child and teen age floors outrank any behavior (existing `band_of` path). Auto-dance and ambient vision follow quiet-hours policy.
- Every firmware tool is additive and absent-safe: a unit on older firmware makes the verb raise `NotSupported` with a plain fix line.
- Error text says what went wrong and what to do.
- The StackChan arrival-prep session owns flashing and the unit; it edits no patches or body files (confirmed 2026-10-20).

## Order

1. BOT-SC-ANIM-01 wiring, BOT-SC-GAZE-01 (host only, no firmware).
2. BOT-SC-SCREEN-01 router, BOT-SC-DANCE-01 host half.
3. Firmware patches 020 to 024, each checked with `STACKCHAN_CHECK_ONLY=1 recipe.sh` (patch applies, Kconfig reconfigures).
4. BOT-SC-VISION-01, BOT-SC-NIGHT-01, BOT-SC-WIFI-01 host halves.
5. Hub items (whisper TTS style, fingerprint endpoint, weather and Frigate renders) filed in the `home` and `stack` backlogs.
