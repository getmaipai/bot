# StackChan timers, alarms and hub announcements (2026-11-13)

Owner decision 2026-11-13: on-device timers, no Bluetooth. Status: built and compiled; nothing has run on a unit.

## What already existed (searched first)

- Hub: Home ships list, reminder and alarm tools (`home/backend/src/lib/alarmCalls.ts`, assist tools v0.2.158). Its timers live in
  the hub and ring where the hub says; no hub command reaches the StackChan, and the hub's safety alarm (`alarm` command, `initiative/alarm.py`)
  is a different thing (amber, hub driven).
- Bot: `link/commands.py` has a fixed five minute in-memory timer for the offline ladder (not wired to the unit); `adapter.py` has
  `create_reminder`, `get_reminders` and `stop_reminder` pushes and an orange "show" fallback.
- Firmware (upstream StackChan): `self.robot.create_reminder` keeps a RAM timer, draws a card with the message and plays the notification
  tone when it fires. It is lost on reboot and has no ring, no cap and no way to ring silently.
- Unit: the PCF8563 RTC is read into the system clock at boot (`hal_rtc.cpp`); the host's `server_time` sets it first.

## What was built

| Piece | Where |
|---|---|
| Timer and alarm logic, plain C, host tested | firmware patch 090 (`tests/firmware/timers_core_test.c`) |
| Schedule in NVS namespace `mp_timers` (key `v1`, version byte, count, check), tick, ring | patch 091 |
| Tools `self.timer.set / alarm / list / cancel / stop / snooze` | patch 092 |
| Touch (screen or head) ends a ring | patch 093 |
| The stop word ends a ring | patch 094 (xiaozhi-esp32 repo) |
| Host service, caps, plain errors, spoken line, count | `bodies/stackchan/timers.py` |
| Hub announcements | `bodies/stackchan/announce.py` |
| Wiring, events, check-in `timers_active` | `app.py` (`_wire_timers_and_announcements`), `link/checkin.py` |

Behaviour: at most 8 active; a timer is 1 s to 24 h; an alarm is the next HH:MM of the unit's local day. A timer is stored as an
absolute Unix time, so it survives a reboot and rings with no hub. Due while the unit was off: rings if at most 10 minutes late,
otherwise dropped and reported (`timer_missed`). A timer set while the clock was never set runs on boot time and is not saved.
When one rings: happy face with the reminder card showing its label, cyan pulsing ring (the lights standard's `pairing` row: cyan at 0.6, a short pulse every 2 s),
the notification tone at once and every 8 s unless `silent`, the screen kept awake, a `timer_fired` event. It ends on a touch, the
stop word, the host (`self.timer.stop`), or by itself after one minute (`timer_ended` with `how`). The host then says "Your timer is
done." (skipped at night and when muted). A snooze (default 5 minutes, at most 1 hour) starts a new timer with the same label.

Announcements: the hub's `announce` command shows the card and tone through the unit's existing one second reminder, then the host
says the line through the body's own speech path. Refused (with the reason in the ack) when `robot.announce.enabled` is off, when
`robot.muted` or `robot.quiet` is true (even urgent), and at night unless `urgent` is true.

## Limits and unverified

- Nothing ran on a unit. The firmware compiled (ESP-IDF 5.5.4, app image 3.83 MB of the 4.99 MB slot).
- On battery the unit shuts down after 10 idle minutes and a timer cannot wake it; on USB the idle shutdown is off. Do not promise a
  timer on a battery unit longer than that without a keep-awake rule (open question for the owner).
- The stop word is armed for the ring on a best-effort basis; patch 049 armed it only while speaking, so whether "stop" is heard in
  standby is the first thing to test. A touch always works.
- At the end of a ring the ring goes dark (the host ring state is not restored; the host repaints on its next change).
- An older firmware has no `self.timer.*`: the hub command answers "could not reach my body".
- The offline ladder's five minute timer (`link/commands.py`) is still separate and not wired to the unit.

## Manual test on the unit (flash a build with patches 090 to 094; this session did not touch the unit)

1. Boot log shows `MAIPAI-TIMERS: loaded 0 timer(s)`.
2. `self.timer.set` seconds=20 label=tea: answers `{"ok":true,"id":1}`; `self.timer.list` shows `left` counting down.
3. Power-cycle the unit (not the host) inside the 20 s; after boot `loaded 1 timer(s)`; it rings at the 20 s mark.
4. Ring: happy face with the card "tea", cyan pulsing ring, tone now and every 8 s; a screen touch ends it within 0.2 s and the
   ring goes dark; the host log shows `unit timer: timer_ended id=1 how=touch`.
5. Leave one ringing: it ends by itself at 60 s (`how=timeout`). Repeat with a head touch (`how=head`) and the word "stop" (`how=stop`).
6. Stop the bot host and Wi-Fi, set nothing, and confirm a timer set earlier still rings.
7. `self.timer.set` 86401 gives `too_long`; nine sets give `full` on the ninth; `self.timer.alarm` at the next minute rings at the minute.
8. Snooze while ringing: ring ends, `list` shows a 300 s timer with the same label.

## What Home needs (not done here; the Home repo was not touched)

- Voice tools (when the turn's device is a StackChan with timers): send `device-command` kinds to the robot channel:
  `timer_set {seconds, label?}`, `alarm_set {hour, minute, label?}`, `timer_list {}`, `timer_cancel {id?}` (no id cancels all),
  `timer_stop {}`, `timer_snooze {seconds?}`. The ack `state` is `{ok: true, ...}` or `{ok: false, error: "<plain words>"}`; speak the
  error. Fall back to the hub's own timer for other bodies and for a StackChan that does not ack.
- Announcements: `device-command` kind `announce` with `{text, urgent?}`; ack `state` is `{status: "delivered"}` or
  `{status: "refused", reason: "disabled" | "muted" | "quiet" | "night" | "empty" | "unreachable"}`; on a refusal Home uses its own notice.
- Registry keys (device scope, honoured by bot): `robot.timers.enabled` (boolean, default true, label "Timers and alarms on this robot",
  help "Lets me set and ring timers and alarms myself, even when Home is off."), `robot.announce.enabled` (boolean, default true, label
  "Announcements from Home", help "Lets Home say things like 'dinner is ready' through me."). `robot.muted` and `robot.quiet` are read
  if Home sends them in the settings frame (boolean); the bot treats a missing key as off.
- Check-in: accept `timers_active` (integer or null) in `PUT /api/devices/me/checkin` and show "Timers: N" on the robot card.
- Plain words for the settings page: one line each, same labels as above; no firmware or tool names.
