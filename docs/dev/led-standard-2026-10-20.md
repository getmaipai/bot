# Light standard for every MaiPai robot (2026-10-20, rewritten 2026-11-13)

Status: approved by the owner 2026-11-13. This note supersedes the 2026-10-20 table (20 rows, 7 colours); the history is in git. The
audit and plan behind it: `docs/dev/stackchan-lights-audit-and-plan-2026-11-13.md`.

One meaning per colour and style, on every body. A person who learns it on one robot reads any other. The ring table below is the
single source: `body/maipai_body/indicator/looks.py` carries the same rows ("the only site of a colour or a level") and a test parses
the table here and fails when a `LookKey`, a colour, a style, a period or a fixed brightness differs from it.

## Principles

1. **Dark by default.** The ring lights only when it tells a person something they need right now and may not see on the screen. The face
   shows feelings and doings (thinking, speaking, charging, boot, ready, sleep); the ring never shows expression.
2. **Light tells the truth about the senses.** Whenever sound leaves the robot for the hub, or a picture is taken that the person is
   meant to know about, a cue is lit that no setting, night level or child level can dim below its floor, and that wins over everything.
3. **No red, ever.** The palette is closed: white, green, blue, amber, cyan, magenta, pink, off; pink is a hue near 330 degrees, never red.
4. **One table, one writer.** No body, renderer or feature names a colour or a brightness. It asks `resolve()` for a look; each body only
   translates a look into its own hardware. On StackChan the light service is the only ring writer (the camera adapter, the night
   controller and the rest renderer tell it facts); a test holds that line.
5. **Five colours, one meaning each:** green = your voice is leaving the robot; pink = a picture is being taken; cyan = I need a person;
   amber = look at the screen; blue = your turn. White is not a status colour.

## The ring table

Priority, highest first; two rows never blend, the higher wins whole. A row not listed here does not exist: no sleep glow, no charging
ring (the charger's red light at the back and the screen's battery glyph show it), no thinking or speaking ring, no pink "I see
someone" glow, no alarm, held, muted, offer, connecting, updating or error rows.

| Key | Pri | Colour | Style | Period | Brightness | Shown when |
|---|---|---|---|---|---|---|
| `live` | 1 | green | steady | - | floor 0.5, ignores every setting and level | the whole time audio streams to Home, held 0.5 s after |
| `camera` | 2 | pink | flash | 0.5 s | floor 0.5, ignores every setting and level | a picture is taken that the person should know about: two quick flashes, then steady for the capture |
| `pairing` | 3 | cyan | pulse | 2 s | 0.6 | setup or pairing waits for a person |
| `attention` | 4 | amber | pulse | 10 s | 0.3 | look at the screen: Home unreachable for 10 s, a fault, or battery under 15 percent and not charging; one short pulse every 10 s; dark at night |
| `listening` | 5 | blue | steady | - | day or night level | from the wake word or tap until the turn closes |
| `dance` | 6 | magenta | steady | - | 0.5 of the level | the one decorative show; the `dancing` fact is raised while the little dance (`dance.py`) paints its own gold, lime and mint show on the ring; dark at night |
| `idle` | 7 | dark | - | - | 0 | everything else: idle, thinking, speaking, charging, boot, ready, night, sleep, screen sleep, power off |

Rules that are not rows:

- **Asleep (the rest renderer's asleep stage):** dark but for `live` and `camera`. Waking re-resolves the table; it never relights a glow.
- **Night (quiet hours or the sensor's dark room):** `listening` shows at the night level (lower still for a child, a teen, an unknown
  person or no presence information); `attention` and `dance` stay dark; the two cues keep their floors.
- **`robot.indicator.enabled` off:** dark, but never `live` or `camera`.
- **Charging read:** a failed battery read is unknown, never "not charging"; a charging or low-battery change counts after two reads
  in a row agree.

Style names are a closed set: `steady`, `breathe`, `pulse` (short on, long off), `blink`, `double`, `flash` (two quick flashes, camera
only). Periods are UNMEASURED design defaults and stay in the look table.

## The silent-capture exception

Jesse asked for continuous silent vision (2026-10-20). It is allowed under four limits: the setting is opt-in and off by default;
the picture is dropped in the same call and only a short text note is kept; it never runs in quiet hours or with a child present;
and the Settings page and the robot's own screen show plainly that ambient vision is on while it is. Visible capture never uses it.
A robot with a camera and a screen should show a small steady "ambient vision on" glyph on the screen (not the light), so the person
can always tell the mode without a flash on every capture.

## How each body shows it

| Body | Hardware | How it shows a look |
|---|---|---|
| Reachy Mini | two-colour eyes (the Eyes part) | direct: `Look(colour, brightness)`; styles by animating brightness at the Eyes driver |
| StackChan | 12-pixel RGB ring, whole-ring colour calls (`set_led_color`, `set_led_colors`), channel max 168 | every pixel the look's colour at `brightness x 168`; styles are driven by the host timer; the face carries expression, the ring carries state, they never share a job |
| Pi build and future builds | light ring or dial, chest LCD | the look goes to the ring or dial; pictures and text go through the display router (`robot/display.py`), never to a light |

## Cue sequences on StackChan

| Moment | Screen | Ring | Sound | Owner |
|---|---|---|---|---|
| Power on, joining Wi-Fi, connecting to Home | text cover, no face | dark (firmware change in a later wave: today the firmware still blinks blue) | none | firmware |
| Wi-Fi needs a person (setup) | the setup instructions | cyan pulse | none | firmware |
| Ready (hub session open) | the face appears | dark | one short soft chime (the firmware's success sound) | face and chime: firmware |
| Wake word heard or a tap opens a turn | head lifts and the face brightens (`perk`) | blue steady | the firmware's rising pop-up tone | host: ring and `perk`; tone: firmware |
| Audio streaming to the hub | listening face | green steady (the live cue outranks blue and is held 0.5 s) | none | host |
| Thinking, speaking, turn over | the face | dark | the reply | host |
| Hub unreachable for 10 s, a fault, low battery | the screen says which | amber pulse every 10 s (not at night) | none | host (firmware while its socket is down, later wave) |
| Charging | the battery glyph | dark (the red light at the back is the charger's own) | none | hardware |
| A picture is taken | the face stays | pink two flashes then steady | none | host, through the light service |
| Asleep, night, screen sleep, power off | sleeping face or screen off | dark | none | host and firmware |

## Faces as drawn on the unit (owner request 2026-10-20)

Source: the mint skin in the firmware (`mint.cpp`, patch 013) and `SetEmotion` in `stackchan_display.cc`. The firmware has no
"thinking" emotion; the thinking cue sends `neutral`. The "gaze up and to one side" option needs a look-direction frame the display
does not have, so it would be a firmware change; none is made.

| Face sent | Eyes | Mouth | Reads as | Host use |
|---|---|---|---|---|
| `neutral` | two round dots | soft smile | friendly attention | listening, thinking, speaking, settle, listen, glance, tilt, attend; moods neutral, doubt, wry |
| `happy` | two "^" arcs | wide open smile | glad | nod, perk, speak; mood happiness |
| `sad` | round dots with inner brows raised | small flat mouth | sad | mood sadness only |
| `angry` | ">" and "<" slants | teeth | cross | mood anger only |
| `surprised` | larger round dots | open oval | startled | mood fear only |
| `sleepy` | "u" arcs | small oval | drowsy | mood sleepiness, night |
| `doubtful` | left dot, right flat line with a raised brow | wavy line | confused or disgusted | not sent by any cue, primitive or mood since 2026-10-20 |
| `winking` | left dot, right "^" | smile with tongue | playful | only on an explicit wink |

The thinking cue used `doubtful` until 2026-10-20; the owner read it as confused or disgusted. The `doubt` and `wry` reply moods and the
`glance`, `tilt` and `attend` primitives now also send `neutral`, so no automatic cue draws the one-eye-flat or raised-brow shapes.
