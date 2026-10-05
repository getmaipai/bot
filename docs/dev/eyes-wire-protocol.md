# Reachy Eyes wire protocol (clean-room note)

Status: every wire string below is UNVERIFIED. This note, the client in
`body/maipai_body/bodies/reachy_mini/eyes_client.py` and the probe in
`scripts/probe_eyes.py` were written from the order's summary of the
vendor's public README and from our own repo notes. No vendor source,
firmware, demo, default or tuned value was read, and nothing from the
vendor package is imported, depended on or locked (a test enforces the
last three).

## What is cited

Only the following facts, all from the public README as summarised to us
(the summary's wording is itself unverified; no line numbers were
available to this session, so none are cited):

| Fact | Where it lives in our code |
|---|---|
| The board is driven over USB serial at 115200 baud | `WireProtocol.baud` |
| Named colours: RED, GREEN, BLUE, WHITE, AMBER, CYAN, MAGENTA | `WireProtocol.colours` (RED is not in the table, our seam bans it) |
| An intensity setting (`set_intensity`) | `WireProtocol.intensity` |
| A blink (`blink`) | `WireProtocol.blink` |
| Blinking can be enabled and disabled | `WireProtocol.blink_enable`, `blink_disable` |
| USB ids `2e8a:10fc` | arrival-day probe noted in `scripts/udev/reachy-eyes-setup.sh`, to be confirmed with `lsusb` |

## What is not known

The README summary gave command names, not line syntax. The exact bytes,
the terminator, the intensity scale and any reply format are therefore
not known. The client keeps all of them as data in one frozen table,
`WireProtocol` (`DEFAULT_PROTOCOL`), so the owner's unit can settle them
by editing that table and nothing else:

| Intent | Wire line (UNVERIFIED) |
|---|---|
| colour | the colour name, upper case, e.g. `CYAN` |
| intensity | `INTENSITY <n>`, `n` an integer percent 0 to 100 (scale UNVERIFIED) |
| blink once | `BLINK` |
| enable blinking | `BLINK ON` |
| disable blinking | `BLINK OFF` |
| line terminator | `\n` |

`OFF` has no documented command, so the client turns the eyes off with an
intensity of 0.

Nothing else is ever written. The test `test_only_table_commands_are_ever_written`
captures every byte sent through a pty over a full run and fails on any line
whose command word is outside the table. A second test bans by name RGB,
ANIMA, CAPTURE, every CFG, ENERGY, SHIMMER, ASYMMETRY, ACK, STARTLE and
RED. These stay out until a public README line or the maintainer's written
reply cites them. A `blink` pulse sends `BLINK`. The seam's `ack` pulse
has no cited wire command, so it is two `BLINK` lines. Breathing is not a
wire feature; if wanted it is a host-driven series of `INTENSITY` lines
by a caller, never autonomy inside this client.

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
the README as summarised documents no status or ping command. It logs
whatever the unit says unprompted for `--listen` seconds. `--send NAME`
may send one named command from the table (for example `blink`), so the
owner can see what the unit answers to each wire line and fix the table.
It cannot send anything outside the table.

Record the unit's answers below when the unit arrives (device check 8):

- [ ] lsusb ids confirmed
- [ ] line terminator
- [ ] colour line syntax
- [ ] intensity syntax and scale
- [ ] blink and blink enable or disable syntax
- [ ] any reply format
