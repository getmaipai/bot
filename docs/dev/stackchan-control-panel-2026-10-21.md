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
