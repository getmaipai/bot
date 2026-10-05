# Measurement runbook: the rows that need the unit

The design record's section 12 names six measurements for the Reachy Mini
body. Everything that can be proven without the physical unit is built and
tested (`body/maipai_body/measure/`, `body/scripts/measure_*.py`); this page
is the order of work on the day the unit arrives. Nothing here has been run
on a unit: the only recorded figures are the simulator rows in
[`measurements.md`](measurements.md), marked `sim`.

## Before the first run

- EXPR-02 simulator rows: on a Mac with `reachy-mini-daemon --sim`, record the command and feed stamps in `measurements.md`.

1. Install the wheel the way the robot is always installed:
   `scripts/install-reachy.sh <host> <wheel>`. That puts the package, including
   `maipai_body.measure`, in the daemon's apps venv at `/venvs/apps_venv`.
   The scripts below are not in the wheel; copy them over and run them with
   that venv's Python (`uv run` cannot resolve on the unit, because
   `body/pyproject.toml` scopes the lockfile to the dev Mac):

   ```
   scp -r body/scripts pollen@<robot address>:maipai-scripts
   ssh pollen@<robot address>
   ```

2. Run the unit tests that guard the rows. They skip everywhere else:

   ```
   MAIPAI_UNIT=1 /venvs/apps_venv/bin/python -m pytest tests/test_unit_hardware.py -q
   ```

   (From a checkout of `body/` with pytest installed in that venv, or from a
   dev machine pointed at the unit's port 8000.) Seven checks: the sampler
   reads a real temperature and throttle flag, a cue moves the real head
   inside the limits, the smallest stall fraction is reached on a free head,
   the array answers with an angle, the audio path delivers blocks, the
   battery probe runs, and a lost hub mid-turn cancels once and settles the
   real head. A failure here means the row below it would be measuring a
   fault.

3. Pair the robot with a hub (M-R1's `pod` and `robot` configurations and
   M-R4's conversation workload run real turns through the hub). Have a
   16 kHz 16-bit mono WAV of a household sentence that ends where the
   speech ends. For M-R3 have the three wake-model files in one directory
   (`melspectrogram.onnx`, `embedding_model.onnx`, `trained_hey_maipai_v2.onnx`).

4. Stop the body app before M-R3 and M-R4, which own the microphone:

   ```
   curl -X POST http://localhost:8000/api/apps/stop-current-app
   ```

   Start it again afterwards with `POST /api/apps/start-app/maipai_bot`.

Every script writes JSON under `./measurements/` and, with `--record`, a
markdown section. On the unit there is no `docs/` tree, so the section lands
in `measurements/section-M-R<n>.md`; carry it back and commit it into
`measurements.md` with the daemon version, image release and profile in its
header (the scripts write all three). Never a hostname, never a transcript.

## The rows

| Row | Run | Time | Reads as |
|---|---|---|---|
| M-R2 | `measure_mr2_cue_motion.py --mode unit --repeats 30 --record`, then `--hold hand --skip-latency --record` | 30 min, then 10 min with a person | p50 and p95 cue to first state-feed delta per primitive, split at the first command; amplitude and peak velocity against the declared limits; stall verdict per axis and fraction, free head first, then held |
| M-R5 | `measure_mr5_link.py --mode unit --trials 10 --record`, then the Wi-Fi cycle (below) | 20 min, then 10 min | cancel latency, pose still, reconnect p50 and p95, the one line once; the real radio's time back to the hub |
| M-R1 | `measure_mr1_budget.py --config daemon`, then `pod`, then `robot` (each on a fresh boot) | 3 hours | RSS, CPU, temperature and throttle flags per configuration; the robot-tier decision |
| M-R3 | `measure_mr3_wake_doa.py` parts 1 to 5 | 3 hours, most of it the false-accept listen | gates from `dev.md` section 11 |
| M-R4 | `measure_mr4_battery.py probe`, then one `run` per workload from a full charge | a day or more of wall clock | runtime to the LED's red by workload; whether any fact is readable; whether it runs while charging |

Each script's own docstring has the exact commands, flags and prompts. Order
of work: M-R2 first (it also checks the envelope against the declared limits on
the real head), then M-R5, M-R1, M-R3, and M-R4 last because it needs the
battery drained and recharged.

The radio itself (M-R5), on the unit, detached from your SSH session because
the connection will drop (use `tmux` or `systemd-run --scope`):

```
/venvs/apps_venv/bin/python scripts/measure_mr5_link.py --mode unit --trials 0 \
    --blackhole-trials 0 --hub-url http://<hub address>:<port> \
    --wifi-off "nmcli radio wifi off" --wifi-on "nmcli radio wifi on" \
    --wifi-outage-s 20 --wifi-trials 5 --record
```

## MOVE-CARRY-01: the carry thresholds (unit)

Every threshold in `body/maipai_body/presence/motion_state.py` is an
UNMEASURED design default. Nothing below has been run.

| Row | Run | Reads as |
|---|---|---|
| Lift and bump | Rest the body on a table. Nudge it with a finger ten times, then lift it by the base ten times and set it down | Per trial: the reported state sequence. Pass: no nudge reaches `lifted`; every lift reaches `lifted`. Record the peak deviation from 1 g and the peak gyro of each, to set `MOVING_ACCELERATION_DEVIATION_M_S2`, `MOVING_GYRO_RAD_S` and `LIFT_MIN_S` |
| Carry | Walk across the room holding the body, three times, at a slow and a normal pace | Whether `carried` is reached and never `freefall` or `tipped`. Sets `CARRY_MOVING_S` |
| Put down | Set the body down gently, then hand it back and hold it as still as a person can, thirty seconds each | Time from touchdown to `put_down`; whether a still hand ever reads as put down before thirty seconds. Sets `PUT_DOWN_STILL_S` |
| Drop while held | Over a cushion only, from 5 cm | `freefall` reported while the hold stays latched, then `put_down` after landing |
| Tilt while held | Tilt the held body past 45 degrees | `tipped` reported, hold stays latched |
| Gravity compensation while held (UNVERIFIED) | With `carry_gravity_compensation` on in a local profile, lift the body with the base tilted, hold it, set it down | Whether the head holds still under gravity compensation, and whether it is released on put down. The flag stays off until this row passes |

## What the simulator already showed, and what it cannot

- The harnesses run end to end against `reachy-mini-daemon` 1.11.0 `--sim`:
  cue to motion for every primitive, the unobstructed stall reference, and
  the link-loss trials against a stand-in hub. The unit's numbers replace
  the simulator's; the sim figures are a baseline, not a prediction.
- The simulator cannot be held, so held-head stall rows only exist on the
  unit. Its microphone array, audio path, temperature and battery do not
  exist, so M-R1, M-R3 and M-R4 have no simulator rows at all.
- M-R5 on the simulator loses the link by software on loopback: it measures
  the body's side (cancel, pose, the reconnect clock, the line), not the
  radio. `blackhole` faults wait out the production client timeouts (120 s
  on the turn and tts streams), which is the realistic Wi-Fi case.

## Calls to confirm when reading the first results

- Stall "fractions" are shares of an axis's declared limit (0.05, 0.1, 0.2,
  0.3), commanded by one `goto`. The design says "at each fraction"
  without saying of what; change `--stall-fractions` if the owner meant
  the envelope's own fractions.
- M-R3's bearings are 0 straight ahead, positive to the robot's left. The SDK
  documents the array angle as 0 rad left, pi/2 front or back, pi right, so
  errors are taken in array-angle space with front and back folded; the raw
  angles are saved per bearing so a wrong convention shows on the first run.
- M-R1's endpoint to transcript runs from the last utterance sample to the
  final transcript and so includes the hub's endpointing silence. M-06's
  figure on the MaiPai build is not recorded yet (the item is open), so the
  `robot` decision needs `--m06-p95-ms` supplied by hand.
- The reconnect line's wording (`LINK_RESTORED_LINE` in `run_loop.py`) is a
  first cut, spoken at the head of the next reply that reaches the hub until
  G4b's offline clips exist.
