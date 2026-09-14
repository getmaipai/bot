# MaiPai Bot: design record

Seeded 2026-09-03 from the platform plan (`purring-chasing-noodle.md`),
rewritten 2026-09-14 as the design record by the robot design pass. This
file is the dev-tier design doc: the decisions, their reasons, the review
queue with every legacy skill's verdict, and the roadmap against the
plan's chapter 13. What is built and what is missing lives in
[`BACKLOG.md`](BACKLOG.md); the owned parts, as the build guide's final
parts, live in [`dev/build-record.md`](dev/build-record.md).

Nothing in this file is household content: every person in an example is
from the org's persona roster, and no measurement below was taken on a
family recording.

## What happened to the old repo

The pre-rebuild robot's full history (the bench-proven Pi 5 build: wake
word, sherpa-onnx-adjacent speech stack, Hailo-10H model, memory schema,
`hublink` pairing, 83 skills) is preserved outside GitHub: a full git
mirror at `legacy-backups/bot-legacy.git` next to this repo on the dev
machine. It had no releases to preserve. Nothing was migrated into this
repo. Per platform plan principle 8, legacy code is a read-only reference
for hard-won logic only (drivers, measurements, the wake-word lessons in
`.github/CLAUDE.md`), never for feature scope or UI; every legacy skill
has a one-line verdict in the review queue below before anything is
rebuilt (section 5.8).

## What this repo is

The robot companion: a body that pairs with the hub like a pod, keeping a
full replica of the household, running the same packages under the same
rules, using the hub as its brain when reachable and its own model when
not. Standalone it is a complete product, never a stub. Full
architecture: platform plan chapters 1, 3, 7, and 8; this file is where
the plan's robot chapter becomes decisions on the owned parts.

## Inputs to the design pass (2026-09-14)

In this order: the org standards; platform plan v2 chapters 0, 1, 3, 7,
8, 9, 12, 13, 14, 15; the outside inventory and first cut
(`home/data-scratch/bot-design/codex-draft.md`, a scratch file, never
committed; its every point is taken or rejected in "The outside draft,
reconciled" below); the owner's parts record (`owned-parts.md` did not
exist at the time of the pass, so the physical questions stay open and
are listed first in "Open questions"); the hub's spec, its chat design
pass (sections 0 to 15 and the coherence review of 2026-09-14), the
companions brief, the media conversation program, the engine as built
(`home/docs/dev/session-a.md`, `turnEngine.ts`, `turnSignal.ts`,
`turnContext.ts`, `memoryJudge.ts`, the two supervisors, the `websearch`
package); the legacy mirror where a claim needed verifying.

The owner's three hard constraints, unchanged: the hardware is fixed to
the owned parts; expressive head movement (the glance, the tilt, the
nod, the perk-up, the settle, idle breathing, speaker tracking) is a
selling feature and a first-class layer driven by the engine's own
`TurnSignal` and `ReplyPlan`, so motion begins before the reply's first
word; and the robot reuses the hub's code as the same pinned packages and
runs in three complete modes.

## The design

### 1. Three modes, one product

| Mode | What runs where | What the family notices |
|---|---|---|
| Connected (paired, the hub reachable) | The robot's own processes do wake, endpointing, speech to text, speaker evidence, presence, expression, playback and physical safety. The hub runs the turn (routing, recall, tools, guards, the composer, the judge) against the hub's store and streams the signal, the plan and the reply to the robot. Accepted records replicate down; the robot's own writes go up. | The hub's model and the hub's knowledge, in the robot's voice, with the robot's face and head. |
| Paired, unreachable | The same household runtime on the robot runs the same turn against the replica with the local model and the locally configured sources; every write goes to the outbox; reconciliation on the next contact. | One short line the first time ("I can't reach the hub, so I'll use my smaller brain here"), then ordinary conversation. No repeated apologies. |
| Robot-only (never paired) | Everything local, authored on the robot's own screen: people, settings, companions, enrollment, bindings, lists, timers, memory. | A complete robot. It never mentions a hub it does not have. |

"Complete" means every promise the product makes is kept locally with the
local model's intelligence and whatever sources the household configured;
it never means equal model quality or fresh web data with no network. A
capability that is not available says so once, in the register guard's
voice, never as a stock disclaimer on every reply.

Internet reachability and hub reachability are two different facts. The
robot tracks both and never confuses "the hub is down" with "the web is
down": a typed source (weather, the media package, the knowledge package)
works robot-only with internet and no hub; a hub-owned integration (a
credential the hub holds) does not.

### 2. The shared-runtime boundary (the draft's P0, decided)

**Decision: two processes on the robot. The household runtime is the
hub's own TypeScript code, run on Bun on the Pi as the same pinned
packages; the body is Python and owns every piece of hardware.** The
household runtime is the turn engine, the turn context and signal, the
guards and the one output boundary, the safety classifier, the memory
store and judge, the scheduler, people and settings and grants, the
package host, the link and the replica, and the schema UI service. The
body is capture and playback, wake, endpointing, direction of arrival,
speaker and face evidence, presence, the head, the eyes and mouth, power
and thermal, the interlocks, and the expression layer. One IPC boundary
between them, on a local Unix socket, with typed, bounded, cancellable
messages; the household runtime is the only writer of household records,
and the body submits typed observations and host results, never rows.

Why this and not the alternatives:

- *A Python port of the engine* violates principle 1 and the owner's
  constraint outright. `turnEngine.ts` imports about thirty hub modules;
  a port is thousands of lines that drift on the first hub fix. The
  hub's backlog carries "Python ports of the shared floor" as required
  for Robot v0.1; this decision retires that item (the floor runs on the
  robot as the same code) and the coordinator is told so.
- *The hub as a required brain* violates principle 2.
- *Bun on the Pi* is a stack deviation (STACK.md names Python for the
  robot) and is justified here as the org rule requires: the robot's
  hardware libraries stay Python, which is the reason STACK.md gives
  for Python; the household runtime is not robot code, it is the hub's
  code running on a second node, and STACK.md already names Bun for it.
  Bun ships `linux-aarch64`; `sherpa-onnx-node` (the hub's STT binding,
  in-process under Bun today) ships `linux-arm64`. The measurement that
  says the Pi carries it is M-01 below and is taken before any robot
  code depends on it.

What the hub must do first (named hub items, filed by the coordinator):

- **RUNTIME-01 (hub):** the household runtime as a workspace package the
  hub itself runs. Today the engine is a set of files under
  `backend/src/lib` reaching the hub's database, settings, package host
  and supervisors through `@/` imports. The extraction makes the stores,
  the supervisors and the surface-specific pieces (the voice sidecar,
  the platform launch adapter, the data directory) injected
  dependencies of one package, with the hub as its first consumer.
  Only after the hub runs it can the robot pin it; the robot never
  copies files. `turnSignal.ts` and `turnContext.ts` are already leaf
  modules (no engine, no database); `hlc.ts` needs only its seed
  function injected.
- **SURFACE-01 (hub):** `robot` admitted to `IMPLEMENTED_SURFACES`
  (`turnEngine.ts:79`, rejected today at `:98`), with the surface
  discriminator the plan promises: spoken presentation (one sentence,
  no links read aloud, "it's on your phone"), memory sensitivity
  (`sensitive` withheld unless present and alone, section 6), and the
  `present` list on the turn.
- **WIRE-01 (hub):** the signal and the plan on the wire. Today
  `TurnStreamEvent` is `turn_meta | delta | spoken_cue | done | error`
  (`wire.ts:117`), and the frozen signal reaches only the log line and
  the turn row. The robot needs `signal` right after `turn_meta` (it is
  frozen before routing, so it costs nothing) and `plan` before the
  first delta when ACT-03 lands, plus `cancel`. Section 5 is the
  consumer's contract.
- **spec-v0.1.0 (Jesse's call, a release):** the tag the robot pins.
  Zero tags exist in `home` today.
- **`spec/link/` (hub v0.3):** the envelope, the op, the never-sync
  allowlist, the states; section 7 adds what the robot needs in it.

The Deno package host runs on the robot as the hub's host does, one
Deno process with Workers and per-worker permissions (plan 4.9). Tier 0
recipes run in the shared TypeScript interpreter. The Python recipe
interpreter and host emulator stay in `home/spec/` as the public
conformance oracle the catalog's CI runs and as the proof that recipes
are language-neutral (Go may need a third); under this design they have
no production consumer on the robot, and that is recorded rather than
hidden: nothing on the robot runs a recipe through Python.

The voice seam is `spec/voice/`, the same contract the hub's own STT and
TTS use. Capture, AEC (on the array, from its own line-out reference),
wake, VAD, endpointing and direction of arrival are the body's, because
they are always-on, latency-critical and tied to the audio device and
the physical mute. Speech to text and synthesis are the household
runtime's, through the same `sherpa-onnx` binding and voice packages the
hub uses, because that is the same code. Audio crosses the socket as
16 kHz mono frames; the pre-roll cap (0.3 s of audio kept ahead of the
speech onset and trimmed while waiting, because Moonshine tiny returns
nothing behind half a second of silent head), the retry from the onset
byte and the 6 s wake patience live on the capture side, where the
legacy robot fixed them (`hal/drivers/voice.py` in the mirror).

Boot order, every mode: the body first (safe outputs, the mute state
read from hardware, the interlocks, capture, wake), then the household
runtime (the encrypted store, the outbox and watermarks, the HLC seeded
from every HLC-bearing table as the hub does, pinned artifacts checked),
then the engines (embed first, chat, the judge last and only when idle).
Wake, stop and the screen are ready before any model is warm. A ready
badge never lights on a stub engine.

### 3. Spec-first records a robot-only household needs

Every record the robot writes is the spec shape from first boot. Where
the spec is silent, the change goes to `home/spec/` first, as a proposal
this section states and the coordinator files; the robot never writes a
private shape and never fills a field with a lie to pass a fixture.

- **Person provenance for a household that has no hub.** Today
  `Person.source` is `hub | local`, with `local` defined as "a robot-only
  guest, never synced". A person created on a never-paired robot is
  neither. Proposal: `source` gains `standalone`, "authoritative on the
  robot that created it because the household has no hub; becomes `hub`
  by the adoption transaction, never by a translation"; every record
  gains nothing else, because the HLC's node component already names
  the origin device, and `local_only` already says "never leaves".
  `Entity.source` already has four values and gains `standalone` too.
- **Adoption is an op, in the log.** A new op kind `alias` in
  `spec/link/`'s op shape: `{ entity, from_id, to_id, prev }`, applied as
  one durable transaction on both sides that rekeys every referencing
  record (turns, memories, entities, relationships, grants, lists, jobs,
  bindings, rapport, open questions, tombstones), with the count of
  references verified on both sides before the step completes (plan
  7.4). Sealed local templates relink their subject key locally without
  the template ever moving. An interrupted adoption resumes from the
  job, idempotently, never a half-adopted household. Local-only people
  stay local by explicit choice on the adoption screen.
- **Device ownership on a shared robot.** `Device.person_id` stays
  required and means "paired by": the admin who approved pairing holds
  the doorkey token (plan 7.4 says exactly this). Who is speaking is
  never read from it; that is the turn's `speaker_evidence` (section
  6). COMP-06's open shared-device question is answered by that split,
  not by a nullable owner.
- **Speaker evidence and presence on the turn.** `conversation-turn`
  gains `speaker_evidence` and `present` (the shapes in section 6), and
  `turn-signal.age_band_basis` gains `claimed_profile`. This is the
  record the spec's own "confirmed present and alone" predicate on
  `sensitive` reads; today three schemas state the predicate and nothing
  defines its input.
- **Jobs, commands and lists.** The hub's backlog carries "a spec-or-
  local verdict for each hub-internal table". The robot's need decides
  three of them: scheduled jobs (a timer set on the robot survives a
  reboot and, once paired, is owned by the node that will deliver it,
  with the hub told so no second alarm fires), commands ("when I say X"
  works standalone) and lists (already spec-shaped) are spec records;
  notification deliveries, cloned voices and model download jobs stay
  local. A job carries `deliver_on: device id`, and the delivering node
  is the only one that fires it.
- **Robot-only settings keys.** Declared by the robot in the registry's
  own format and sent on `hello`; the hub stores no copy (plan 3.2).
  The robot's keys are `device` scope, which no hub key uses yet; the
  first ones are the expression envelope (section 5), the mute
  behavior label (section 9), the idle policy and the local search URL
  (section 8). Two keys today are `honoured_by: [home, bot]`; every key
  a robot honours is marked as the robot claims it.
- **The capability grant list.** The robot's twenty-item grant list
  (`safety_stop`, `drive`, `camera`, `microphone`, and the rest, plan
  3.1) is hub v0.3 work in the spec's own words. Until it lands the
  robot's authorizer reads the household's roles and the ceiling, and a
  physical action needs an adult present and confirmed (section 6).

### 4. The local engine set

The engine rule holds: llama-server is the only engine the supervisor
launches, on the hub and the robot. What the robot pins per role, and
the measurement that decides where a decision is still open:

| Role | v0.1 decision | Measurement first |
|---|---|---|
| chat | llama-server on the Pi's CPU, `taskset` to four cores, Q4_K_M, `--cache-reuse 256`, the prefix cache primed with the same stable prefix as the hub. Candidate models in order: Qwen3-1.7B, then Qwen3-4B if it fits the budget. | **M-02:** the hub's real rendered prompt (stable prefix plus a volatile zone of the bench's own turns, the ordinary tool set) on the owned Pi, three seeded runs of the conversation fixture per model, first delta p50 and p95, generation tokens per second, RSS. Decision rule: the largest model whose first delta p95 is under 2.5 s with the prefix cached ships; if the 1.7B misses it, M-03 is promoted into v0.1. |
| a Hailo chat provider | Not an engine. If it is ever used it is a local OpenAI-compatible provider under plan 4.11's own rule ("any OpenAI-compatible endpoint is a provider"), a `platforms: [bot]` sidecar the household runtime addresses by URL exactly as `MAIPAI_LLAMA_SERVER_URL` works today, with its own `ModelCapabilities` record and the same safety floor outside it. Not in v0.1 by default. | **M-03:** the rendered prompt's token count against the HEF's 2,048-token ceiling (CHAT-12's budget applies; nothing required is dropped to fit), the legacy 0.62 s first reply with retained context re-measured on the current HailoRT, and the cost of sharing the HAT with vision (one LLM or VLM resident, a 3.5 to 7.6 s swap). If the prompt does not fit, the option closes. |
| embed | The hub's nomic-embed-text-v1.5 Q4_K_M (84 MB, 768 dimensions) through llama-server, so the robot is in the hub's vector space: the routing corpus embeds once, ACT-02's heads load, and `embedding_space` reads `hub-nomic` on both nodes. The plan's "MiniLM on the robot" line is superseded by this measurement unless it fails. Embeddings are still regenerated on receipt and never sync. | **M-04:** embed latency per utterance on the Pi (the routing path pays one embed on a literal miss); acceptance under 60 ms warm. |
| judge and background | The 4B (Jesse's decision, MEM-05), on the CPU at the lowest priority, preempted per fact by any interactive turn as the hub's judge is, draining only the robot's own offline turns when paired (the hub judges hub-owned turns) and every turn when robot-only. | **M-05:** seconds per judged turn on the Pi with the prompt cache, and the RSS with `--cache-ram 0`; the drain of a household day (about 300 turns) must fit the robot's idle hours on the dock. If it does not, the queue is bounded and reported as a Repair, never a smaller judge chosen silently. |
| stt and vad | Moonshine tiny and Silero through `sherpa-onnx`, the hub's own `stt.ts`, in the household runtime. | **M-06:** endpoint-to-transcript latency on the array, p50 and p95, on the robot-only bench rows (same-breath command, long pause, tail-syllable wake, empty transcript). |
| tts | A voice package with a Piper backend through `sherpa-onnx` (the lineage proven on the Pi), behind the same `spec/voice/` contract as the hub's Pocket TTS. The companion's `voice` binding names a voice package; if that package is not installable on the bot platform, the robot uses its default voice and shows "voice not available on this robot" on the companion's settings row, never a silent substitution and never a different companion. | **M-09:** time to first audio sample for a one-sentence reply per voice, and Pocket TTS on the Pi as the measured candidate. |
| speaker id | `sherpa-onnx`'s CAM++ speaker embedding, local, in the body. | **M-07:** the SPEAK-01 acceptance on the array with three enrolled roster voices; the threshold and margin are set by that run, never the legacy defaults (0.6 and 0.10). |
| wake | Our own trained model only, in the openWakeWord format both trainers produce (the legacy robot shipped its own `hey_maipai.onnx`, v2 calibrated at 0.8, with an in-source claim of zero false accepts per hour at 85 percent recall on real audio whose recording set must be re-verified before the number is trusted), scored in the body through the ONNX runtime with the feature front-end the trainer used. The stock `hey_jarvis` (the hub's phase-1 detector, non-commercial) never ships on the robot; the license of the shared front-end models the artifact needs is verified by the coordinator before v0.1. `sherpa-onnx`'s keyword spotter (Apache 2.0, a phrase from text, no training) is the measured alternative if the trained model misses the gate. | **M-08:** false accepts per hour and false rejects on held-out real-microphone recordings through the array, at the runtime threshold, plus the near-miss set ("hey my bike"); the artifact ships only with those numbers recorded. |
| vision | The Hailo's YOLO, SCRFD, ArcFace and pose pipelines lifted from legacy (measured 19, 20, 2 and 28 ms), one capture owner, derived observations only. The still-image request the hub can make is a v0.2 host call. | **M-10:** the full concurrent load (capture and tracking, wake, an interactive turn, playback) on the Pi: CPU, RSS, thermal over an hour, so the concurrency numbers are real before the head moves. |
| generation | Unavailable on the robot; a request is answered honestly and, when paired, offered to the hub. | none |

Process and memory budget: **M-01** measures the resident set of the
body, the household runtime, the Deno host, the three llama-server
processes and the vision pipeline together on the 16 GB Pi with the
chosen chat model, and records it in `budgets.json`'s robot row. No robot
code that depends on the runtime split lands before M-01 is recorded.

Two rules the measurements cannot move: `enable_thinking: false` on
every request (a robot reciting its chain of thought is a correctness
bug), and no `--cache-reuse` on the judge (its prompts never repeat;
the hub measured the cache growing the process to 11 GB).

### 5. The expression layer

A robot package (`platforms: [bot]`, category "Robot body") beside the
shared engine. It consumes the engine's frozen `TurnSignal`, the
`ReplyPlan` when one exists, the turn's phase and the body's own safety
state. It runs no model, never reads the reply text for sentiment, and
keeps no personality of its own: a companion may select a permitted
expression style through the binding contract only, and the style is a
scale on the envelope, never a second vocabulary.

**The vocabulary**, one declaration in the package that settings, the
bench and the screen all read:

| Primitive | Trigger | Form on the two owned axes (yaw, pitch) and the eyes | Suppressed or reinterpreted when |
|---|---|---|---|
| listen | wake, or a person addressing the robot before wake | eyes open toward the speaker's direction, a small yaw toward the direction of arrival, neck steady | mute engaged (eyes show the mute state instead) |
| glance | a new speaker's direction, or plan `react` with a real physical target | a short yaw excursion toward the target and back, eyes leading the neck | no target with a fresh track; never a sweep through a person's face; `point` never invents a physical place for a source |
| tilt | signal `question`, or plan `ask_back` | a small pitch change with a slight yaw and an eye pose; there is no roll axis, so the "curious tilt" is pitch and eyes, never a promised lateral tilt | the question is a safety refusal or a confirmation ask (a steady look instead) |
| nod | signal `inform` with an allowed `react` or `say`, or a backchannel | one compact pitch dip and recovery; it means "heard you", never "saved that" or "that is true" | plan `say` forbidden by the guards (an unsupported claim), `defer`, a safety line, a tool failure |
| perk | `happiness` at `moderate` or `high` with `react` allowed | a slight pitch rise, quicker but inside the envelope, eyes brightened | the companion forbids playfulness, the child band's negative-emotion rule, any intensity never exceeds the envelope |
| attend | plan `care`, or `sadness` or `fear` at any intensity | a minimal orient and hold, a slower settle, eyes soft | never a dramatic imitation, never a shake, never an approach |
| settle | signal `closing`, plan `close`, `defer`'s quiet variant, or end of turn | a small return toward neutral, eyes relax | never a power-off drop; sensing stays on |
| breathe | no active turn and the idle policy allows it | a very small, smooth pitch and yaw oscillation about neutral, the legacy 8 s cycle as the starting value | a hand or face near (ToF or touch), service mode, dock transitions, thermal or power pressure, uncertain geometry, mute engaged |
| track | a current partner with a fresh track or a fresh direction of arrival | deadbanded gaze with velocity and acceleration limits | stale or conflicting tracks (freeze, then settle); never a snap between voices |
| stop | e-stop, touch conflict, barge-in, a stale controller, a lost link mid-turn, any reflex | the trajectory cancels into the measured safe stopping behavior | never suppressed by anything |

**The cue contract.** The engine emits a typed `ExpressionCue` at fixed
points of every turn, whatever produced the reply, and the package maps
the cue to a primitive. The cue carries the turn id, a cue sequence
number, the phase, the signal fields the primitives read (`primary_act`,
`expressed_emotion`, `emotion_intensity`, `target`, `repair`,
`age_band`), the plan's move states when a plan exists, and the reply
source. The points, with the engine path inventory from
`prepareTurn()` so the universal claim ("every path cues") has its
enumeration:

| Phase | When | Paths that produce it |
|---|---|---|
| `heard` | end of speech (VAD end), before transcription | the body's own, every turn |
| `signal` | the signal frozen, before safety and routing (`turnEngine.ts:1651`) | every turn, including the safety refusal, the credential line, the forget and household commands, the literal pattern, the plugin run, the unspoken-argument ask, the parked confirm, the plugin error, the model turn |
| `resignal` | the protocol layer replaced the signal on a pending-ask answer (`:1718`), or a literal win froze a directive (`:1812`) | the confirm yes and no, the bound value, the cancel, the literal directive |
| `plan` | the plan built, before the prompt (ACT-03; absent until then, and the mapping falls back to the signal alone) | every model turn; a fixed-line turn carries the engine's fixed plan (`say` required, the rest forbidden) |
| `outcome` | a package or command finished, or failed, before the reply text | plugin success, plugin error, command success and failure, the lookup miss, the tool-call resolution |
| `speak` | each sentence released by the output boundary | every reply source, including a guard replacement and the malformed line (the cue says `replaced`, and the nod is withheld) |
| `done` | the turn finalized | every turn |
| `cancel` | barge-in, an abort, a link loss mid-turn, an engine error after `turn_meta` | the streaming path's abort signal; the body's own barge-in; the link's circuit breaker |

Where the cue is authoritative: in connected mode the hub's engine emits
it over the link (WIRE-01) and the robot renders it; in the other two
modes the same engine emits it locally over the socket. The body never
classifies the utterance a second time to cover a late hub cue. A cue
that arrives after its turn's `done` or `cancel`, or out of sequence, is
dropped and counted; a link loss clears every cue id of the old turn,
and the local continuation is a new turn with its own cues, so the same
nod never fires twice. Engine-down and a stream error produce no
`TurnValue` on the hub today; on the robot they produce `cancel` with a
reason, and the eyes show "thinking stopped", never a frozen pose.

**Timing.** Measured on the body's monotonic clock: `t_heard`,
`t_cue_received`, `t_motion_command`, `t_encoder_onset` (the first AS5600
delta above the noise floor), `t_first_audio_out` (the first sample
handed to the playback device). Acceptance: cue to command under 50 ms
p95; encoder onset before the first audio sample on every eligible row,
with p50 and p95 of cue to onset reported, never a mean; suppressed rows
counted with their reason. The audio scheduler may hold a ready first
word for at most 100 ms waiting for a safe onset; if motion cannot start
safely it is suppressed and speech continues. An urgent safety utterance
is never held for an animation.

**Arbitration.** One controller in the body reads encoder feedback,
expires targets and detects disagreement and stall. Priority: physical
inhibit and reflex, then service and calibration restrictions, then
consented tracking, then expression, then idle. Small compatible
trajectories blend inside one limiter; a full-amplitude track plus an
expression is never summed and clipped after. Loss of the controller,
the link or the model never leaves a trajectory running; whether the
safe state is hold, controlled settle or release is an owned-build
measurement (section 10), and until it is taken the default is a
controlled settle at the calibrated slow rate.

What motion must never say: anger or disgust acted out at a person, a
nod on an unexecuted or unsupported claim, a visible endorsement of a
harmful claim, a wheel movement to express anything.

### 6. Speaker evidence on a shared device

The robot is a shared surface. Identity is per turn, never sticky for a
conversation (COMP-06). What the body knows about who is speaking is
evidence, typed on the turn, and the engine reads the type, never a bare
score.

`speaker_evidence` on the turn: `{ person_id | null, basis: signed_in |
voice | face | voice_and_face | claimed | unknown, level: confirmed |
tentative | unknown, present: [{ person_id | null, basis, level }] }`.
Rules:

- `signed_in` is the robot's own screen (a PIN or passkey on the DSI
  touch surface) and is authoritative for turns typed or tapped on the
  screen while that touch session is live; it never carries to a voice
  turn from across the room.
- `confirmed` is a voice match above the calibrated threshold with the
  margin and no conflicting face on the speaking track, or a face match
  on the speaking track with a tentative voice agreeing. `tentative` is
  one signal alone below the confirmed bar. Direction of arrival ties a
  voice to a track; it never identifies anyone.
- `claimed` is the answer to the who-is-speaking ask, or "it's me,
  Sage". A claim selects the person for personalization: their own
  companion binding, their person-scope recall of ordinary records, and
  the attribution of what they said. A claim is never access: the
  content ceiling, `adult_only` disclosure, `sensitive` records,
  unrestricted mode, a consequential action and any settings write
  need `confirmed` or `signed_in`. The band for a claim is the claimed
  person's register band only when no enrolled print for that person
  contradicts it; with an enrolled print that disagrees, the turn is
  `unknown`.
- A close tie between two enrolled people is `unknown` with the two
  candidates carried, and the ask names them ("Sage or Bramble?"),
  because a child scoring a whisker under a parent is family, not a
  stranger (the legacy gallery's three-way answer, kept). A far miss
  against every enrolled print is `unknown` with no candidates and the
  open ask.
- `unknown` gets the device's binding, an anonymous context, the child
  band (`age_band_basis: unknown_speaker_default`), and the ask before
  a personal memory is read, a personal state is changed or an
  age-dependent decision is made (COMP-06, the pass's section 13 part
  6). The org invariant holds by construction: nothing reads the
  utterance for the band, and a claim cannot raise access.
- `present` is the body's list of people with a fresh track or a fresh
  voice in the last thirty seconds (a starting value, measured), each
  at its own level. "Confirmed present and alone" is exactly one entry
  at `confirmed` and no unknown track; `sensitive` records enter the
  context only then, and the audience is rechecked at speech delivery,
  not only at turn start: a new face during a sensitive sentence stops
  the sentence and the settle primitive plays.
- Face and voice templates are enrolled with consent on the robot's
  screen, sealed locally, never replicated, never updated from an
  uncertain match, deleted with the person on every robot. A guest's
  voice is never enrolled silently.

The device token is a doorkey; the wake word is a slot; the person is
the evidence. A PIN on the screen or the hub's approval is the authority
for anything consequential.

### 7. Pairing and sync semantics

Plan 7.1 to 7.4 are the design; this section decides what they leave
open.

- **HLC.** One implementation, the hub's `hlc.ts`, on both nodes.
  Compare numerically on `wall_ms`, then `counter`; the node component
  is never compared lexically for authority. **Tie authority:** ties on
  identical `wall_ms` and `counter` are resolved by a `node_rank` the
  link assigns (the hub is 0, each robot its pairing sequence), looked
  up from the device table, so "the hub wins ties" is a policy in the
  merge, not an accident of device id strings. The hub's comparator
  gains the rank lookup in `spec/link/`'s item. On receipt, the local
  clock advances to `max(local, remote) + 1` per the HLC algorithm; a
  remote `wall_ms` more than an hour ahead of local wall time still
  merges (order is the clock's job) and raises a Repair naming the
  drift. A robot with no time source since boot keeps stamping from its
  RTC and marks time unsynced; relative timers work, absolute ones say
  so.
- **The bootstrap snapshot** is taken inside one read transaction on
  the hub at a log position, and the pull starts at that position, so
  nothing written during the snapshot is lost between snapshot and
  tail.
- **Tombstones** stay in the log forever on both sides; the outbox
  spool never drops a durable op (the legacy queue's "max 500, drop
  oldest" is rejected). Under disk pressure the robot raises a Repair
  and pauses non-durable telemetry, never the outbox. A forget on
  either side wins against any stale replica or restore.
- **Side effects.** Every consequential action has an operation id.
  After a disconnect with an unknown outcome the robot asks the hub
  for the turn's status on reconnect before anything is retried; if
  the hub is unreachable a consequential action is never re-executed
  to finish a sentence; an idempotent op (a list add, a memory) is safe
  to resend by id. The reply says what is unknown.
- **Continuation after a lost link mid-turn.** Plan 7.2 says a turn in
  flight is never resumed on the wire; plan 7.5 says the local model
  continues mid-sentence. Both hold: the wire turn is dead; the local
  continuation is a new turn whose prompt carries the sentences that
  were actually spoken as the prefix (from the body's playback ledger,
  never the generated text), with new cue ids (section 5) and the
  outcome ledger consulted so no tool runs twice.
- **Restrictive-wins** applies immediately on both sides; a loosening
  waits for a newer hub HLC (plan 7.3). Robot-origin person and grant
  ops land in pending review on the hub.
- **A replaced hub** is a new pairing: the old token is frozen, the
  robot keeps working locally, and adoption runs into the replacement.
  A restored same-instance hub proves its identity and reconciles
  tombstones and watermarks before ordinary traffic (`409 rewind`).
  Unpair asks once: keep the household as local, or wipe.
- **Never synced** (the allowlist, with a grep test on the robot too):
  face and voice templates, the utterance log, captures, the flight
  recorder, credentials and their hashes, sessions, embeddings,
  pairing tokens, the device key.

### 8. Hub-less lookup: the default, decided

The evidence ladder is unchanged in every mode: a typed source first,
then the generic web rung, then the model's own knowledge for stable
facts only. What differs in the paired-unreachable and robot-only modes
is what is configured, never the ladder.

**Default: the generic web rung is off until the household connects a
search server.** Typed sources that need no account (weather, the media
package, the knowledge package) work with internet and no hub. The
`websearch` package is marked `platforms: [home, bot]` and reads the
same `search.searxng_url` setting; on a robot-only household the setup
screen offers "connect a search server" as the opt-in, with the privacy
row shown, and until then a question that needs the web rung ends the
ladder honestly ("I can't check the web from here") once, in the
register guard's voice. A time-sensitive question never gets a model
guess. The robot does not host a search server itself in v0.1 (RAM and
update burden on the Pi; M-01's budget decides whether v0.2 offers it
as a package). A direct keyless search provider is rejected outright:
no verified maintained provider, and "we are the user" forbids the
scraping and the block-handling it would need.

### 9. Privacy invariants that must be physical

- **The microphone mute is a physical cut or it is not called a mute.**
  The invariant (plan 8, accessibility): when muted, no audio reaches
  any process, and the indicator is driven by the same physical state,
  never by software. The legacy robot had no such cut: its mic-cut
  switch and camera shutter left the design on 2026-09-01, the mute
  became a software hush on the heart knob (an amber "mic off" glyph),
  and its privacy page said so honestly. On the owned parts the
  mechanism is an owner question (the first in "Open questions"):
  whether a switch part in the build can cut the array's USB 5 V with a
  contact the Pi can read. Until it is answered and wired, the robot
  ships the honest software mute, labeled "software mute" on the screen
  and in the settings key's description, the physical cue is not
  claimed, and the accessibility promise is recorded as not yet met. No
  new part is proposed here. The colors of the mute and recording cues
  are the platform's declared state set (UI.md), not a robot decision;
  legacy used amber for muted and red for recording, and the plan's
  text says red for the mute, which the coordinator reconciles in the
  declaration once.
- **Raw audio and images never leave the body process** except as a
  consented enrollment or recording, and never leave the robot except
  as the transcript, the derived observations and an explicit
  still-image request the hub makes (v0.2). Nothing ambient streams to
  the hub. The robot's privacy page carries the "what leaves the
  robot" table: the hub (transcripts, records, state), the configured
  sources, the update check.
- **Every state a spoken cue carries is on the light ring and the
  screen, and every screen state has a sound** (plan 8). Recording (a
  consented capture) has its own visible and audible indication for its
  whole duration.

### 10. Safety envelopes for motion and movement

Nothing in software certifies a mechanism. The envelopes come from
measurements on the assembled owned parts, and the body refuses
expression until they exist.

- **The head.** A calibration mode runs first: find the mechanical stops
  per axis from the encoders, set soft limits inside them by a margin,
  measure the unloaded and loaded (final shell mounted) servo current
  across the range, the settling time, the maximum velocity the rail
  sustains without sag on the audio and compute rails, and the pinch
  clearances at every pose. The expression envelope (amplitude, velocity,
  acceleration, jerk, a current cap) is written from that run into the
  robot's device-scope settings with the run's date; the primitives are
  fractions of it. The legacy 8 degrees per 50 ms tick (160 degrees per
  second commanded) and the legacy pan and tilt bounds are camera-assist
  configuration and are not used as limits. Pinch protection is
  mechanical plus the validated limits; a hand or face near (ToF,
  touch) freezes the head; the e-stop chain must cut the servo rail
  (owner question).
- **The drive.** Out of Robot v0.1's scope entirely: the base motors
  are not commanded, and their controller's enable is never asserted,
  until a later stage with its own measured stopping distance,
  rollaway and stability envelope on the loaded body. The legacy
  arbiter's priority logic (teleop over autonomous, the 0.5 s lease,
  the watchdog, the cliff, impact, tip and freefall stops) is carried
  as logic and tests when that stage comes, never as numbers. A brake
  timer fallback with no feedback is not engagement.
- **Power and thermal.** A robot-only policy over the owned sensors and
  rails that gives the shared resource governor an admission budget.
  The legacy defaults (41 V float, 39 V rebalance, a 25 percent UPS
  reserve, a 5 s goodbye grace, the 20 percent return request, the
  cold-charge inhibit) are archived software settings, not limits for
  the owned pack; the charger, BMS, gate and interlock policy is
  resolved against the actual parts before charging control is
  enabled, and an unknown pack temperature or a failed sensor never
  substitutes the board's temperature. Under pressure the order is:
  suspend idle motion and background jobs, announce the reduction once,
  persist state, shut down safely.
- **The e-stop and the bumpers** are in the fail-safe chain that cuts
  motion power, independent of the Pi. In legacy they were pure power
  interruptions with no sense line, so software could not say whether
  the stop was pressed; the fresh build wires a sense contact to a GPIO
  input where the owned switch has a spare contact, and otherwise infers
  the state from the rail voltage the INA228 already measures, so the
  body reports the stop and never gates it. The legacy brake interlock
  (normally engaged, released only by a heartbeat into a monostable, a
  latched fault when feedback disagrees) is the right shape and is
  carried as logic when the drive stage comes.

### 11. The bench

One bench, the hub's own (`conversationFixture.ts`, `conversationRunner.ts`,
`conversationScore.ts`, `conversationLive.ts`), run in three fresh states
with a transport adapter and the body's measurement adapter, never a
second corpus with easier answers:

1. **connected:** the hub's engine over the link, the robot rendering;
2. **paired, unreachable:** the same replica seeded, the link cut on
   purpose, the local model;
3. **robot-only:** a locally authored seeded household of roster
   people.

Every run's header records the mode, the source revision and the pins
(spec, runtime, packages), the engine build, the model hash, quantization
and context, a sanitized description of the Pi, the HAT and the RAM
(never a hostname), the thermal and power state, and per-stage timings
(the hub's `[turn]` line plus the body's motion and audio stamps). A
remote 8B result is never described as local performance.

Robot-only rows, in the fixture's own expectation kinds plus the body's:

- wake and endpointing: the same-breath command, a long pause after
  the wake word, the tail-syllable false wake, an empty transcript,
  noise, accented and overlapping speakers; the held-out real-mic wake
  numbers (M-08);
- double-talk and barge-in: self-wake at real playback levels, a "stop"
  said over speech, the exact spoken prefix in history, no
  acknowledgment of an unexecuted action;
- speaker evidence: speech under two seconds, an unknown voice, a close
  tie, conflicting face and voice, two speakers, a visitor entering
  before a sensitive sentence, "not me", the device binding fallback,
  the child-band unknown speaker;
- expression: the same inform, question, happy disclosure and closing
  in all three modes produce the same primitive from the same signal
  and plan while the envelope obeys local state; every non-model path
  (a literal recipe, a safety refusal, an ask, a confirm, a tool
  failure, a timeout, a cancellation) is a cue or a counted
  suppression; motion onset before the first audio sample on every
  eligible row with command and encoder stamps separate; late, missing,
  duplicated and out-of-order cues never move the head twice or late;
- body safety: encoder disagreement, a stuck servo, an exhausted rail,
  touch or a near face, a blocked axis, camera or direction loss,
  e-stop, thermal and low reserve, dock transitions, all stopping or
  suppressing without the hub or the model;
- the link: loss before accept, after a tool ran and before its ack,
  mid-speech, during sync; a duplicate op, a clock rollback and a far-
  future peer clock, conflicting updates, a stale snapshot, a corrupt
  pairing file, a wrong certificate or instance;
- forget and deletion surviving offline writes, reconnect, restore and
  adoption; local-only records, templates and secrets never in a sync
  payload (the never-sync grep test, every producer enumerated);
- robot-only life: people, settings, a companion set and a binding
  created on the screen, a restart, recall, the local judge draining,
  a timer while offline, a USB export and restore, a later pairing
  with matching counts and reference integrity, a role restriction
  applied within a minute when reachable;
- load: the real rendered prompt at the local context, conversation
  plus perception plus playback plus the judge at once, background
  preemption, a model crash, a missing artifact, a full disk, internet
  down against hub down.

Deterministic tests drive fake sensors and scripted cues through the
repo's own pytest and `bun:test` structures; physical tests then prove
encoder motion, clearance, stability, safe stop and the mic-to-speaker
timeline on the final parts. A screenshot or a recording used as
evidence is seeded, opened and judged. No browser window, no machine
preference, no live model in a per-commit test.

### 12. Robot v0.1 against the hub's state and queue

The hub today (2026-09-14): RECALL-02, OUT-01, ACT-01, REG-01 and EXP-01
landed; LOOKUP-01, ASK-01, MEM-06 core, AGE-01 core, CHAT-13 and CHAT-16
with ACT-03 core queued in that order; no spec tag; no `spec/link/`; no
runtime extraction; the robot surface rejected at one line; the signal
not on the wire; no plan at runtime; the companions block, SPEAK-01 and
WAKE-02 after CHAT-16.

So Robot v0.1 is two tracks. The **body track starts now** and depends on
nothing in the hub queue: the parts record, the wiring from-to tables,
the lifted HAL drivers, the array firmware check, the calibration mode
and the head envelope, the vision pipeline, the presence funnel, the
expression package driven by scripted cues on the bench, capture and
endpointing with the legacy fixes, the mute question answered, and
measurements M-01, M-06, M-07, M-08 and M-10. The **household track
waits on named hub items**: RUNTIME-01 (the package the robot pins),
spec-v0.1.0, SURFACE-01 and WIRE-01 for connected mode, `spec/link/`
and hub v0.3 for pairing. Local conversation on the robot (paired-
unreachable and robot-only) needs only RUNTIME-01 and the tag; the
expression layer's plan-driven half needs ACT-03; the composer's voice
rules need CHAT-16; speaker evidence beyond the child-band default needs
SPEAK-01's hub half and the section 6 spec fields; the bindings need
COMP-06.

Robot v0.1 is defined as chapter 13 defines it and is tagged when hub
v0.3 ships the link: the bench Pi converses and remembers across reboots
with no hub; pairs; a child's `drive` deny on the hub refuses "follow
me" within a minute (with drive itself out of scope, the refusal is of
the request); "turn off the kitchen light" works with the hub off and
"open the garage" needs the physical confirm. This pass adds the
owner's constraint as a v0.1 proof: motion begins before the first word
on the bench's eligible rows, in all three modes, with the numbers in
the run header.

## The outside draft, reconciled

The inventory and first cut (Codex, 2026-09-14) was raw material. Each of
its points is taken, changed or rejected here, with the reason, the way
the hub's chat design pass handled its own outside reviews.

**Taken as written.** The reading of the three modes (connected,
paired-unreachable, robot-only) and the rule that "complete" means
functioning local behavior with honest capability reporting, never
equal model intelligence. The parity table's row-by-row conclusion that
every queued hub item stays queued on the robot until it is in family
use on the hub. Running the hub's TypeScript engine on the robot as the
same pinned package behind a local IPC boundary with Python owning the
hardware (section 2 makes it the decision). The expression package as a
product layer consuming the engine's own signal and plan, running no
model and reading no reply text; its primitive table; "a nod means
heard you, never saved that"; the two owned axes give yaw and pitch and
never roll, and wheel yaw never simulates it; the arbitration order;
the timing stamps and the rule that physical onset precedes the first
word; the 100 ms hold. The speaker-evidence rules: the device token is
a doorkey, a wake phrase is not authentication, presence is rechecked
at delivery, the legacy thresholds are code defaults, not calibrated
limits. The sync rules: HLC numeric, never text; tombstones never
dropped for capacity; adoption as a durable rekey with counts verified;
a replaced hub is a new pairing; credentials never transit ordinary
sync. The three hub-less lookup options and their costs (section 8
picks). The power and thermal posture and the warning that archived
numbers are software defaults, not limits for the owned pack. The bench
as the hub's own with a transport adapter and robot rows; the robot-only
row list; the header fields. The honest-transition wording for a hub
outage and the rule that a robot-only household never hears about a
hub. That new package names are not existing modules.

**Taken with a correction from the mirror.** The legacy 0.3 s figure is
the pre-roll kept ahead of the speech onset, not a post-wake silence
cap; the post-wake patience is 6 s. The legacy robot's wake model was
its own trained `hey_maipai.onnx`; `hey_jarvis` appears once, as a
diagnostic that proved the array's firmware fault. There is no XVF3800
firmware check in the legacy code; the finding is a documentation row,
and the fresh body adds the check to its self-test. The legacy link had
no instance verification (the ping's instance id was stored and never
compared) and no offline spool wired in; both are lessons about what
the fresh link must do, not transport code to lift. The legacy head has
no deadband and no acceleration limit, only a per-tick slew cap; the
deadband and the limits in section 5 are new requirements. The mute is
known, not unknown: legacy had a software hush only, the hardware cut
having left the design on 2026-09-01. The ToF count is two bought
against a seven-sensor design; the servo rail is a 2 to 3 A isolated
buck in the finished design against a 6 A bench supply and a stated
stall past 5 A, a tension the docs leave open (an owner question here).

**Changed.** The draft left the hub-less lookup policy to the designer;
section 8 decides it. The draft asked whether the llama-server-only
rule admits a Hailo adapter; section 4 answers that a Hailo path, if
measured worthwhile, is a local provider under plan 4.11's existing
provider rule, never an engine, and not in v0.1 by default. The draft
warned against inventing `Person.source: robot`; section 3 proposes
`standalone` spec-first instead of leaving the provenance undefined.
The draft's eight-step sequencing table becomes the two-track split in
section 12, because the body track has no hub dependency and should not
wait. The draft's LAN latency allowance table is not adopted as
acceptance: the bench measures each leg and the header records it; the
only gating numbers are the cue-to-command p95 and the onset-before-
first-word ordering. The draft's "shared-device ownership needs a
nullable owner" reading is answered by keeping `person_id` as "paired
by" and putting the speaker on the turn.

**Rejected.** The draft's suggestion that the plan's Python recipe
interpreter is the robot's production Tier 0 runtime: under section 2
the shared TypeScript interpreter runs on the robot and the Python one
stays the public conformance oracle. The draft's implication that a
Python port of the safety floor is required for v0.1: the floor runs
on the robot as the same code. The direct keyless search provider, in
any form. A separate robot mood or emotion inference of any kind.

## Review queue

Every legacy robot skill, by its concrete `id` in
`robot/robot/cognition/skills/` at the mirror's head (83 ids, including
the chat fallback; base classes, registry helpers and `calendar_facts.py`
are not skills). The draft proposed these verdicts; this pass confirmed
each against the design above and changed the ones marked. "Merge"
drops the old implementation for the named shared capability;
"Redesign" means a review and a decision before anything is built, not
a commitment; "Rebuild as designed" means the robot's own package built
to this record. A family-use verdict from the owner is still owed on the
rows that say so; nothing on this list is a requirement by virtue of
having existed.

| Legacy skill | Verdict | Reason |
|---|---|---|
| absence_check | Redesign | An opt-in check-in belongs to the shared initiative policy, never an assumed watch; family-use verdict owed |
| sight | Rebuild as designed | Bounded perception facts from the body through a robot host package (section 4's vision row), never model prose about what it sees |
| whereami | Merge | One local location and state capability with uncertainty stated |
| bodyparts | Merge | Installed parts are the device's capability declaration, declared once |
| can_you | Merge | Answered from ready packages and permissions, never a hand-written list |
| cannot_look_up | Drop | A failed lookup is a typed outcome at the one reply boundary, not a routed feature |
| compare_capture | Redesign | Consented image comparison only after the shared image and evidence contracts exist (v0.2's still-image host call) |
| content_rating | Merge | Shared media metadata and the content ceiling on evidence (the pass's section 13) |
| dictionary | Merge | The same `define` package |
| dismiss | Merge | The shared pending-ask and notification cancellation, one state machine |
| escalation_drill | Drop | A synthetic drill belongs to a bench, not a household feature |
| holiday | Merge | `almanac-holiday` |
| convert | Merge | The same `convert` recipe |
| math | Merge | The same `math` recipe |
| health | Merge | The robot's diagnostics package reports measured state only |
| home | Merge | The shared Home Assistant connector with the robot's own credentials when local |
| hush | Merge, changed | One quiet policy across surfaces; on the robot the hush is the software mute and is labeled so until a physical cut exists (section 9); mandatory safety and recording cues never hush |
| introduce | Redesign | Section 6: a claim personalizes and never grants access; enrollment on the screen with consent |
| myname | Merge | A scoped person edit after the right evidence level |
| whoami | Merge | The shared current-speaker state with an honest unknown |
| notme | Rebuild as designed | Clears the turn's speaker evidence and any claimed binding; section 6's correction path |
| remember_person | Merge | ASK-01 and the shared entity creation; no private schema |
| joke | Merge | The same `joke` package with its declared offline behavior |
| languages | Merge | Installed speech and model capability metadata, not a promise list |
| legend | Merge | Cue help generated from the robot packages' declarations |
| logbook_add | Merge | The shared explicit memory and note capability after scope review |
| logbook_query | Merge | Shared scoped recall, never a second search engine |
| shopping | Merge | `list-add` and `list-view` |
| lookup | Merge | The shared evidence ladder and ready lookup tools (section 8) |
| media | Redesign | Shared media packages; metadata and playback are separate acceptance items (Robot v0.2) |
| remember | Merge | Shared idempotent ingestion and explicit remember |
| find | Merge | Scoped recall; a live location is never inferred from an old memory |
| note_location | Merge | A shared entity location fact with source and clock |
| message | Redesign | Person-addressed delivery with consent through the notification system, never a robot-only messaging service |
| moon | Merge | `almanac-moon` |
| charge | Rebuild as designed, changed | A docking request constrained by the owned interlocks, and only after the drive stage; not v0.1 (section 10) |
| follow | Redesign, changed | Explicit consent, the current partner's identity, and a measured mobility envelope first; after the drive stage, not v0.1 |
| stop | Rebuild as designed, changed | Two halves: the physical stop is a body reflex with no hub and no model in the path; the spoken "stop" is barge-in at the boundary; both local in every mode |
| goto | Redesign, changed | Only after localization, routing and stopping evidence on the owned body; not v0.1 by inheritance |
| news | Merge | The same `news` package |
| on_this_day | Merge | `almanac-onthisday` |
| not_now | Merge | Shared pending asks and jobs with declared deferral |
| resume | Merge | Shared continuation; an executed side effect is never replayed (section 7) |
| persona | Merge, changed | Per-person companion sets (COMP-04) and the device binding (COMP-06); never a global persona switch |
| forget_all | Merge | The shared erase and tombstone lifecycle, local templates included |
| read_scene | Redesign | Local OCR with an explicit image source through the composer, after the still-image contract |
| recap | Merge | Scoped episode summarization (RECALL-02's rules), never copied lines |
| recipe | Redesign | An evidence-backed cooking capability if the family uses one; never the legacy route |
| record | Redesign | Explicit capture consent, a visible and audible recording indication, a retention policy (section 9) |
| recovery | Merge | Shared Repairs and health, with the robot's local recovery screen |
| reminder | Merge | The same `remind` package on the scheduler port; delivery ownership per section 3 |
| task_cancel | Merge | Shared job cancellation |
| task_snooze | Merge | Shared job update |
| task_list | Merge | Shared scoped job listing |
| robot_state | Rebuild as designed | One measured state from the presence funnel feeding the link, speech and the screen (plan 7.5) |
| routine | Redesign | Shared declarative routines on the scheduler port; no second orchestration engine |
| routine_home | Redesign | Opt-in shared home routine over available local hosts |
| routine_night_check | Redesign | Family-use and privacy verdict from the owner before any patrol scope |
| routine_watch | Redesign | A consented observation policy, never default watching; owner verdict owed |
| routine_check_in | Redesign | The shared notification and check-in policy, never a safety-monitor claim |
| routine_medication | Redesign | An explicit reminder only, no adherence inference |
| routine_list | Merge | Shared routine records and schema UI once designed |
| routine_edit | Merge | Shared routine editor and permissions once designed |
| routine_stop | Merge | Shared routine cancellation, with the immediate local physical stop where a routine moves anything |
| what_said | Merge | The last actually spoken reply from the playback ledger, never unheard generated text |
| scan_code | Rebuild as designed | A bounded local barcode and QR decoder; decoded content is untrusted data |
| screens | Redesign | Shared player devices and permissions, not the legacy discovery scope |
| showtimes | Merge | Future shared evidence-backed media lookup, no invented listings |
| idle_report | Drop | Unsolicited status chatter; the shared initiative policy decides what is said unprompted |
| where_are_we | Merge | One local location and state capability |
| heard_check | Merge | The shared voice repair behavior |
| greet | Merge | The engine's greeting act and the companion's register |
| help | Merge | Generated capabilities and the shared help UI |
| chat (the fallback) | Drop | The literal same turn engine replaces it (section 2) |
| sports | Merge | The same `sports` package |
| temperature | Rebuild as designed | Names the sensor it reports; pack, board and room are never conflated |
| time | Merge | `almanac-time`, with the unsynced-clock rule (section 7) |
| date | Merge | `almanac-date` |
| timer | Merge | The same `timer` package; the delivering node owns the alarm |
| tv_show | Merge | Shared media metadata lookup |
| weather | Merge | The same `weather` package, marked for the bot platform |
| web_search | Merge, changed | The same `websearch` package and setting; the hub-less provider is decided in section 8 (the household's search server, opt-in) |
| where_to_watch | Merge | Shared streaming-availability metadata with source, region and freshness |

## Roadmap

Against platform plan chapter 13. Robot v0.1 starts standalone and is
tagged when hub v0.3 ships the link; this record splits its work into
the body track (starts now) and the household track (waits on the hub
items named in section 12). `BACKLOG.md` carries the items.

| Chapter 13 says | This record's reading |
|---|---|
| Prepare the Pi with the lifted drivers | The body track's first items: the parts record, the wiring tables, the HAL drivers lifted as drivers, the array firmware self-test, M-01 |
| The head | Calibration mode, the envelope, the expression package on scripted cues, M-10 |
| The voice loop on sherpa-onnx | Capture and endpointing in the body; STT and TTS through the shared voice contract once RUNTIME-01 exists; M-06, M-08, M-09 |
| The local llama-server | M-02, M-04, M-05; the chat model chosen by the decision rule in section 4 |
| The safety layer | The same classifier as the hub, in the household runtime; the physical layer in the body |
| Tier 0 packages from the same bundle | Through the shared host once RUNTIME-01 exists; `platforms: [home, bot]` on the packages the robot needs |
| Memory in spec shape with the outbox from first boot | The household runtime's store, the outbox spool and watermarks, the spec fields of section 3 |
| Wi-Fi provisioning | The access point and captive portal, mirrored on the DSI screen |
| The shell served standalone | The schema pages on the DSI, the local first run, enrollment and bindings authored on the robot |
| Backups to USB | The export bundle in spec shapes plus the separately protected node keys |
| Tagged when hub v0.3 ships the link | Pairing, adoption, memory and settings sync, the robot-owned Home Assistant key, the ESPHome native API |
| Robot v0.2 | Media on the robot, cross-node skills, wake-word propagation, robot backups to the hub, the still-image host call, the Hailo provider if M-03 says so, the drive stage's own design pass |

## Open questions

Physical facts only the owner has (the parts record `owned-parts.md`
answers these; the build record carries a question mark for each until
then):

1. The microphone mute: is there an owned switch that can cut the
   array's USB 5 V with a contact the Pi can read, or does the robot
   ship the software mute (section 9)?
2. The exact pan-tilt kit and servo models, the horn geometry, the
   mechanical stops, the head and shell mass, and the encoder magnet
   mounting (section 10).
3. The servo rail in the finished build: the 2 to 3 A isolated buck of
   the design against the stall past 5 A the bench guide states, and
   its protection.
4. The main pack, cells, BMS, charger current, the 36-to-12 V and 5 V
   converters, the fuses and breaker, the shunt, the charge gate and
   travel inlet, the dock switch and contacts, as owned and wired.
5. The hoverboard controller, motors, firmware, wheel size, brake
   actuator and feedback, casters, and the loaded center of gravity
   (needed only when the drive stage starts).
6. Whether the e-stop and bumper switches have a spare contact for a
   sense line.
7. How many VL53L5CX units are installed and where; which two radar
   modules (the docs name the class and once LD2410); the rear camera.
8. The speaker and its supply in the finished build (the bench used a
   wall charger); the USB hub model and the port allocation.
9. The SSD model and interface, the Camera Module 3 variant, the UPS
   cell model, the RTC battery.
10. The head and shell mounts and dimensions, the eye and mouth module
    variants, the heart display and rotary module, the second Pico, the
    fan, the underglow strip length, and the follow-and-carry modules
    (the UWB pair, the load cells and their capacity, the IR and 433 MHz
    parts, the basket).

Product owner's calls:

11. The family-use verdicts on the "Redesign" rows that describe
    watching, patrols, check-ins, recording, messaging and following
    (absence_check, routine_night_check, routine_watch,
    routine_check_in, record, message, follow): build, or drop outright.
12. When `spec-v0.1.0` is cut (a release, Jesse's call), and whether
    the hub's RUNTIME-01 extraction is scheduled before or after
    CHAT-16 in Session A's queue.
13. The chat model on the robot once M-02 reports: the decision rule in
    section 4 picks, but a model choice that trades latency for
    honesty is the owner's to confirm (the legacy bench moved 14 traps
    on a stack change alone).

## Notes for later

Not actionable yet. Captured so the pre-rebuild robot's hard-won numbers
(`bot-legacy.git`) are not lost between now and when voice and the local
model land. Every number below is tied to one specific Pi 5 board, one
HailoRT version, and one serving stack; the org's `.github/CLAUDE.md`
"Training models" rule (learned 2026-08-31) already covers the wake-word
training discipline that applies regardless of which numbers below still
hold, so it isn't repeated here.

- **Local model placement and choice**, measured on the bench Pi
  (`docs/dev/inference.md`, `docs/dev/design-decisions.md`, 2026-09-02/03
  in `bot-legacy.git`). Serve with `llama-server` directly, not Ollama:
  Ollama cost ~2x on the same model, same prompt, and hides quantization
  control. Flags that mattered on a Pi 5: `--threads 4` pinned with
  `taskset -c 0-3` (more threads thrashed cache, didn't help), `--batch-size
  256 --ubatch-size 64` (this board is memory-bandwidth-bound, desktop-sized
  batches hurt), `--mlock --no-mmap`, Q4_K_M quantization, and
  `enable_thinking: false` on every request (a voice robot reciting its
  chain-of-thought to the room is a correctness bug, not just a latency
  one). Gemma 3 specifically needed `--swa-full --cache-reuse 256` to
  reuse a prompt prefix at all; without them a one-word prompt change went
  from 2.73s to 12.32s. **A serving-stack change alone moved a
  105-question honesty bench score by 14 traps and 3 recalls on the
  identical model and prompt** - the recorded lesson is that a model
  evaluation is only valid for the exact stack it ran on, so none of the
  numbers below should be trusted if the serving stack changes.
  - Final CPU comparison (210 questions, two runs each, realistic
    `minute`-latency case): qwen3:0.6b 1.05s and ties Gemma on honesty;
    gemma3:1b+SWA 2.73s; llama3.2:1b (what shipped for months) 3.63s and
    worst on both axes.
  - After narrowing the chat prompt's job (moving knowledge, judgment and
    guards out to a classifier and deterministic checks, 2026-09-03):
    qwen3-0.6b CPU 79% guarded, qwen3-1.7b CPU 95% guarded, Qwen2.5-1.5B
    on Hailo-10H 83% guarded, **Qwen3-1.7B on Hailo-10H 96% guarded** -
    the model that shipped for live conversation.
  - **Architecture that shipped 2026-09-03: two models, two jobs.** Talk
    (the reply the person is waiting for) runs on the Hailo-10H AI HAT+ 2,
    in-process, one KV cache, uninterruptible mid-prefill. Think (memory
    judge, mood, unfinished business, episode summaries - anything
    reasoning *about* a conversation rather than *in* one) runs on a
    separate CPU `llama-server` copy, because when reflection once shared
    the HAT it blocked a live reply for 24 seconds. Constraints to
    re-verify on new hardware: a 2048-token context ceiling on
    Hailo-hosted models, one LLM/VLM exclusive per HAT (3.5-7.6s reload to
    swap between them), and HailoRT 5.3.0 required but not shipped by
    Raspberry Pi OS at the time.
  - **Flag hard for revalidation:** all of this is one Pi 5 plus one AI
    HAT+ 2 plus one HailoRT version. If the rebuild changes any of those,
    none of the tok/s, latency, or honesty-percent numbers transfer; the
    *harness* (`robot.bench.honesty`, `robot.bench.latency`, raw-vs-guarded
    columns) and the *methodology* (real chat turns not a glued transcript,
    honesty runs on the real mic-to-speaker stack not synthetic audio, one
    serving stack per benchmark) are the durable part.

- **Wake word, the robot's own version** (`docs/dev/design-decisions.md`,
  `hal/drivers/voice.py`, bench 2026-09-01 in `bot-legacy.git`). Corrected
  2026-09-14 against the mirror: the pre-rebuild robot ran its own
  trained `hey_maipai.onnx` (openWakeWord format, v2 calibrated at a 0.8
  threshold, v1 at 0.4, with an in-source claim of zero false accepts per
  hour at 85 percent recall on real audio whose recording set is not in
  the mirror and must be re-verified); the stock `hey_jarvis` phrase was
  used once, as the diagnostic that proved the array's firmware fault. It
  also found its own half of the wake-to-STT gap: a natural pause after
  "hey maipai" left Moonshine STT a buffer whose head was silence, and
  Moonshine transcribed that to nothing. The fix keeps at most 0.3 s of
  audio ahead of the speech onset (`PRE_ROLL_S`, trimmed continuously
  while waiting), retries once from the byte where the VAD first heard
  speech, and stays awake for up to 6 s (`WAKE_PATIENCE_S`) when the
  first attempt hears nothing. **This is not the same mechanism as the
  hub's 1.5s figure** (`home/docs/dev.md`'s Notes for later), and the two
  aren't in tension: the hub's buffer captures audio continuously
  *before* the wake word fires, so a command said in the same breath as
  the wake phrase isn't clipped by wake-detection latency; the robot's
  0.3 s figure trims silence accumulated *after* the wake word fires,
  while waiting on VAD following a pause. A real implementation needs
  both, and the bench rows in section 11 test both. A second, shallower
  bug (the wake word firing on a phrase's tail syllable, then a
  leftover-syllable "turn" going back to sleep on an empty transcript)
  compounded the pause case and needed its own fix.
  **Separately, a real hardware gotcha, not a software one:**
  the XVF3800 mic array shipped with firmware that silently corrupted
  audio - LEDs, levels and playback all looked correct - while the wake
  score was 0.0007 instead of 0.998; traced to a USB/firmware bug and
  fixed by flashing v2.1.0. No code checked the firmware version in the
  legacy tree (a docs row only); the fresh body's self-test does.
  - The hub's wake-word note (0.47 threshold, 2/4-frame hysteresis,
    FA-per-hour numbers) is prior art measured on different hardware and
    a browser runtime, not a robot-side number to reuse directly.

- **STT/TTS choices carried from the same lineage:** Moonshine tiny (STT)
  and Piper (TTS) on Pi CPU, alongside speaker-ID via sherpa CAM++ (a
  minimum of 2 s of speech, threshold 0.6 and margin 0.10 as code
  defaults, a three-way known, unknown, unavailable answer where an
  ambiguous match is "unavailable", never "unknown"). No Moonshine or
  Piper latency numbers survived beyond the pre-roll finding above;
  measure fresh (M-06, M-09).

- **Audio hardware requirement, worth re-verifying on new hardware:** any
  speaker driving the robot's voice must take 3.5mm analog input, never
  USB-audio or Bluetooth-only - a USB/BT speaker bypasses the XVF3800's
  line-out reference and blinds its hardware echo canceller, so the robot
  can't hear "stop" while talking. Confirmed working 2026-09-02:
  quiet-room double-talk through the array showed zero self-triggered
  wakes, and a real "stop talking" said over playback was heard and
  transcribed. The array's channel 0 (the conference tuning) scored the
  wake word at 0.9986 against channel 1's ASR tuning; direction of
  arrival is read from the array's own beam selection once at wake and
  once at speech onset, with its zero and mirror flags unverified on the
  mounted head.

- **Head, presence and power numbers in the mirror** that are code
  defaults, not measured envelopes: head service 20 Hz, an 8 degree
  per-tick slew cap, camera-assist bounds of plus or minus 60 degrees pan
  and minus 20 to plus 45 degrees tilt with pan assist clamped at 30,
  idle breathing on an 8 s cycle at 2.5 degrees pan and 1.5 tilt on
  different phases so the axes never trace a circle, breathing gated off
  when docked, in quiet hours or with a person within 0.5 m, a 3 s floor
  scan every 20 s when idle. Presence funnel: heartbeat 1 s, thinking
  hold 6 s with a 0.5 s settle gate, engagement timeout 30 s, a 2 s stop
  hold. Motion: a 0.5 s command lease that must outlast the controller's
  0.3 s watchdog; the hard-stop order e-stop, tilt, falling, airborne,
  impact, silent tilt, rollaway, reflex stop, silent ranger, care stop,
  boundary, watchdog. Power: warm 70 C, hot 76, critical 82 with 3 C
  hysteresis; float at 41 V, rebalance below 39, full 42, a fourteen-day
  balance interval refused when the clock is untrusted, a 20 percent
  return request, a 5 C charge inhibit that also applies to an unknown
  pack temperature, a 25 percent UPS reserve, a 5 s goodbye grace.
