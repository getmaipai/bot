# Reachy Eyes wire protocol (clean-room note)

Status: every wire string below is UNVERIFIED. This note, the client in
`body/maipai_body/bodies/reachy_mini/eyes_client.py` and the probe in
`scripts/probe_eyes.py` use only this citation for vendor protocol claims:
the vendor README as summarised to the owner on 2026-10-05. No vendor
source, firmware, demo, default or tuned value was read, and nothing from
the vendor package is imported, depended on or locked (a test enforces
the last three).

## What is cited

The following command names and transport details are cited to the vendor
README as summarised to the owner on 2026-10-05. Their syntax and behavior
remain UNVERIFIED until the unit probe is run.

| Fact or command | Citation | Where it lives in our code |
|---|---|---|
| USB serial, 115200 baud | the vendor README as summarised to the owner on 2026-10-05 | `WireProtocol.baud` |
| Colour names RED, GREEN, BLUE, WHITE, AMBER, CYAN, MAGENTA (UNVERIFIED as wire strings) | the vendor README as summarised to the owner on 2026-10-05 | `WireProtocol.colours` (RED is not in the table; our seam bans it) |
| Command name `set_intensity` | the vendor README as summarised to the owner on 2026-10-05 | `WireProtocol.intensity` |
| Command name `blink` | the vendor README as summarised to the owner on 2026-10-05 | `WireProtocol.blink` |
| Blinking can be enabled and disabled | the vendor README as summarised to the owner on 2026-10-05 | `WireProtocol.blink_enable`, `blink_disable` |
| USB ids `2e8a:10fc` | `scripts/udev/reachy-eyes-setup.sh`, to be confirmed with `lsusb` at arrival | `find_eyes_port()` |

## What is not known

The README summary gave command names, not line syntax. The exact bytes,
the terminator, the intensity scale and any reply format are therefore
not known. The client keeps all of them as data in one frozen table,
`WireProtocol` (`DEFAULT_PROTOCOL`), so the owner's unit can settle them
by editing that table and nothing else:

| Intent | Wire line (UNVERIFIED) | Citation |
|---|---|---|
| colour | `CYAN` (example) | the vendor README as summarised to the owner on 2026-10-05 |
| intensity | `INTENSITY <n>`, `n` an integer percent 0 to 100 (scale UNVERIFIED) | the vendor README as summarised to the owner on 2026-10-05, command name only |
| blink once | `BLINK` | the vendor README as summarised to the owner on 2026-10-05, command name only |
| enable blinking | `BLINK ON` | the vendor README as summarised to the owner on 2026-10-05, command names only |
| disable blinking | `BLINK OFF` | the vendor README as summarised to the owner on 2026-10-05, command names only |
| line terminator | `\n` (UNVERIFIED) | probe on the owner's unit |

`OFF` has no documented command, so the client turns the eyes off with an
intensity of 0.

Nothing else is ever written. The test `test_only_table_commands_are_ever_written`
captures every byte sent through a pty over a full run and fails unless each
complete line matches one documented command and its allowed argument grammar.
A second test bans by name RGB, ANIMA, CAPTURE, every CFG, ENERGY, SHIMMER,
ASYMMETRY, ACK, STARTLE and RED. The owner decision of 2026-10-05 is: no
maintainer contact, clean-room go given. A `blink` pulse sends `BLINK`. The
seam's `ack` pulse has no cited wire command, so it is two `BLINK` lines.
Breathing is not a wire feature; if wanted it is a host-driven series of
`INTENSITY` lines by a caller, never autonomy inside this client.

## Client behaviour

- One writer thread owns the port. Callers never touch it; `set_look`,
  `pulse` and `off` enqueue and return at once.
- The port opens with `exclusive=True` and a 50 ms write timeout.
- Latest look wins: a burst of `set_look` calls collapses to the last one.
  Pulses are queued in order (bounded) and never dropped for a look.
- A write error or timeout closes the port and starts reconnect with a
  backoff that doubles from 0.5 s to a 30 s cap, resetting on success.
  The wanted look is replayed after every reconnect.
- Replies are never required. After each write and while idle the client
  drains whatever the board sent into a bounded log (`replies`), so the
  device's buffer never fills. Nothing parses them.
- Never raises `BodyLost`; an absent device reports `connected=False`.

## Arrival-day probe

`uv run python scripts/probe_eyes.py` finds the board by USB ids (or
`--port`), opens it with the same settings and, by default, sends nothing:
the README summary as relayed to the owner documents no status or ping
command. It logs whatever the unit says unprompted for `--listen` seconds.
`--send NAME` may send one named command from the table (for example
`blink`), so the owner can see what the unit answers to each wire line and
fix the table. It cannot send anything outside the table.

unit probe results: pending (scripts/probe_eyes.py on the owner's unit at arrival)

- [ ] lsusb ids confirmed
- [ ] line terminator
- [ ] colour line syntax
- [ ] intensity syntax and scale
- [ ] blink and blink enable or disable syntax
- [ ] any reply format
