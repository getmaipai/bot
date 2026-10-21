# StackChan brightness, default levels and the swipe-down control panel (2026-10-21)

Owner request, relayed by the firmware session. Part 1 is host code (shipped with the next batch).
Part 2 is `firmware/patches/045-control-panel.patch`: written, checked with
`git apply --unidiff-zero --check` against the tree after patches 037, 038 and 044, and the two touched
objects (`stackchan_display.cc`, `hal_mcp.cpp`) compile in the scratch ESP-IDF tree. It has not been
flashed. Patches 040, 041 and 043 are not in the recipe; when one returns it must be regenerated
against the tree that includes 045, because zero-context hunks are placed by line number.

## 1. Host: spoken brightness and the hub's default levels

**Voice** (`bodies/stackchan/brightness.py`, same matcher style as `volume.py`): "set brightness to
50%", "brightness 100", "brighter", "dimmer", "darker", "it's too bright", "it's too dark", "dim your
screen", "full brightness". The confirmation is "Brightness 50." Steps are 20, the floor is 10, so a
phrase can never leave the screen dark: "screen off" is answered with a line that says so instead of
turning the screen off (a dark screen with no touch wake reads as a dead robot). Sentences about
the volume, and "dim the lights", are left to their own handlers.

**Day and night** (`presence/night.py`): by day a spoken level is stored as the owner brightness in
`owner_levels.json`; at night it sets only a temporary night level and the day edge restores the
stored owner level exactly (same rule as the volume).

**Hub defaults** `robot.volume` (70) and `robot.brightness` (100): they arrive in `settings_changed`
and in the hello values, the same path as `robot.camera.watch_level`. A value is stored as the owner
level and applied now by day. At night the night levels stay; the day level shows at the next day
edge. `owner_levels.json` also keeps the last value the hub sent (`hub_volume`, `hub_brightness`), and
a default is applied only when it differs from that. Without this, every `settings_changed` or
reconnect repeating the unchanged default would undo a level the person set by voice or on the unit.
Changing the default in Settings still takes effect once.

## 2. Firmware design: swipe-down control panel (patch to add after 036, name `045-control-panel.patch`)

### What exists

- Patch 036 already builds a quick-settings screen on `lv_layer_top()` with a Volume slider
  (20 to 100), a Brightness slider (10 to 100), up to four saved Wi-Fi buttons and Done. Today it
  opens on a swipe up anywhere and closes on a swipe up or down or Done. Swipe down anywhere stops
  talking; swipe left and right change the volume by 10 with a toast.
- Gesture direction comes from `LV_EVENT_GESTURE` on the avatar panel. LVGL gives the direction
  only, not where the touch began.
- Patch 021 queues events `{kind, at_ms}` (cap 16) in `hal_mcp.cpp` behind `push_event`, which sits
  in that file's anonymous namespace, and `self.robot.get_events` returns and clears them. The host
  polls every 2 s while awake, every 1 s drowsy or asleep, never during a turn.
- It has no timeout, no tap-outside dismissal, and tells the host nothing about a changed level.

### Changes

1. **Trigger.** Store the touch start on `LV_EVENT_PRESSED` (`lv_indev_get_point`). A downward
   gesture that began in the top 30 px opens the panel. A downward gesture elsewhere still stops
   talking. Swipe up no longer opens it. The cost: a swipe down that starts in the top 30 px no
   longer stops talking; it opens the panel.
2. **Shape.** A sheet on `lv_layer_top()`, full width, about 110 px high, anchored to the top: the
   two sliders and a Wi-Fi button that opens the existing full list (so 036's Wi-Fi switching
   stays). Built on open and deleted with `lv_obj_delete_async` on close, so it holds no memory
   while closed.
3. **Dismiss.** (a) swipe up on the sheet; (b) a transparent full-screen catcher object under the
   sheet whose `LV_EVENT_CLICKED` closes it (tap outside); (c) an `lv_timer` of 5 s, reset by
   `LV_EVENT_PRESSING` and `LV_EVENT_VALUE_CHANGED` on the sheet and both sliders, so dragging never
   times out.
4. **Applying.** Unchanged: `VALUE_CHANGED` sets the codec volume and the backlight live while
   dragging.
5. **Telling the host.** On `LV_EVENT_RELEASED` of either slider call a new
   `void push_level_event(int volume, int brightness)` declared in a small header
   `main/hal/device_events.h` and defined in `hal_mcp.cpp` (outside the anonymous namespace).
   `DeviceEvent` gains `int volume = -1, brightness = -1`; `get_events` appends
   `,"volume":N,"brightness":M` only for `level_changed`. A pending `level_changed` is replaced, not
   appended, so a sequence of drags cannot push touch or shake events out of the 16-slot queue.

### Host side (done in this change)

`DeviceEvent` carries `volume` and `brightness`; `level_changed` is a known kind. `wake_on_touch`
hands each `level_changed` to `NightController.set_levels_from_unit` before the first-look drain
check, so a level set just before a poll is never dropped as old news, and it never counts as a
touch (no reaction, no wake). By day the levels become the owner levels; at night they become the
temporary night levels, exactly like a spoken change. Within the host's 2 s poll the owner
levels follow the unit.

### Check after a flash

1. Swipe down from the top edge: the sheet drops in with both sliders at the current levels.
2. Drag volume: the speaker changes live; release; within 2 s `owner_levels.json` on the hub host
   has the new volume.
3. Do nothing for 5 s: it closes. Drag a slider for 8 s: it stays open until 5 s after the release.
4. Tap outside, then swipe up on the sheet: both close.
5. Swipe down in the middle of the face while it speaks: it stops talking and no sheet opens.
6. At night (quiet hours) drag brightness: the screen follows; after day returns, the earlier
   day brightness is back.

### Decisions (firmware session, 2026-10-21)

The design is approved as written, including that a swipe down starting in the top 30 px no longer
stops talking. A swipe down anywhere else still does. A left or right volume swipe also queues
`level_changed`. The Wi-Fi list keeps its own Done button and closes after 20 s without touch.

### Risks

- The start point of a gesture is the thing to prove on the unit (the LVGL indev point after
  `GESTURE` is the release point, so the start must be saved on `PRESSED`).
- Only the two touched objects were compiled; the scratch tree cannot link a full image.
- The sheet is sized to its content; if three rows do not fit the 240 px screen height with the
  8 px padding, the Wi-Fi button is the one that clips. Look at it on the first flash.

## 3. Why swipes and taps do nothing on the face (investigation 2026-10-21)

Owner report: the swipe-up quick-settings panel from patch 036 never opened, swipes do nothing on
the face, and earlier a tap did nothing. Patch 045 is parked (kept in `patches/`, taken out of
`recipe.sh`) until swipes work; the stock panel may then be enough.

**What the code shows, end to end.** The FT6336 is created at I2C 0x38 and polled every 20 ms by
`PollTouchpad` in `hal/board/stackchan.cc`; it stores (points, x, y) with `hal_bridge::set_touch_point`.
`Hal::lvgl_init` makes a pointer indev whose read callback copies that point
(`hal/hal.cpp`). The face is a 320x240 `Container` made by `MintAvatar::init`, non-scrollable, with
non-clickable children that bubble to it. 036 hangs `LV_EVENT_GESTURE` on that container, and the
stock tap handler (`onClick`, toggles chat, only when `is_xiaozhi_ready()`, 2 s apart) is on the
same object. The boot cover and the boot logo do not sit above it: the cover is hidden by flag
after STANDBY, and the logo is created first, so below the face. LVGL 9.4 defaults (gesture limit 50 px,
minimum velocity 3 px per read) suit a normal swipe at the 33 ms read period. Nothing in the code
blocks touch input, so the cause is not visible from reading.

**What the serial captures show.** `serial*.log` (2026-10-20) have `Init FT6336`,
`create lvgl touchpad indev` and no `FT6336 read failed` warning, so the controller answers on the
bus. They cannot show touches at all: the only per-touch log line in the firmware is commented out
in `lvgl_read_cb`, and the `HAL-HeadTouch` lines are the head sensor, not the screen.

**Ranked guesses.** (1) The controller answers but reports no points (num stays 0): wrong work
mode, a reset line the board does not release, or a lost interrupt; nothing above it would then
see a touch. (2) Touches arrive but land on a different object than the face panel. (3) Presses
arrive but LVGL does not recognise the gesture or click. The three give different log lines, so
one flash tells them apart.

**Diagnostic: `046-touch-diagnostics.patch`** (in the recipe; compiled, applies after 044). Every
line below also goes to the host as a low-rate event (patch 021's queue, at most 20 a minute, none
while the queue is nearly full) and is logged there as `unit touch: <kind> <fields>`, so the serial
monitor (which resets the unit when opened) is not needed. On the serial port: `HAL: touch down x= y=` and `touch up` per finger (transitions only);
`face: pressed`, `clicked (xiaozhi_ready=)`, `long pressed`, `scroll began`, `gesture dir=` for each
LVGL event on the face; `face: gesture ignored (...)` when 036 drops a gesture. Read it as: no
`touch down` means guess 1; `touch down` without `face: pressed` means guess 2; `pressed` without
`gesture` or `clicked` means guess 3.

## 4. First flash of 046: what the host log showed, and the tap changes (2026-10-21)

Swipe up and down now open the stock panel, so the touch path works. The host log (`unit touch:`
lines, 11:41 to 11:43) showed two things.

**Swipes from the top bezel became taps.** The two taps that started listening were
`touch_down y=16`, `face_pressed`, `touch_up`, `face_clicked` and `touch_down y=0`, then the same.
A finger that starts on the very top edge reports one point at y 0 to 16 and loses it at the edge,
so LVGL saw a press and a release with no movement: a tap. Patch 047 ignores a tap whose press began
within 24 px of the top (serial line `face: tap ignored`, host event `click_ignored`).

**Touches with no `face_pressed`.** The `touch_down y=132` at 11:42:11 came 0.1 s after the unit
reconnected (`connection open`, `connection closed during a session`), so the boot cover, which is
clickable and sits on top until the first STANDBY, took it. The burst at 11:43:01 (six down/up pairs
at x 160 to 231, y 113 to 159) matches the quick-settings sliders and Wi-Fi buttons: while that
panel is open it is on the top layer and takes the presses, so the face never sees them. No
`gesture` event appears in the window. The likeliest reason is the diagnostic limits (12 queued
events, 20 a minute) and the host not reading events during a turn; not proven. The next test should
swipe once at idle, wait for the line, and then swipe again.

**Tap to stop.** The stock tap handler toggles the chat state. While speaking it sends an abort,
which the host already handles. While listening it called `CloseAudioChannel()`, which is a no-op
with the persistent websocket (patch 003), so the tap did nothing. Patch 047 sends the host an
abort (which cancels the turn and returns the device to idle) and sets the device idle itself. It
also drops the debounce from 2 s to 0.8 s, so a tap can stop what a tap started.

**Spoken stop.** At idle only the wake word is armed (`CONFIG_USE_AFE_WAKE_WORD`, "Hi, StackChan").
While listening the host hears everything, so `stop_phrases.py` handles a whole-utterance stop
("stop", "StackChan stop", "be quiet", "quiet", "never mind", "cancel", "that's enough", "stop
talking", "stop listening", "enough", "stop it") locally: the turn ends, the device goes idle,
nothing is said and the hub is not asked. "Mute" and "shut up" remain volume commands.

**Stopping while it speaks.** See `stackchan-spoken-stop-2026-10-21.md`. In short: while it speaks,
xiaozhi keeps only the wake word armed and a wake word calls `AbortSpeaking`; a plain "stop" is
not heard. The wake-word front end does run echo cancellation against the board's hardware
reference channel, so "Hi, StackChan" over the robot's own voice may work; that is the first thing
to test.

**Heart and surprise faces.** The unit's own stroke reaction sets the open-mouthed happy face and
restores it 3 s after the hand lifts. The host now puts the neutral face back 3 s after any stroke,
shake or heart (never during a conversation), so the open mouth cannot linger.

## 5. Phantom pets (2026-10-21)

The unit showed its petted heart and open-mouthed happy face at random, and the host log had a
"petted" line every 10 to 13 s with nobody there. Cause: `hal_head_touch.cpp` called the strip
touched when any of its three pads read 1 or more (readings are 0 to 3), set up once at sensitivity
level 3 with no baseline read, and fired a press at once. The stock `HeadPetModifier` then shows the
happy face, the heart and shy decorators and a head motion on every swipe, with no host involved.
Host side (0.2.21): a lone head event is ignored unless it was held 400 ms, a second follows
within about 4.5 s, or several arrive together. Firmware side (048): see the patch header. If a
gentle real stroke is missed, `head_touch_stats` will show max=1; lower `kPressIntensity` to 1.
