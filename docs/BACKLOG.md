# Backlog

What's built and what's missing on the way to Robot v0.1. Scannable,
not narrative: the design and the reasons live in
[`dev.md`](dev.md) (rewritten 2026-09-14 as the design record; its
section numbers are cited below), the owned parts in
[`dev/build-record.md`](dev/build-record.md). Update this file in the
same commit as the change that closes or opens a gap.

Size tags: **S** (a session or less), **M** (a real slice, days), **L**
(a platform-level capability with its own design note first).

Repo state as of 2026-09-14: `bot/` has no source tree, only docs, legal
files and `scripts/check.sh` on the standards core. The intended layout
once code lands, cited by the items below: `body/` (Python, uv, Ruff,
pytest: the hardware supervisor), `runtime/` (Bun: the pinned household
runtime's robot adapter and its `bun:test` suite), `packages/` (the
robot-only catalog packages), `docs/`, `scripts/`. Nothing in `body/`
or `packages/` may copy a hub package or a hub record type
(`dev.md` section 2). Since 2026-09-27 `body/bodies/` holds one
profile per supported body behind the HAL seam (`maipai/` for the
owned build, `reachy_mini/` for the daemon client): the bodies design,
[`dev/design-reachy-mini-2026-09-27.md`](dev/design-reachy-mini-2026-09-27.md),
and the "Reachy Mini body" area below.

Every item is pickup-ready: objective, pointers, a pattern to mirror,
acceptance, out of scope, exit check. An item that waits on a hub item
names it; the hub items themselves are filed by the coordinator in
`getmaipai/home` and are listed under "Hub dependencies".

Two milestones (`dev.md` section 12, amended on the outside review of
2026-09-14): **Robot v0.1-standalone**, demonstrable and not a release,
is the bench Pi with no hub carrying a roster household authored on the
screen through wake, a turn, a spoken reply, a fact remembered across a
reboot, the safety floor, a timer, expression cues with onset before the
acoustic onset, the honestly labeled mute, and M-01, M-02, M-05, M-06,
M-07, M-08 and M-10 recorded. **Robot v0.1** is that plus the link, tagged
when hub v0.3 ships it. An item marked "after standalone" starts only
when the standalone proofs are green.

## Step 0: repo scaffolding

- [x] Repo reset to a clean history (S): `LICENSE` (AGPL-3.0), `NOTICE`,
      `README.md`, `docs/dev.md`, `scripts/check.sh` pinned to
      `@maipai/standards` std-v0.3.0. Verified by `git log` (`f217451`,
      `578c43c`).
- [x] Port the pre-rebuild bench and wake-word learnings into `docs/dev.md`
      (S): done 2026-09-06 (`f4e9c9a`), corrected against the mirror
      2026-09-14 (the shipped wake model, the pre-roll figure, the
      software mute).
- [x] The design pass (L): `docs/dev.md` rewritten as the design record
      with the 83 legacy verdicts, this backlog, and the build record,
      2026-09-14.
- [x] **`check.sh` grows its own steps** (S). Objective: when `body/` and
      `runtime/` exist, `scripts/check.sh` runs Ruff, pytest, `bun test`
      and the spec fixtures before the standards core; `--docs` runs the
      core alone. Mirror: `home/scripts/check.sh`. Acceptance: a
      deliberate lint error in each tree fails the gate; a docs-only
      commit passes in seconds. Out of scope: CI. Exit: `bash
      scripts/check.sh` green. Verified at this commit: runtime block
      proven with a deliberate type error, body block by the identical
      guard.
- [x] the standards pin resolves through a per-tag worktree and pins std-v0.3.0 (verified at this commit)

## Hub dependencies

Not this repo's items. What the household track waits on, by name, so a
session never privately implements a pending hub behavior (`dev.md`
section 12).

| Hub item | What the robot needs from it | Robot items that wait |
|---|---|---|
| RUNTIME-01: the household runtime as a workspace package the hub runs, with an explicit package API | The engine, context, signal, guards, boundary, safety classifier, store, judge, scheduler, people, settings, host and link as one pinned package; the injected ports and the exposed calls declared (`dev.md` section 2), the hub its first consumer through that API | RT-00 to RT-06, LINK-*, BENCH-02 |
| spec-v0.1.0 (Jesse's call) | The tag the robot pins as `maipai-spec` | RT-01, SPEC-* |
| SPEC (section 3): `Person.source: standalone`, the `alias` op, `speaker_evidence` and `present` on the turn, `age_band_basis: claimed_profile`, the jobs and commands verdict, the `bot` mark on the keys the robot honours | The shapes the robot writes from first boot | RT-02, SPEAK-02, LINK-03 |
| SURFACE-01: `robot` admitted as an implemented surface with the spoken presentation and the `present` list (landed on the hub 2026-09-15) | Connected mode | LINK-04, RM-05 |
| WIRE-01: `signal`, `plan` and `cancel` on the turn stream (`signal` and `cancel` landed 2026-09-15; `plan` follows ACT-03) | The expression cues in connected mode | EXPR-03, RM-05 |
| ROBOT-DEVICE-01 (hub, filed 2026-09-27 for the bodies design): the Devices page's "Add a robot": find a unit advertised on the LAN, accept the code the robot spoke or showed on its own page, mint a device token of kind `robot` (the kind exists in `devices.ts` and nothing mints it), rotate the unit's default password into the credentials center as part of the add | Pairing for a body with no screen | RM-05, RM-08 |
| ROBOT-ROUTES-01 (hub, filed 2026-09-27): the turn stream, `POST /api/turn/{id}/cancel`, and the `stt` and `tts` routes accept a `robot` device token with `surface: robot`, scoped to that device's conversation | The `pod`-tier speech path and the connected turn | RM-04, RM-05 |
| ROBOT-CARD-01 (hub, filed 2026-09-27): the robot's card on the Devices page from the device's live state (listening, thinking, speaking, muted, tracking, on battery with level unknown where the body cannot read it), and the body's daemon version with its update as a row on the Updates page, a person's click | The states this body cannot show on itself; the daemon's update | RM-05, RM-08 |
| ACT-03 (with CHAT-16): the ReplyPlan at runtime | The plan-driven half of expression | EXPR-03 |
| `spec/link/` and hub v0.3: the envelope, ops, states, the never-sync allowlist, node rank | Pairing and sync | LINK-01 to LINK-05 |
| COMP-06 and SPEAK-01 (hub halves) | Bindings synced as records; the voice-print policy | SPEAK-02, SPEAK-03 |
| `platforms: [home, bot]` on websearch, the almanac, timer, remind and list packages (Tier 0) and on media-lookup and knowledge (Tier 1); weather, define, joke, trivia, math, convert, remember and recall are marked already | The Tier 0 set on the robot; the typed sources under the Deno host | RT-04, RT-06 |
| The plan amendment recorded by the coordinator: the shared TypeScript interpreter and floor run on the robot; the hub's "Python ports of the shared floor" item retires | Nothing to build; a doc change on the hub | none |
| HOME-STACK-02 (the Stack client and the role wire in Home's backend) and STACK-17 (the Stack's Linux ARM profile: `chat`, `embed`, `judge` on pinned llama-server, the body's speech as a managed engine, systemd from STACK-95) | The robot runs Home's platform code, so its own Stack is installed and called the way Home's is; RUNTIME-01's supervisor port is that client, never an in-process supervisor | RT-01, M-01 through M-10, BODY-02 |
| RF-05b (the Stack's wire shapes move into `shared/spec`: role request and reply headers, the event feed, the health item, the settings and precious-state declarations) | The Python body pins `maipai-spec` at Home's version and speaks those shapes to the robot's Stack | RT-01, SPEC-* |
| HOME-STACK-04 and 05 (the Engines page, the Updates and Repairs wiring in Home's admin) | The robot's engines, updates and repairs appear on the same pages when it is paired, behind the same admin sign-in; the Stack itself has no login | Pairing items under `spec/link/` |

## Measurements

Each is a bench run on the owned Pi with the header `dev.md` section 11
requires, recorded in `docs/dev/measurements.md` (created by the first
one), never a hostname, never a household recording. A measurement's
decision rule is in `dev.md` section 4; the number decides, the session
does not.

- [ ] **M-01: the process budget** (S). Objective: the body, the
      household runtime, the Deno host, three llama-server processes and
      the vision pipeline together on the 16 GB Pi for one hour: RSS and
      headroom, CPU per process and total, sustained power draw from the
      UPS HAT's and the INA228's telemetry (and a bench meter where one
      is owned), SoC temperature, and the firmware's throttle flags.
      Pointers: `scripts/bench/budget.py` (new). Acceptance: the numbers
      recorded in `budgets.json`'s robot row; swap at zero; zero
      throttling over the hour. Out of scope: tuning. Exit: the recorded
      table. Waits on RT-01 for the runtime's share; the body's share
      first.
- [ ] **M-02: the chat model on the Pi** (M). Objective: the hub's real
      rendered prompt with the ordinary tool set, three seeded fixture
      runs per candidate (Qwen3-1.7B, Qwen3-4B, and MiniCPM5-1B as the
      third candidate since 2026-09-27, see
      `dev/research-minicpm5-reachy-mini-2026-09-27.md`: its XML tool
      calls must parse to `tool_calls` through llama-server before its
      latency run counts; Q4_K_M, llama-server
      pinned to four cores, `--cache-reuse 256`), first delta p50 and
      p95, generation rate, RSS, and the quality gates in the same run:
      the fixture's hard rows (credential, cross-person, unsafe-and-
      crisis, consequential-once), the guard corpus at the hub's floor,
      and the legacy honesty method's raw and guarded columns as a
      recorded score. Acceptance: the decision rule applied (latency
      under the rule and every hard row green) and the model named; the
      honesty score handed to the owner (question 13). Waits on RT-01.
      Background turns: see the one note under "Household runtime on
      the robot"; this item records the named model's value.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05.
      Nothing for it is dispatched or started until the owner says so.
- [ ] **M-03: the Hailo provider option** (M, only if M-02's rule promotes
      it or v0.2 asks). Objective: the rendered prompt's token count
      against the 2,048-token ceiling, first reply with retained context
      on the current HailoRT, the swap cost against vision. Acceptance:
      "fits and faster" or "closed", with numbers.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05.
      Nothing for it is dispatched or started until the owner says so.
- [ ] **M-04: embed latency** (S). nomic-embed-text-v1.5 through
      llama-server on the Pi; acceptance under 60 ms warm per utterance.
- [ ] **M-05: the judge drain and its preemption** (S). First the
      mechanism: llama-server's freeing of a slot when the client aborts
      the request, verified in the installed source with the line cited
      in `docs/dev/measurements.md`. Then the abort-at-arrival test: the
      chat engine's first-token delay with a judge decode aborted at the
      interactive arrival against an idle judge, acceptance within 100
      ms; the 4B per judged turn with the prompt cache and `--cache-ram
      0`; a 300-turn day against the idle hours; a Repair when it does
      not fit, never a smaller judge.
- [ ] **M-06: endpoint to transcript** (S). Moonshine and Silero in the
      body's speech process on the array, p50 and p95 on the wake rows of
      `dev.md` section 11. Needs only VOICE-01, not the runtime.
- [ ] **M-07: speaker evidence on the array** (S). SPEAK-01's acceptance
      (three enrolled roster voices, an unenrolled voice unknown, a
      change mid-conversation), the threshold and margin set by the run
      against the gates of `dev.md` section 11: at most one false accept
      in a hundred stranger utterances, at most one false reject in ten
      household utterances, the unenrolled voice unknown every time.
- [ ] **M-08: the wake word on the array** (M). False accepts per hour and
      false rejects on held-out real-microphone recordings at the runtime
      threshold, the near-miss set included, against the gates of
      `dev.md` section 11 (at most one false accept per two hours on the
      negative bank at room level; at least nine wakes in ten at one
      meter quiet and eight in ten at three meters with a television on;
      the near-miss set never waking); the shared front-end models'
      license verified in the same record. A miss on any gate is a
      finding and the alternative (the keyword spotter) is measured the
      same way, never a threshold moved to pass.
- [ ] **M-09: time to first audio** (S). Per voice package on the Pi,
      Pocket TTS as the candidate beside Piper.
- [ ] **M-10: the concurrent load** (S). Capture and tracking, wake, an
      interactive turn and playback together for an hour: CPU, RSS,
      thermal, sustained power, capture dropouts and playback underruns
      from the device counters (acceptance: zero of each). Rides with
      M-01 once the runtime exists.

## Body: bring-up and calibration

The body track starts now; nothing here waits on the hub.

- [ ] **BODY-01: the parts record and the wiring tables** (S). Objective:
      `docs/dev/build-record.md` filled from the owner's answers (the
      numbered questions in `dev.md`), and one from-to wiring table per
      stage under `docs/user/build/` in the org's Instructables format.
      Mirror: the legacy `docs/src/content/docs/user/build/head/*.mdx`
      from-to tables. Acceptance: no question mark left on a Stage 1
      row; every wiring row names both ends. Out of scope: later
      stages' parts. Exit: `bash scripts/check.sh`.
- [ ] **BODY-02: the head-and-voice HAL, lifted as drivers** (M).
      Objective: `body/hal/` with the PCA9685, AS5600 through the
      TCA9548A, the MPU-6050, the MPR121 (the near-hand freeze), the UPS
      HAT, the Pico face controller link, one Picamera2 capture owner
      and the Hailo tracking pipelines (YOLO, SCRFD, pose) with derived
      observations only, each behind the typed HAL seam with a fake for
      tests. Pointers: the mirror's `robot/robot/hal/drivers/`.
      Acceptance: every driver's fake passes the same pytest suite as the
      hardware run; the capture pipeline's measured frame rate recorded.
      Out of scope: the room sensors (BODY-09), ArcFace (SPEAK-04), the
      drive controller, the brake. Exit: `bash scripts/check.sh`.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05. Nothing for it is dispatched or started until the owner says so.
- [ ] **BODY-09: the room sensors** (S, after standalone). Objective: the
      VL53L5CX units, the radars, the VEML7700, the BME688, the MCP23017,
      the INA228 and DS18B20 when fitted, behind the same seam with
      fakes; the ToF near-face rule joins the freeze. Acceptance: the
      fakes and the hardware run agree; the count and positions from the
      owner's answer (question 7) recorded. Exit: `bash
      scripts/check.sh`.
- [ ] **BODY-03: the array self-test** (S). Objective: `body/audio/` opens
      the XVF3800 directly (never behind a hub), reads its firmware
      version and refuses below 2.1.0 with a Repair, checks channel 0's
      level and zero-crossing ratio against the recorded healthy values,
      and reads direction of arrival from the array's beam selection at
      wake and at onset. Acceptance: a deliberately wrong version string
      in the fake raises the Repair; the healthy check passes on the
      bench array. Exit: `bash scripts/check.sh`.
- [ ] **BODY-04: calibration mode and the head envelope** (M). Objective:
      find the stops per axis from the encoders, set soft limits inside
      them, measure servo current unloaded and with the shell, settling
      time, the rail's sustainable velocity, and pinch clearances, with
      the servo rail measured under a two-servo stall and the e-stop
      chain proven to cut that rail in the same run; write the envelope
      (amplitude, velocity, acceleration, jerk, current cap) into
      device-scope settings with the run date; refuse expression without
      the whole gate of `dev.md` section 10 (the rail, the e-stop, the
      mute answered, the clearances). Pointers: `body/head/calibrate.py`, `body/head/
      controller.py` (one controller, encoder feedback, target expiry,
      disagreement and stall detection, the priority order of `dev.md`
      section 5). Acceptance: the envelope recorded; a fake encoder
      disagreement stops the head in the deterministic test; the
      physical run's numbers in `docs/dev/measurements.md`. Out of scope:
      the primitives. Exit: `bash scripts/check.sh`.
- [ ] **BODY-05: the presence funnel** (S). Objective: one state
      (speaking, thinking, listening, idle; mic live as a separate fact)
      feeding the eyes, the mouth, the ring, the screen and the link,
      with the legacy event-order tests (the 0.5 s settle gate against
      the 45 ms flash). Pointers: `body/presence/`, the mirror's
      `robot/robot/presence/service.py`. Acceptance: the legacy trace
      replays without a flash. Exit: `bash scripts/check.sh`.
- [ ] **BODY-06: power and thermal supervision** (M). Objective: the
      admission budget for the resource governor, the pressure order
      (idle motion off, background off, one announcement, persist, safe
      shutdown), the UPS reserve, an unknown pack temperature treated as
      a fault, never the board's temperature; charging control disabled
      until the owner's answers on question 4 are in. Pointers:
      `body/power/`. Acceptance: the deterministic tests for each
      pressure path; no charging control path enabled. Exit: `bash
      scripts/check.sh`.
- [ ] **BODY-07: the mute** (S, after the owner answers question 1).
      Objective: if a hardware cut exists, the body reads its state from
      the contact and drives the indicator from that state alone; if
      not, the software mute is labeled "software mute" in the settings
      key description and on the screen, and the privacy page says so.
      Acceptance: with the cut, a muted state with the process still
      running receives zero frames (tested with the fake and on the
      bench); without it, the label is present in both places. Exit:
      `bash scripts/check.sh`.
- [ ] **BODY-08: the e-stop and bumper sense line** (S, after question 6).
      Objective: the stop state readable by the body, from a spare
      contact or inferred from the rail voltage, reported to the state
      and the link, never gated by software. Acceptance: the fake and
      the bench both show the state flip within one tick. Exit: `bash
      scripts/check.sh`.

## Reachy Mini body (2026-09-27)

The second supported body: the bodies design
[`dev/design-reachy-mini-2026-09-27.md`](dev/design-reachy-mini-2026-09-27.md)
(cited below by section). The unit is ordered with a lead time of up
to 90 days; Pollen's MuJoCo simulator (`reachy-mini-daemon --sim`,
`mjpython` on the dev Mac) serves the identical API and is the bench
for every item until the box lands. Items marked "unit" need the
hardware. Measurements M-R1 to M-R6 are the design's section 12 and
are recorded in `docs/dev/measurements.md` with the daemon version,
the image release and the profile id in the header.

Two bodies, one body layer (owner decisions, 2026-10-05): the Reachy
Mini and the Pi 5 + Hailo-10H build are two profiles over one body
layer, never two code lines. The Reachy Mini (Wireless, CM4 4 GB) is the
connected body: the hub runs its turns, it must work away from home
over Tailscale, and it keeps working in a limited way when the hub is
gone. The Pi + Hailo build is the standalone-capable body.
Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05. Nothing for
it is dispatched or started until the owner says so.
The offline ladder (LINK-STATE-01 below) is scoped to the Reachy Mini.

- [ ] **RM-00: the body-capability vocabulary** (S, spec first, filed
      in `commons` as BODY-VOCAB-01). Objective:
      `spec/vocab/capabilities.json` gains the ids a body profile
      declares (section 2): `head_6dof`, `head_pan_tilt`, `roll`,
      `antennas`, `body_yaw`, `eyes`, `mouth`, `light_ring`, `doa`,
      `state_feed`, `encoders`, `touch`, `distance`, `imu`,
      `battery_readout`, `physical_mute`, `camera_shutter`,
      `moves_recorded`, plus the speech placement `speech_pod` and
      `speech_robot`; a `Device.capabilities` fixture for a Reachy Mini
      row and one for the MaiPai build. Mirror: CAP-VOCAB-01 in
      `commons/docs/BACKLOG.md`. Acceptance: both fixtures validate in
      TypeScript and Python; the tag is bumped and `bot` pins it.
      Out of scope: any renderer. Exit: `commons` `bash
      scripts/check.sh` and the tag.
- [x] **RM-01: the profile and the daemon client** (M, sim). Objective:
      `body/bodies/reachy_mini/` wraps the `reachy-mini` SDK (PyPI,
      Apache-2.0) behind the HAL seam BODY-02 names, declaring the
      profile (section 2) from RM-00's ids: the state feed from
      `ws://…/api/state/ws/full` as the encoder stand-in, `goto_target`
      and `set_target` as the actuator, `get_DoA`, the audio sample
      calls, `get_frame`, the IMU, motors enable and disable; a fake
      built from responses recorded against the simulator, passing the
      same pytest suite as the live run. If BODY-02 has not declared
      the seam yet, this item declares it with this profile as its
      first implementation and BODY-02 becomes its second. Pointers:
      `body/hal/` (BODY-02), the daemon's `/openapi.json`. Acceptance:
      the suite green on the fake and on the simulator; the profile's
      declaration is the one place the axes and limits are named;
      `scripts/check.sh` runs the body block. Out of scope: expression,
      speech. Exit: `bash scripts/check.sh` and the simulator run.
      Verified at this commit: `bash scripts/check.sh` green (the body
      block runs Ruff, `ruff format --check` and the deterministic
      pytest suite); the full suite (15 tests) also run and passed live
      against `reachy-mini-daemon` 1.11.0 in `--sim --headless` mode
      with `MAIPAI_BODY_LIVE=1`, including a real goto-then-hold trace
      recorded into `fixtures/state_frames.jsonl` and a real connection
      loss (closing the daemon socket underneath a live client) proving
      `BodyLost`. Not run: anything needing the physical unit (up to 90
      days out per the design record).
- [ ] **RM-02: the expression column on the simulator** (M, sim, with
      EXPR-01). Objective: the primitive table's Reachy Mini column
      (section 5: roll for the tilt, the antennas as a channel, body
      yaw following the head past the delta limit, the `speak` sway on
      the playback ledger's audio envelope, the muted pose) rendered by
      EXPR-01's package on this profile, with the envelope as fractions
      of the daemon's declared limits written into device-scope
      settings with the run's date, `minjerk` for the primitives,
      `set_target` only for track, breathe, speak and stop. Acceptance:
      every primitive renders from its cue in the deterministic test
      with the fake; the suppression table holds; M-R2's simulator rows
      (cue to first state-feed delta, amplitude, peak velocity, settling
      time per primitive) recorded. Out of scope: the unit's numbers.
      Exit: `bash scripts/check.sh` and the recorded rows.
      **Not fully landed**, box stays unchecked: body yaw does not yet
      follow the head past the 65-degree delta limit (that is a
      tracking-loop behavior, EXPR-04's, not one primitive's own
      render). "Device-scope settings" is a Python dict
      (`expression/envelope.py`) with a source and date, the same shape
      as `profile.py`'s axes, since no settings store exists in this
      repo yet. Landed and verified: every other primitive (listen,
      glance, tilt, nod, perk, attend, settle, breathe, track, speak,
      stop) renders on this profile through the HAL seam, `minjerk` for
      the goto-driven primitives, `set_target` for exactly
      track/breathe/speak/stop; M-R2's rows recorded in
      `docs/dev/measurements.md` from a real run against
      `reachy-mini-daemon` 1.11.0.
      **2026-09-27 addition: the muted pose, corrected by a same-day
      audit.** A first cut rendered the muted pose from cue suppression
      (every suppressed `listen`/`breathe` cue re-rendered it), which a
      Fable-model audit caught as wrong on three counts: it fought the
      design's own contract ("muted is a state, not a cue-driven
      primitive," `primitives.py`), it never consulted
      `presence/arbitration.py` so it fought the daemon's own tracker
      every tick once EXPR-04's idle loop exists, and there was no
      unmute transition. `ExpressionEngine.set_muted(muted, arbitration)`
      replaces that: edge-triggered (renders once per state change, a
      repeat call is a no-op), gated by `expression_may_drive()`, and
      renders `settle` on the falling edge. `handle()` went back to
      plain `rendered=False` suppression. Antennas fully down is 0.30
      of range (`envelope.py`'s new `"muted"` row), not the daemon's
      full range - deliberately conservative per section 7's "no
      full-range excursions" (this body has no near-hand sensor).
      `stop` still always renders normally regardless (its suppression
      reason is always `None`; see 2026-09-27's second addition below).
      Tested against the fake; not yet run against a live daemon.
- [x] **RM-03: the app packaging and the install scripts** (S, sim).
      Objective: `maipai-bot` as a Python package exposing
      `MaiPaiBody(ReachyMiniApp)` under the `reachy_mini_apps`
      entry-point group, scaffolded with `reachy-mini-app-assistant`
      and run by the daemon as its app (section 3); `scripts/
      install-reachy.sh` performing the documented offline install
      over SSH (copy the wheel, `pip install` into `/venvs/apps_venv/`,
      register, remove the vendor apps, restart `reachy-mini-daemon`),
      and `scripts/build-space.sh` producing the Hugging Face Space
      layout (tag `reachy_mini_python_app`) from a release, never
      pushed by the script. Acceptance: the daemon's app list shows the
      app on the simulator and starts and stops it cleanly (SIGINT
      handled, the stop event honored); the install script is
      idempotent. Out of scope: the password rotation (RM-08, a hub
      flow). Exit: `bash scripts/check.sh` and the simulator run.
      **2026-09-27 addition: vendor-app removal, with a post-condition
      added the same day by an audit.** `install-reachy.sh` now removes
      every installed app except `maipai_bot` between registering the
      startup app and restarting the daemon, over the daemon's own
      `/api/apps` job API (`list-available/installed`, `remove/{name}`,
      polled via `job-status/{job_id}`) - the earlier plan to guess
      vendor entry-point names was dropped in favor of enumerating
      whatever the daemon actually reports installed, so nothing needs
      guessing. A Fable-model audit found the daemon's own "done" status
      proves nothing: `pip` and `uv` both exit 0 with a "not installed"
      warning when the entry-point name doesn't match the actual
      distribution name, which is exactly the mismatch our own app has
      (`maipai_bot` the entry point, `maipai-body` the distribution at
      the time - fixed separately as G12 below, which renamed the
      distribution to `maipai-bot`). The script now re-lists installed apps after
      the loop and fails if anything but `maipai_bot` remains, instead
      of trusting the job status. Verified against a stand-in HTTP
      server built from `reachy_mini/daemon/app/routers/apps.py`'s own
      request and response shapes (read directly from the installed
      `reachy-mini` 1.11.0 package, not assumed): confirms `maipai_bot`
      is excluded, every other installed app is removed, a failed
      removal job fails the script, and a job that reports "done" while
      the app is still listed also fails the script. Not yet run against a live or
      simulated daemon (none was reachable this session), so the actual
      HTTP calls over a real SSH session remain unverified end to end -
      the next simulator run should exercise this step for real before
      it goes anywhere near a physical unit.
      Verified at this commit: `bash scripts/check.sh` green; live
      against `reachy-mini-daemon` 1.11.0 (`--sim --headless`) with
      `maipai-body` installed into its own venv, `POST
      /api/apps/start-app/maipai_bot` moved the app to `running`
      (confirmed by `/api/state/full` showing a near-neutral held
      pose), and `POST /api/apps/stop-current-app` stopped it cleanly
      in about a second, released the robot-app lock, and the daemon
      returned the robot to its zero position on its own. Finding worth
      recording: the daemon starts an installed app by running its
      entry point's *module* as `python -m <module>` in a subprocess,
      never by importing the class directly, so `app.py` needs its own
      `if __name__ == "__main__":` block (the first live start finished
      instantly with no error because that block was missing). Not run:
      `scripts/install-reachy.sh` against a real unit or a live daemon
      (none reachable; the SSH steps are syntax-checked and its argument
      validation is tested, not the scp/ssh/systemctl calls themselves -
      see the 2026-09-27 addition above for the vendor-app-removal
      step's own verification level).
- [ ] **RM-04: the `pod`-tier speech path** (M, sim then unit, after
      ROBOT-ROUTES-01). Objective: wake, Silero VAD, endpointing and
      direction of arrival in the body from the daemon's 16 kHz audio,
      the pre-roll and wake-patience fixes of VOICE-01; the endpointed
      utterance (wake word to end of speech, nothing before) to the
      hub's `stt` route; the hub's `tts` stream to the daemon's
      speaker with the same chunked playback the browser uses; barge-in
      through the chip's echo cancellation; the honest software mute.
      Pointers: `body/speech/` (VOICE-01), home's `stt` and `tts`
      routes and `streamingWavPlayer.ts` for the chunk handling.
      Acceptance: a spoken question on the simulator's software echo
      path round-trips to a spoken reply; "stop" over playback is heard;
      nothing ambient leaves the body (a test asserts the bytes sent are
      the endpointed span). Out of scope: the `robot` tier (M-R1
      decides). Exit: `bash scripts/check.sh` and the round trip.
- [ ] **RM-05: the hub client** (M, sim, after ROBOT-DEVICE-01 and
      ROBOT-ROUTES-01). Objective: pairing by the spoken code and the
      app's own page (section 9), the token sealed and the fingerprint
      pinned, the link states; the turn stream with `surface: robot`,
      `speaker_evidence` and `present`; the `signal` and `cancel`
      events driving EXPR-01's package (the `plan` event when it
      exists), scripted cues on the bench before; the device state
      frame (activity, muted, tracking, on battery) for ROBOT-CARD-01;
      the one register-guard line when the hub is unreachable and
      silence about a hub it was never paired with. Acceptance: a
      three-turn conversation on the simulator with cues rendered
      before the first audio sample on eligible rows; M-R5's link-loss
      rows behave as section 7 says. Out of scope: the oplog and the
      replica (no runtime on this body). Exit: `bash scripts/check.sh`
      and the simulator run.
      **Implementation landed across G4** (pairing, the sealed token,
      the link states) **and G9** (the turn stream driving cues through
      the real run loop, deterministic tests proving cue order before
      the first audio sample). Box stays unchecked: this item's own
      acceptance is a live simulator run of a three-turn conversation,
      not exercised yet - see G9's own entry above for what's built and
      what a live run would still need (a combined stand-in, or a real
      `reachy-mini-daemon --sim` session). The device state frame for
      ROBOT-CARD-01 is G10's own item, not started.
- [x] **RM-06: presence and tracking** (S, sim, after RM-01).
      Objective: the daemon's face tracking as the `track` source under
      the arbitration priority, its "a face is tracked" fact plus the
      array's direction of arrival and speech flag as the presence
      funnel's observations (BODY-05's funnel, this body's inputs), the
      IMU's tip and freefall observations. Acceptance: the funnel's
      state tests on the fake; tracking yields to expression and stop.
      Out of scope: identity. Exit: `bash scripts/check.sh`.
      **This item's own acceptance line has the priority backwards**
      from the design record section 6 it names as its source
      ("consented tracking sits below inhibit, reflex and service,
      above expression and idle"): tracking outranks expression and
      only yields to a stop or service condition, the opposite of
      "tracking yields to expression." Implemented and tested against
      the corrected, sourced reading
      (`body/maipai_body/presence/arbitration.py`). Landed and
      verified: the HAL seam's `FaceTracker` protocol
      (`enable_tracking`/`disable_tracking`/`get_face_target`), the
      arbitration priority with tests for every ranking, and tip and
      freefall detection from the IMU (design-default thresholds, not
      a validated safety limit, same framing as `expression/
      envelope.py`); exercised live against `reachy-mini-daemon`
      1.11.0, which honestly reports no face, no IMU and no direction
      of arrival in this sim scene, so only the mechanism (no crash, a
      well-typed absence) was proven live, not a real detection.
      **Box checked 2026-09-28:** the one thing that kept it open -
      "BODY-05's own funnel... needs a turn-aware runtime to mean
      anything and does not exist" - is no longer true. G9 built that
      funnel (`ConversationLoop`, `idle`/`listening`/`thinking`/
      `speaking`) and wired these exact observations into it
      (`_presence_loop()`), with tests proving tracking engages with a
      face present and disengages while speaking, matching the
      corrected priority above. Live detection against a real face
      still waits on a sim scene (or unit) that actually has one to
      detect, same caveat as before.
- [ ] **RM-07: privacy on the unit** (S, unit, first day). Objective:
      the unit on an isolated network with every outbound connection
      captured for 24 hours before and after the MaiPai install, the
      vendor's apps removed and the store token never set; the list on
      the robot's privacy page (SETUP-04's page, this body's rows) and
      in `measurements.md`; the "what leaves the robot" table in the
      design's section 8 words. Acceptance: the capture recorded; the
      page's rows match it; the software mute and camera-off are
      labelled so. Out of scope: fixing the vendor's image. Exit: the
      recorded capture and the page.
- [ ] **RM-08: install and update from Home** (M, unit, after
      ROBOT-DEVICE-01 and ROBOT-CARD-01). Objective: the Devices page's
      add flow runs RM-03's offline install over SSH and rotates the
      default password into the credentials center (refusing to finish
      while it stands); Bot's release pushes the wheel the same way;
      the daemon's PyPI update surfaced as a row and applied only on a
      click. Mirror: UPDATES.md; CREDENTIALS.md. Acceptance: a fresh
      unit joins Home with no terminal and no third-party account; the
      daemon version appears on the card and in the update row. Out of
      scope: the Space listing (owner's call). Exit: the flow exercised
      on the unit and its captures.
- [x] **G10-BODY: push the robot.state frame to the hub** (S, design
      resolved 2026-09-29 by design-resolver, unblocking `home`'s
      ROBOT-CARD-01). Objective: `body/maipai_body/link/state.py`'s
      `StateReporter`, modelled directly on `link/prints.py`'s
      `PrintSync` (same `hub_credentials`/`stop_event`/`requests.Session`
      constructor shape) - pushes `PUT /api/devices/me/state`
      (`commons/spec/schemas/robot-state.schema.json`: `activity`
      including a `starting` value for the pre-conversation-loop window,
      `muted`, `tracking`, `on_battery`/`battery_level` nullable-unknown
      for this body per design §7, `daemon_version`) on every change and
      a 15s heartbeat otherwise. `ConversationLoop` gains an `on_change`
      callback fired from `_enter()`, `set_muted()`, and the tracking
      edge in `_presence_loop()`, setting a `threading.Event` the
      reporter thread wakes on. Started in `run_paired_body` as soon as
      pairing is confirmed, before the conversation-loop build, so
      `starting` is reportable during the (potentially minutes-long)
      first-boot model download - not after, or the card would wrongly
      read "unreachable" the whole time. On a send failure: log and wait
      for the next wake, never retry-loop; a rotated cookie is picked up
      naturally on the next send via the existing `hub_credentials`
      reader. Full reasoning: `home`'s `docs/dev.md`, "Robot device
      state" (2026-09-29). Mirror: `link/prints.py` and its tests
      exactly. Acceptance: a stand-in HTTP server receives a frame on
      each funnel transition of a scripted turn; a heartbeat fires after
      15s idle (an injected interval in the test, not a real 15s wait);
      `starting` is sent before the loop exists; a rotated cookie is
      picked up on the next send; no crash or busy-loop on a connection
      refused or a 401. Out of scope: the mute command arriving FROM the
      hub (filed separately, `home`'s ROBOT-MUTE-01 - this item is
      report-only, robot to hub); `daemon_version` resolution if the
      SDK/daemon exposes nothing (send `null`, file a follow-up). Depends
      on `home`'s own hub-half route landing first (or a fake for local
      testing) and `commons/spec`'s `robot-state.schema.json`. Exit:
      `bash scripts/check.sh`. Landed 2026-09-29: the body pushes state
      on changes and a 15s heartbeat; Reachy Mini reports SDK version
      `1.11.0` from `reachy_mini.__version__`.
- [x] **G10-VERSION: the robot sends `app_version`** (S, after
      `commons` spec-v0.1.57). `state_snapshot()` in
      `body/maipai_body/app.py` sends the installed `maipai-bot`
      version (`importlib.metadata`, `null` when not installed) as
      `app_version` in both the first `starting` frame and every later
      frame, beside `daemon_version`, which stays the vendor SDK's
      version. The hub compares `app_version` to a `getmaipai/bot`
      release. Bot does not pin `maipai-spec` (see `AGENTS.md`), so
      there is no pin to bump; the schema-fit test runs when
      `MAIPAI_ROBOT_STATE_SCHEMA` points at commons'
      `spec/schemas/robot-state.schema.json`. Landed 2026-09-29.
- [ ] **RM-09: the user guide** (S, with RM-08). Objective: the
      user-tier page from the box to the first conversation (the
      vendor's Wi-Fi setup, Add a robot in Home, the spoken code, what
      the antennas mean, the honest limits: software mute, software
      camera-off, no battery readout, no screen), with generated
      screenshots of the Devices flow. Mirror: DOCS-02. Acceptance: the
      dad test on the page; every screenshot opened and judged. Exit:
      the standards core.
- [ ] **MOVES-01: the recorded moves package** (S, after RM-02, after
      v0.1). Objective: a catalog package (`platforms: [bot]`, category
      Robot body, `requires: ["moves_recorded"]`) that fetches Pollen's
      emotions library (Apache-2.0) and dances library (licence
      unverified; excluded until stated) on demand at a pinned revision
      with a checksum, never vendored, and plays a named move through
      the body at the plan's `react` slot or on a person's ask, never
      on sentiment. Mirror: the org's "download, don't vendor" rule;
      a Tier 0 package's manifest. Acceptance: "do the happy dance"
      plays the move through the body (proven on the fake body and the
      MuJoCo simulator only; not verified on a physical unit); the
      reply path's cues are untouched (a test asserts no move plays
      from a cue). Exit: the
      catalog's CI and `bash scripts/check.sh`.
      Status 2026-10-05: body side built in `body/maipai_body/moves/` (format, pinned fetch, player, ask and react entry points, tests); box stays unchecked until `scripts/pin_moves_library.py` has pinned the emotions library with network, the simulator run is done, and the catalog manifest exists.
      Needs the unit: run `cd body && MAIPAI_BODY_LIVE=1 uv run pytest tests/test_moves_live.py -v` with the robot's daemon answering on port 8000 (the simulator, `reachy-mini-daemon --sim`, is what has been run so far); the move's physical motion is judged by eye on the unit.
      Status 2026-10-05 (S-MOVES-FINISH): the pin is NOT done. `body/scripts/pin_moves_library.py` was run twice from the cloud sandbox and both runs failed at the first request, `huggingface.co:443` refused by the sandbox's egress proxy (CONNECT 403, organization policy). `pins.json` stays `{"pins": []}`; no checksum was invented. An admin runs it from a machine that reaches huggingface.co and commits the diff.
      Simulator run 2026-10-05: `reachy-mini-daemon --sim --headless` (reachy-mini 1.11.0, MuJoCo 3.3.0) answered on port 8000, but this sandbox's daemon cannot start its media server (no GStreamer webrtc rust plugin), so `ReachyMini()` with the default media backend fails on port 8443 and `MAIPAI_BODY_LIVE=1 pytest tests/test_moves_live.py` errors in fixture setup, not in a test. The same two tests, `test_moves_live.py::test_do_the_happy_dance_plays_the_move_on_the_body` and `test_moves_teach.py::test_a_taught_move_replays_through_the_player_within_the_envelope`, were then run against the same simulator with `ReachyMini(media_backend="no_media")` injected into `ReachyMiniClient`, and both passed (the daemon accepted the whole stream; nothing was read back from the state feed, and the physical motion was not looked at). Not run: the `body_client[live]` fixture itself, because the sandbox cannot run the daemon's media server.
      React entry point 2026-10-05: `moves/react.py` is the hook for the plan's `react` slot, behind the `MAIPAI_BOT_REACT_MOVES` flag (off unless set to 1, true, yes or on). `ConversationLoop` takes an optional `react_hook` and calls it after the reply is spoken with the move name from `TurnEvent.react_move` and the plan cue's `react_allowed`; a failing hook is logged and never costs the turn. The turn stream carries no move name on the wire yet, so the real client never sets `react_move` and the hook is dormant until the hub sends one (a Home-side shape, not decided here). Tests: `body/tests/test_moves_react.py`.
      Outbound connection (org rules: Download, don't vendor; Privacy: no connection added without review). What: the emotions library's move files (JSON). From where: huggingface.co, a public dataset, no account or token. When: only when an admin runs `body/scripts/pin_moves_library.py` or installs the package; never at runtime without that. What is sent: an ordinary file request (URL and standard HTTP headers), no household data. Every file is pinned by full commit revision and sha256 checksum before use: `ensure_move` refuses an unpinned or checksum-mismatched file (tests in `body/tests/test_moves.py`).
- [ ] **MOVES-02: teach it a move** (S, after MOVES-01). Objective: a
      catalog app: gravity compensation on, a person moves the head
      and antennas by hand, the body records the trajectory in the
      vendor's move JSON shape, names it, replays it; offline, no
      model. Acceptance: a recorded move replays on the simulator
      within the envelope. Exit: the catalog's CI.
      Status 2026-10-05: body side built, tests first
      (`body/tests/test_moves_teach.py`). The seam gains `Teachable`
      (gravity compensation on and off, plus the state feed);
      `moves/recorder.py` writes the vendor's move JSON, refusing a
      recording outside the envelope rather than clipping it;
      `moves/store.py` keeps one slug-named file per move on this device
      and never shadows a library name; `moves/teach.py` turns gravity
      compensation on only for the recording, always off after, then
      holds the pose; replay is MOVES-01's `MovePlayer`, and "do my
      wave" goes through `MovesService`. Not built: a spoken "teach you
      a move" trigger and the catalog manifest (no catalog host in this
      repo yet); the box stays unchecked. The simulator has no hand, so
      its run replays a scripted trajectory.
      Needs the unit: `cd body && MAIPAI_BODY_UNIT=1 MAIPAI_UNIT_HOST=<robot> uv run pytest tests/test_moves_teach_unit.py -v -s`,
      or interactively `uv run python scripts/teach_move_live.py wave --seconds 8 --host <robot>`.
      Whether gravity compensation holds the head up without drift, how
      faithfully the replay follows the hand, and the state feed rate
      actually reached at 50 Hz are all unmeasured and judged on the unit.
      UNVERIFIED until that unit run: the client calls SDK methods
      `enable_gravity_compensation` and `disable_gravity_compensation`,
      which the pinned OpenAPI fixture does not confirm; the fake and
      simulator only record the requested state.
      SDK names checked 2026-10-05: `enable_gravity_compensation` and `disable_gravity_compensation` exist in reachy-mini 1.11.0, at `reachy_mini/reachy_mini.py` lines 1088 and 1092 of the wheel, each sending `SetGravityCompensationCmd(enabled=True|False)` to the daemon. The names are confirmed; what the daemon does with the command under MuJoCo (whether the simulated head holds its pose, drifts or ignores it) stays UNVERIFIED, and so does the behavior on a physical unit.
      Outbound connection: none. Taught moves are written and read on this
      device only; the modules import no network library (a test asserts it).
- [ ] **GUEST-01: a store app as a guest** (M, after v0.1; the design's
      section 11). Objective: a catalog package of kind `app` wrapping
      a Hugging Face Space at a pinned revision with its `data_sources`
      and `permissions` declared and the supply-chain gate passed; Home
      launches it, the body stops itself, the daemon starts the guest,
      and MaiPai restarts when the guest exits or Home says stop; the
      card says wake, stop and the safety floor are unavailable for the
      duration. Acceptance: one reviewed community app (no cloud model,
      no store token) runs and yields on the simulator. Exit: the
      catalog's CI and `bash scripts/check.sh`.
- [ ] **M-R1: the Compute Module budget** (S, unit). The daemon alone;
      with the `pod`-tier body; with `stt` and `tts` on the robot: RSS,
      CPU, temperature and throttle flags over an hour with a turn
      every two minutes. Decision rule in section 12: the `robot` tier
      only if endpoint-to-transcript p95 is under M-06's figure plus
      500 ms and nothing throttles.
      Status 2026-10-05: script, sampler and decision rule built and proven on fakes
      (`body/scripts/measure_mr1_budget.py`, `dev/measure-runbook.md`); needs the unit.
- [ ] **M-R2: cue to motion** (S, sim then unit). Cue to first
      state-feed delta p50 and p95 per primitive; the stall behaviour
      under a held head at each fraction; amplitude, peak velocity and
      settling time against the declared limits.
      Status 2026-10-05: sim rows recorded in `dev/measurements.md` (p50 and p95, stall
      reference); the unit run and the held-head rows need the unit.
- [ ] **M-R3: wake and direction of arrival on this array** (S, unit).
      False accepts per hour and recall at section 6's ear gates on the
      daemon's 16 kHz path; bearing error at eight angles; barge-in
      through the chip's echo cancellation at conversation level.
      Status 2026-10-05: script, bearing maths and the M-08 gates built and proven on
      scripted audio (`dev/measure-runbook.md`); needs the unit.
- [ ] **M-R4: battery** (S, unit). Runtime idle, in conversation, and
      with tracking, by the clock to the LED's red; whether any
      readable fact exists; whether it runs while charging. The card
      says "battery level unknown" until this row exists.
      Status 2026-10-05: probe, crash-safe heartbeat log and report built and proven on
      fakes (`dev/measure-runbook.md`); needs the unit.
- [ ] **M-R5: the link** (S, sim then unit). Wi-Fi loss mid-turn and
      mid-sentence: `cancel` raised, the pose settled, the one line on
      reconnect; reconnection p50 and p95.
      Status 2026-10-05: sim rows recorded in `dev/measurements.md`, with the loop fixed to
      cancel once and say the line once; the radio and the Compute Module need the unit.
- [ ] **M-R6: the household runtime on the Compute Module** (M, unit,
      after v0.1, after RT-01). Bun, the pinned runtime, the embed model
      and MiniCPM5-1B at Q4_K_M beside the daemon and the `pod`-tier
      body on 4 GB: boots or not, first delta p95 with the prefix
      cached, the hard rows. M-02's decision rule. A pass opens a
      paired-unreachable mode for this body as its own design
      amendment; a fail is recorded and the product table's wording
      stands.
- [x] **G12: packaging for the unit** (S, filed and landed 2026-09-27
      by a Fable-model audit, `docs/dev/reachy-mini-gap-audit-2026-09-27.md`).
      Objective: `body/pyproject.toml` pinned `reachy-mini[mujoco]`,
      pulling the multi-hundred-MB simulator onto the robot for no
      reason (already flagged as a known gap in `install-reachy.sh`'s
      own header); the entry point (`maipai_bot`) and the distribution
      name (`maipai-body`) disagreed, which the same audit's 1.3 found
      makes the daemon's own remove/update silently no-op against our
      own app the way it can against a mismatched vendor app. Landed:
      `mujoco` moved to an opt-in `sim` extra (`uv sync --extra sim` for
      the bench; a bare `uv sync` or the robot's own `pip install` of
      the wheel pulls neither mujoco nor its native deps - verified,
      `uv sync` uninstalls six packages going from the old pin to the
      base); the distribution renamed to `maipai-bot` (the design
      record's own section 3 already named it this), verified by a real
      `uv build --wheel` producing `maipai_bot-0.1.0-py3-none-any.whl`
      still exporting the unchanged `maipai_body` import path inside it.
      Acceptance: `uv build --wheel` from a clean state, `import
      maipai_body.app` from the built wheel, no mujoco in the base
      dependency set - all verified on the dev Mac. Not verified here:
      `pip install` of that wheel in a fresh Linux aarch64 venv (no
      container runtime in this environment); the wheel is pure-Python
      with no platform-specific code, so this is a low-risk gap, not a
      guess dressed up as done.
      **2026-10-05 S-RM08-BOT / S-G12-AARCH64:** added
      `scripts/prepare-bot-release.sh <tag>` to build the version-matched
      `maipai_bot-<v>-py3-none-any.whl`, write a SHA-256 sidecar, and
      stage both under `dist/bot-release/<tag>` for an owner-created Bot
      release. It never creates or uploads a release. Added
      `install-reachy.sh --dry-run <host> <wheel>` to print the scp and
      SSH plan, including package install, daemon startup registration,
      vendor-app removal, restart, and cleanup. Dry-run has no SSH
      effects and does not require the wheel to exist. Stand-in daemon
      test suite reused to cover the existing daemon install/registry
      route behavior; release and dry-run tests added. Aarch64 compile
      attempted for base and voice on macOS; uv cannot build the
      transitive pygobject/pycairo because Cairo and pkg-config are
      unavailable. The direct dependency probe resolved without
      transitive dependencies but did not prove
      `onnxruntime==1.30.0`; `uv sync --extra voice` on the dev Mac did
      resolve `onnxruntime==1.30.0`. Full aarch64 compile result remains
      unverified.
- [x] **G1: audio capture and playback through the daemon's media path**
      (S-M, filed and landed 2026-09-28,
      `docs/dev/reachy-mini-gap-audit-2026-09-27.md`). Objective: the
      seam's `AudioIO` protocol (`hal/seam.py`) and the client's
      pass-throughs existed typed `object`, with no consumer and no
      `start_recording`/`start_playing`/`stop_*` calls at all - real,
      verified vendor facts (`reachy.media.start_recording()` first,
      `get_audio_sample()` returns float32 `(n, 2)` at 16 kHz or `None`,
      `push_audio_sample()`/`start_playing()`/`stop_playing()` for
      output, all read in the installed 1.11.0 package). Landed: the
      seam typed properly (`npt.NDArray[np.float32]`, the four new
      start/stop calls, `get_input_audio_samplerate`/
      `get_output_audio_samplerate`), both implemented on the real
      client and the fake (a WAV fixture stands in for the microphone,
      chunked like a real gstreamer appsink rather than handed back
      whole); `body/maipai_body/speech/` (`AudioCapture` downmixes to
      mono channel 0 and re-chunks into fixed 32 ms/512-sample blocks
      with a 0.3 s pre-roll ring; `AudioPlayback` opens the output
      stream once and keeps a ledger of what was pushed, for G8's own
      barge-in to read later). Deterministic: 12 tests, including the
      audit's own numbers (a synthetic 3 s 16 kHz WAV yields exactly 93
      full 512-sample blocks, the pre-roll ring holds exactly 0.3 s).
      Live, against `reachy-mini-daemon` 1.11.0 (`--sim --headless`,
      `MUJOCO_GL=cgl`): a 5 s capture wrote a real 16 kHz mono WAV (3.46
      s of it had audio actually queued - a real timing fact, not a
      bug, confirmed by the deterministic suite's exact-count tests
      passing against synthetic data); a pushed 1 kHz tone reached
      `push_audio_sample` with no exception and no underrun/xrun
      warning anywhere in the daemon log.
      **Finding worth its own record:** this dev Mac's cached Hugging
      Face token (`~/.cache/huggingface/token`) does not just turn on
      the central relay (the already-documented privacy finding,
      `docs/user/reachy-mini-privacy.md`) - it broke the connection
      outright the first several attempts, `KeyError: 'Producer
      reachymini not found.'` from
      `reachy_mini/media/webrtc_utils.py`'s `find_producer_peer_id_by_name`,
      inside `MediaManager._init_webrtc()`, which the vendor SDK calls
      during `ReachyMini.__init__` regardless of `connection_mode`
      (`localhost_only` did not avoid it). Moving the token aside and
      restarting the daemon ("No HF token found, central signaling
      relay disabled") fixed it immediately and reproducibly. Recorded
      for RM-07's first-day capture and for anyone else's dev bench:
      **a cached Hugging Face token can silently break local audio on
      this SDK version**, not just add an unwanted outbound connection.
      `/code-review low` (one pass) caught three real defects before
      commit, all fixed: `AudioPlayback.stop()` was clearing the ledger
      G8's barge-in needs to read right after calling `stop()`, now
      cleared on the next `start()` instead; `poll_blocks()` called
      `get_audio_sample()` once per call despite its own docstring
      saying "drains," now loops until the client returns `None` so a
      slow-polling caller can't fall behind the daemon's queue; the
      pre-roll ring's `round()` sizing gave 0.288 s at 16 kHz, not the
      0.3 s this entry claims, now `math.ceil()` so it's never short.
      Disclosed, not fixed: the fake's fixture, once exhausted, returns
      `None` indistinguishable from a live mic's idle `None` - fine for
      a fixture sized to its test's own polling window, a footgun for
      one that isn't.
      A second `/code-review medium` pass (parallel session, same commit's
      diff) caught six more before this follow-up: `test_hal_seam.py`'s
      own `AudioIO` completeness list still named the pre-G1 three
      methods, silently no longer guarding the six new ones; `poll_blocks()`
      re-concatenated the whole growing buffer on every loop iteration
      (`O(n^2)` against a real queue backlog), now collected into a list
      and concatenated once; `BLOCK_SAMPLES` was a fixed 512 despite the
      seam's own "never assume 16 kHz" docstring, now derived from
      `get_input_audio_samplerate()` in `start()`; `AudioCapture.start()`/
      `stop()` had no idempotency guard unlike `AudioPlayback`'s, so a
      stray second `start()` mid-recording silently dropped the pre-roll
      ring; the fake's replay-from-start semantics on a second
      `start_recording()` were undocumented, now a docstring says why;
      three tests reached into the fake's private `_mic_cursor`/
      `_mic_samples` for loop control instead of asserting on
      `poll_blocks()`'s own public return, now fixed. Re-reviewed clean.
      A third `/code-review low` pass, on that follow-up's own diff, caught
      two more low-severity edge cases in the same `start()`: deriving
      `_block_samples` from `get_input_audio_samplerate()` with no floor
      meant a vendor call returning `0` would size to a non-positive block
      count and raise `ZeroDivisionError` on every subsequent `poll_blocks()`
      instead of failing where the bad value actually came from, now a
      `ValueError` raised in `start()` itself; `_recording` was set `True`
      before sizing was known to succeed, so a `get_input_audio_samplerate()`
      exception would leave a retried `start()` silently swallowed by the
      idempotency guard with sizing never completed, now `_recording` flips
      only after sizing succeeds. Both new tests, one proving the raise, one
      (already added) proving idempotency doesn't discard the pre-roll ring.
- [x] **G2: wake word on the robot** (M, `docs/dev/reachy-mini-gap-audit-2026-09-27.md`,
      `docs/dev/wakeword-community-research-2026-09-28.md`). Objective:
      score G1's capture blocks against MaiPai's own trained "hey maipai"
      detector, fire once per phrase, capture DoA at the wake instant.
      Landed: `body/maipai_body/speech/wake.py` (`WakeEngine` Protocol,
      `WakeScorer` driving it over G1 blocks with `WAKE_THRESHOLD = 0.8`,
      `OpenWakeWordEngine` wrapping openWakeWord's own `Model` class
      directly - not a hand-rolled mel-spectrogram/embedding pipeline,
      matching what the legacy driver already did and for the same
      reason, avoiding a heavier dependency footprint than needed);
      `body/maipai_body/speech/models.py` (the pinned-URL/checksum
      on-demand fetcher, the two shared openWakeWord front-end assets
      real and fetchable, ported from `home`'s own `wakewordAssets.ts`
      pattern with corrected checksums - see below); `[project.optional-
      dependencies] voice` in `body/pyproject.toml` (`openwakeword`,
      opt-in like `sim`, not a base dependency). 19 deterministic tests:
      the scorer's threshold/reset/DoA-capture logic against a scripted
      fake engine (no model needed), the fetcher's download/checksum/
      caching logic against a real local HTTP server. Gated, not part of
      the always-on suite (real binary model files, never tracked):
      `MAIPAI_WAKEWORD_MODELS_DIR`/`MAIPAI_WAKEWORD_FIXTURES_DIR`-driven
      tests verified locally against the actual extracted
      `trained_hey_maipai_v2.onnx` (from `legacy-backups/home-legacy.git`)
      and the real openWakeWord front-end - a synthetic "hey maipai"
      sample scored 0.94 (threshold 0.8), a synthetic "hey my car" scored
      0.05, and `reset()` was proven to actually clear the model's own
      rolling window (0.94 on silence right after a wake without it, 0.0
      with it).
      **Acceptance correction, verified against real data, not guessed:**
      the audit's own acceptance named "hey my bike" as the near-miss
      fixture; `home` issue #5 (closed, real-speech bench table) shows
      the trained v2 model reliably false-fires on that exact phrase
      ("MaiPai" is phonetically "my pie," a permanent, untrainable
      collision) - so the real near-miss test uses "hey my car" instead
      (v2 cleanly rejects it on both real speech and this session's own
      synthetic sample), and "hey my bike" is documented, not chased, in
      `wake.py`'s own `WAKE_THRESHOLD` docstring.
      **A silent, version-specific bug found and fixed:** `reachy-mini==
      1.11.0` hard-pins `onnxruntime==1.27.0`, which was verified on this
      machine to silently mis-score every wake-word inference (near-zero
      on a clear wake sample, no error) while `1.30.0` scores the same
      files correctly. Verified before overriding it, not just forced:
      `reachy-mini`'s own bundled kinematics models (`fknetwork.onnx`,
      `iknetwork.onnx`) produce byte-identical output under both
      versions, so the exact pin isn't a real behavioral dependency for
      motion - `[tool.uv] override-dependencies = ["onnxruntime==1.30.0"]`
      forces the version proven to work, with the reasoning and the one
      unverified residual (`reachy_mini/vision/face_detector.py`'s own
      model, no consumer built yet) recorded in `pyproject.toml`'s own
      comment. Both onnxruntime wheels and openwakeword's pure-Python
      wheel confirmed available for aarch64 Linux (the robot's real
      target), satisfying the audit's own (b).
      **A separate bug found and filed, not fixed here:** every checksum
      in `home`'s own `wakewordAssets.ts` is one hex character short of
      a valid sha256, so its own wake-word downloads can never pass
      verification - filed as
      [home#185](https://github.com/getmaipai/home/issues/185), fixed
      with freshly recomputed values in this repo's own `models.py`.
      **Shipped the org's way (2026-09-28, Jesse's word):** `v0.1.0`
      cut, `trained_hey_maipai_v2.onnx` attached as a release asset,
      round-tripped (uploaded, downloaded back, checksum matched
      exactly). Its download URL 404s for an anonymous request against
      a private repo - a real robot has no GitHub credentials and
      shouldn't need any - so `bot` was made public (Jesse's call, after
      a full-history `gitleaks` and PII-wordlist scan came back clean on
      all 42 commits); the asset then fetches with a normal 302, exactly
      like openWakeWord's own public releases. `models.py`'s `WAKE_PHRASE`
      now carries the real URL and the same checksum computed
      before the release existed - a genuine chain of custody, not a
      re-trust of whatever got uploaded.
      **A critical bug found only by live-testing, not by any test in
      this repo:** the very "drain until `None`" loop a prior review
      added to `AudioCapture.poll_blocks()` (G1's own follow-up commit)
      hangs forever against a REAL continuously-recording microphone.
      The real appsink's own pull
      (`reachy_mini/media/gstreamer_utils.py`'s `get_sample()`) blocks up
      to a real 20 ms waiting for the next buffer; a live mic almost
      always has one within that window, so `None` essentially never
      happens while recording - the loop never exits, one 20 ms wait
      after another, and G2's live wake test hung indefinitely the
      moment `poll_blocks()` was called against the real simulator
      daemon instead of the finite fake. The fake's own fixture runs dry
      and legitimately returns `None` for a completely different reason
      (exhaustion, not backpressure), which is exactly why this passed
      every deterministic test and the gate, every time, and only broke
      the moment real hardware was in the loop. Fixed: `poll_blocks()`
      pulls exactly one buffer per call again (the original, actually-
      live-verified design), with the real appsink behavior recorded in
      its own docstring so a future review doesn't "fix" this the same
      wrong way twice. **This is why G2's own acceptance needed a real
      microphone, not just a gate:** after the fix, a genuine acoustic
      test (this dev Mac's own speaker playing a synthetic "hey maipai"
      clip, its own built-in mic capturing it through the real daemon's
      real pipeline, G1's real `AudioCapture` and G2's real `WakeScorer`
      end to end) fired exactly once at score 0.9346, DoA correctly
      `None` (this Mac has no real direction-of-arrival array to read).
      `/code-review medium` (one pass) caught three real defects, all
      fixed: the onnxruntime fix above was verified only against `uv
      sync` (the dev bench) - `scripts/install-reachy.sh` installs onto
      the real unit with plain `pip` over SSH, which never sees `[tool.uv]
      override-dependencies` (a uv-resolver-only directive, not wheel
      metadata) and would re-resolve straight back to reachy-mini's own
      broken `onnxruntime==1.27.0` pin, so the fix never reached
      production until this pass caught it; the script now installs with
      the `[voice]` extra and force-installs `onnxruntime==1.30.0`
      explicitly afterward, every run. `models.py`'s `ensure_asset` let a
      raw `requests` exception (offline, DNS failure) propagate
      unwrapped, against the org's own "clear failure message when
      offline" standard for third-party model fetches - now wrapped in
      `WakewordModelUnavailable` with a clear message, cleaning up the
      `.part` file first. The real-model test's own `_max_score_over`
      helper had an off-by-one (`range`'s stop was `len - block`, not
      `len - block + 1`), silently dropping the last complete block
      whenever a fixture's sample count was an exact multiple of the
      block size - exactly the block most likely to hold the peak score.
      Fixing the install script's own client-side variable expansion
      (`'$REMOTE_WHEEL[voice]'` needed braces, `'${REMOTE_WHEEL}[voice]'`
      - bash read the bare form as an array subscript and expanded to
      nothing, caught by `shellcheck`, not the review) was a second-order
      fix the review's own finding required to actually work.
- [x] **G4: the hub client on the robot - discovery, pairing, the
      sealed token** (M, `docs/dev/reachy-mini-gap-audit-2026-09-27.md`).
      Objective: browse `_maipai._tcp`, request a pairing code as kind
      `robot`, poll until approved, redeem for a session, seal the
      token, re-redeem on demand. Landed: `body/maipai_body/link/`
      (`discovery.py`: `_maipai._tcp` mDNS browse via `zeroconf`, with
      TXT-record parsing split into a pure `parse_service_info()` so it's
      tested without real mDNS traffic; `store.py`: `PairingStore`, one
      sealed `0o600` file, atomic replace, fail-soft on a corrupt file -
      ported in shape from the legacy `HubPairingStore`, deliberately
      without its own crypto module, which this rebuild doesn't carry
      ("download, don't vendor" - real encryption-at-rest for this file
      is a separate future hardening item, not something to half-build
      by copying legacy's `SecretBox` uncritically); `client.py`:
      `HubLinkClient` against the real, verified-in-source hub endpoints
      (`POST /api/auth/quick-connect/code`, `GET .../poll`, `POST
      /api/auth/devices/redeem`), `request_code()`/`await_approval()`
      split as two steps (not one blocking `pair()` call) specifically
      so a caller can show the code before blocking on approval;
      `lifecycle.py`: `LinkLifecycle`, the small state machine (resume a
      persisted pairing, else discover-and-pair, then a 24h re-redeem
      heartbeat) that both the settings page and the real daemon wiring
      read from. `app.py` now sets `custom_app_url` to a real settings
      page (`static/index.html`, polling a new `/api/state` route) and
      runs the link lifecycle on its own thread alongside `run_body`.
      34 deterministic tests: the store's round-trip/permission/atomicity/
      corruption handling, the discovery parser's TXT-record cases, the
      client's full code/poll/redeem flow against a real local HTTP
      server standing in for the hub (not mocked at the `requests`
      layer - the same pattern RM-03's own commit used), including the
      401/403 refusal paths (403 is ROBOT-DEVICE-01's own unrotated-
      credential gate, confirmed the client surfaces it as
      `PairingRefused` rather than a raw HTTP error), and the lifecycle
      state machine against scripted fakes (the code visible before
      approval completes - the one bug this session's own design caught
      before it shipped: an initial `pair()`-only version blocked
      silently with no code ever reaching the settings page, since
      nothing surfaced it until the whole call returned).
      **Live-verified, not just gated:** constructed the real `MaiPaiBody`
      class (not a fake) and ran its actual `settings_app` under a real
      `uvicorn` server bound to port 8042 - a real HTTP `GET /api/state`
      and `GET /` both served correctly, confirming the FastAPI wiring
      this session added to the SDK's base class actually works, not
      just imports cleanly.
      **Design ambiguity resolved via `design-resolver`, not guessed**
      (the audit's own instruction): the gap-audit flagged "does the
      robot speak the pairing code, or does the app page carry it
      alone" as unresolvable without research. Verdict: pre-rendered
      clips are the right answer (the design record already commits to
      speaking in three places, and "until the robot tier exists" may
      mean permanently, per M-R1's own adoption gate) - but building
      that asset-rendering pipeline is separable work, not part of G4's
      own pairing mechanics, so this pass ships the app-page-only
      interim state the resolver confirmed is legitimate for now (see
      the offline-speech-clips item below, and the one-line amendment
      to `docs/dev/design-reachy-mini-2026-09-27.md`'s section 9).
      **Not done, deliberately out of this pass's scope:** a full live
      pairing run against a real `home` dev server (the audit's own
      "Live: against a dev hub, the Devices page's add flow completes
      end to end" acceptance) - `home` may have other sessions actively
      working in it, and the deterministic stand-in server already
      exercises the identical wire contract read straight from `home`'s
      own route source, so this residual gap is recorded rather than
      chased through a cross-repo live session this pass didn't own.
      `/code-review medium` (one pass) caught three real defects, all
      fixed: `verify_fingerprint()` existed but nothing ever called it -
      `refresh()`/`_redeem()` sent the device token to whoever answered
      at the pairing's own `base_url` with zero identity verification,
      the exact defense the module's own docstring claimed. Now
      `_redeem()` calls a new `_verify_identity()` first: an https
      pairing gets a real, live certificate check with a confirmed
      mismatch refusing the redeem before the token is sent; a
      plain-http pairing gets a best-effort fresh-mDNS check that only
      refuses on a *confirmed* mismatch (a live answer at the same
      host:port with a different instance id), never on an inconclusive
      one (no answer at all - mDNS is unreliable by nature, and
      refusing the robot's own credential on a network hiccup would be
      worse than the narrow risk this honestly-scoped check accepts).
      `LinkLifecycle.state` returned the live mutable object, not a
      copy, so a reader doing several attribute accesses (the settings
      page's own three fields) could observe a torn combination mid-
      write; now a `copy.copy()` happens inside the same lock the
      writer uses. `_heartbeat()` recursed into `run()` on every failed
      re-redeem, growing the call stack by one frame per re-pair for
      the life of a process expected to run for months; `run()` is now
      one outer loop at constant stack depth, `_heartbeat()` returns
      instead of recursing. 3 new tests cover the identity check's
      three real outcomes (confirmed mismatch, inconclusive silence, a
      different service entirely); the state-copy and no-recursion
      fixes are covered by the existing lifecycle suite continuing to
      pass, not new dedicated tests.
      **A re-review of that fix (medium) caught three more real gaps,
      all fixed:** the plain-http identity check's own doc claims
      overstated what it catches - a real attacker who took over the
      address (ARP spoof, DHCP reassignment) simply doesn't run an
      mDNS responder, so the check finds nothing and, correctly per
      its own inconclusive-is-not-a-mismatch rule, proceeds anyway;
      it only catches the narrow, implausible case of a second,
      differently-identified responder answering at the identical
      host:port. Both `_verify_identity`'s own docstring and the
      module docstring now say this plainly: https is the only path
      with real protection here, http's check is honest best-effort,
      not a defense. The https certificate-pinning branch - the
      security-critical half of the whole fix - had zero test
      coverage; `test_link_client_https.py` (3 new tests) now drives
      it against a real self-signed certificate (generated by the
      system's own `openssl` CLI, no new runtime dependency) and a
      real TLS handshake, trusted via `requests`' own `verify=<cert
      path>` option, never `verify=False` (the same weakening pattern
      `_https_fingerprint`'s own docstring is explicit about avoiding
      everywhere else in this module) - covering a real pin-and-match,
      a real refresh success, and a real confirmed-mismatch refusal
      with zero redeem calls sent.
      **A third pass (low effort - the last one, per the org's own
      no-third-loop rule) caught a real mistake in that same commit's
      own third fix:** the "skip the redundant re-discovery in
      `await_approval()`" change was built on a false premise -
      "`request_code()` just discovered this address moments ago" -
      but `_poll_until_approved()` sits between them and can block for
      up to five minutes waiting for approval, not moments. The skip
      had reopened the exact gap `_verify_identity()` exists to close,
      for the first and highest-stakes redeem of all (the one that
      first sends the device token). Reverted outright: `_redeem()`
      always verifies again, the now-unused `verify_identity` parameter
      is gone rather than left as dead API surface, and the ~3s mDNS
      cost this whole detour tried to avoid is negligible against a
      pairing flow that can already run for up to five minutes. No new
      review round was dispatched for this fix (the org's own "a third
      pass never happens" rule) - verified instead by the full gate
      staying green (196 tests) and reading the reverted diff
      carefully by hand.
- [ ] **G4b: pre-rendered offline speech clips** (S, blocks family use
      and RM-05's unreachable-line acceptance - `design-resolver`'s own
      G4 verdict, 2026-09-28). Objective: the phrases the robot must be
      able to speak with no hub reachable to synthesize them - the 32
      pairing-code characters plus a short prompt, "I can't reach home
      right now" (RM-05's own acceptance), the freefall line (design
      record section 7), the reconnect line (M-R5) - rendered once at
      release time from a MaiPai voice, shipped as a Bot release asset
      (never a tracked file, matching G2's own model-asset pattern), not
      generated at runtime (an unpaired robot has no hub to synthesize
      with). Acceptance: every clip plays through G7's future playback
      path; the pairing flow speaks the code via these clips instead of
      only showing it on the app page; a licence check on the voice
      model used to render them is recorded in `docs/dev.md` before
      release, matching `dev.md:365`'s existing rule for the wake-word
      front-end. Out of scope: any clip beyond the four phrase classes
      named above - a new hub-unreachable line discovered later gets its
      own clip added to the same bundle, not a special case.
      Status 2026-10-05: manifest, bundle, composition, playback,
      render script and the lifecycle `on_code` hook are built and
      tested with fakes; clips unrendered, licence check and run-loop
      wiring open.
- [x] **G3+G6: the streaming turn round trip** (M, revised design -
      `docs/dev/robot-streaming-turn-2026-09-28.md`, superseding the
      original gap-audit's own batch-WAV G3/G6). Objective: after G2's
      wake fires, stream captured audio to the hub's own streaming STT
      session instead of buffering and uploading a WAV; give up cleanly
      if nobody follows the wake with speech; call the turn route with
      whatever transcript comes back and translate the reply's own
      event stream into expression cues. Landed:
      `body/maipai_body/speech/stt_stream.py` (`SttStreamClient` -
      opens `wss://.../api/stt/stream` using `websockets`' own sync
      client, already a bot dependency, no new one added; forwards G1
      capture blocks as binary frames from the wake instant; the whole
      of G3 folds in here as one small piece of logic, not a separate
      module - a `WAKE_PATIENCE_S = 6.0` timer that cancels on a real
      `{t:"vad",speaking:true}` and otherwise sends `{t:"end"}` and
      gives up, exactly as the revised design specifies, with no local
      VAD, no endpointer, no local `Utterance` object at all);
      `body/maipai_body/speech/turn_client.py` (`TurnClient` - `POST
      /api/turn/stream`, real newline-delimited JSON parsing per
      `home`'s own route source, not SSE; `signal` becomes a `Cue`
      through the already-built `expression/cue.py` from EXPR-01, not
      a new mapping; accumulated `delta` text becomes the reply on
      `done`; every `error` kind becomes `CANCEL` at the floor, since
      nothing calls for a per-code cue yet). `HubLinkClient` gained a
      `session_cookie` property so a different transport (`websockets`
      doesn't share `requests`' own cookie jar) can authenticate with
      the same redeemed session.
      16 deterministic tests, all against real local servers standing
      in for the hub (a real `websockets.sync.server` for STT, a real
      `http.server` streaming real NDJSON for the turn route) - proving
      the actual wire protocol, not a mocked response object. Two real
      bugs found this way, neither of which a mock would have caught:
      `SttStreamClient._give_up()` didn't handle the hub closing the
      connection without ever answering `{t:"end"}` (a real
      `ConnectionClosed`, not a timeout - now treated as a successful
      give-up, since there's nothing left to wait for either way); a
      leftover unused `_CANCEL_CODES` constant in `turn_client.py`
      implied a per-error-code cue mapping that was never actually
      wired up, removed in favor of an honest comment (every error kind
      maps to `CANCEL` at the floor, deliberately, not by omission).
      **Not yet built:** the actual run loop that calls these two
      clients back to back and renders the cues they produce - that's
      G9's own job, which assembles G2 through G8 into one state
      machine. This lands the two clients proven correct in isolation,
      ready for G9 to wire in.
      `/code-review medium` (one pass) caught three more real defects,
      all fixed: `_give_up()`'s own `ws.send({"t":"end"})` call sat
      outside the `try/except ConnectionClosed` that guarded the
      `recv()` right after it, so a hub closing the connection at that
      exact moment raised an unhandled `SttStreamError` instead of the
      intended graceful timeout - both the send and the recv are now
      inside the one guard. `TurnClient.stream()` mapped every
      `requests.RequestException`, 401/403 included, to `TurnLinkLost`,
      indistinguishable from a genuine dropped connection - a caller
      built to "reconnect" on `TurnLinkLost` had no way to know it
      actually needed to re-redeem through `HubLinkClient` instead; a
      new `TurnAuthFailed` now covers 401/403 specifically, checked
      before `raise_for_status()`, matching the same pattern
      `HubLinkClient._redeem()` already uses. Both `SttStreamClient` and
      `TurnClient` now raise a clear `ValueError` immediately if
      constructed with an empty `session_cookie`, rather than silently
      sending the literal header `Cookie: session=None` when a caller
      reads `HubLinkClient.session_cookie` before any successful pairing
      (its type is `str | None` for exactly this reason). 5 new tests,
      including one that reverts the `_give_up` fix and confirms it
      genuinely fails without it, matching the session's own standing
      rigor for a review-caught fix.
- [x] **G7: the reply on the robot's speaker - streamed TTS playback**
      (S-M, `docs/dev/reachy-mini-gap-audit-2026-09-27.md`). Objective:
      stream the hub's own `POST /api/tts` WAV reply into G1's
      `AudioPlayback` as it arrives, resampled to the daemon's real
      output rate, emitting `SPEAK` before the first push and `DONE`
      when the stream ends. Landed: `body/maipai_body/speech/
      tts_playback.py` (`TtsPlaybackClient` - mirrors the browser's own
      reference player, `streamingWavPlayer.ts`: parses only the
      44-byte header for `sampleRate`/`numChannels`/`bitsPerSample`,
      never trusts the declared data-chunk size since Pocket TTS writes
      a placeholder there, ends when the stream ends; resamples with
      `scipy.signal.resample_poly` - a maintained resampler, never
      hand-rolled, per the audit's own instruction - now an explicit
      `voice` extra dependency, not left as openwakeword's own
      transitive pin). `AudioPlayback` (G1) gained a small
      `output_samplerate()` method so this module doesn't reach into
      its private `_client`. The design record's own open question
      (section 5: the vendor's `HeadWobbler` vs our own `speak`
      primitive) was already answered before this session started -
      "the `speak` cue's rendering on this body is a low-amplitude
      pitch and antenna motion modulated by the outgoing audio's
      energy... no model" - so nothing new to resolve; the vendor's
      wobbler is never enabled. The `speak` primitive's own static
      rendering already exists from EXPR-01; making it genuinely
      energy-modulated from the ledger (section 5's full description)
      is a separable refinement, not blocking this item's own floor.
      Mid-stream cancellation (a `stop_event`) was added beyond the
      audit's own text once its acceptance criterion ("the ledger holds
      the pushed prefix when the stream is stopped at 40 percent") made
      clear G7 itself needs a stop hook, not just G8 later.
      8 deterministic tests against a real local HTTP server streaming
      a real generated WAV in 1 KB chunks (the audit's own acceptance
      shape), covering a full stream's duration matching within one
      block, the `on_first_chunk` callback firing before the stream
      ends, a mid-stream stop keeping a real non-empty prefix, a 401
      raising a distinct `TtsAuthFailed` (not conflated with a dropped
      connection, matching G6's own fix), and the 16kHz-source identity
      path needing no resampling at all.
      **Live-verified against the real `reachy-mini-daemon --sim`:** a
      real local stand-in server streamed a real 24kHz WAV; the real
      `TtsPlaybackClient` resampled it to 16kHz and pushed it through
      the real `AudioPlayback` wrapping a real `ReachyMiniClient` - 36
      real chunks reached the real daemon with zero errors, and the
      pushed duration matched the source to within 1 ms (3.001s against
      a 3.0s fixture).
      `/code-review low` (one pass) caught four real defects, all
      fixed: three separate paths (a 401, any other non-2xx via
      `raise_for_status()`, an unsupported `bits_per_sample`) each left
      the HTTP response unclosed, leaking the connection back to the
      pool - `speak()` now wraps the whole request in a `with` block, so
      every exit path (success, exception, or an early `return` deep
      inside `_stream_into_playback`) closes it, not just the
      `stop_event` branch that already called `close()` explicitly.
      `_pcm16_to_float32`'s downmix assumed every streamed chunk
      boundary lands on a whole multi-channel frame (4 bytes for
      16-bit stereo); truncating to just an even byte count let a
      stereo-or-wider stream's `reshape()` raise on a genuinely
      misaligned trailing partial frame - fixed by truncating to whole
      frames and carrying the remainder to the next chunk, the same
      leftover-byte pattern G1's own `capture.py` already uses. Proven
      with a hand-crafted chunk sequence, not a real server: `requests`'
      own `iter_content(chunk_size=4096)` always re-buffers to a clean
      multiple of 4 regardless of how the server writes, so no real
      HTTP round trip can actually reach this code misaligned - only a
      fake response object splitting bytes at a deliberately
      frame-odd offset reproduces it, and the new test was verified to
      genuinely fail without the fix (an earlier attempt at this same
      test, driven through a real stand-in server, passed regardless of
      whether the fix was present - a false-confidence test caught and
      replaced before landing, not shipped).
- [x] **G8: barge-in and the honest software mute**
      (S-M, `docs/dev/reachy-mini-gap-audit-2026-09-27.md`). Objective:
      a "stop" heard during playback cuts it locally, cancels the turn
      on the hub, and renders `CANCEL`; a software mute state stops
      capture reaching the wake scorer while capture itself keeps
      running, and is labeled "software mute" everywhere, never
      "physical mute" (this body has none, design record section 8).
      Landed folded into G9's `ConversationLoop` rather than as a
      separate module, since the revised streaming design left no
      local VAD or endpointer to attach a second detector to: a wake
      firing again while already `speaking` is barge-in (G2's own
      `WakeScorer`, reused, not a new model), stops `AudioPlayback`
      locally, posts `POST /api/turn/{id}/cancel`
      (`TurnClient.cancel()`, new this pass), and renders `CANCEL`
      exactly once (a review-caught race made sure of that, see G9's
      own entry). `ConversationLoop.set_muted()` is the mute state
      itself: edge-triggered, gates `_poll_wake()` so capture drains
      but is never scored while muted, and renders the muted pose
      through `ExpressionEngine.set_muted()`'s existing edge-triggered
      contract (EXPR-01). The acceptance's own grep test (no "physical
      mute" wording anywhere in `body/`) still passes.
      **Not yet built:** the actual command that calls `set_muted()` -
      nothing in this repo does yet. **Correction (2026-09-29,
      design-resolver, resolving G10's own state-frame transport):**
      this is NOT G10's own device-state frame (that frame is
      read-only telemetry, robot to hub - see G10-BODY below); it needs
      its own item, filed as ROBOT-MUTE-01 in `home`'s `docs/BACKLOG.md`
      (a settings key or a device-command channel, undecided - a real
      product call, not resolved here). The mechanism is real and tested
      (`test_set_muted_is_edge_triggered_and_updates_state`,
      `test_poll_wake_drains_capture_but_never_scores_while_muted` in
      `body/tests/test_run_loop.py`); only the caller is missing.
- [x] **G9: the run loop - one state machine driving audio, cues,
      tracking and the head** (M, `docs/dev/
      reachy-mini-gap-audit-2026-09-27.md`). Objective: replace
      `app.py`'s own `run_body` idle wait with the funnel (`idle`,
      `listening`, `thinking`, `speaking`) driven by G6's turn events
      and G8's mute, presence ticking in on its own thread, expression
      rendered through the existing `ExpressionEngine`. Landed:
      `body/maipai_body/run_loop.py` (`ConversationLoop` - `run()`
      drains wake, drives one turn at a time through `_run_turn()`
      -> `_speak()`; a `_presence_loop()` on its own thread enables the
      daemon's own face tracker when a face is present and the funnel
      isn't `speaking`, the one body-specific carve-out the general
      `arbitration.py` priority table doesn't model on its own, since
      tracking otherwise outranks expression there). `TurnClient`
      gained `cancel()` and a `with`-wrapped `stream()` request (the
      same connection-leak class G7's own review had just caught in
      `tts_playback.py`, found and fixed here proactively before a
      review had to catch it twice).
      A real bug found by the new tests, not by inspection: `_run_turn`
      was rendering every cue the turn stream emitted, including its
      own terminal `DONE` event - which means "the reply text is fully
      known," a different moment from "done speaking it" - firing the
      settle primitive before speech had even started. Fixed: only
      `CANCEL` and non-`DONE` cues render from that loop; `_speak()`
      alone renders the real `SPEAK` (before the first audio push) and
      `DONE` (once playback actually finishes, or `CANCEL` on a
      barge-in instead).
      10 tests in `body/tests/test_run_loop.py` against scripted
      stand-ins for every network-facing dependency (each already has
      its own real-server-backed suite) and a real `ExpressionEngine`
      rendering onto `FakeReachyMiniClient`, covering the happy path's
      cue order, no-speech and stream-cancelled turns skipping speech,
      a dropped turn-stream connection, barge-in, presence/tracking
      (enabled with a face present and not speaking, disabled while
      speaking or with no face), and `set_muted()`.
      `/code-review medium` (one pass) caught four real concurrency
      defects in the barge-in path, all fixed: `_next_cue_seq()`'s
      plain `+= 1` raced between the main funnel thread and the speak
      worker thread's `on_first_chunk` callback, now lock-protected;
      the barge-in polling loop kept scoring wake blocks for as long as
      the speak worker thread stayed alive rather than stopping the
      instant barge-in fired, letting a slow-to-exit worker's next
      block trigger a second `turn.cancel()` and a duplicate `CANCEL`
      render, now gated on `not barge_in.is_set()` too; `speak_thread
      .join(timeout=5.0)` let `_speak()` return while the worker might
      still be alive and pushing to the shared, unlocked
      `AudioPlayback`, so a fast-following turn's new speak thread
      could overlap and corrupt playback - now an unbounded `join()`
      (correctness over latency, bounded in practice by the TTS
      client's own (10, 120)s connect/read timeout); a dead
      `speak_cue_rendered` event was set but never read, removed. A
      low-effort follow-up pass on just the fix hunks found nothing
      further. The duplicate-`CANCEL` fix has its own regression test,
      verified (by hand, reverting the fix) to genuinely fail without
      it and pass with it.
      **Landed 2026-09-28: live verification against the real
      `reachy-mini-daemon --sim`** (RM-05's own acceptance).
      `tests/test_run_loop_live.py`: the "combined stand-in hub server"
      this note asked for turned out to be unnecessary -
      `ConversationLoop`'s three hub-facing clients are constructed
      independently, so nothing requires them to share a `base_url`;
      each got its own real local server instead (the same wire shapes
      `test_turn_client.py`/`test_tts_playback.py`/`test_stt_stream.py`
      already proved correct), while the head/expression/presence side
      talks to a real daemon (`--sim --headless --no-media`, confirmed
      startable in this environment without touching any real host
      hardware). Audio is the one seam still faked (`_LiveAudioIO`,
      delegating every other HAL call straight to the real
      daemon-backed client): the daemon's own documented fallback would
      otherwise use the host machine's real microphone with no consent
      prompt (the 2026-09-27 privacy finding, `docs/dev.md`), and
      `--no-media` makes `AudioCapture.start()` raise on the daemon's
      own `-1` sample rate anyway. Skipped unless `MAIPAI_BODY_LIVE=1`
      and a daemon answers on the live port - the same gate
      `conftest.py`'s own `body_client` fixture uses, unchanged by this
      pass. Verified as a real, meaningful test, not a vacuous pass: a
      negative control (pointing `turn_client` at an unreachable port)
      correctly failed with `TurnLinkLost`, then the correct wiring was
      restored and re-verified green. A three-turn conversation
      completes with cues rendered `HEARD` -> `SIGNAL` -> `SPEAK` ->
      `DONE` in order and `SPEAK` before `DONE` on every turn, checked
      after each one, not just once. Full body suite green both ways
      (292 passed/11 skipped without `MAIPAI_BODY_LIVE`; 300 passed/3
      skipped with it and the daemon running - the 3 remaining skips
      are the real-wake-word-model-gated tests, unrelated).
      **Still not built:** the 0.5 s settle-gate (`SETTLE_GATE_S`,
      BODY-05's legacy flash test - no funnel state renders shorter
      than this) is defined but not enforced anywhere; the funnel's
      real transition times are recorded in `RunLoopState.trace`
      regardless, so a test can measure the gap, but nothing currently
      holds a fast state open to close it.
- [x] **G11 (floor only): presence and tracking wired into the run
      loop** (bot, `docs/dev/reachy-mini-gap-audit-2026-09-27.md`).
      Objective (the audit's own floor, not the full item): "nothing
      beyond G9 - wire presence and tracking into the run loop so the
      robot turns to a face and toward a speaker." Landed as part of
      G9's `_presence_loop()` (see above): tracking engages within one
      presence tick of `get_face_target().detected` going true and the
      funnel not being `speaking`, disengages otherwise. Covered by
      `test_presence_enables_tracking_when_face_present_and_not_speaking`
      and `test_presence_never_enables_tracking_while_already_speaking`.
      **Not yet built - the rest of G11 is real vision, not the floor**:
      the still-image call's own design note is done, see G11-VISION
      below. Face identity is no longer out of scope (reversed
      2026-09-28, `design-reachy-mini-2026-09-27.md` section 4's
      amendment; see FACE-01 below) - a separate track from this
      item's own presence/tracking floor, which stays anonymous. Live
      tracking against the real simulator with a face injected into
      the scene (the audit's own acceptance for this floor) is
      deferred with G9's own live-verification gap above.
- [x] **G11-VISION: design note for the still-image call** (S, design
      only - `docs/dev/design-vision-still-image-2026-09-28.md`).
      Objective: the gap audit's own instruction ("record the
      still-image call as its own design item... before any code") for
      G11's still-image, general-scene-understanding call - not
      identity, see FACE-01 below for that separate track. Landed: the
      consent question resolved without a screen (the spoken request
      itself is the consent event, matching the wake-word precedent,
      never a modal this body cannot render - confirmed against
      section 5's "no eye, mouth, ring or screen" fact); the capture
      and hub-route shape (reusing `document_attachments`'s own wire
      shape and the `cancel` route's own request pattern, a `home`-side
      decision named but not built here); the one real blocker named
      honestly - the Stack's `vision` role is declared in three places
      (`wire.ts`, `stack/backend/src/roles.ts`, `home`'s `llm.ts`) and
      wired to zero engines or models anywhere, so no end-to-end path
      exists today regardless of what this repo builds. A stale
      `Camera` seam docstring claiming "RM-06 is its real consumer" was
      checked and found false (RM-06 only ever consumes `FaceTracker`);
      corrected. Also landed, the one piece real regardless of the hub
      blocker: `FakeReachyMiniClient.get_frame()` now returns a real
      given frame instead of always `None` (`camera_frame` constructor
      param, mirroring the audio fixture pattern), 3 new tests in
      `test_camera_frame.py`.
      **Extended same day:** found the vendor SDK already JPEG-encodes
      a frame on the daemon's own side (`media_manager.py`'s
      `get_frame_jpeg() -> bytes | None`) - no image-processing
      dependency needed here at all. Added `Camera.get_frame_jpeg()` to
      the seam, wired on the real client and the fake (a
      `camera_frame_jpeg` constructor param, independent of
      `camera_frame`); `body/maipai_body/vision/capture.py`
      (`capture_frame_data_uri()`) wraps it as a `data:image/jpeg;
      base64,...` URI, verified against `home`'s own
      `document_attachments` validation regex in the new test.
      **Live-verified against the real `reachy-mini-daemon --sim`:**
      both `get_frame()` and `get_frame_jpeg()` return `None` cleanly
      against a real client and an empty sim scene (no crash, correct
      propagation), and `capture_frame_data_uri()` raises
      `CameraUnavailable` exactly as designed - the same "mechanism
      proven, not real content" honesty RM-06 already established for
      face/IMU/DoA in this scene. 7 new tests total (4 in
      `test_camera_frame.py`, 3 in `test_vision_capture.py`).
      **Not built:** any turn-loop wiring, hub route, or consent-flow
      code - all wait on the `vision` role existing on the hub side.
- [ ] **FACE-01: face identity on the robot** (M, after the spec's
      print record; models resolved 2026-09-28, the design pass this
      entry used to ask for is done). The chain of record:
      `docs/dev/face-voice-recognition-design-2026-09-28.md` is the
      feasibility study; `design-reachy-mini-2026-09-27.md` section 4's
      amendment is the design record's verdict reversing the prior
      exclusion (the owner's call, confirmed live);
      **`docs/dev/design-face-recognition-models-2026-09-28.md` is the
      model decision**, and **`dev.md` section 6 ("Speaker evidence on
      a shared device") is the canonical spec this item implements**:
      the `speaker_evidence` wire shape, the confirmed/tentative
      fusion, the close-tie and far-miss rules, "present and alone",
      and the "never a score, an embedding, a track's geometry or a
      face crop leaves the robot" line are decided there and must not
      diverge. Decided (the models doc has the checks): the face model
      is OpenCV Zoo's SFace (`face_recognition_sface_2021dec.onnx`,
      Apache-2.0, MobileFaceNet backbone, 112x112 in, 128-d out,
      sha256 `0ba9fbfa...`, 68.8 ms published on a Raspberry Pi 4B,
      the CM4's own SoC), one file on every surface that matches a
      face; the voice model is the legacy CAM++ pin, byte-identical
      (512-d, read off the graph), and **it runs on the hub inside
      the STT session this body already streams to after the wake
      word (G3+G6), never on this body**: no `sherpa-onnx` here, no
      per-utterance embedding here, and the `voice` evidence joins
      the turn on the hub. The earlier text's "ArcFace's usual
      backbones are ResNet-scale" was wrong for the artifact legacy
      actually pinned (Hailo's `arcface_mobilefacenet`, 2.04M
      parameters), which is unusable here anyway: a `.hef` runs on no
      CPU, and its InsightFace weights are non-commercial. Objective:
      opportunistic, capped-rate face identity, triggered by the
      presence system's own `get_face_target()` (RM-06), never
      continuous: a subclass of the vendored
      `reachy_mini.vision.face_detector.FaceDetector` whose `_decode`
      keeps all five YuNet landmarks (the shipped `Face` keeps three;
      the `kps_*` outputs carry ten values; composition, never an
      edit to the vendored file); a `numpy` similarity transform to
      SFace's 112x112 five-point template (verify the template in the
      installed OpenCV source, not from memory); one single-thread
      SFace session; a local gallery of the household's synced face
      prints that loads only prints whose model id and sha256 match
      the model it runs and raises a Repair for any other; the
      per-modality verdict (threshold, margin, `confirmed` /
      `tentative` / `unknown` with candidates, thresholds set by the
      measurement, the legacy 0.36 a starting value only); the result
      on the turn request as `speaker_evidence` `basis: "face"`, which
      the hub's engine fuses with its own voice result. Dependencies
      added: none (`onnxruntime` 1.30.0 and `numpy` are already base
      dependencies through `reachy-mini`; the model file comes through
      the same pinned-URL-and-checksum pack pattern the wake word
      uses). Pointers: `hal/seam.py`'s `Camera` protocol and
      G11-VISION's fixture-backed `get_frame()`; `presence/
      observations.py`'s `read_presence()` as the trigger;
      `body/maipai_body/speech/wake.py` for the model-pack pattern;
      the mirror's `perception/enroll.py` `FaceGallery.identify`
      (best score per person, margin against the runner-up) as the
      reference for the verdict, not lifted. Acceptance: the spec's
      print record exists first (a `commons` item, named in the models
      doc section 5, not filed from here); a deterministic suite
      against the fixture-backed fake (recorded aligned crops, known
      prints, a close pair, a far miss, a print from a foreign model
      id refused with a Repair), sharing the spec's fusion fixtures;
      enrollment revocation removes local matching for that person
      within one sync; a recorded CPU measurement of the capped-rate
      check on the unit beside the daemon, the wake scorer and the
      audio stream (an M-R-style row in `docs/dev/measurements.md`).
      Out of scope, each named in the models doc for the repo that
      owns it: the print record (`commons/spec`); the enrollment UI,
      the encrypted store and the sync, the voice print in the STT
      session, the turn engine's fusion, and the browser-side matcher
      (`home`); the robot's guided in-person enrollment ceremony (a
      later item here, on top of the same record); gesture recognition
      on the hub/web and Go surfaces (confirmed in scope by Jesse
      2026-09-28, not analyzed, a `home`/`go` item regardless). Exit:
      `bash scripts/check.sh`, plus the CPU measurement recorded in
      `docs/dev/measurements.md`.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05. Nothing for it is dispatched or started until the owner says so.
      **Landed 2026-09-28: the offline pipeline (detect, align, embed,
      match), not yet the run-loop wiring.** `vision/detect.py`
      (`FiveLandmarkDetector`, all five YuNet points); `vision/
      align.py` (OpenCV's `alignCrop` translated line for line from
      its actual C++ source, checked against known synthetic
      transforms - no real OpenCV install to compare against - plus a
      hand-rolled pure-numpy bilinear warp, since the design's own
      "dependencies added: none" ruled out both `opencv` and `scipy`);
      `vision/embed.py` (the SFace session, preprocessing built to
      match `blobFromImage`'s exact semantics - BGR/RGB swap, no /255
      - verified against the real downloaded model by hand and now a
      dedicated regression suite); `vision/gallery.py` (the three-way
      verdict above, `tentative`/`unknown`-with-candidates/`unknown`-
      with-none, never `confirmed` alone; refuses a foreign-model
      print outright); `vision/recognize.py` ties them together.
      `model_assets.py` is a new generic extraction of the
      pinned-URL-and-checksum download mechanism (G2's own wake-word
      module used to own this outright; now both share it, kept
      behavior-identical - its existing suite still passes). 26 new
      tests.
      **Landed 2026-09-28: the run-loop wiring.** `_presence_loop()`
      runs a capped-rate (3s) check when a face is detected; `_run_turn()`
      populates `speaker_evidence` (person/basis/level only, never the
      verdict's own score or candidates) from the most recent verdict
      under a 10s staleness bound, validated against the hub's own
      person-id format (`commons/spec`'s `conversation_turn_schema.py`,
      checked directly) before sending, downgrading rather than
      risking the hub's schema refusing the whole turn. The actual
      recognition work runs on its own thread, off the presence
      thread's own tick, so it can't delay tracking's own enable/
      disable decisions; a camera or pipeline failure leaves a
      still-fresh verdict alone rather than wiping it. Two review
      passes (8 findings, all fixed, two hand-verified by reverting
      and confirming the new test fails). 5 more tests (23 total in
      `test_run_loop.py`).
      **Landed 2026-09-28: the print record (`home`, `spec-v0.1.54`)
      and the daemon's real construction.** The print record: FACE-01's
      part of the gap closed from the other side, `commons/spec`'s
      `BiometricPrint` schema plus `home`'s own `biometric_prints`
      table, consent authorization and `/api/biometric-prints` CRUD
      (full record in `home`'s own `docs/dev.md` - see that repo's
      FACE-01 entry for the hub-half design, including a pre-commit
      review catching and fixing a real authorization bug before it
      shipped). Real construction: `app.py`'s `run_paired_body`
      replaces the old `run_body` (deleted, no longer called from
      anywhere - folded into this function, which keeps its
      neutral-hold-and-honor-stop_event floor for the unpaired case)
      with a state machine that holds neutral until G4's hub link
      reports paired, then builds and runs the real G9
      `ConversationLoop`: `AudioCapture`/`AudioPlayback` over the
      HAL seam, `WakeScorer` with the real openWakeWord models (G2's
      own `ensure_wakeword_models`), `SttStreamClient`/`TurnClient`/
      `TtsPlaybackClient` pointed at the paired hub's `base_url` and
      the live `session_cookie` (`LinkLifecycle` gained two small
      public accessors, `pairing_store` and `hub_client`, for this -
      neither existed before, both were private), `ExpressionEngine`,
      and FACE-01's own `FiveLandmarkDetector`/`ensure_embedder`
      (SFace)/`FaceGallery` (model_id `sface-2021dec`, matching `home`'s
      identical `KNOWN_MODELS` string on purpose). The gallery starts
      empty - no print-sync mechanism from hub to robot exists yet,
      a real follow-up item, not this one - so every face check
      reports `unknown` until one does; that is the honest state.
      6 new/rewritten tests in `test_app.py` (never-paired holds and
      stops within a second, a lost connection, the paired transition
      with `_build_conversation_loop` mocked so no real network or
      model download happens in the deterministic suite, and an
      unreadable-pairing-record edge case), full body suite green
      (290 passed, 10 skipped - the real-model-gated ones, unchanged).
      **A known, explicitly filed gap, not solved this pass:**
      `TurnClient`/`SttStreamClient`/`TtsPlaybackClient` each capture
      `session_cookie` as a plain string at construction time; G4's own
      `REFRESH_INTERVAL_S` (24h) re-redeem may rotate that cookie, and
      nothing currently reconstructs these three clients afterward - a
      robot paired and running continuously past roughly a day could
      see hub calls start failing with a stale cookie until the process
      restarts. Filed as FACE-04 below.
      A `/code-review medium` pass caught three more real defects in
      `run_paired_body`, all fixed before landing: a model-download
      failure (`AssetUnavailable`/`ChecksumMismatch`, or a bare network
      error) is a plain `RuntimeError` subclass, not `BodyLost`, so it
      used to propagate uncaught and crash the whole daemon process -
      on every restart, for a fresh install with a flaky network, until
      someone noticed - now caught and logged, treated the same as the
      unreadable-pairing-record case; a paired-but-no-session-cookie
      state (a hub regression, or a proxy stripping `Set-Cookie`) used
      to silently fall back to an empty-string cookie and build every
      hub client anyway, surfacing only as an opaque 401 deep inside
      the first real turn instead of a clear error at the point it's
      actually known - now the same clean early return as the sibling
      unreadable-pairing case. Two new regression tests for both. The
      fourth finding (`stop_event` not polled during the first-boot
      model download, so a stop can take as long as the download
      instead of one second) is a real, narrower-than-it-sounds gap
      (only the very first paired boot on a fresh install, before
      models are cached) - documented in the module's own docstring
      rather than fixed this pass, filed as FACE-05 below.
      **Still not built:** the CPU measurement (needs the unit, not
      just Mac sanity numbers). Live verification against
      `reachy-mini-daemon --sim` landed separately the same day - see
      G9's own entry above.

- [x] **FACE-03 (bot half): pull hub-synced face prints into the
      gallery** (M, landed 2026-09-28). Objective: close the gap FACE-01 left
      explicit ("the gallery starts empty - no print-sync mechanism
      from hub to robot exists yet") so a paired robot recognizes the
      household's actual enrolled faces, not just `unknown` forever.
      Design resolved 2026-09-28 (`home`'s `docs/dev.md`, "FACE-03:
      hub-synced face prints on the robot" - read that record first,
      this entry is the bot-side half of the same decision). The hub
      side (`GET /api/biometric-prints/sync`, device-gated) is `home`'s
      own FACE-03 item. Shape:
      - `body/maipai_body/link/prints.py` (`PrintSync`): pulls the
        sync route using the same live cookie/URL reader the speech
        clients already use (`app.py`'s `_hub_credentials_reader`,
        FACE-04); once as soon as `link.state.paired`, then every 60s
        (a starting interval, measured like every other one in this
        module); replaces the gallery wholesale on each pull (no
        delta/tombstone logic needed - a revoked print is simply
        absent from the next snapshot); clears the gallery on a 401/403
        or when unpaired.
      - `vision/gallery.py`: `FacePrint` gains an `id` field;
        `FaceGallery` gains `replace_all(prints)` swapping the whole
        list under a lock (the run loop reads the gallery from another
        thread - the same reason `_build_conversation_loop` already
        runs on its own thread, FACE-05).
      - A print whose `model_id`/`model_sha256` doesn't match this
        body's own SFace pin is skipped with a logged Repair
        ("re-enroll `<person>` for the current model"), one bad print
        never aborting the rest of the load (`FaceGallery.add` today
        raises on the first mismatch - the loader must catch per-print).
      - Runs on its own thread, mirroring FACE-05's build-thread-plus-
        poll pattern in `run_paired_body`, so a slow/stalled pull can
        never delay `stop_event` handling.
      - Storage: memory only, never written to disk (this body has no
        sealed-at-rest store; `link/store.py` relies on file-mode 0600
        alone, and a plaintext embedding cache would be a new gap this
        item should not introduce).
      Acceptance: the fake-hub deterministic suite recognizes a fixture
      face against a synced print; a revoked print is gone from the
      gallery within one pull cycle (a test drives two pulls, second
      snapshot omits a person, assert `identify` now returns
      `unknown`); a foreign-model print is skipped and the rest still
      load; losing the hub session (401/403) empties the gallery rather
      than serving stale matches. Exit: `bash scripts/check.sh`; on
      real hardware, a hub-enrolled face gets `tentative` at the right
      person with CPU/latency recorded in `docs/dev/measurements.md`
      (needs the unit, same standing gap as FACE-01's own measurement).
      **Landed 2026-09-28: hub snapshots now populate the bot's face
      gallery on startup and every 60 seconds.** `PrintSync` reuses the
      live cookie/URL reader, replaces snapshots wholesale, clears on
      401/403, and keeps the last good gallery through transient
      failures. `FaceGallery` skips foreign-model prints per record and
      protects `add`, `remove`, `identify`, and `replace_all` with a
      lock. The offline tests cover replacement, revocation, auth
      clearing, mixed-model snapshots, transport failures, and stopping.
      Out of scope: the oplog replica (`spec/link/`, LINK-03, this
      item's snapshot-pull is explicitly a stopgap ahead of it per the
      design record); robot-side standalone enrollment (a later item on
      top of the same print record, per the models design's own §5).

- [x] **FACE-04: reconstruct the hub-facing speech clients on session
      cookie rotation** (S, filed 2026-09-28 from FACE-01's own
      construction pass). Objective: `TurnClient`, `SttStreamClient`
      and `TtsPlaybackClient` each hold a `session_cookie` snapshot
      taken once at construction (`app.py`'s `_build_conversation_loop`,
      called once when `run_paired_body` first observes
      `link.state.paired`); `LinkLifecycle`'s own 24-hour re-redeem
      (`REFRESH_INTERVAL_S`) may issue a new cookie on the hub's own
      session, which none of these three clients would ever see. A
      robot paired and running past that boundary risks every hub call
      failing with a stale credential until the process restarts.
      Files: `app.py` (`run_paired_body`, `_build_conversation_loop`),
      the three speech client classes. One reasonable shape: give
      `run_paired_body` (or `ConversationLoop` itself) a hook that
      reconstructs the three clients whenever `link.hub_client
      .session_cookie` changes from what they were built with, checked
      on some natural cadence (a presence tick, a turn boundary) rather
      than a dedicated poller. Acceptance: a scripted test that rotates
      a fake link's cookie mid-run and confirms a subsequent turn uses
      the new value, not the stale one.
      **Landed 2026-09-28: per-turn credential refresh.** The loop checks
      the live session cookie and pairing URL at each turn boundary and
      reconstructs its three hub clients only when that pair changes.
      Exit: `bash scripts/check.sh`.
- [x] **FACE-05: stop_event isn't polled during the first-boot model
      download** (S, filed 2026-09-28 from a code review of FACE-01's
      construction pass). Objective: `app.py`'s `run_paired_body` stops
      polling `stop_event` the instant it observes `link.state.paired`
      and doesn't check it again until `_build_conversation_loop`
      returns - `ensure_wakeword_models`/`ensure_embedder`'s
      synchronous, blocking downloads on a fresh install, with no
      cancellation hook. A stop or SIGINT landing in that window can
      take as long as the download does (seconds to tens of seconds on
      a slow connection), not the one-second contract the module's own
      docstring otherwise promises and RM-03's own acceptance names.
      Every boot after the first finds the models cached
      (`model_assets.py`'s `is_installed`) and returns immediately, so
      this is real but narrow: exactly one boot per fresh install, or
      per cache wipe. One reasonable shape: run
      `_build_conversation_loop` on its own thread, `join()` it with a
      short poll loop that also watches `stop_event`, and treat a stop
      mid-download as "never reached conversational state" (log and
      return) rather than trying to cancel the in-flight download
      cleanly. Acceptance: a scripted test with a fake `_build_
      conversation_loop` that blocks past `stop_event.set()` confirms
      `run_paired_body` still returns within roughly a second. Exit:
      `bash scripts/check.sh`. **Landed 2026-09-28: the conversation
      loop builds on a daemon thread while `run_paired_body` polls
      `stop_event`, honoring a stop during downloads within one poll
      interval.**

- [ ] **BODY-DAEMON-UPDATE-01: the body software version moves only with a Bot release (amends the Reachy design section 10 and RM-08)** (S, docs, filed 2026-10-01 from home's ROBOT-UPDATES-01 decision; needs Jesse's agreement before the design text changes). Objective: replace the independent "daemon PyPI update as a row, applied only on a click" in `docs/dev/design-reachy-mini-2026-09-27.md` section 10 and in RM-08 above with: the body daemon's version is pinned by Bot's release and moves with it, shown on the card and Updates row as detail ("Body software"), never as its own update. Why: `body/pyproject.toml` hard-pins `reachy-mini==1.11.0` and `scripts/install-reachy.sh` overrides `onnxruntime` because the vendor's own pin silently breaks the wake word, so a daemon upgraded alone from PyPI would break the Bot wheel (UPDATES.md: a sidecar never updates alone). Pointers: those two places, home's ROBOT-UPDATES-01 (landed, home `docs/dev.md`). Acceptance: both texts say it; RM-08's acceptance line about "the daemon version appears ... in the update row" becomes "the MaiPai version and the body software version appear on the card and the Updates row". Out of scope: any code. Exit: `bash scripts/check.sh --docs` in bot.

- [ ] **ROBOT-TAILSCALE-01: the hub half of the Reachy joining the
      tailnet and reaching the hub away from home** (M, hub half, filed
      in `home`; the bot half may be S; needs a CREDENTIALS.md review
      before dispatch, since the auto-provision path is a new credential
      class). Objective: a Reachy Mini off the home LAN reconnects to its
      hub over Tailscale with its pairing intact. Facts from
      `dev/robot-tailscale-access-2026-09-28.md`: the hub's address book
      (`hubEndpoints.ts`) sorts detected LAN first (priority 10) and the
      Tailscale entry next (priority 60), and records a `.ts.net` name
      or a `100.64.0.0/10` address with kind `overlay`; a `.ts.net`
      name or tailnet address is reachable only by a tailnet member, so
      the robot must be its own tailnet node (section "The crux"); both
      join paths are decided (owner's call 2026-09-28, "both": the
      owner joins the robot by hand with `tailscale up`, and the hub
      mints a single-use, tagged, pre-authorized auth key at pairing,
      stored through `lib/secrets.ts`); pairing stays LAN mDNS
      (`_maipai._tcp`), Tailscale is a post-pairing fallback only
      (section "What G4 should build regardless"); the 24 h re-redeem
      heartbeat already exists (`LinkLifecycle`, `link/lifecycle.py`).
      Not there yet: no authenticated hub-endpoints route (the doc names
      `GET /api/devices/me/hub-endpoints`, gated like `redeem` and
      returning `listHubEndpoints()` unfiltered, unlike the CA route),
      no client that walks the book, and no latency budget for a remote
      turn (M-R5 measures reconnect p50 and p95 only; the budget is
      proposed from the number recorded here and set by the owner, never
      guessed). Hub half: the route, the Tailscale OAuth or API
      credential setup and its consent flow, the key-minting call, and
      the revoke path that removes the robot's tailnet node with the
      device token. Bot half: `link/` caches the book, walks it in the
      server's priority order, re-fetches it on every successful
      connection, and detects a hand-joined tailnet (a `tailscaled`
      identity already present). Acceptance: a Reachy off the home LAN
      reconnects over the tailnet with its pairing state preserved (no
      new code, no re-pair); a turn completes over the tailnet with its
      latency (first delta and total, p50 and p95 over a fixed set)
      recorded in `docs/dev/measurements.md`; revoking the device ends
      access (the next redeem and the next tailnet call both fail).
      Out of scope: installing Tailscale on the hub; a relay or proxy
      for a robot that is not a tailnet member; any change to LAN
      pairing. Reuse check: `hubEndpoints.ts` and `tailscale.ts` are used
      verbatim, `lib/secrets.ts` stores the credential, `link/` extends
      the existing `LinkLifecycle` and `HubLinkClient`, and M-R5's
      harness measures the latency; no new address detection, no new
      secret store. Exit: `bash scripts/check.sh` in bot, the hub's own
      gate in `home`, and the recorded latency row.
- [ ] **LINK-STATE-00: `reconnecting` and `sleeping` activity values**
      (S, spec first, filed in `commons`; prerequisite of LINK-STATE-01).
      Objective: `robot.state.activity` gains the values `reconnecting`
      and `sleeping`, so the hub's robot card can tell a robot that is
      walking its addresses from one that has gone quiet. The shape is
      in `commons`' `docs/plans/robot-state-spec-01-2026-09-29.md` (that
      repo is not in this checkout, so it is cited by name only; this
      item does not edit it). Acceptance: the schema, its fixtures and
      the tag carry both values, `home`'s card renders them, and `bot`
      pins the tag. Exit: the `commons` gate and the tag.
- [ ] **LINK-STATE-01: the offline ladder's first rungs as one state
      machine** (S, Reachy Mini only, after LINK-STATE-00; the spoken
      parts also wait on G4b's clips or a local TTS). Objective: one
      machine in `body/maipai_body/link/`, driven by `LinkLifecycle` and
      the funnel in `run_loop.py`: `connected` goes to `reconnecting`
      on `link_lost` (the `turn_client.py` and `stt_stream.py` case) or
      a failed re-redeem, and while there walks the address book (LAN
      first, then the tailnet entry from ROBOT-TAILSCALE-01); after N
      minutes (a setting, default to be measured) it goes to
      `sleeping`; a redeem from either state returns it to `connected`
      with a reconnect cue. The states are reported through
      `StateReporter` as `activity` once LINK-STATE-00 lands. Rungs:
      rung 0 is body-only: breathe, settle, an antenna away pose,
      tracking off after a while, and a stir on reconnect (primitives
      from RM-02, no new axis). Rung 1 is the wake word plus a closed
      list of fixed local commands (stop, quieter, louder, timer, what
      time is it, are you connected?) with fixed replies. It needs the
      sherpa-onnx keyword spotter named in `dev.md`'s wake row (the
      measured alternative to the trained wake model) or a documented
      alternative; its CPU and false-accept cost on the CM4 beside the
      wake model is UNVERIFIED and gets a measured row (M-R1's bench)
      before it ships on that body. Rung 2 is a dynamic offline status
      built by templates from real `LinkLifecycle` and address-walk
      values (state, last contact, the address being tried, last error),
      no model; it is always visible on the app page and spoken only if
      a local TTS or the G4b clip set can say it. Queue rule: rungs 0
      to 2 queue nothing, and the status line says so ("nothing is
      saved for later"). Any later text queue replays only after the
      person confirms, and a write or physical tool never runs from a
      replay without that confirmation (the approval design). On the
      Reachy Mini there is no rung 3 unless M-R6 passes. The Pi + Hailo
      build may adopt the same state machine later, decided when the
      owner prioritises that build.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05.
      Nothing for it is dispatched or started until the owner says so.
      Acceptance, as
      tests on the funnel and `run_loop.py` with the fake body and an
      injected clock: `link_lost` moves `connected` to `reconnecting`
      and a failed re-redeem does the same; the address walk tries LAN
      before the tailnet entry; the machine reaches `sleeping` only
      after N injected minutes and not before; a redeem returns it to
      `connected` and fires exactly one reconnect cue; each rung 1
      command yields its fixed reply and nothing outside the list runs a
      turn; the rung 2 text contains only values read from the lifecycle
      and the walk; no turn text is queued in rungs 0 to 2; a replay
      fixture holding a write tool does not run it until a confirmation
      event arrives; the funnel never leaves `idle` during an outage
      except for a rung 1 command. Out of scope: any model call offline,
      the clip set itself (G4b), a text queue beyond the replay rule
      above. Reuse check: `LinkLifecycle`, `StateReporter`, the RM-02
      primitives and `WakeScorer` are reused; the machine adds no new
      transport, no new store and no new body axis. Exit: `bash
      scripts/check.sh`. **Built 2026-10-05 on the branch
      `cloud/reachy-link-state`, not landed: everything that needs no
      unit (state machine, walk, rungs 0 to 2 behind a recognizer
      interface, the queue and replay rules, the published activity
      values). Open: the tailnet seam waits on ROBOT-TAILSCALE-01; no
      keyword spotter exists, so rung 1 is wired off and its CPU and
      false-accept row is UNVERIFIED; the clips rung 1 needs are not in
      the G4b bundle; the default intervals are unmeasured. Boot with the hub away
      (review fix): a body with a stored pairing starts the supervisor and
      builds the loop without waiting for the first redeem, so the ladder,
      sleeping and the wake cue run from power-on. Still not covered: a
      body that was never paired still waits for pairing (there is no hub
      to be away from), and a first boot with an empty model cache and no
      network cannot build the loop (the wake model download fails), so the
      ladder runs but a wake is not heard. Second review fixes
      (2026-10-05): a stored pairing with no contact since power-on now
      starts the machine `reconnecting` at boot (it started `connected`
      until the first redeem's walk failed, so retries and the wake's offline
      path waited on it); the device token goes to a changed address only
      after a positive identity proof (pinned certificate on https, the
      pairing's instance id presented for that address on http, so a hub
      reached at its tailnet name passes), and the walk tells a network
      failure and an identity mismatch (next address) from a 401 or 403
      (revoked: the walk stops, the token goes nowhere else, nothing
      retries it, and the body asks for a new code). Still open: the
      tailnet entries must carry the hub's instance id once
      ROBOT-TAILSCALE-01 fills that seam, and plain-http identity is no
      defense against an on-path attacker. See
      `docs/dev/offline-ladder-unit-checks.md`.**

## Voice loop

- [ ] **VOICE-01: the speech process** (M). Objective: `body/speech/`
      is the robot's one speech process on one `sherpa-onnx` runtime:
      capture at 16 kHz in 32 ms blocks, the wake scorer (the trained
      artifact through ONNX with its front-end, never the stock phrase),
      Silero VAD, the 0.3 s pre-roll trimmed while waiting, the retry
      from the onset byte, the 6 s patience, the tail-syllable rule,
      Moonshine STT, synthesis, and the CAM++ embedder, served to the
      runtime as the `spec/voice/` contract (STT stream, synthesis,
      the wake and endpoint events), with playback through the array's
      line-out and a ledger of what was actually spoken. Audio never
      crosses the socket. Mirror: the mirror's
      `robot/robot/hal/drivers/voice.py`; the hub's `spec/voice/ts/`
      client and stub server as the contract's shape. Acceptance: the
      wake and endpointing rows of `dev.md` section 11 pass with recorded
      fixtures; the hub's voice-contract client talks to the body's
      server in a test; M-06 and M-08 recorded. Out of scope: the
      runtime. Exit: `bash scripts/check.sh`.
- [ ] **VOICE-02: barge-in and double-talk** (S, after VOICE-01).
      Objective: a "stop" over playback cuts playback locally within one
      block, sends `cancel` to the runtime, and the ledger holds the
      exact spoken prefix. Acceptance: the double-talk rows pass on the
      bench array at real playback levels with zero self-wakes. Exit:
      `bash scripts/check.sh`.
- [ ] **VOICE-03: the voice packages on the robot** (S, after VOICE-01).
      Objective: a Piper voice package served by the body's speech
      process through the shared voice contract;
      the companion's voice binding resolved to an installed voice with
      the "voice not available on this robot" row when it is not; M-09.
      Acceptance: the same text through the hub's normalizer and the
      robot's produces identical speech text (the spec fixtures). Exit:
      `bash scripts/check.sh`.

## Household runtime on the robot

Every item waits on RUNTIME-01 and spec-v0.1.0, and RT-00 and IPC-01 are
written and reviewed before any of the others is coded.

Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05. Nothing for
it is dispatched or started until the owner says so.

Background turns (owner decision 2026-10-05): the assistant features
(heartbeat, errands, scheduled tasks) are gated by a per-model
`background_turns` flag, a new field in the commons model record, off
for models below the capability floor. M-02 records the named model's
value; RT-02 and RT-03 carry it.

- [ ] **RT-00: the runtime API contract, consumed** (S, before code).
      Objective: a written record in `docs/dev/runtime-api.md` of the
      ports the robot injects (the store, the supervisors and the launch
      adapter, the voice-contract client, the package host, the data
      directory, the surface, the clock) and the calls it uses, each
      mapped to RUNTIME-01's declared API by name, so the robot depends
      on the API and never on a module path. Acceptance: every port and
      call names its counterpart in the hub's package; nothing else is
      imported. Exit: `bash scripts/check.sh` (doc gate).
- [ ] **IPC-01: the body contract** (S, before code). Objective:
      `body/contract/` declares once, as a versioned schema, the
      observations (speaker evidence, presence, mute, stop, power and
      thermal, the admission budget), the host calls, the expression
      cues and cancellation with deadlines; types generated for both
      sides; a version handshake on connect that refuses a mismatch; an
      unknown message answers an error and never disconnects. Mirror:
      the link envelope's own rules (plan 7.2). Acceptance: the
      generated types on both sides pass one fixture set; a mismatched
      version is refused in a test. Exit: `bash scripts/check.sh`.
- [ ] **RT-01: pin and boot the household runtime** (M). Objective:
      `runtime/` pins the hub's runtime package and the spec tag by
      version and digest in the lockfile, boots it on Bun with the
      robot's data directory, the encrypted store, the outbox and
      watermark spools, the HLC seeded from every HLC-bearing table, and
      the pinned artifacts checked; the socket to the body; no ready
      badge on a stub engine. Acceptance: the spec fixtures round-trip
      through the robot's store; a boot check refuses a package whose
      version or digest differs from the lockfile and refuses a path
      dependency (the robot consumes the tagged package, never a source
      snapshot); a boot with a missing artifact shows the Repair and
      still answers wake and stop. Out of scope: pairing. Exit: `bash
      scripts/check.sh`.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05.
      Nothing for it is dispatched or started until the owner says so.
- [ ] **RT-02: the robot's records from first boot** (S, after the spec
      fields land). Objective: people, settings, entities, lists, jobs,
      commands, turns, memories written in spec shape with `standalone`
      provenance and the outbox op in one transaction. Acceptance: the
      never-sync grep test on the robot; a record written on the robot
      round-trips byte-identical through the hub's validator. Exit:
      `bash scripts/check.sh`.
      Background turns: see the one note under "Household runtime on
      the robot".
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05.
      Nothing for it is dispatched or started until the owner says so.
- [ ] **RT-03: the local engines** (M). Objective: llama-server for chat
      (the model M-02 names), embed (nomic) and the judge (the 4B, its
      own process at a lower CPU weight, its in-flight request aborted
      on an interactive arrival, resumed from the per-fact checkpoint),
      through the shared supervisors with the robot's launch adapter
      (four cores, Q4_K_M, `--cache-reuse` on chat only,
      `enable_thinking: false`). Acceptance: M-02, M-04, M-05 recorded;
      the abort-at-arrival test in the deterministic suite with the stub
      engine. Exit: `bash scripts/check.sh`.
      Background turns: see the one note under "Household runtime on
      the robot".
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05.
      Nothing for it is dispatched or started until the owner says so.
- [ ] **RT-04: the Tier 0 set in the interpreter** (S). Objective: the
      bundled Tier 0 packages marked for the bot platform installed from
      the same signed bundle and run by the shared TypeScript recipe
      interpreter inside the runtime, no Deno process yet. Acceptance:
      the recipe conformance fixtures pass on the robot; a package's
      `platforms` without `bot` is refused at install. Exit: `bash
      scripts/check.sh`.
- [ ] **RT-06: the Deno package host** (M, after standalone). Objective:
      the shared Deno host as one process with Workers on the Pi, the
      Tier 1 packages (media-lookup, knowledge) under it, `timeout_ms`
      4000, the budget from M-01. Acceptance: a package reading outside
      its directory fails; the typed-source rows of the fixture pass
      robot-only with internet. Exit: `bash scripts/check.sh`.
- [ ] **GOV-01: one resource governor** (S, with BODY-06 and RT-03).
      Objective: the body computes the admission budget from power and
      thermal state and publishes it on the contract; the runtime's
      governor reads it and admits Bun, Deno, llama-server and the Hailo
      pipelines by that one policy; no process keeps its own. Acceptance:
      a fake thermal ceiling in the body pauses the judge and the idle
      motion in the deterministic test. Exit: `bash scripts/check.sh`.
      Pi + Hailo build: NO PRIORITY by owner decision 2026-10-05. Nothing for it is dispatched or started until the owner says so.
- [ ] **UPD-01: self-update with rollback** (M, after standalone).
      Objective: the robot's own update path per UPDATES.md: stage, swap,
      health check, rollback, the runtime pin and the body versioned
      together, a backup taken first. Acceptance: a deliberately broken
      build rolls back on the bench Pi. Exit: `bash scripts/check.sh`.
- [ ] **RT-05: the spoken surface** (S, after SURFACE-01). Objective:
      turns run with `surface: robot`, one sentence on voice, links
      never read aloud, the `present` list supplied by the body, the
      output boundary and guards on every reply source including hub
      output in connected mode. Acceptance: the fixture's voice rows
      pass in paired-unreachable mode. Exit: `bash scripts/check.sh`.

## Expression

- [ ] **EXPR-01: the expression package on scripted cues** (M). Objective:
      `packages/expression/` (`platforms: [bot]`, category "Robot body")
      declares the primitive table of `dev.md` section 5 once, maps cues
      to primitives, scales by the calibrated envelope, blends inside
      one limiter, and is driven on the bench by a scripted cue source
      before any engine exists. Pointers: `body/head/controller.py`
      (BODY-04) as the only actuator. Acceptance: every primitive
      renders from its cue in the deterministic test with a fake
      controller; the suppression table (near hand, service, dock,
      thermal, mute, stale track) holds for each; a physical run's
      encoder trace per primitive recorded. Out of scope: the engine's
      cues. Exit: `bash scripts/check.sh`.
      **Not fully landed**, box stays unchecked: no blending limiter
      exists (`dev.md` section 5's "a full-amplitude track plus an
      expression is never summed and clipped after" rule - summing two
      simultaneous continuous signals rather than clipping after the
      fact - has no design yet and none was invented here rather than
      guess at what "compatible" means numerically). The arbitration
      half of this note is stale: `dev.md` section 5's priority order
      (inhibit/reflex, service, tracking, expression, idle) is RM-06's
      `presence/arbitration.py`, landed after this item.
      **2026-09-27 addition, corrected the same day by an audit:** the
      vendor SDK's own `goto_target` blocks the calling thread until the
      daemon's task completes (verified in the installed `reachy_mini`
      package's `wait_for_task_completion` call), so two primitives
      cannot collide on a single calling thread today; `ExpressionEngine`
      holds a lock around every render, closing the "nothing stopping
      two from firing back to back" case for a second thread (EXPR-04's
      continuous idle/track/breathe loop, once it exists, calling
      `handle()` beside the turn-driven discrete cues). A Fable-model
      audit found this locked `stop` too, inverting `suppression.py`'s
      own "stop is never suppressed" rule the instant a second thread
      exists: a `goto` in flight on one thread would make a `stop`
      handled on another thread wait for it, when `stop` is supposed to
      preempt everything. `stop` now bypasses the lock and is issued
      immediately; the audit also found `hold()` never sent the
      daemon's own `StopMoveCmd`, so a goto's task kept winning the
      pose regardless (`client.py`'s `hold()` sends it now, before
      re-holding the present pose - idempotent, acked even when nothing
      was running). Neither fix helps a `stop` cue arriving on the same
      thread as the blocking goto it's meant to cancel; that needs gotos
      issued from a worker the engine never blocks on, EXPR-04's own
      shape, not something a lock can do on one thread. Verified against
      a fake that blocks like the real client, from two real threads,
      including a case proving `stop` returns before a slow goto on
      another thread finishes. This closes the collision and preemption
      risk, not blending itself - two non-stop renders still queue
      cleanly one after another rather than interleaving; they don't
      merge into one smoother motion. Built at
      `body/maipai_body/expression/` against the HAL seam's generic
      `HeadActuator`, not `body/head/controller.py` (BODY-04): BODY-04
      and the MaiPai build's own profile do not exist yet (they need
      the owner's physical calibration run), and the seam is what both
      bodies' controllers implement, so this is the more general
      reading of "the only actuator," recorded here rather than
      guessed silently. Landed and verified: the cue-to-primitive
      mapping (`cue.py`), the suppression table for the six named
      reasons (`suppression.py`), every primitive rendering from a
      scripted bench sequence (`scripted_source.py`, `engine.py`)
      against the fake in the deterministic suite, and a real run's
      state-feed trace per primitive recorded in
      `docs/dev/measurements.md` (Reachy Mini has no encoders; the
      state feed is RM-01's own stand-in, same as its acceptance
      already established).
- [ ] **EXPR-02: motion onset measurement** (S, after EXPR-01 and
      VOICE-01). Objective: the stamps of `dev.md` section 5
      (`t_heard`, `t_cue_emitted`, `t_cue_received`, `t_motion_command`,
      `t_encoder_onset`, `t_first_audio_out`, `t_acoustic_onset` from the
      array's own capture of the playback) on the one monotonic clock;
      cue-to-command p50 and p95 measured after the socket with the
      socket leg beside it, cue-to-acoustic-onset p50 and p95, the
      ordering result per row against the acoustic onset, the device's
      output latency recorded once, suppressed rows failed unless a
      listed safety reason was present. Acceptance: the numbers in the
      bench header; the negative rows (a dropped, duplicated and late
      cue, a deep playback buffer, a socket loss, a disagreeing hub
      stamp) each behave as section 5 says. Exit: `bash
      scripts/check.sh`.
- [ ] **EXPR-03: the engine's cues** (M, after WIRE-01 for connected mode
      and RT-01 for local; the plan half after ACT-03). Objective: the
      runtime emits `ExpressionCue` at the phases of `dev.md` section 5
      for every reply path and every infrastructure path (both
      inventories in that section, each path a test), locally over the
      socket and over the link; cue ids cleared
      on link loss; the same primitive from the same signal in all
      three modes. Acceptance: the expression rows of section 11 in the
      three modes; onset before the first audio sample on every eligible
      row. Exit: `bash scripts/check.sh` and the three-mode bench.
- [ ] **EXPR-04: tracking and idle** (S, after BODY-04, BODY-05).
      Objective: deadbanded gaze with velocity and acceleration limits
      on a fresh track or direction of arrival; freeze then settle on a
      stale or conflicting track; breathing on the idle policy with its
      suppressions. Acceptance: the deterministic trajectory tests; the
      physical run recorded. Exit: `bash scripts/check.sh`.
- [ ] **EXPR-05: a body-agnostic web dashboard** (M, sim; owner's ask,
      2026-09-27). Objective: a small web page (a lightweight Python
      HTTP server in `body/`, no framework beyond what a health check
      needs) that shows a body's live state - head pose, antennas, body
      yaw, direction of arrival - as a 2D schematic and simple telemetry
      readout, and lets someone trigger any expression primitive by
      name, all through the HAL seam alone: the fake, the Reachy Mini
      client, and the MaiPai build's own client once it exists all work
      against the identical page with zero changes to it. A live 3D
      view (loading real meshes in a browser, matching Pollen's own
      MuJoCo viewer) is explicitly out of scope for this item - it is a
      real, separate undertaking (WebGL, a model per body), tracked
      here only as a possible follow-up once the 2D dashboard is real
      and useful. Pointers: `docs/dev/hal-seam.md`'s own "what's
      deliberately not built yet" note; `maipai_body.expression.engine`
      and `maipai_body.presence.observations` as the two things the
      page actually calls. Acceptance: the dashboard renders and
      accepts commands against the fake in a deterministic test (no
      browser needed - assert on the HTTP/WS responses); a live check
      against the Reachy Mini simulator, screenshotted and opened.
      Out of scope: a 3D view; anything MaiPai-build-specific. Exit:
      `bash scripts/check.sh` and the live check.

## Speaker evidence and presence

- [ ] **SPEAK-01: voice evidence in the body** (M, after VOICE-01).
      Objective: CAM++ embeddings on speech of two seconds or more in
      the speech process, direction of arrival tying a voice to a
      track, the three-way answer (known, unknown with candidates on a
      close tie, unavailable), enrollment with consent on the screen,
      templates sealed locally and deleted with the person; the screen
      sign-in as the `signed_in` basis; M-07 against its gates.
      Acceptance: SPEAK-01's real-microphone acceptance recorded within
      the gates; templates absent from every export and sync payload
      (the grep test). Out of scope: face evidence. Exit: `bash
      scripts/check.sh`.
- [ ] **SPEAK-04: face evidence and fusion** (M, after standalone).
      Objective: ArcFace on the speaking track, the confirmed and
      tentative fusion rules of `dev.md` section 6, conflicting face
      and voice as unknown, face templates under the same consent,
      sealing and deletion rules. Acceptance: the conflicting-evidence
      and visitor rows of section 11; templates absent from every
      payload. Exit: `bash scripts/check.sh`.
- [ ] **SPEAK-02: `speaker_evidence` and `present` on the turn** (S,
      after the spec fields and RT-05). Objective: the body's evidence
      typed on every turn; `claimed` from the who-ask; confirmed and
      signed-in the only levels that open the ceiling, disclosure,
      `sensitive`, consequential actions and settings; the child band on
      unknown; "present and alone" (exactly one entry in the list, at
      confirmed, the speaker) computed and rechecked at delivery; only
      the derived fields of section 6 leave the robot, with the stated
      readers and retention.
      Acceptance: the speaker rows of section 11; the band-claim and
      unknown-speaker rows from the hub's fixture pass on the robot.
      Exit: `bash scripts/check.sh`.
- [ ] **SPEAK-03: the bindings on the robot** (S, after COMP-06).
      Objective: the companion-binding records resolved per turn
      (speaker's, then device, then household), authored on the screen
      robot-only, synced when paired. Acceptance: two roster people
      binding one word to two companions on the bench. Exit: `bash
      scripts/check.sh`.

## Standalone setup and the screen

- [ ] **SETUP-01: Wi-Fi provisioning** (M). Objective: first boot brings
      up an access point with a captive portal and shows the same steps
      on the DSI screen; a paired household can push credentials over
      the link later. Acceptance: a fresh image reaches a network from
      the screen alone. Exit: `bash scripts/check.sh` and the seeded
      screenshot opened and judged.
- [ ] **SETUP-02: the standalone first run** (M, after RT-01, RT-04).
      Objective: the shared schema pages on the DSI at touch size:
      household name and locale, the owner's profile with a PIN, the
      AI-outputs disclaimer, the default packages, people and children
      with the band's safe defaults, companions and voices, enrollment,
      the optional search server (section 8) with its privacy row; no
      phone, no hub, no cloud. Acceptance: a roster household authored
      entirely on the screen converses and survives a reboot; the
      screenshot set generated and judged. Exit: `bash
      scripts/check.sh`.
- [ ] **SETUP-03: USB export and restore, and the store's recovery** (S,
      after RT-02). Objective: the export bundle in spec shapes plus the
      separately protected node keys; the encrypted store's key lives on
      the device (the keystore pattern) and a restore on a fresh image
      needs the key file from the emergency kit; what is lost without it
      (everything in the store; the templates always) is stated on the
      screen before an export; robot-owned credentials re-entered when
      they cannot be restored securely. Acceptance: a seeded household
      exported, wiped, restored, counts equal; a restore without the key
      file refuses with the stated message. Exit: `bash
      scripts/check.sh`.
- [ ] **SETUP-04: the robot's privacy page** (S). Objective: the "what
      leaves the robot" table (the hub, the configured sources, the
      update check), the derived speaker and presence fields with their
      readers and retention, and the mute's honest label ("software
      mute" wherever the product speaks of it until a physical cut
      exists). Acceptance: every outbound endpoint in the code has a
      row; the words "physical mute" appear nowhere while question 1 is
      open. Exit: `bash scripts/check.sh`.

## Link and sync

All after `spec/link/` and hub v0.3.

- [ ] **LINK-01: discovery and pairing** (M). mDNS browse, the ping's
      instance id compared to the stored one before any credential is
      sent (the legacy gap), the six-digit code on the screen, the token
      sealed at 0o600 with atomic replace and a corrupt file meaning
      unpaired, the hub's fingerprint pinned, re-trust on a changed
      certificate, rate limits on codes and attempts. Acceptance: the
      wrong-instance and wrong-certificate rows.
- [ ] **LINK-02: the transport** (M). One outward WebSocket, the
      envelope, a bounded writer, jittered backoff, the sub-second
      circuit breaker, no hedging, telemetry droppable and durable ops
      never. Acceptance: the link-loss rows of section 11.
- [ ] **LINK-03: the oplog and merge** (L). The hub's HLC with the node
      rank tie authority and its lifecycle (`dev.md` section 7), the
      clock quarantine past one hour ahead with the re-stamp rule for
      unsent ops, the outbox and watermark spools, push then pull,
      append-only union for memory, per-field LWW for settings,
      hub-authoritative people with restrictive-wins, tombstones forever,
      the snapshot at a log position, the alias, delete and forget
      precedence of section 3, the never-sync allowlist with its grep
      test, property tests with Hypothesis on the robot side over
      arbitrary interleavings including alias races. Acceptance: the
      plan's 7.3 test list plus section 11's sync rows and its adoption,
      restore and forget table.
- [ ] **LINK-04: connected turns** (M, after SURFACE-01, WIRE-01). The
      hub as the brain with the robot's persona block, conversation id,
      `surface: robot`, the `present` list and the spoken policy; the
      cues over the link; the local continuation with the spoken prefix
      on loss; the five-state effect ledger (requested, sent, confirmed,
      unknown, failed) consulted on reconnect, the executor queried
      before any retry, the state said out loud, a stale unknown as a
      Repair. Acceptance: the cable-pull row from chapter 13's proof and
      the lost-ack-after-a-lock row with the spoken state.
- [ ] **LINK-05: adoption, unpair, replacement** (M, after standalone and
      LINK-03). The `alias` op, the
      adoption screen's link, create or keep-local per person, counts
      verified both sides, resumable; unpair's keep-or-wipe; a replaced
      hub as a new pairing; restore with `409 rewind`. Acceptance: the
      robot-only-then-paired rows.
- [ ] **LINK-06: the Home Assistant device** (M). The ESPHome native API
      with Noise, the robot's own HA key offered at setup, the light
      with the hub off and the garage with the physical confirm
      (chapter 13's proof). Acceptance: a live HA instance exercised
      and recorded.

## Lookup

- [ ] **LOOKUP-01: the search server setting robot-only** (S, after
      RT-04). Objective: the same `websearch` package and
      `search.searxng_url` setting; the setup screen's opt-in with the
      privacy row; the ladder ends honestly once when unset; a
      time-sensitive question never gets a model guess. Acceptance: the
      internet-down against hub-down rows; the honesty line passes the
      register guard. Out of scope: hosting a search server on the Pi.
      Exit: `bash scripts/check.sh`.

## Safety and power

- [ ] **SAFE-01: the physical stop path** (S, with BODY-04). The e-stop,
      a near hand or face, touch, a stale controller and barge-in cancel
      any trajectory into the measured safe stopping behavior with no
      hub and no model in the path; the default a controlled settle
      until the owned-build measurement says otherwise. Acceptance: the
      body-safety rows of section 11 in the deterministic suite and on
      the bench.
- [ ] **SAFE-02: the drive stage's design note** (L, not v0.1). Before
      any base motion: the loaded stopping distance, rollaway and
      stability envelope, the brake interlock carried as logic, the
      arbiter's priority logic and tests, the sense lines. Acceptance: a
      design note in `dev.md` first.

## Bench

- [ ] **BENCH-01: the deterministic suite** (S, with the first body
      code). pytest for the body with fake sensors and scripted cues;
      `bun:test` for the runtime adapter; both in `check.sh`; no live
      model, no browser window, no machine setting. Acceptance: the
      suite runs offline in under a minute.
- [ ] **BENCH-02: the hub's bench in three modes** (M, after RT-01;
      connected after LINK-04). The transport adapter and the body's
      measurement adapter on the hub's `conversationLive.ts`, the three
      fresh states, the header, three seeded runs each. Acceptance: the
      robot-only rows, the negative timing rows and the adoption,
      restore and forget table of `dev.md` section 11 added to the
      fixture as failing rows first, then green.
- [ ] **BENCH-03: the physical proofs** (S, per stage). Encoder motion,
      clearance, stability, safe stop and the mic-to-speaker timeline
      on the final parts, each recorded with the header. Acceptance: the
      stage page's closing check filled with the recorded number.

## Docs and status

- [ ] **DOCS-01: the build guide, stage by stage** (M, with BODY-01).
      `docs/user/build/` in the Instructables format, final parts only,
      one page per stage ending in its check, no owner notes.
- [ ] **DOCS-02: the user tier** (S, with SETUP-02). Welcome, first run,
      privacy, safety, getting to know the robot, at the dad-test level,
      screenshots generated and judged.

## Legacy review queue

Complete: the 83 verdicts are in [`dev.md`](dev.md) under "Review
queue". Seven "Redesign" rows wait on the owner's family-use verdict
(`dev.md`, "Open questions", item 11).
