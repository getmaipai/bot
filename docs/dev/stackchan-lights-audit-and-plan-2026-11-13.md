# StackChan lights: audit and plan (2026-11-13)

Owner ask (2026-11-13): "standardize all the light choices it makes: charging, low battery, listening, talking, etc. We should have a
design but I don't think it's great and we probably don't follow it. Lights should be off when StackChan is off, and ideally lights are
not on all the time, only when needed. Audit and show me the plan." Status: AUDIT AND PLAN ONLY. No code, no flash, no unit test was done.
Evidence is cited as `file:line` (bot repo paths are relative to `body/maipai_body/` unless they start with `docs/` or `tests/`, which is `body/tests/`; the
firmware tree is the pinned source at `~/esp/stackchan-build/stackchan-02-run/build/StackChan/firmware/`, unpatched; the patches are in
`bodies/stackchan/firmware/patches/`). Live numbers come from the hub log `/usr/local/maipai-home/data/logs/launchd.err.log`.

## The short version (plain words)

1. We do have a standard: `docs/dev/led-standard-2026-10-20.md`. It is still marked DRAFT (line 5), it has 20 rows and 7 colours, and
   it was never reviewed. The code follows its table, but the firmware, two host side paths and the user guide do their own thing.
2. The ring is lit far more than the standard wants. Over the last three days the host asked for a lit ring most of the time the unit
   was connected: the night "sleep" glow (dim blue) and the "charging" breathe (green) together covered 97 percent of today's
   connected time. "Idle is dark" (owner ruling 2026-10-21) is true only for a few minutes a day.
3. The charging light blinks on and off about once a minute. It is not the charger: the battery read fails now and then, a firmware
   patch turns a failed read into "not charging", and the ring follows (132 "charging" changes in three days).
4. The link between the unit and the host drops every few minutes at night (12 times today, 19 yesterday). Every drop wakes the
   sleeping robot, which lights the ring again for about three minutes before it goes back to dark.
5. What the owner saw today fits the code: amber is the firmware's own "offline" ring; green on connect is the charging breathe (the
   host's blue "connecting" pulse is never written to the unit); pink is the new "I see someone" glow from bot 0.2.64, which is off by
   default so it was most likely switched on to try it; the white ring after power-off is the firmware's dim white at boot, or the base
   board keeping its last colour, and one 10 minute check on the unit decides which (section 6).
6. Nothing in the firmware or the host turns the ring off when the power button is held. Patch 050 blanks the ring only for the idle
   shutdown and the screen sleep, and its own header says the button is not covered.
7. The plan: one short table (6 lit states, 5 colours, everything else dark), the firmware boot and offline rings generated from the same
   table, three bypasses removed, a test that fails on any row outside the table, and a firmware patch that blanks the ring on the
   power key. The host part ships as a bot release; the firmware part needs a build, a flash and a release.
8. The owner answered the same day (section 8): the face should show feelings and doings, the ring only what a person needs when the
   face may not be seen; the pink "I see someone" glow goes; the ring never shows charging, because the red light at the back already
   does (it is the charger chip's own LED, switched on by the firmware at boot). Section 10 is the full table he asked for: 39
   conditions, each with its face, its ring, its sound and who drives it. Only 7 rows light the ring. Two new faces are needed
   (`listening` and `thinking`); everything else reuses the nine faces the unit has (section 9).
9. Sounds (section 14): the unit has five short tones built in (ready chime, listen pop, offline tap tone, an error tone and an unused
   low battery tone), stored inside the app image as Opus clips of 1 to 2 KB. There is room for hundreds more (1.36 MB free in the
   app slot; the nearly full 4 MB assets partition is for the models and icons, not sounds). The plan adds seven earcons in one
   timbre (rising for good, falling for bad), re-renders the five to match, and keeps every sound silent at night except first setup,
   the camera click and the shutdown.
10. Dance (section 15): the unit already has four head dances behind a tool, a music detector and a start and stop policy that nothing
    calls, and "dance" by voice is refused. The plan makes dance the one light show: three ring patterns in the firmware synced to the
    dance, started by voice, the hub or Settings command (and later music), ended by anything real, never at night, never over a privacy cue.
11. Offline (sections 16 to 18): one shared "link" screen (black, a glyph slot, a text slot) replaces today's boot cover and serves every
    not-yet-linked state (joining Wi-Fi, Wi-Fi setup, connecting to Home, waiting for approval), and the same glyph-and-text strip sits
    in the face's corner while the robot is offline but still usable, with a muted face palette. All of it is firmware, drawn from its
    own link state with the palette switch and the Wi-Fi icons it already ships; no new image assets beyond a 1 KB key glyph.
    The wake word still gets an answer with no Home: the body's five pre-rendered lines (built, never yet played on the unit) when the
    body is up, and sixteen short clips in our own synthesized voice played by the firmware when there is no host, varied, rate limited,
    quiet at night. No new on-unit commands beyond the stop list until their RAM cost is measured.
12. Decisions D1 to D3 are settled; D4 (one amber), D6 (approve the face stills), D7 (one earcon family), D8 (firmware-side light show),
    D9 (the offline looks) and D10 (both offline voice tiers) are recommended and open (section 12).

## 1. The existing standard and the rulings

| What | Where | What it says |
|---|---|---|
| The light standard | `docs/dev/led-standard-2026-10-20.md:1-45` | One meaning per colour and style on every body; no red; quiet by default; the look table in `indicator/looks.py` is the only site of a colour or a level; a 20 row state table; priority list at line 45. "Status: DRAFT, pending architect review" (line 5). |
| Idle is dark | `docs/dev/led-standard-2026-10-20.md:34`; `indicator/looks.py:78-79` | Owner ruling 2026-10-21: "no lights for idle; the ring lights only for a real state". The IDLE row has weight 0 and resolves to dark. |
| Camera is a pink flash | `docs/dev/led-standard-2026-10-20.md:25,83`; `looks.py:73` | Jesse 2026-10-20: pink, two quick flashes then steady, floor 0.5, no setting can dim it. Replaced the red ring. |
| Charging and low battery | `docs/dev/led-standard-2026-10-20.md:39-40,88`; `looks.py:91-92` | Jesse 2026-10-20: charging is a slow green breathe (4 s, 0.3) while docked; low battery an amber pulse every 20 s. |
| Night | `looks.py:36-43,166-171`; `indicator/settings.py:51-52` | Night is the household quiet hours (default 21:00 to 07:00); the night level is 0.15 and a child, teen, unknown or missing presence multiplies it by 0.4. |
| The sleep row | `looks.py:83,232-237`; `settings.py:35,53` | Idle at night shows dim blue (0.3 of the night level) unless `robot.indicator.sleep_eyes` is "off"; the default is "dim". |
| The one look table and its tests | `looks.py:1-11,71-95`; `tests/test_indicator_looks.py:44,190,197` | A row per state and no red; no colour literal outside `looks.py` in `indicator/`; no module outside the seam names a palette member. |
| Priority | `looks.py:199-240` | live, camera, alarm, then (if enabled) fault, held, muted, updating, pairing, connecting, offline, battery low, offer, charging, night sleep, dancing, then the turn funnel. |
| No new status UI | `home/docs/design/RULES.md:508-512` (S6, owner-approved 2026-10-17) | "System status reaches the person through the existing mechanisms." A new status surface needs an architect verdict and is DUPLICATE when an existing mechanism covers it (lines 540-543). The ring is an existing mechanism; this plan adds no new one. |
| The settings keys | `settings.py:37-45,103-135` (0.2.64) | `robot.indicator.enabled` ("Show what I am doing with my eyes"), `brightness` (0.6), `night_brightness` (0.15), `sleep_eyes` (off or dim), `alarm` ("Blink amber when I tip or fall"), and since 0.2.64 `sees` ("Glow pink when I see someone", off by default). They live in "Devices, this robot, Lights" (line 32). |
| The vision glow (0.2.64) | `looks.py:66-71,101-108,162,247-249` (0.2.64); `app.py:1297-1323,1858` | Three steady pink rows (faint 0.25 for "maybe", 0.55 for a person, 1.0 for a face), shown while idle when `robot.indicator.sees` is on. CHANGELOG 0.2.64 line 13: "off by default". |
| User guide | `docs/user/stackchan.md:30-37` | Blue listening, green "sound is being sent", purple thinking, white speaking, "Dim white ring: awake and waiting" (line 35), pink flashes, amber "needs attention". |

## 2. Who lights the ring today (every writer)

The ring is 12 RGB pixels on the base, driven by a PY32 IO expander over I2C (`firmware main/hal/hal_io_expander.cpp:48-55`). The host
reaches it through two MCP tools: `self.robot.set_led_color` (whole ring, upstream `hal_mcp.cpp:72-93`) and `self.robot.set_led_colors`
(per pixel, patch 012 lines 19-35). Channel values run 0 to 168 (`bodies/stackchan/profile.py` `LED_CHANNEL_MAX`).

### 2a. Host writers

| # | Writer | What it shows | Through the one table? | Evidence |
|---|---|---|---|---|
| H1 | `StackChanLightService` and `StackChanRingIndicator` | The resolved look: live, camera, connecting, offline, charging, battery low, sleep, listening, thinking, speaking, sees | Yes (the intended path) | `bodies/stackchan/light_service.py:192-231`, `ring_indicator.py:66-97`, `ring.py:18-27` (the one RGB map) |
| H2 | `LightPoller` | Feeds connecting, offline, charging, battery low once a second; battery once a minute | Yes (facts in) | `light_wiring.py:73-98,111-132` |
| H3 | The turn funnel | Feeds idle, listening, thinking, speaking | Yes | `app.py:1718` (0.2.64), `light.update(funnel=...)` |
| H4 | The vision tracker | Feeds `sees` (maybe, person, face) | Yes | `app.py:1858` (0.2.64) |
| H5 | The rest renderer (idle sleep) | Ring dark when asleep, restored on wake | Half: `set_sleeping` blanks the indicator, bypassing the table's own sleep row | `bodies/stackchan/routines.py:143-144`; `light_service.py:128-136`; `app.py:1840` (0.2.64) |
| H6 | The night controller (dark room) | Writes 12 black pixels straight to the unit when the room goes dark | No: direct `leds.many`, the service does not know | `presence/night.py:416-417`; `app.py:1629-1631` (0.2.64; main `app.py:1116-1118`) |
| H7 | The camera adapter | Two pink flashes then steady pink at brightness 1.0 (168, 42, 92), then black at the end | Half: it reads the table's colour but writes the ring itself and at a different brightness (1.0) than the service's own camera row (0.6 by day) | `bodies/stackchan/adapter.py:66-69,396-422` |
| H8 | The notification fallback | Whole ring orange (168, 36, 0) when a "show" alert cannot reach the unit, never restored | No: an RGB literal outside `ring.py`, outside the palette | `adapter.py:263-266` |
| H9 | The self-test | A 0.15 s white pulse at 0.5, inside `suspended()` only | Yes (by design) | `ring_indicator.py:30-33,89-92`; `light_service.py:111-126` |
| H10 | The write guard | Skips every ring write while no unit session is open | n/a | `light_wiring.py:159-162` |

Facts nobody feeds on StackChan: `alarm`, `held`, `muted`, `offer`, `fault`, `pairing`, `updating`, `dancing`. The only `update`
callers are H2, H3 and H4 (grep `light.update(` in `app.py`; `orientation.py` has no LED code, lines 37-43 are comments). So eight rows
of the table can never show on this body, and the setting "Blink amber when I tip or fall" (`settings.py:125`) promises a light that no
code sends.

### 2b. Firmware writers (unit firmware 0.2.61, log line "unit firmware: fw version=0.2.61")

| # | Writer | What it shows | Evidence |
|---|---|---|---|
| F1 | Ring init at boot | Black, written twice, after the PY32 answers (up to 1.2 s wait) | `hal_io_expander.cpp:16-55` |
| F2 | Boot cover (patch 033) | A blue blink (0, 17, 84), 250 ms on every 2 s, while joining Wi-Fi and opening the hub session; cyan (0, 91, 101) for Wi-Fi setup. Not a breathe. | patch 033 lines 69-94 (`BootRingTick`), 72-73, 80-88 |
| F3 | First Standby (patch 033) | All 12 pixels dim white (35, 35, 31), "the ring settles to idle white" | patch 033 header and line 64 (`HideBootCover`) |
| F4 | Upstream state colours | Removed by patch 033: listening green (0, 50, 0), standby black, speaking blue (0, 0, 50) | upstream `stackchan_display.cc:506,521,529`; patch 033 lines 118-130 |
| F5 | Offline (patch 075) | Steady amber (40, 18, 0) after 10 s without the hub socket, plus "Offline" in the speech bubble; cleared when the socket is back; host colours set meanwhile are kept in a shadow and come back | patch 075 header item 4, lines 120, 148-164 |
| F6 | Screen sleep and idle shutdown (patch 050) | Blanks the ring on entering the power-save sleep, restores it on wake, blanks before `pmic_->PowerOff()` on the idle shutdown | patch 050 lines 26, 31, 39-40, 75 |
| F7 | Power key hold | Nothing. The AXP2101 cuts power with the shortest hold time (register 0x27 = 0, `stackchan.cc:107`); no handler blanks the ring first. Patch 050's header says so. | patch 050 header line 1; `axp2101.cc:37-41` (`PowerOff` sets bit 0 of 0x10) |
| F8 | Charging and battery | No ring behaviour. Battery reads go to the screen; the host reads them through `self.battery.get_status` (patch 010). A failed I2C read returns 0, so "charging" reads false (patch 009). | `stackchan.cc:624-632,678-692`; patch 009 lines 13-18; patch 010 lines 10-20 |
| F9 | Default `Led` class | Not used: the board returns `NoLed`, whose `OnStateChanged` is empty, so the generic xiaozhi state colours never fire | `xiaozhi-esp32/main/boards/common/board.cc:65-68`; `main/led/led.h:12-15` |

Power facts: the idle shutdown is 600 s on battery and off while on USB by default (`hal.h:118-119`); the screen sleep comes first
(`stackchan.cc:366-368`). Which rail feeds the PY32 and the ring is not in any code we have; patch 050's header asserts "the ring is fed
from the base rail and keeps its last colours when the PMIC cuts the CoreS3", and the owner's white ring after power-off today agrees
with it, but it is an assertion, not a measurement.

## 3. What the ring actually did (hub log, three days)

The host logs one line per change of the resolved key (`light_service.py:222-224`). It does not log the firmware's own writes (F2, F3,
F5), the rest renderer's dark (H5) or the night controller's dark (H6), so "lit" below is what the host asked for, not what the owner saw.
Time share is the time between one line and the next, within the span of the day's lines.

| Day | Span | Changes | Host asked for a lit ring | Looks by share of the span |
|---|---|---|---|---|
| 2026-11-13 (to 09:09) | 9.1 h | 49 | 97 percent | sleep 66.8 percent (17 changes), charging 30.1 (13), idle 2.7 (6), connecting 0.3 (13) |
| 2026-11-12 | 23.5 h | 538 | 86 percent of the span, but 73 percent of it is "connecting", which is never written (H10): about 12 percent truly lit | connecting 73.4 (69 changes), idle 14.3 (76), charging 9.7 (119), sleep 1.8 (13), listening 0.3 (98), thinking 0.3 (46), speaking 0.2 (24), live 0.1 (93) |
| 2026-11-11 | 14.5 h | 30 | 0 (unit never connected) | connecting 100 |

What the numbers show:

- **Dark idle is rare.** Yesterday, with the unit in use, the host asked for dark (idle) 14 percent of the time and lit looks the rest
  of the connected time. Today, during the night, it asked for the dim blue sleep row or the green charging breathe 97 percent of the
  time. The 2026-10-21 ruling "no lights for idle" holds only for the IDLE row; the sleep and charging rows fill the gap.
- **Charging flaps once a minute.** 132 "charging" changes in three days for a unit that sat on USB (log 09:03:34 charging, 09:07:37
  idle, 09:08:37 charging, 09:09:38 idle). The poller reads the battery once a minute (`light_wiring.py:78-83`), a failed AXP2101 read
  comes back as `charging=false` (patch 009), and `battery_low = percent < 15 and not charging` flips with it (`light_wiring.py:125`).
  The green breathe therefore comes and goes for no reason a person can see.
- **The link flaps at night and wakes the robot.** `state=ws_down ... error=104` 12 times today and 19 yesterday (the unit's socket to the
  host, connection reset). Each drop logs "connecting", then on reconnect "sleep" or "charging", then "rest: awake -> drowsy", and 150 s
  later "rest: ring dark" (log 00:05:48 to 00:08:56, 00:09:28 to 00:12:03, and so on). So at night the ring glows about three minutes
  out of every four to ten.
- **The turn looks are brief and busy.** Yesterday's 98 listening, 93 live, 46 thinking and 24 speaking changes happened in about
  11 minutes of lit time in all, with 116 and 117 changes in the 16:00 and 20:00 hours. Blue, green, violet and white follow each
  other within seconds on every question.
- **Never seen in three days:** camera (0), offline (0), battery low (0), error, pairing, updating, held, muted, offer, dancing. The
  host's offline row cannot fire in practice: it means "the unit is connected but the robot host cannot reach Home", and the robot host
  runs inside the Home install on the same Mac. The amber the owner sees is the firmware's (F5).
- **One crash reboot** at 02:54:54 ("unit boot: boot reason=4 crash_resets=9"). After a reboot the firmware shows the boot blink, then
  dim white (F3) until the host's first write.

## 4. Design against reality against what the owner saw

| State | The standard says (`led-standard-2026-10-20.md`) | The code does | Owner saw today | Verdict |
|---|---|---|---|---|
| Idle, awake | dark (line 34) | dark (`looks.py:79`), but the firmware writes dim white at the first Standby after every boot (F3) and the user guide says "Dim white ring: awake and waiting" (`docs/user/stackchan.md:35`) | white ring after "off" | Contradiction in three places |
| Idle at night (quiet hours) | dim blue, 0.3 of the night level, or off by setting (line 35) | dim blue by default (`settings.py:53` "dim"); 67 percent of tonight | | Lit by default; against "off unless needed" |
| Asleep (rest renderer, 5 min quiet) | not in the table | ring dark (H5), restored on wake | | A second night rule outside the table |
| Dark room (night controller) | not in the table | 12 black pixels direct (H6) | | A third darkener, bypasses the service |
| Connecting (boot, Wi-Fi, hub) | blue slow pulse 2 s, 0.5 (line 36) | firmware: blue blink 250 ms every 2 s (F2); host: blue pulse resolved but never written (H10) | "green when connecting" | The host row is invisible; what shows on connect is the charging breathe within a minute (log 08:49:28 connecting, 08:49:42 idle, 08:50:29 charging) |
| Offline (hub unreachable) | amber, two short pulses every 10 s, 0.3 (line 37) | host: amber double (30, 14, 0 at day level), never fired; firmware: steady amber (40, 18, 0) (F5) | orange or amber | Same colour, two patterns, two different meanings (host: Home unreachable; firmware: host unreachable) |
| Fault or error | steady amber 0.7 (line 24 in the table) | row exists (`looks.py:87`), nobody feeds `fault` | "yellow when refused" (not found in code; the nearest are the error row at 0.42, which reads yellower than the 0.18 offline, and the orange fallback H8) | Amber at three brightnesses reads as three colours |
| Pairing or setup | cyan slow pulse 2 s, 0.6 (line 38) | firmware cyan blink for Wi-Fi setup (F2); host row never fed | | Half built |
| Charging | green breathe 4 s, 0.3, "dark when full" (line 39) | green breathe while `charging` is true, flapping once a minute (section 3); never "dark when full" (no full fact) | "green when connecting" | Noisy, and the screen already shows the battery |
| Battery low | amber pulse every 20 s, 0.3 (line 40) | row exists (`looks.py:92`), never seen; flips with the failed read | | Shares amber with offline and error |
| Listening | blue steady, day level (line 31) | blue (0, 20, 101) (`looks.py:80`) | | Follows the standard |
| Live (voice to Home) | green steady, at least 0.5 (line 23) | green (0, 101, 17) with a 0.5 s hold (`light_service.py:143-154`) | | Follows the standard; overlaps the charging green in hue (steady versus breathe is the only difference, line 39 admits it) |
| Thinking | magenta breathe 3 s, 0.8 (line 32) | violet (36, 0, 81) breathe (`ring.py:24`) | | Follows; one more colour for a 2 s state the face already shows |
| Speaking | white steady, day level (line 33) | white (101, 101, 91) | | Follows; white also means "updating" and the firmware's boot white (F3) |
| Camera capture | pink, two flashes then steady, floor 0.5 (line 25) | the adapter writes (168, 42, 92) itself (H7); the service's own camera row would give 0.6 by day | | Two writers, two brightnesses for one cue |
| Vision glow "sees" (0.2.64) | not in the standard | three steady pinks, off by default (`settings.py:45`) | pink | A second meaning for pink, the privacy colour |
| Held, muted, offer, dancing, alarm | rows at lines 26-30, 42 | rows exist, no StackChan caller | | Dead rows; the alarm setting label promises a light that never comes |
| Updating firmware | white fast pulse 1 s (line 41) | row exists, no caller; updates are a host side operation (firmware README) | | Dead row |
| Power off (button) | not in the standard | nothing blanks the ring (F7) | white ring stayed on | Missing state |
| Idle shutdown and screen sleep | not in the standard | firmware blanks (F6) | | Works, but outside the table |
| Unit off on USB | not in the standard | unknown which rail feeds the ring (section 2b) | white ring stayed on | Needs the check in section 6 |
| Notification fallback | not in the standard | orange (168, 36, 0), never restored (H8) | | Outside the palette, bypasses the table |
| Self-test pulse | not in the standard table | white 0.15 s (H9) | | Fine, person-driven |

Duplicates and clashes, in one list:

1. Amber means three things (offline, fault, battery low) at three brightnesses, and the firmware's offline is a fourth amber with a
   fourth pattern.
2. Pink means two things (a picture is being taken; I see someone).
3. Green means two things (your voice is leaving the robot; the battery is charging), told apart only by steady versus breathe.
4. White means three things (speaking; updating; the firmware's "awake" after boot).
5. Blue means three things (listening; connecting; night sleep).
6. Dark has four owners: the IDLE row, the rest renderer, the night controller and the firmware's screen-sleep blank.
7. Three writers bypass the service: the night controller (H6), the camera adapter (H7) and the orange fallback (H8). The firmware
   writes dim white (F3) and amber (F5) on its own.

## 5. The proposed standard: one table

Principles (the owner's, 2026-11-13): the ring is OFF by default and ON only when it tells the person something they need right now;
always off when the unit is off; minimal and calm; one meaning per colour; one table drives the firmware's boot and shutdown rings, the
host's looks, the docs and a test that fails on any row outside it.

| Pri | State | Colour | Pattern | Brightness | When it is shown | Who writes it |
|---|---|---|---|---|---|---|
| 1 | Live: your voice is leaving the robot for Home | green | steady | at least 0.5; ignores every setting and level | the whole time audio streams to Home, held 0.5 s after | host |
| 2 | Camera: a picture is being taken that you should know about | pink | two quick flashes, then steady | at least 0.5; ignores every setting and level | the whole capture | host (through the service only) |
| 3 | Needs you: setup or pairing waits for a person | cyan | slow pulse, 2 s | 0.6 | Wi-Fi setup screen (firmware), pairing waiting for an admin (host) | firmware before the host connects, host after |
| 4 | Attention: look at the screen | amber | one short pulse every 10 s | 0.3 | Home unreachable for more than 10 s, a fault, battery under 15 percent and not charging; the screen says which ("Offline", "Battery low", the fault line) | firmware while its socket is down, host otherwise; one shared timing |
| 5 | Listening: it is your turn to talk | blue | steady | day level (0.6), night level at night | from the wake word or tap until the turn closes | host |
| 6 | Updating: do not unplug me | white | fast pulse, 1 s | 0.5 | a firmware install, start to end | host (only if the install is ever device side; else drop the row) |
| 7 | Thinking and speaking | dark (owner decision D1) | | | the face and the voice carry both | |
| 8 | Charging | dark (owner decision D3); the screen's battery glyph shows it | | | optional: one 3 s green breathe when the plug goes in, then dark | host |
| 9 | Idle, awake, day or night | dark | | | | |
| 10 | Asleep (rest), dark room, screen sleep | dark | | | | host and firmware |
| 11 | Boot: joining Wi-Fi, opening the Home session | dark; the screen says "Connecting to Wi-Fi..." and "Connecting to Home..." | | | | firmware |
| 12 | Ready: the Home session opens | dark (the chime and the face say it) | | | | |
| 13 | Power off (button, idle shutdown), and off while still on USB | dark, blanked before the power cut | | | | firmware |

Five colours, each with one meaning: green = your voice is leaving; pink = a picture; cyan = I need you; amber = look at the screen;
blue = your turn. White only if updating stays. Night and child levels scale rows 5 and 6; rows 1 to 4 keep their floors.

Priority is the row order: live and camera (privacy) over everything, then needs you, attention, listening, updating. Two rows never
blend; the higher wins whole.

What stays on the screen (the face), never on the ring: charging and the battery level (the firmware's own battery glyph), "Offline" and
"Connecting" words (patch 033 and 075 already do this), the thinking face and the moving mouth, the sleeping face, the orientation pose
faces, the night face, and the "ambient vision on" glyph the 2026-10-20 standard asks for. The ring never shows expression.

The vision glow (`robot.indicator.sees`): not in the table. Pink keeps one meaning. If it is kept at all it is a developer switch under
a Developer heading, never in the user table or the user guide (owner decision D2).

States to REMOVE:

- The dim white "awake" ring: patch 033 line 64 and `docs/user/stackchan.md:35`.
- The night sleep glow (dim blue): the `SLEEP` row and the `sleep_eyes` key, or `sleep_eyes` default "off" if the key must stay.
- The charging breathe as a standing light (owner decision D3).
- Thinking violet and speaking white (owner decision D1).
- The host "connecting" blue pulse (never written) and the firmware boot blue blink (the screen text carries it).
- The firmware's own steady offline amber as a separate pattern: it becomes row 4's pulse, from the shared table.
- The three ambers (ERROR 0.7, OFFLINE 0.3 double, BATTERY_LOW 0.3 pulse): one attention row.
- The dead rows on StackChan: HELD, MUTED, OFFER, DANCING, ALARM, ALARM_DIM (keep them in the Reachy table only if Reachy still uses them;
  the standard note says which). The "Blink amber when I tip or fall" setting goes with them.
- The orange notification fallback (`adapter.py:265`).
- The night controller's direct black write (`presence/night.py:416-417`): it tells the service a fact instead.
- The camera adapter's own ring writes (`adapter.py:396-422`): it raises the cue and the service writes.

## 6. Power off: what we know and the one check that decides

Known from code: the ring is written over I2C through the PY32 on the base; the CoreS3 is cut by the AXP2101 (`PowerOff`, register
0x10 bit 0); the hold-to-off time is the shortest (register 0x27 = 0); patch 050 blanks the ring before the idle shutdown and on the
screen sleep but not on the button; the AXP2101 has a power-key and plug IRQ status register 0x49 (`docs/dev/stackchan-sensor-map.md:10`).
Not known: whether the base keeps the ring powered and holding its last colour when the CoreS3 is off on USB, and whether holding the
button on USB turns the unit off or reboots it.

Two readings of today's white ring:

- A: the base holds its last colour across the cut. Then the last colour written was white: the firmware's boot white (F3) after a
  reboot the host never followed (the host writes dark within a second of a session opening, `light_wiring.py:73-98`, so white persists
  only when no session opens).
- B: on USB the AXP2101 cut re-powers the CoreS3 at once (a reboot, not an off), the firmware runs the boot blink and then dim white (F3),
  and the screen stayed off because the screen-sleep state was restored or the host never connected.

The check (10 minutes on the unit, needs the owner's go and the other session's pause): with USB attached, hold the power button; read
the host log for a new "unit boot" line and the serial log for a reboot; note the ring. Repeat on battery. Let the unit reach the idle
shutdown on battery and note the ring. Result A means the fix is a firmware blank on the power-key long-press IRQ before the PMIC cuts,
plus no boot white. Result B means the fix is no boot white and a dark boot ring, plus the screen-sleep blank already in patch 050. Both
fixes are in the plan either way; the check only says which one the owner will notice.

## 7. Plan

| Step | What | Who | Size | Risk |
|---|---|---|---|---|
| 1 | Owner decisions D1 to D5 (section 8), then rewrite `docs/dev/led-standard-2026-10-20.md` to the section 5 table (one table, superseding the 2026-10-20 rows) and run the architect on it (it is a design note on a governed path) | this session | S, 1 h | none |
| 2 | Host table: `looks.py` rows and `resolve_key` to the new table; remove the dead rows and the sees rows (or move them behind a developer switch); one attention row fed by offline, fault and battery low; `settings.py` drops `sleep_eyes` and `alarm` (or defaults them off) and relabels; the night controller, rest renderer and camera adapter feed facts to the service instead of writing the ring; delete the orange fallback; `test_indicator_looks.py:44` becomes "the LookKey set equals the table in the standard doc" (parse the doc table, compare), and the grep test extends to `app.py`, `adapter.py` and `presence/night.py` (no `leds.many` or `set_led_color` outside `ring_indicator.py` and the self-test) | Codex brief (decided, testable), one slice per run; Sonnet subagent if Codex credits are out | M, 8 to 10 files, about 2 h | the 0.2.64 vision glow tests change; the rest renderer wiring is subtle (0.2.57 regression history, CHANGELOG line 78) |
| 3 | Charging read: a failed battery read keeps the last known values and the ring sees a change only after two reads agree; log the flip | Codex | S, 2 files, 30 min | none |
| 4 | Generate the firmware's ring constants from the table: a small script writes `ring_table.h` (the RGB for cyan, amber, the pulse timings) from `looks.py` and `ring.py`, and the firmware patches include it, so the firmware and the host cannot disagree | Codex | S, 3 files, 1 h | the patch set must still apply with `STACKCHAN_CHECK_ONLY=1 recipe.sh` |
| 5 | Firmware patch 08x: (a) patch 033: no dim white at Standby, boot ring dark, cyan pulse only for Wi-Fi setup; (b) patch 075: offline amber becomes the table's pulse (timer in the firmware, same period); (c) patch 050: blank on the AXP2101 power-key IRQ (register 0x49) before the cut, and blank when the socket to the host has been down longer than the idle shutdown | a Claude session with the ESP-IDF toolchain (`~/esp/stackchan-build`) | M, half a day plus a build | needs a build, a flash of the owner's unit and a bot release with a firmware version bump (`firmware/pins.toml:6`, `release.sh`); the flash waits for the listening session to finish with the unit |
| 6 | The unit check from section 6, then the flash | this session, with the owner's go | 10 min plus 15 min | the unit is in use; ask first |
| 7 | Docs: `docs/user/stackchan.md:30-37` table rewritten from the standard (seven rows become five), `docs/dev/stackchan-sensor-map.md` ring row, CHANGELOG, Settings labels | this session | S, 1 h | none |
| 8 | Release: bot 0.2.65 with steps 2 to 4 (works with firmware 0.2.61 as is, since the firmware changes are boot, offline and shutdown only); then the firmware release when step 5 is built and flashed | the releaser session | S | the live hub ship needs the owner's word in that turn |

Verification before "done": the table test fails when a row is added outside the doc; a run on the unit with the hub log showing a day
where the ring is lit only during turns (the "StackChan ring look" lines are the measure, section 3); the power-key check from section 6
repeated after the flash; the user guide table equals the standard table.


## 8. Owner answers (2026-11-13) and the face question

The owner answered the first five decisions the same day: (D1) "we could have the face show things vs lights, we will need to design
what that line is; you currently don't have anything for the face other than idle, petted, sleeping, tilted"; (D2) drop the pink
"I see someone" glow (remove `robot.indicator.sees` and its look keys); (D3) "there's also a red light in the back when you have it
plugged in already", so the ring needs no charging light at all; (D4) "let's plan it: I need to see a full table of faces and lights and
conditions". Sections 9 to 13 answer that: the faces the unit has, one master table of every condition with its face, ring and sound,
the new faces needed, and the revised decisions and plan.

**The red light at the back.** It is the charger chip's own LED, not ours. The AXP2101 power chip on the CoreS3 has a CHGLED pin; the
firmware enables it at boot with `WriteReg(0x69, 0b00110101)` (`stackchan.cc:102`; register 0x69 is the AXP2101 "charge LED" setting,
listed in `docs/dev/stackchan-sensor-map.md:10`). In that mode the charger drives the LED itself: on while charging, off when the
battery is full or the cable is out. No host or firmware code reads or sets it after boot. It could be switched off by clearing bit 0
of that register (a firmware change), but the owner's point stands the other way: the hardware already shows charging, so the ring
must not. The exact meaning of the mode bits (bits 1 to 5) is from the AXP2101 register map and is UNVERIFIED on the unit; the one check
is to watch the LED with the cable in, with the battery full, and with the cable out.

## 9. The faces the unit can show (inventory)

The screen draws one face at a time from the mint skin (firmware patch 013; the base set is `bodies/stackchan/face_set.json`, the
host's map is `bodies/stackchan/expression_map.py`). The firmware animates the mouth while it speaks, blinks and drifts the eyes while
idle (idle motion), and draws two decorators of its own: a heart (`main/stackchan/avatar/decorators/heart.cpp`) and a dizzy swirl
(`decorators/dizzy.cpp`). The face does not depend on the ring in any way (`renderer.py:81`).

| Face (name sent) | What it looks like | Where it is used today | Shown today (hub log, to 09:24) |
|---|---|---|---|
| `neutral` | two round dots, soft smile; the firmware adds blinks and idle eye drift | idle; listening (mouth off); thinking; speaking (mouth animated); the settle after a turn; the reply moods neutral, doubt, wry; every head primitive (`expression_map.py:55-81`); the wake blink end and the rest "awake" stage (`routines.py:148-150`); the reaction hold end (`reactions.py:127`) | 14 "rest: face neutral sent"; every turn (98 turns yesterday, not logged as faces) |
| `happy` | two "^" arcs, wide open smile | the reply mood happiness; `nod`; the host's "smile" for a pet or tap when the firmware has no heart tool (`reactions.py:154`); the firmware's own face for a stroke | 282 "heart (petted): smile" yesterday, 2 "tapped" |
| `sad` | round dots with the inner brows raised, small flat mouth | the reply mood sadness only (`expression_map.py:65`) | 0 |
| `angry` | ">" and "<" slants, teeth | the reply mood anger only (`expression_map.py:64`) | 0 |
| `surprised` | larger round dots, open oval mouth | the reply mood fear; a shake (`reactions.py:98`); upside down (`orientation.py:32`) | 1 shake yesterday |
| `sleepy` | "u" arcs, small oval | the drowsy rest stage (`routines.py:132`); face down and on its back (`orientation.py:33-34`); the reply mood sleepiness; the asleep stage on firmware older than 0.2.54 | 14 today, 272 yesterday (the rest renderer re-sends it after every wake) |
| `sleeping` (patch 073) | both eyes and the mouth shut, no "Zzz", no idle motion | the asleep rest stage with the screen dimmed to 5 (`routines.py:126-136`) | 12 today, 22 yesterday |
| `doubt` (sent as `doubtful`) | left dot, right flat line with a raised brow, wavy mouth | on a side, left or right (`orientation.py:30-31`); the firmware's own "Can't reach Home" face for 3 s on a tap while offline (patch 075 line 202) | 0 |
| `wink` (sent as `winking`) | left dot, right "^", smile with tongue | only an explicit wink; no automatic sender since 2026-10-20 (`led-standard:148`) | 0 |
| heart decorator | a small heart beside the face for 2.5 s | the firmware's own stroke reaction; the host asks for it through `self.screen.show_symbol` when the firmware has the tool (`app.py:1939-1941`, `reactions.py:146-152`) | not logged as a face |
| dizzy decorator | a swirl over the eyes | the firmware's own shake reaction | not logged |
| night palette (patch 017) | the same faces in dimmer colours | the night controller's dark-room night (`presence/night.py`) | 7 night starts today |
| no face: text cover | "Connecting to Wi-Fi...", "Connecting to Home...", the Wi-Fi setup instructions, "Offline", "Can't reach Home" in the bubble | boot (patch 033), offline (patch 075) | at every boot |

What the owner listed (idle, petted, sleeping, tilted) is what shows on its own. The reply mood faces exist but show only when the hub's
reply carries an emotion, and the firmware has no thinking, listening or "I heard you" face: thinking sends `neutral` with the head
attending, listening sends `neutral` with the mouth off, "I heard you" is the `perk` head lift (`led-standard:122-124,138-139`).

## 10. The master table: every condition, its face, its ring, its sound

The rule for the split: **the face says what the robot is feeling or doing; the ring is only for things that need the person when the
face may not be seen** (from across the room, while it is asleep, while it is offline or still booting and has no face). Every row with a
lit ring says which of those it is. Night and child levels dim the ring rows that are not privacy cues.

Columns: the condition; what triggers it; the proposed FACE (an existing face name, or NEW); the proposed RING; sound or speech; who
drives it; how it is today (face / ring); priority (ring rows only, highest wins whole).

| # | Condition | Trigger | FACE (proposed) | RING (proposed) | SOUND or speech (proposed) | Driver | Today (face / ring / sound) | Pri |
|---|---|---|---|---|---|---|---|---|
| 1 | Boot, joining Wi-Fi | power on | the shared link screen (section 18): black, the glyph slot cycling the Wi-Fi bars, the text slot "Connecting to Wi-Fi..." | off | nothing | firmware | text / blue blink / nothing | |
| 2 | Wi-Fi setup needed | no saved network | the shared link screen: the Wi-Fi glyph with a slash, the setup instructions in the text slot | cyan slow pulse 2 s, 0.6 (needs a person, no voice yet) | NEW earcon `needs_you` (two notes rising), once on entry, at night too (the unit cannot work without it); the wake word gets the local clip set `no_wifi` ("I can't find the Wi-Fi", section 17) | firmware | text / cyan blink / nothing | 3 |
| 3 | Connecting to Home | Wi-Fi joined, session opening (boot), or a reconnect after the face has shown | boot: the shared link screen, the glyph cycling, "Connecting to Home..."; reconnect: the face stays, normal palette, the same glyph cycling in the face's corner strip (sections 16 and 18) | off | nothing (it happens constantly: 19 reconnects yesterday); the wake word gets the local clip set `connecting` ("Still connecting, one moment", section 17) | firmware | text / blue blink / nothing | |
| 4 | Pairing needed or refused | Home refuses the device or waits for an admin | the shared link screen: the link glyph with a key, "Waiting for Home to approve me" (the robot can do nothing useful until an admin acts, so the full screen is right; section 18) | cyan slow pulse 2 s, 0.6 (needs an admin at the app) | NEW earcon `needs_you`, once, day only; the wake word gets the local clip set `refused` ("I need to be approved again", section 17) | firmware (from the link state) | nothing / boot blink runs on / nothing | 3 |
| 5 | Ready, connected to Home | the session opens (first time, after an update, or back online after an outage) | `neutral` appears, normal palette, glyph gone | off | the existing `success` chime (rising, 1.0 s), day only except the first boot | firmware (face, chime), host (ring) | neutral / dim white then dark / chime | |
| 6 | Idle, awake | quiet | `neutral`, blinks, idle eye drift (exists) | off | nothing | firmware | neutral / dark or charging breathe / nothing | |
| 7 | Drowsy | 2 min quiet (1 at night) | `sleepy` (exists) | off | nothing | host | sleepy / unchanged / nothing | |
| 8 | Asleep | 5 min quiet (2.5 at night) | `sleeping`, screen level 5 (exists) | off | nothing | host | sleeping / dark / nothing | |
| 9 | Night (quiet hours or a dark room) | household hours, or the sensor and the camera say dark | the night palette (exists) | off (the sleep glow goes) | nothing; spoken lines and non-safety earcons are skipped | host | night palette / dim blue glow / nothing | |
| 10 | Waking up | a touch, a person, a turn, a shake | the wake blink: `sleeping` then `neutral` (exists) | off | nothing | host | same / glow returns / nothing | |
| 11 | Wake word heard, or a tap opens a turn | the firmware wake word, a tap | NEW `listening` (eyes a little wider, mouth closed, head lifts); until then `neutral` plus `perk` | blue steady, day level (your turn, seen across the room) | the existing `popup` tone (rising, 0.5 s), re-rendered in the family timbre | host (face, ring), firmware (tone) | neutral plus perk / blue / popup | 5 |
| 12 | Hearing you (voice streaming to Home) | the turn is open and audio flows | `listening` stays | green steady, at least 0.5 (privacy) | nothing (constant) | host | neutral / green / nothing | 1 |
| 13 | Thinking | the hub works on the reply | NEW `thinking` (eyes up and to one side, small mouth, head attends); until then `neutral` plus `attend` | off | nothing | host | neutral / violet breathe / nothing | |
| 14 | Speaking, by emotion | the reply plays | the reply mood face: `neutral`, `happy`, `sad`, `angry`, `surprised`, `sleepy` (exist) with the mouth animation | off | the reply (host speech through the hub's voice, normalized by the spec normalizer) | host (mood, speech), firmware (mouth) | mood face / white / the reply | |
| 15 | Turn over | the reply ends, no follow-up | `neutral` (`settle`) | off | nothing | host | neutral / dark / nothing | |
| 16 | A head command | "turn to me", "look left" | the face stays | off | the spoken acknowledgement (exists) | host | same / dark / line | |
| 17 | Looking around for a face | a person hint, movement, a changed room | `neutral`, head sweeps (exists) | off | nothing | host | neutral / dark (pink if `sees` on) / nothing | |
| 18 | Face found or a person followed | the detector sees someone | no change; the head follows (exists) | off (the `sees` rows go) | nothing | host | same / pink glow if on / nothing | |
| 19 | Camera picture for Home or a person | "what do you see", enrolment, a consented capture | the face stays | pink two quick flashes then steady, at least 0.5 (privacy) | NEW earcon `shutter` (a short click), at night too (privacy is safety); played by the firmware when the host asks | host (asks), firmware (plays) | same / pink flashes / nothing | 2 |
| 20 | Local looking (the robot's own stream) | camera watch on | nothing (silent-capture rule; Settings says watching is on) | off | nothing | | same / dark / nothing | |
| 21 | Petted or stroked | the head strip | the firmware `happy` plus heart; host restores `neutral` (exists) | off | nothing; kind words get the heart and a line (exists) | firmware, host | same / dark / nothing | |
| 22 | Tapped | a quick tap | `happy` for a moment (exists) | off | nothing | host | same / dark / nothing | |
| 23 | Shaken | the motion sensor | `surprised` plus the firmware dizzy swirl (exists) | off | one short spoken line, not at night (exists) | host, firmware | same / dark / line | |
| 24 | Tilted on a side | the gravity axis | `doubt` (exists) | off (the alarm row goes) | one spoken line per change, at most one per 2 min, not at night (exists) | host | same / dark / line | |
| 25 | Upside down | the gravity axis | `surprised` (exists) | off | spoken line (exists) | host | same / dark / line | |
| 26 | Face down or on its back | the gravity axis | `sleepy` (exists) | off | spoken line (exists) | host | same / dark / line | |
| 27 | Picked up or carried | not sensed on StackChan; reads as a shake or a tilt | as rows 23 to 26 | off (the held row goes) | as rows 23 to 26 | | | |
| 28 | Put down, upright again | the axis back to +y | `neutral`; sensors ignored 30 s (exists) | off | nothing | host | same / dark / nothing | |
| 29 | Low battery (under 15 percent, not charging) | the battery read crosses 15 | `sleepy` as "tired", refreshed while idle; the screen glyph | amber one short pulse every 10 s, 0.3 (the person may be away) | the existing `low_battery` earcon (falling, 1.0 s, shipped but unused today) once per crossing, then the spoken line "My battery is low. Please plug me in." once; at night the earcon only | host (line), firmware (earcon on its own read) | nothing / amber row never fired / nothing | 4 |
| 30 | Charging starts, cable in | the charger (AXP2101 VBUS) | nothing on the face; the screen battery glyph and the red charge LED at the back (hardware) | off | NEW earcon `plug_in` (two notes rising), day only | firmware (its VBUS event), hardware (LED) | nothing / green breathe, flapping / nothing | |
| 31 | Fully charged | the charger stops | nothing; the red LED goes off | off | NEW earcon `charged` (three notes rising), once, day only | firmware, hardware | nothing / breathe until the read flips / nothing | |
| 32 | Unplugged | VBUS goes | nothing; the screen glyph | off | NEW earcon `unplug` (one note falling), day only | firmware | nothing / nothing / nothing | |
| 33 | Home unreachable (offline), standing | the socket to the host down 10 s | the face stays (the robot is still usable): the muted palette, eyes a little lowered, blinks and drift on, and the same link strip as the shared screen (the link glyph with a slash plus "Offline") in the face's corner instead of the speech bubble; local reactions keep working (sections 16 and 18) | amber one short pulse every 10 s, 0.3 (the person may be away) | NEW earcon `offline` (two notes falling), once when it goes down, day only | firmware (the host cannot write) | normal face plus "Offline" / steady amber / nothing | 4 |
| 34 | Offline, a tap or the wake word | a person tries while down | `doubt` and "Can't reach Home" for 3 s (exists), then back to row 33 | as row 33 | tier 1 (body up, Home down): the body's pre-rendered line ("I can't reach home right now", five variants, exists but never played on the unit, section 17); tier 2 (no host): NEW local clip set `no_host` played by the firmware ("I can't reach my home base right now"), varied, rate limited, quiet hours respected; the `vibration` tone stays for a tap | body (tier 1), firmware (tier 2) | doubt plus text / amber / tone | 4 |
| 35 | Back online | the socket returns | as row 5: normal palette, glyph gone, bubble cleared | off | as row 5: the `success` chime, day only; the local clip `back` ("I'm back") only if the outage lasted over a minute and it is day | firmware | bubble cleared / amber cleared / nothing | |
| 36 | Error or fault | the host's fault fact | `sad` as "sorry", the spoken error line (`error_line.py`, exists) | amber one short pulse every 10 s, 0.3 | the existing `exclamation` earcon (falling, 0.9 s) then the error line; at night the earcon only | host | nothing / error row never fed / nothing | 4 |
| 37 | Updating firmware | an install (host side today) | the firmware's own update screen, if ever device side | white fast pulse 1 s, 0.5, only if device side; else the row goes | nothing during; after the reboot row 5's chime and the host line "I'm updated to version 0.2.65" (the normalizer reads the number) | host (line) | never | 6 |
| 38 | Screen sleep (firmware power save) | 5 min idle on battery | screen off | off, blanked (patch 050, exists) | nothing | firmware | screen off / blanked / nothing | |
| 39 | Power button, shutting down | the button held | `sleeping` for the last moment (reuse) | off, blanked before the cut (NEW: the power-key IRQ, section 6) | NEW earcon `goodbye` (three notes falling), at night too (a person is holding it) | firmware | nothing / keeps its last colour / nothing | |
| 40 | Idle shutdown on battery | 10 min idle | screen off | off, blanked (patch 050, exists) | nothing (nobody is there) | firmware | screen off / blanked / nothing | |
| 41 | Off, still on USB | the unit off, cable in | screen off | off, held dark (section 6 decides how) | nothing | firmware or hardware | screen off / white stayed on / nothing | |
| 42 | Self-test (Settings, Lights and Sounds) | the admin runs it | the face stays | the test's own colours and the white pulse (exists) | each earcon in turn (NEW: the sound self-test) | host | same / test / nothing | |
| 43 | DANCE, light show (section 15) | voice "dance", the Settings button or hub command, or music (if the auto setting is on) | the firmware dance faces (Happy squint and open mouth, Robot, Panic wide eyes, LookAround) with `happy` and `wink` between moves | the one decorative ring: rainbow sweep, beat pulse or sparkle at 0.5, colours outside the status meanings, synced to the dance; privacy cues (rows 12 and 19) still win at once | the host line "Let's dance" at the start (optional, day only); no music is played by the unit | host (starts, picks the pattern), firmware (runs the moves and the show) | four head dances exist, no ring, no faces beyond the keyframes, "dance" is refused by voice | |
| 44 | Dance ends | the sequence ends, or at once on a touch, a wake word or turn, a shake or tilt, a picture, low battery, offline | `neutral` | off, back to the normal rules | nothing | host, firmware | | |

Ring rows and why each one passes the rule: rows 12 and 19 are privacy cues the whole room must be able to see; rows 2 and 4 need a
person while the unit has no face or voice; rows 29, 33, 34 and 36 need a person who may be away or asleep, with the screen saying which;
row 11 needs the person now ("I heard you, your turn") and is seen from across the room where the face is not. Row 37 only if a device
side install ever exists. Row 43 is the one decorative exception, asked for on purpose and ended by anything real. Everything else is a
feeling or a doing: the face.

Five ring colours, one meaning each: green = your voice is leaving the robot; pink = a picture; cyan = I need a person; amber = look at
the screen; blue = your turn. White only if row 34 stays.

## 11. New faces needed, and what is reused

New (describe only; the owner approves a preview still before any skin change, per the 2026-11-10 rule):

1. `listening`: the eyes a little wider and rounder than neutral, mouth closed, drawn so "I heard you" reads at a glance; it replaces
   the blue ring's job up close and keeps it at a distance (row 11 and 12).
2. `thinking`: the eyes up and to one side, a small closed mouth, no brow; it replaces the violet breathe (row 13). The 2026-10-20 note
   already says this needs a look-direction frame the skin does not have (`led-standard:140-141`).
3. The OFFLINE family (section 16, firmware-driven): a `muted` face palette (the normal face in grey-blue, eyes a little lowered) and
   two small corner glyphs: the link glyph (cloud with a slash; the shipped `icon_wifi_slash` asset can stand in) and a key beside it for
   "waiting for approval". The connecting animation reuses the shipped `icon_wifi_low`, `medium`, `high` icons cycled. Text: "Waiting for
   Home to approve me".
4. Dance faces (section 15): none new; the firmware's four keyframe dances already shape the eyes and mouth, and `happy` and `wink` fill
   the gaps.

Reused: `sleepy` as "tired" (row 29), `sad` as "sorry" (row 33), `sleeping` for the last moment before the power cut (row 36),
`doubt` for offline taps and sides (rows 24, 32), `surprised` for shakes and upside down (rows 23, 25), `happy` plus the firmware heart
for pets and taps (rows 21, 22), `neutral` plus the head for everything else. Optional later, not needed for the standard: a `curious`
face whose eyes lead the head during the look around (row 17).


## 12. Revised decisions (after the owner's answers)

- **D1 (decided, with the face work):** the ring is dark for thinking and speaking; the face carries them. Two new faces (`listening`,
  `thinking`) go into the mint skin and the host map; until they exist, `neutral` plus the head moves stand in. The split rule in
  section 10 is the line the owner asked to design.
- **D2 (decided):** the `sees` glow goes: `robot.indicator.sees`, the three `SEES_*` look keys, `SEES_ROWS`, the `on_sees` wiring and
  their tests are removed; the vision tracker keeps working without a light.
- **D3 (decided):** no charging light on the ring, ever; the hardware red LED and the screen glyph show it. The CHARGING row goes. Low
  battery stays as the amber attention pulse with the earcon, the spoken line and the tired face.
- **D4 (to confirm, recommended):** one amber "look at the screen" row for offline, fault and low battery, one short pulse every 10 s at
  0.3, with the screen saying which. The master table assumes it.
- **D5 (unchanged):** host first (bot 0.2.65), then one firmware release that carries the ring patch (boot dark, offline pulse, power-key
  blank), the two new faces, the offline face family, the earcons, the local clips and the light show; the 10 minute power check and the
  flash wait for the listening session to release the unit.
- **D6 (new):** the owner approves preview stills of the two new faces and the offline face family before they go into the skin.
- **D7 (new, sounds, recommended):** one earcon family in one timbre (section 14), rising for good and falling for bad, all eleven
  rendered by one script, the five shipped ones re-rendered to match; silent at night except the safety three (`needs_you` at first
  setup, `shutter`, `goodbye`); every earcon follows the volume setting. Alternative: keep the five shipped sounds as they are and add
  only the new six.
- **D8 (new, dance, recommended):** the light show runs in the firmware (one `self.robot.light_show` tool with three patterns, synced to
  the dance modifier), the host starts and ends it; triggers are the voice word and the hub or Settings command (no head taps); auto
  dance to music stays off by default behind a setting; no show at night (head and face only). Alternative: the host drives the pixels
  over the socket (20 writes a second, the path that timed out in 0.2.40).
- **D9 (new, offline look, recommended):** the muted palette plus a corner link glyph for offline, the glyph plus a key for "waiting for
  approval", the glyph cycling for connecting; all drawn by the firmware from its own link state; the owner approves one still of each.
- **D10 (new, offline voice, recommended):** both tiers (section 17): the body's existing five-line bundle is installed and verified on
  the hub (tier 1, zero firmware work), and the firmware gets a local clip set of about 16 phrases in our own synthesized voice, rendered
  at release time by the Stack's TTS and embedded in the app image, with a cycle, a rate limit and quiet hours. No new on-unit commands
  beyond the stop list (section 17 says why).

## 13. Plan, revised

| Step | What | Who | Size | Risk |
|---|---|---|---|---|
| 1 | Rewrite `docs/dev/led-standard-2026-10-20.md` into the section 10 master table (faces, ring, sound, driver), superseding the 2026-10-20 rows; architect verdict on the note | this session | S, 1 h | none |
| 2 | Host ring table: `looks.py` to the ring rows (LIVE, CAMERA, PAIRING, ATTENTION, LISTENING, DANCE as a mode flag, UPDATING only if device side); remove SEES_*, CHARGING, SLEEP, ERROR, OFFLINE, BATTERY_LOW (merged into ATTENTION), THINKING, SPEAKING, HELD, MUTED, OFFER, DANCING, ALARM, ALARM_DIM, CONNECTING; `resolve_key` to the section 10 priority; `settings.py` drops `sees`, `sleep_eyes`, `alarm`; the night controller, the rest renderer and the camera adapter feed facts instead of writing the ring; the orange fallback goes; the table test compares the `LookKey` set with the doc's table; the grep test covers `app.py`, `adapter.py`, `presence/night.py` | Codex brief, one slice per run | M, 10 to 12 files, about 3 h | the rest renderer wiring (0.2.57 history); the 0.2.64 vision tests |
| 3 | Battery read: a failed read keeps the last values; a change counts after two reads agree; the poller feeds `battery_low` only (no `charging` fact for the light; the power rule still gets it) | Codex | S, 2 files, 30 min | none |
| 4 | Host faces and lines: `expression_map.py` gets `listening` and `thinking` behind a firmware-version check (as `sleeping` is), the low battery "tired" refresh and the fault "sorry" face; `face_set.json` grows by two; the low battery and "updated" spoken lines through the normalizer; the tier 1 offline bundle installed and verified on the hub (it has never played, section 17) | Codex | S, 5 files, 1.5 h | the map's "every primitive accounted for" check |
| 5 | Sounds: a render script makes the eleven earcons from one synth definition (section 14) and the sixteen local clips from the Stack TTS (section 17) into Opus Ogg; the firmware patch embeds them beside the shipped five and adds `self.audio.play_sound(name)`; the sound self-test row in Settings | Codex (script), the firmware session (patch) | M, 1 day | the voice licence line in the manifest (section 17); the app image grows about 120 KB of 1.36 MB free |
| 6 | Generated ring header: a script writes the firmware's ring constants (cyan, amber, the pulse period and width, the three show patterns) from `looks.py` and `ring.py`; the firmware patches include it | Codex | S, 3 files, 1 h | the patch set must still apply (`STACKCHAN_CHECK_ONLY=1 recipe.sh`) |
| 7 | Firmware patch 08x: patch 033 becomes the shared link screen (section 18: one cover, one glyph slot, one text slot, used for Wi-Fi joining, Wi-Fi setup, connecting to Home and waiting for approval; boot ring dark, no Standby white, cyan only for Wi-Fi setup and approval); patch 075 (offline amber becomes the table's pulse; the muted palette and the same link strip in the face's corner for offline and reconnecting, from the link state; the local clip reply to the wake word with the cycle and rate limit); patch 050 (blank on the AXP2101 power-key IRQ before the cut, the `goodbye` earcon; VBUS in and out earcons; the `charged` earcon); patch 013 (the `listening` and `thinking` emotions and the `muted` palette in the mint skin, after the owner approves the stills); patch 020 (the `light_show` tool and the dance faces between moves) | a Claude session with the ESP-IDF toolchain | L, two days plus a build | needs a build, a flash of the owner's unit and a bot release with a firmware version bump (`firmware/pins.toml:6`); the flash waits for the listening session |
| 8 | Dance on the host: route the voice word "dance" (today refused by `head_commands.py:127`) to `companion.dance` plus the show; the Settings button; the auto-dance setting wiring `presence/auto_dance.py` and `speech/music.py` (both unwired today); every end condition in section 15 | Codex | M, 6 files, 3 h | the 20 Hz pixel path is not used (the show is firmware side) |
| 9 | The unit checks from section 6 (power key on USB and on battery, idle shutdown) and the red LED check from section 8, then the flash | this session with the owner's go | 20 min plus 15 min | the unit is in use; ask first |
| 10 | Docs: `docs/user/stackchan.md:30-37` becomes the ring rows, a faces table and a sounds table; `docs/dev/stackchan-sensor-map.md` ring, charge LED and sounds rows; CHANGELOG; Settings labels | this session | S, 1.5 h | none |
| 11 | Release: bot 0.2.65 with steps 2 to 4 and 8 (works with firmware 0.2.61: the firmware changes are boot, offline, shutdown, sounds, faces and the show); the firmware release after steps 5 to 7 and 9 | the releaser session | S | the live hub ship needs the owner's word in that turn |

Verification before "done": the table test fails on any `LookKey` outside the doc; a day of the hub log where "StackChan ring look"
shows only listening, live and camera during use and nothing else; the power-key check repeated after the flash; the new faces and the
offline looks opened on the unit and judged against the approved stills; each earcon and each local clip heard on the unit, by day and
in quiet hours; the user guide tables equal the standard.

## 14. Sounds: the earcons and the spoken lines

Rules (owner, 2026-11-13): every sound follows the volume setting (`bodies/stackchan/volume.py` drives the firmware's speaker volume);
silent in quiet hours and the sensor night except for safety (first setup, a picture, a shutdown in hand); no sound for things that
happen constantly (reconnects, hearing, thinking, looks); one earcon family in one timbre, rising for good news and falling for bad, so
they sound like a set; a spoken line only where a tone cannot carry the meaning.

How the firmware stores and plays sounds today: the five shipped sounds are Ogg Opus files of 0.5 to 1.0 s and 1.1 to 2.3 KB each
(`xiaozhi-esp32/main/assets/common/*.ogg`; durations read from the Ogg granule position). They are embedded in the application image,
not the 4 MB assets partition (`main/CMakeLists.txt:865,894` `EMBED_FILES`; `assets/lang_config.h:72-82` exposes them as string views),
and played by `AudioService::PlaySound` through the Opus decoder (`audio_service.h:17,132`). The app image is 3,812,384 bytes of a
5,177,344 byte OTA slot (`partitions.csv`, `build/maipai-stackchan.bin`): 1,364,960 bytes free. The assets partition holds
3,794,083 of 4,194,304 bytes (`build/generated_assets.bin`): 400,221 bytes free, and it is for the wake and stop-word models, the fonts
and the icons, not sounds. Budget: at about 2 KB per second of Opus, an earcon is 1 to 2.5 KB and a 3 s spoken clip about 6 KB; the
eleven earcons plus sixteen clips (section 17) are about 120 KB, under a tenth of the free app slot. Several hundred would fit.

Existing sounds and who plays them:

| Sound | Where | Played today | In the new table |
|---|---|---|---|
| `success.ogg` (rising, 1.0 s) | embedded, `application.cc:319` | once at ready | row 5 "connected", row 35 "back online", row 37 after an update |
| `popup.ogg` (rising, 0.5 s) | embedded, `application.cc:808,906` | on the wake word and a tap that opens a turn | row 11 |
| `vibration.ogg` (0.8 s) | embedded, patch 075 line 204 | the offline tap tone | row 34 |
| `exclamation.ogg` (0.9 s) | embedded, `application.cc:150,189,385,420` (upstream alerts) | upstream errors only | row 36 error |
| `low_battery.ogg` (1.0 s) | embedded, never referenced in our build | never | row 29 |

New earcons (firmware assets, played by the firmware on its own events; the host asks for `shutter` and the dance start through a NEW
MCP tool `self.audio.play_sound(name)`, there is no such tool today, `hal_mcp.cpp` has none):

| Name | Shape | Row | Night |
|---|---|---|---|
| `needs_you` | two notes rising, repeated once a minute while waiting at first setup only | 2, 4 | yes at first setup, no for approval |
| `shutter` | one short click, non-tonal, same decay as the family | 19 | yes (privacy) |
| `plug_in` | two notes rising | 30 | no |
| `charged` | three notes rising | 31 | no |
| `unplug` | one note falling | 32 | no |
| `offline` | two notes falling, once when the link has been down 10 s | 33 | no |
| `goodbye` | three notes falling, before the power cut | 39 | yes (a person is holding it) |

Plus the five shipped ones re-rendered in the same timbre so the twelve sound like one set (D7). Spoken lines (host speech through the
hub's voice, the spec normalizer reads numbers and abbreviations, `speech/normalize.py`): "My battery is low. Please plug me in." (row
29, once per crossing, day only); the error line (row 36, exists); "I'm updated to version 0.2.65" (row 37, after the reconnect); "Let's
dance" (row 43, optional). Offline lines are local clips, section 17.

## 15. DANCE, the light show mode

What exists today: four keyframe dances in the firmware (`main/stackchan/modifiers/dance.h`: Happy sways with squinting eyes and an open
mouth over about 4 s, Robot, Panic, LookAround), exposed as `self.robot.dance(name)` and `self.robot.stop_dance` by patch 020 (lines
29-56) and wrapped by `companion.py:86-96` (`DANCES`). A pure music detector (`speech/music.py`, beat and tonality score over a 4 s
window) and a start and stop policy (`presence/auto_dance.py`: start after 3 s of music, dance 10 s, re-arm after 10 s of quiet) are
written and tested but wired to nothing (no caller in `app.py`). The voice word "dance" is in the list of movement asks the head command
parser refuses (`head_commands.py:29,127`). The `DANCING` ring row (white steady 0.35) has no caller. There is no light show and the unit
plays no music.

The mode: the one place the ring is lit for show and the face changes on purpose. While it runs, the status rules are suspended except
privacy: if audio starts streaming to Home or a picture is taken, the live green or the pink flash wins at once and the show resumes
after.

| Part | Proposal |
|---|---|
| Faces | the dance's own keyframe faces (Happy squint and open mouth, Panic wide eyes, Robot, LookAround), `happy` and `wink` between moves; no new face |
| Ring patterns (firmware, D8) | `rainbow`: the hue walks around the 12 pixels, one turn every 2 s; `beat`: all pixels pulse on the beat, the colour stepping through the hue each bar, at the detected tempo (`speech/music.py`) or 120 BPM when asked by voice; `sparkle`: random pixels flicker in two colours. Brightness 0.5 by day. The colours are deliberately outside the five status meanings: the ring is in a show, not telling a state |
| Sync | the firmware runs the dance modifier and the show from the same start tick; the host passes the pattern, the length in ms and the tempo |
| Who starts it | voice "dance" or "dance for me" (routed to `companion.dance` instead of the refusal); a Dance button on the robot's Settings page with the four names; music, only if the auto-dance setting is on (off by default) |
| How long | one sequence (about 4 to 6 s) for a button; up to 30 s for a voice ask ("dance longer" repeats); 10 s for auto dance |
| How it ends | at the end of the sequence, or at once on a touch, the wake word or a real turn, a shake or a tilt, a picture, low battery, the link going down; then the ring goes back to the normal rules (dark unless a status row applies) and the face to `neutral` |
| Night | never in quiet hours or the sensor night: a dance asked for at night runs as head and face only, no show, no line |
| Never | during a turn, while listening, while the camera cue is up, while asleep (a dance wakes it first) |
| Sound | the host line "Let's dance" at the start by day; no music from the unit (the no-music-scraping rule stands) |

## 16. The OFFLINE face family (owner, 2026-11-13)

Today (row 33) the face stays normal while the hub link is down; the only signs are the "Offline" bubble, a doubt face for 3 s on a
tap (patch 075 lines 90-104, 197-215) and the firmware's steady amber. The owner asked for a standing look. The host cannot send faces
while the link is down, so all of this is firmware, driven from the link state patch 075 already tracks (`offline_indicator(on)`).

| State | Face | Glyph | Text | Cost |
|---|---|---|---|---|
| Offline (link down 10 s) | the normal face in a NEW `muted` palette (grey-blue, eyes a little lowered), blinks and idle drift on, calm; local reactions keep working (the firmware heart on a pet, the tap feedback) | a small "no link" glyph (cloud with a slash) in the top corner; the shipped `icon_wifi_slash.bin` (1,212 bytes, kept by `recipe.sh:324`) can stand in until a cloud glyph is drawn | "Offline" bubble (exists) | cheap: the palette switch is patch 017's runtime `avatar->setPalette(name, night)` (lines 59-71), already used for the night face; a corner glyph is one `lv_img` on the face layer from the same asset path the status icons use |
| Waiting for approval, refused | the `muted` palette | the link glyph plus a NEW key glyph beside it (about 1 KB as a `.bin`, like `icon_bell`) | "Waiting for Home to approve me" | the glyph asset plus the refused state from the hello reply (patch 018 hands the token off; the refusal is already logged by the firmware) |
| Connecting (reconnect after the face has shown) | the normal palette | the link glyph animated: the shipped `icon_wifi_low`, `medium`, `high` icons cycled every 300 ms, zero new assets | "Connecting to Home..." in the bubble only if it lasts over 10 s (reconnects are constant) | cheap |
| Boot (no face yet) | the cover text (patch 033) | the same cycling glyph on the cover | "Connecting to Wi-Fi...", "Connecting to Home..." (exist) | cheap |
| Back online | the saved palette restored, the glyph hidden, the bubble cleared (patch 075 clears the bubble today) | | | cheap |

The host does nothing for these while down and must not fight them when the link returns: the firmware restores the saved palette
itself, as patch 075 clears the bubble. The host's own night palette call (`presence/night.py`) still works when the link is up.

## 17. Local offline voice: answering the wake word with no Home

The wake word runs on the unit (WakeNet in the firmware), so the unit can answer even when nothing else works. Two tiers:

**Tier 1, the body is up and Home is down.** Already designed and partly built: `turn.py:1311-1325` plays a pre-rendered line from the
offline clip bundle when a turn fails with `TurnLinkLost`, `TurnAuthFailed` or `TtsAuthFailed` (`turn.py:1215-1216`, also `:988` and
`:1375`). The bundle (`speech/offline_clips.json`, rendered by `scripts/render_offline_clips.py` with `pocket-tts-english`, CC-BY-4.0,
`licence_checked: false`) has five unreachable lines ("Sorry, I can't connect to the home hub right now", "I can't reach home right
now", "I'm having trouble connecting to home", "I can't get through to home just now", "I'm not able to connect to home right now"),
six reconnect lines ("I'm back in touch with home" and five more), the freefall, carry and thermal lines and the pairing-code characters.
`OfflineSpeaker.say_phrase` picks a variant and never repeats the last one (`offline_clips.py:230-255`); the loop breaker rate-limits it.
It has never played on the unit: the hub log has no "offline line" or "clip bundle" line in three days, and the body on the hub runs
inside the Home install, so Home being down usually means the body is down too. Work: install and verify the bundle on the hub (plan
step 4), and set the licence line (the owner's rule: our own synthesized voice only; `pocket-tts-english` is a model, not a person, and
its CC-BY credit line is in the manifest).

**Tier 2, no host at all** (the body restarting, Wi-Fi down, the refused state, a reconnect in progress). The firmware plays a local clip
when the wake word fires while its socket is down. The hook exists: patch 075 answers a tap or the wake word with the `vibration` tone, a
doubt face and "Can't reach Home" within 400 ms (patch 075 header item 2, lines 197-215); the clip is played the same way the chime is
(`PlaySound` on an embedded Ogg Opus string view, section 14). The set, chosen by the link state the firmware knows:

| State | Clip set | Phrases (varied, one per ask) |
|---|---|---|
| no Wi-Fi | `no_wifi` | "I can't find the Wi-Fi." / "I'm not on the Wi-Fi right now." / "I can't see the Wi-Fi yet." |
| Wi-Fi up, host unreachable | `no_host` | "I can't reach my home base right now." / "I'm having trouble reaching home." / "Home isn't answering me yet." / "I can't get through to home just now." |
| refused, waiting for approval | `refused` | "I need to be approved again." / "Home needs to let me back in." |
| connecting | `connecting` | "Still connecting, one moment." / "Almost connected, give me a moment." |
| back online (after an outage over a minute) | `back` | "I'm back." / "I'm connected to home again." |

Sixteen clips of 1.5 to 3 s at about 2 KB per second of Opus: about 60 to 90 KB, embedded in the app image beside the earcons (1.36 MB
free; the assets partition's 400 KB free is not needed). A small cycle (never the same phrase twice in a row, as `OfflineSpeaker`
does), a rate limit (one clip per 10 s, at most three a minute, then the tone only), the volume setting, and quiet hours: at night the
tone only, no clip. Rendered at release time by `release.sh` from the Stack's own TTS (the same voice the hub speaks with, our own
synthesized voice, no real person), committed as generated assets with their text and checksums in a manifest like
`offline_clips.json`, so a release is reproducible and the licence line travels with them.

**Local commands beyond the wake word.** The stop-word model is MultiNet `mn5q8_en` with seven phonetic commands fixed in the patch
(`stop`, `stackchan stop`, `be quiet`, `quiet`, `that's enough`, `never mind`, `cancel`; patch 049 lines 181-188), armed only while the
unit speaks, dropped for good if it costs more than 6 KB of internal RAM and refused below 16 KB free (patch 049 lines 172-175). Two more
phrases ("what's wrong", "are you connected") need no new model: MultiNet takes commands as phoneme strings at start-up, so the list
can grow in the same patch. What they do need is arming the recogniser while idle and offline, which is new: today it listens only
during speech, and the internal RAM floor that gates it (12.5 KB lowest seen) is the real limit. Recommendation: the wake word alone
triggers the local clip in this release; add "are you connected" as a stop-list entry armed during the offline state only after the
RAM cost is measured on the unit (one check: free internal RAM with the recogniser armed while idle). Not feasible: free speech or any
phrase outside the fixed list.

## 18. One shared "link" screen (owner, 2026-11-13)

How the no-link screens are made today, with real sizes:

| Screen | How it is drawn | Assets | Code |
|---|---|---|---|
| Connecting to Wi-Fi, Connecting to Home (boot) | patch 033: one black `lv_obj` over the face and one wrapped `lv_label`; `ShowBootCover(text, ring_kind)` swaps the text and starts the ring blink; `HideBootCover` at the first Standby | none | 119 added lines (`033-connecting-screen-and-boot-ring.patch` lines 16-52, 97-116) |
| Wi-Fi setup needed | upstream status text in the same cover (patch 033 maps the Wi-Fi config strings to the cyan blink, line 110) | none (the pruned `setup_stackchan_front_view.bin`, 58,980 bytes, belongs to the servo setup app, `app_setup/workers/servo.cpp:41`, not to Wi-Fi) | shared with the above |
| Offline, Can't reach Home | patch 075: text into the face's speech bubble, `SetChatMessage("system", ...)` (lines 96, 104, 203), the avatar's `setSpeech` | none | about 30 of the patch's 189 added lines |

So the screens already share almost everything: no image assets, one cover, one label, one bubble. The shared design makes it one
component:

| Slot | Content | States |
|---|---|---|
| background | black, full screen (the existing cover) | all not-yet-linked states |
| glyph slot | top centre, 32 px: the shipped `icon_wifi_low`, `medium`, `high` (1,212 bytes each, already in the assets partition) cycled every 300 ms for "connecting"; `icon_wifi_slash` (1,212 bytes) for "no Wi-Fi" and "offline"; the slash glyph plus a NEW key glyph (about 1 KB) for "waiting for approval" | |
| text slot | the wrapped label below the glyph: "Connecting to Wi-Fi...", the setup instructions, "Connecting to Home...", "Waiting for Home to approve me", "Reconnecting..." | |
| corner strip | the same glyph and a short word ("Offline", "Reconnecting") at 16 px in the top corner of the face, used when the face is shown | offline, reconnecting |

Which states get the full screen and which keep the face: the full link screen is for states where the robot can do nothing useful
until the link exists: boot (no face yet), Wi-Fi setup, connecting to Home at boot, and waiting for approval (an admin must act in the
app; the robot cannot talk or move for a person). The face with the corner strip and the muted palette is for states where the robot is
still usable (the owner's rule: complete without a hub): offline after the face has shown, and a reconnect in progress. The speech
bubble goes back to speech only.

What it saves: no new image assets for the screens (the key glyph is the only one, about 1 KB; the four Wi-Fi icons are already
shipped); the cover code of patch 033 and the bubble writes of patch 075 fold into one `ShowLinkScreen(glyph, text, ring)` and one
`ShowLinkStrip(glyph, word)` of about 100 lines, replacing about 150 today; no second screen object, no second font. The muted palette
is one more entry in the mint skin's palette table (patch 017 already carries seven plus the night one). Nothing here touches the 4 MB
assets partition beyond the key glyph.
