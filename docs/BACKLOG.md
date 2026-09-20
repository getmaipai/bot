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
(`dev.md` section 2).

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
      `@maipai/standards` std-v0.2.0. Verified by `git log` (`f217451`,
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

## Hub dependencies

Not this repo's items. What the household track waits on, by name, so a
session never privately implements a pending hub behavior (`dev.md`
section 12).

| Hub item | What the robot needs from it | Robot items that wait |
|---|---|---|
| RUNTIME-01: the household runtime as a workspace package the hub runs, with an explicit package API | The engine, context, signal, guards, boundary, safety classifier, store, judge, scheduler, people, settings, host and link as one pinned package; the injected ports and the exposed calls declared (`dev.md` section 2), the hub its first consumer through that API | RT-00 to RT-06, LINK-*, BENCH-02 |
| spec-v0.1.0 (Jesse's call) | The tag the robot pins as `maipai-spec` | RT-01, SPEC-* |
| SPEC (section 3): `Person.source: standalone`, the `alias` op, `speaker_evidence` and `present` on the turn, `age_band_basis: claimed_profile`, the jobs and commands verdict, the `bot` mark on the keys the robot honours | The shapes the robot writes from first boot | RT-02, SPEAK-02, LINK-03 |
| SURFACE-01: `robot` admitted as an implemented surface with the spoken presentation and the `present` list | Connected mode | LINK-04 |
| WIRE-01: `signal`, `plan` and `cancel` on the turn stream | The expression cues in connected mode | EXPR-03 |
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
      runs per candidate (Qwen3-1.7B, Qwen3-4B, Q4_K_M, llama-server
      pinned to four cores, `--cache-reuse 256`), first delta p50 and
      p95, generation rate, RSS, and the quality gates in the same run:
      the fixture's hard rows (credential, cross-person, unsafe-and-
      crisis, consequential-once), the guard corpus at the hub's floor,
      and the legacy honesty method's raw and guarded columns as a
      recorded score. Acceptance: the decision rule applied (latency
      under the rule and every hard row green) and the model named; the
      honesty score handed to the owner (question 13). Waits on RT-01.
- [ ] **M-03: the Hailo provider option** (M, only if M-02's rule promotes
      it or v0.2 asks). Objective: the rendered prompt's token count
      against the 2,048-token ceiling, first reply with retained context
      on the current HailoRT, the swap cost against vision. Acceptance:
      "fits and faster" or "closed", with numbers.
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
- [ ] **RT-02: the robot's records from first boot** (S, after the spec
      fields land). Objective: people, settings, entities, lists, jobs,
      commands, turns, memories written in spec shape with `standalone`
      provenance and the outbox op in one transaction. Acceptance: the
      never-sync grep test on the robot; a record written on the robot
      round-trips byte-identical through the hub's validator. Exit:
      `bash scripts/check.sh`.
- [ ] **RT-03: the local engines** (M). Objective: llama-server for chat
      (the model M-02 names), embed (nomic) and the judge (the 4B, its
      own process at a lower CPU weight, its in-flight request aborted
      on an interactive arrival, resumed from the per-fact checkpoint),
      through the shared supervisors with the robot's launch adapter
      (four cores, Q4_K_M, `--cache-reuse` on chat only,
      `enable_thinking: false`). Acceptance: M-02, M-04, M-05 recorded;
      the abort-at-arrival test in the deterministic suite with the stub
      engine. Exit: `bash scripts/check.sh`.
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
