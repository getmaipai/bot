# The offline ladder: what is built, and what needs the unit

LINK-STATE-01 (Reachy Mini only). Built and tested without the unit; nothing
on this page has been run on a unit, and no number here is a measurement.

## What is built

- `link/state_machine.py`: `connected`, `reconnecting`, `sleeping`, on an
  injected clock. `link_lost` (the funnel) or a failed re-redeem
  (`LinkLifecycle`) moves `connected` to `reconnecting`; `tick()` moves it to
  `sleeping` after `sleep_after_s`; a redeem from either returns it to
  `connected`. The phase is published as `robot.state.activity`
  (`reconnecting`, `sleeping`, spec-v0.1.73) through the existing
  `StateReporter`, by `ConversationLoop.snapshot()` whenever the funnel is idle.
- `link/address_walk.py`: LAN first (the paired address, then a fresh mDNS
  answer), then the tailnet entries. The tailnet provider
  (`no_tailnet_endpoints`) is the marked seam for ROBOT-TAILSCALE-01 and
  returns nothing today, so the walk is LAN only until that item's bot half
  lands. `HubLinkClient.refresh(base_url=...)` redeems at the address the walk
  found. Only a LAN answer is kept as the pairing's address; a tailnet answer
  is used for the session (`active_base_url`, which the turn clients read) and
  the stored LAN address stays the record.
- A wake during an outage is never silent. The funnel first walks the
  addresses once at once (`OfflineRungs.retry_link`), so a hub that already
  came back costs no dead time and the wake runs as a normal turn. If the walk
  fails, the `perk` acknowledgement plays; with no recognizer wired the rung 2
  status line is the reply (`line.unreachable` if the bundle can say it, the
  text on the app page always), and with one wired rung 1 listens as before.
- Boot with the hub away: with a stored pairing, `run_paired_body` starts the
  supervisor and builds the loop without waiting for a successful redeem (the
  loop reads the live cookie at its first turn). Rung 0 renders nothing until
  the funnel attaches its body, so no cue stage is spent early. Not covered: a
  body never paired, and a first boot with an empty model cache and no network.
  The machine starts `connected` only because it must start somewhere, so
  with a stored pairing `run_paired_body` also calls
  `LinkStateMachine.booted_without_contact` before the supervisor starts: the
  phase is `reconnecting` from power-on (unless the hub-link thread already
  redeemed, checked under the machine's lock), so the supervisor retries and
  a wake takes the offline path while the first redeem's walk is still in
  flight. `tests/test_link_review_fixes.py` drives that real ordering (no
  hand-called `reconnect_once`).
- Who gets the device token at a changed address (`link/client.py`,
  `_verify_changed_address`). The pairing's own address keeps the older
  check. Any other address the walk tries needs a positive proof, or the
  token is not sent: https, the certificate pinned at pairing time (no pin, or
  a certificate that cannot be fetched, is no token; an unfetchable one counts
  as a network failure); plain http, the instance id the pairing carries
  (`hub_instance_id`) presented for that address, either the walk's mDNS
  answer at that host and port or the tailnet address book's entry
  (`HubEndpoint.instance_id`, which ROBOT-TAILSCALE-01 must fill from the
  hub's own authenticated response). The candidate's host name and the LAN
  name mDNS advertises are not compared, so a hub reached at its tailnet name
  passes. Limit, stated plainly: an mDNS TXT record is unauthenticated, so on
  http this rejects the wrong hub, not an on-path attacker; https is the only
  path with that defense.
- Failure kinds in the walk (`address_walk.FailureKind`): a network failure
  and an identity mismatch both go on to the next address (a mismatch never
  sent the token); a 401 or 403 from the redeem is `revoked`, stops the walk,
  and the token is sent nowhere else. `LinkLifecycle` remembers the revoked
  token and presents it no more (no walk, no supervisor retry, no wake retry),
  reports `pairing revoked ...` as the last error (rung 2 and the app page),
  sets `paired` false, and `run()` leaves the heartbeat (polled every 5 s) to
  ask for a new code; a fresh pairing tells the machine it redeemed. The
  pairing's own address is still trusted as the pairing made it, so a 401 from
  it counts as authoritative.
- `link/supervisor.py`: the walk at once on a loss, then every
  `reconnect_interval_s`, and every `sleeping_interval_s` once asleep.
- Rung 0 (`link/rung0.py`): `settle` and `breathe` on loss, the `muted`
  primitive's pose as the antenna away pose after `away_after_s` (at once when
  sleeping), tracking off after `tracking_off_after_s` and while sleeping,
  `perk` then `settle` on reconnect plus the `line.reconnect` clip when the
  bundle can say it. `breathe` renders once per outage: the continuous loop is
  EXPR-04, not built.
- Rung 1 (`link/commands.py`): a closed list (stop, quieter, louder, timer,
  what time is it, are you connected) behind a `CommandRecognizer` interface.
  `speech/kws.py` is the sherpa-onnx keyword spotter that implements it
  (`uv sync --extra kws`; the model is fetched and checksummed on first use).
  It is not wired into the app: that waits on the CPU and false-accept row
  below and on a `VolumeControl` for the body. Replies are clip ids plus text;
  the text is on the app page, the clips are spoken only when the bundle can
  say every id.
- Rung 2 (`link/status.py`): a template over the machine's real values (last
  contact, attempts, the address tried, the path that answered, the last
  error), no model. Always on the app page; spoken only as `line.unreachable`.
- The queue rule (`link/replay.py`): rungs 0 to 2 queue nothing and the line
  says "Nothing is saved for later." The gate also holds the replay rule for a
  future queue: nothing replays, and no write or physical tool runs, without a
  confirmation event.
- Setting: `MAIPAI_LINK_SLEEP_AFTER_MIN` (minutes). Default 30 is a
  placeholder, UNMEASURED. The rung 0 and supervisor intervals are placeholders
  too (`Rung0Settings`, `SupervisorSettings`).

## UNVERIFIED

- The sherpa-onnx keyword spotter's CPU and false-accepts on the Compute
  Module beside the wake model (`docs/dev/measurements.md`, "Rung 1 keyword
  spotter"). The recognizer exists but is not wired until this row does.
- That the Compute Module's wake model and a keyword spotter can share the
  microphone stream the way `AudioCapture` hands blocks out.
- Every default interval above.

## Clips rung 1 needs and the bundle lacks

G4b owns the clip set. `link.commands.missing_clip_ids(load_manifest())`
returns the ids to add: `cmd.stopped` ("Stopped."), `cmd.quieter`
("Quieter."), `cmd.louder` ("Louder."), `cmd.timer_set` ("Timer set."),
`cmd.timer_done` ("Your timer is done."), `cmd.time_prefix` ("It is"), and
the digit clips `char.0` and `char.1` (the pairing alphabet has no 0 or 1).
Until they exist those replies are text on the page only.

## Needs the unit

Run in order, on the unit, with the apps venv (see `measure-runbook.md` for
the copy-over steps).

1. The unit-only test (the real head, injected clock):

   ```
   MAIPAI_UNIT=1 /venvs/apps_venv/bin/python -m pytest tests/test_unit_hardware.py -q -k link_state
   ```

2. Watch the cues on the real head (body app stopped first):

   ```
   curl -X POST http://localhost:8000/api/apps/stop-current-app
   /venvs/apps_venv/bin/python scripts/link_ladder_unit_check.py --host localhost --port 8000
   ```

   Pick `away_after_s` and `tracking_off_after_s` from what is seen.

3. The real radio's time back to the hub, which the sleep and walk intervals
   should be chosen from (detached from SSH; this is the M-R5 command):

   ```
   /venvs/apps_venv/bin/python scripts/measure_mr5_link.py --mode unit --trials 0 \
       --blackhole-trials 0 --hub-url http://<hub address>:<port> \
       --wifi-off "nmcli radio wifi off" --wifi-on "nmcli radio wifi on" \
       --wifi-outage-s 20 --wifi-trials 5 --record
   ```

4. The keyword spotter's CPU beside the wake model. Install `sherpa-onnx` into
   the apps venv, start the probe as its own process (it feeds a recorded
   utterance to the spotter at real-time pace, which is what a live microphone
   does), and run M-R1's sampler beside it with the probe named so it gets its
   own figures:

   ```
   /venvs/apps_venv/bin/pip install "sherpa-onnx>=1.13.8,<2"
   /venvs/apps_venv/bin/python scripts/measure_kws.py cpu --wav <utterance.wav> \
       --seconds 3700 --mode unit --label "pod config, beside the wake model" --record &
   /venvs/apps_venv/bin/python scripts/measure_mr1_budget.py --config pod \
       --utterance-wav <file.wav> --process kws=measure_kws.py --image-release <release> --record
   ```

   Then recall and false accepts, on real speech through the array. Record the
   six commands and the near-miss list as 16 kHz mono wavs named
   `<phrase with underscores>__<n>.wav` (`stop__01.wav`; any other name is a
   near miss), and a long non-command recording (a television at room level):

   ```
   /venvs/apps_venv/bin/python scripts/measure_kws.py accuracy --wav-dir <dir> \
       --mode unit --label "room, 1 m" --record
   /venvs/apps_venv/bin/python scripts/measure_kws.py false-accepts --wav <long.wav> \
       --wake-events-per-hour 30 --mode unit \
       --label "television news at room level" --record
   ```

   The tests' fixtures are synthesized speech and prove nothing about this row.

5. Real volume: `VolumeControl` is a seam with no body implementation. The
   daemon has `/api/volume/current` and `/api/volume/set`; the step size
   (`VOLUME_STEP`) needs ears on the unit.

6. Spoken replies: render the `cmd.*` and digit clips (G4b), then confirm each
   plays through `tests/test_offline_clips_unit.py`'s unit test.
