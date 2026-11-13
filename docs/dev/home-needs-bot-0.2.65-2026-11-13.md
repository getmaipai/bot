# What Home needs for Bot 0.2.65 (2026-11-13)

The Home repo was not touched by the integration. Spec first (`commons/spec`), then Home.

## Settings keys to register (device scope, honoured by bot)

| Key | Type, default | Label (plain words) |
|---|---|---|
| `robot.dance.enabled` | boolean, true | "Dance when asked" |
| `robot.dance.show_ring` | boolean, true | "Light show during the dance" |
| `robot.timers.enabled` | boolean, true | "Timers and alarms on this robot" |
| `robot.announce.enabled` | boolean, true | "Announcements from Home" |

Timers and announcements also read `robot.muted` and `robot.quiet` (boolean) when Home sends them in the settings frame; a missing key
counts as off.

## Settings keys to remove

`robot.indicator.sleep_eyes`, `robot.indicator.alarm` and `robot.indicator.sees` are no longer declared by the bot. Delete them from the
registry and the Lights page. Stored values are ignored. The three that stay: `robot.indicator.enabled` (new label "Light up when I am
listening or need you"), `robot.indicator.brightness` ("Light brightness by day") and `robot.indicator.night_brightness` ("Light
brightness at night"); the ring table is in `docs/dev/led-standard-2026-10-20.md`.

## Device commands Home sends on the robot channel

- `dance {}`: the Dance button on the robot's settings page. The ack state is `{"dance": "started" | "refused", "why": ...}`.
- Timer tools (when the turn's device is a StackChan): `timer_set {seconds, label?}`, `alarm_set {hour, minute, label?}`, `timer_list {}`,
  `timer_cancel {id?}` (no id cancels all), `timer_stop {}`, `timer_snooze {seconds?}`. The ack state is `{ok: true, ...}` or
  `{ok: false, error}`; speak the error. Fall back to the hub's own timer for other bodies or a robot that does not ack.
- `announce {text, urgent?}`: the ack state is `{status: "delivered"}` or `{status: "refused", reason}` with reason one of `disabled`,
  `muted`, `quiet`, `night`, `empty`, `unreachable`; on a refusal Home uses its own notice.

## Check-in fields (`PUT /api/devices/me/checkin`)

New and nullable: `timers_active` (integer), `self_restarts` (integer, how often the unit restarted itself), `heal_hold` (boolean, the
unit's restart guard is holding) and `mic_level` (integer). Show "Timers: N" on the robot card.

## Details

Full text for timers and announcements: `docs/dev/stackchan-timers-and-announcements-2026-11-13.md`. Dance:
`docs/dev/stackchan-little-dance-2026-11-13.md`.
