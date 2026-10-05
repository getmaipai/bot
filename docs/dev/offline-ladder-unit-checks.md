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
  found and keeps it.
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
  No real recognizer is wired. Replies are clip ids plus text; the text is on
  the app page, the clips are spoken only when the bundle can say every id.
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
  Module beside the wake model. No recognizer ships until this row exists.
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

4. The keyword spotter's CPU beside the wake model (M-R1's sampler, with the
   spotter running as its own process, named so it gets its own figures).
   There is no recognizer in this repo to start, so this row cannot run yet;
   when one exists:

   ```
   /venvs/apps_venv/bin/python scripts/measure_mr1_budget.py --config pod \
       --utterance-wav <file.wav> --process kws=<pattern> --image-release <release> --record
   ```

   Its false-accept rate has no harness (M-R3 covers the wake model only).

5. Real volume: `VolumeControl` is a seam with no body implementation. The
   daemon has `/api/volume/current` and `/api/volume/set`; the step size
   (`VOLUME_STEP`) needs ears on the unit.

6. Spoken replies: render the `cmd.*` and digit clips (G4b), then confirm each
   plays through `tests/test_offline_clips_unit.py`'s unit test.
