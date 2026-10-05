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

### Decisions in one line

Kept current as the record is amended (last: the outside review of
2026-09-14, reconciled below).

1. Two processes on the Pi: the hub's TypeScript household runtime on
   Bun as the same pinned package, consumed through an explicit package
   API; a Python body that owns every piece of hardware and is the
   robot's one speech process behind `spec/voice/`.
2. No private record shape, ever, even for a day: a field the pinned
   spec lacks travels in memory to the engine and is not persisted.
3. Chat on llama-server CPU, the model chosen by M-02's latency and
   quality rule; a Hailo path only ever as a local provider; the hub's
   nomic embed on the robot; the 4B judge preempted by aborting its
   in-flight request.
4. Expression is a robot package driven by a typed cue at fixed points
   of every reply path and every infrastructure path; onset is proven
   acoustically, on one clock, with suppressions counted as failures
   unless a listed safety reason was present.
5. Speaker evidence is per turn: a claim personalizes, never grants
   access; "alone" means no other person present at any level; only
   derived fields leave the robot, with a stated retention.
6. HLC ties by a link-assigned rank (the plan's "hub lowest", made
   deterministic); a clock more than an hour ahead is quarantined;
   forget outranks alias; consequential effects have a ledger with an
   unknown state that is said out loud.
7. The generic web rung is off until the household connects a search
   server; a robot-hosted one is a v0.2 measurement.
8. The mute is a physical cut or it is labeled "software mute"
   everywhere the product speaks of it.
9. Expression waits for the calibration gate, which includes the servo
   rail and the e-stop cutting it; charging control waits for the
   owner's parts answers; the drive is out of v0.1.
10. Robot v0.1 has a demonstrable standalone milestone first
    (v0.1-standalone: conversation, memory, voice, safety, expression
    on the bench Pi with no hub) and is tagged when hub v0.3 ships the
    link; adoption, replacement, face fusion, the Deno host, the room
    sensors and the Hailo provider come after the standalone proofs.
11. MaiPai Bot is the robot companion on any supported body (added
    2026-09-27, [`dev/design-reachy-mini-2026-09-27.md`](dev/design-reachy-mini-2026-09-27.md)):
    the body's hardware layer is a set of profiles behind the one HAL
    seam, each declaring its capabilities in the spec's vocabulary;
    Reachy Mini is the second profile, running MaiPai as the daemon's
    own app, a connected body whose turns the hub runs, its speech
    placement chosen by measurement, its recorded moves a catalog
    package and never a second expression vocabulary. Principle 2's
    standalone promise stays the MaiPai build's until M-R6 says
    otherwise.

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

**The capability matrix.** What a family actually gets in each mode,
with what each cell needs. "Same package" never means same
capability: a cell says what is there. "Waits" names the hub item;
"v0.2" means not in Robot v0.1 at all. The review queue's "Merge"
verdicts point into this table for availability.

| Capability | Connected | Paired, unreachable | Robot-only | Needs network | Needs a credential | In v0.1 |
|---|---|---|---|---|---|---|
| Conversation, memory, recall, the guards, the safety floor | the hub's engine and model | the same runtime, the local model | the same | no | no | yes, v0.1-standalone (waits on RUNTIME-01 and the spec tag) |
| Timers, reminders, lists, "when I say X" commands | the hub owns, the robot delivers | local, delivered locally | local | no | no | yes (waits on the jobs and commands spec verdict for the persisted shape) |
| Math, convert, remember, recall, define, joke, trivia, weather | the hub's package | the same package locally | the same | weather, define, joke, trivia: yes | no | yes (`platforms: [home, bot]` already) |
| The almanac, timer, remind, list packages | the hub's | local | local | no | no | waits on the `platforms` mark on those packages |
| The media package and the knowledge package (typed sources) | the hub's | local, Tier 1 under the Deno host | the same | yes | no | after v0.1-standalone (waits on the `platforms` mark and the Deno host, RT-06) |
| Web search (the generic rung) | the hub's search server | the household's search server if configured | the same | yes | a search server URL | yes, opt-in |
| Home Assistant lights and locks | the hub's integration or the robot's own key | the robot's own key, if HA is reachable | the robot's own key | LAN | the robot's HA key | with the link milestone (LINK-06) |
| Calendar, email, streaming accounts, people location | the hub's connectors | unavailable unless the robot holds its own | unavailable | yes | yes | no |
| Media playback on the robot | a player device of the hub | unavailable (a later download cache) | local files only, later | LAN | no | v0.2 |
| Image and video generation | offered to the hub | unavailable, said once | unavailable | no | no | no |
| A still image reasoned about by the hub | v0.2 host call | unavailable | unavailable | LAN | no | v0.2 |
| Speaker evidence: the screen sign-in and the voice print | local | local | local | no | no | yes, v0.1-standalone |
| Face evidence fused with voice | local | local | local | no | no | after v0.1-standalone (SPEAK-04) |
| Companion bindings per person and device | synced records | the replica | authored on the screen | no | no | waits on COMP-06 |
| Sensitive records on a shared device | withheld unless present and alone | the same | the same | no | no | waits on the `present` spec field; withheld entirely until then |
| Expression: listen, glance, tilt, nod, perk, attend, settle, breathe, track, stop | the hub's cues over the link (waits on WIRE-01) | the local engine's cues | the same | no | no | yes on scripted cues, then on the local engine; the plan-driven half waits on ACT-03 |
| Pairing, sync, adoption, replacement | the link | the outbox, reconciled later | not needed; can pair later | LAN | the pairing code | the link milestone (hub v0.3) |
| Autonomous driving, following, docking, patrols | no | no | no | no | no | no (the drive stage has its own design pass) |

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
  hub itself runs, with an explicit package API. Today the engine is a
  set of files under `backend/src/lib` reaching the hub's database,
  settings, package host and supervisors through `@/` imports. The
  extraction declares the ports the package needs injected (the record
  store, the engine supervisors and their launch adapter, the voice
  contract client, the package host, the data directory, the surface,
  the clock) and the calls it exposes (run a turn, stream a turn,
  cancel, the judge tick, the scheduler tick, the link's apply and
  emit), and the hub becomes its first consumer through that API. The
  robot's `runtime/` consumes only the API, never a module path inside
  the package. Only after the hub runs it can the robot pin it; the
  robot never copies files. `turnSignal.ts` and `turnContext.ts` are
  already leaf modules (no engine, no database); `hlc.ts` needs only
  its seed function injected. The pin is a version and a digest in the
  lockfile, and a boot check refuses a mismatch and refuses a path
  dependency, so the robot consumes the tagged package and never a
  source snapshot.
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

The voice seam is `spec/voice/`, the contract the hub's own STT and TTS
already sit behind (the hub's TTS is a separate Python sidecar behind
it today). **The body is the robot's one speech process** (amended on
the outside review, which found the earlier split a second speech
path): capture, AEC (on the array, from its own line-out reference),
wake, VAD, endpointing, direction of arrival, speech to text, synthesis
and speaker embedding all run in the body's single `sherpa-onnx`
process on one ONNX runtime, exactly as plan chapter 8 says, and the
body serves the voice contract to the household runtime, which is the
contract's client the way the hub is a client of its own sidecar. Audio
never crosses the socket as frames; the runtime receives transcripts
and hands back text, and the same voice packages and the same speech
normalization fixtures apply on both nodes. The pre-roll cap (0.3 s of
audio kept ahead of the speech onset and trimmed while waiting, because
Moonshine tiny returns nothing behind half a second of silent head),
the retry from the onset byte and the 6 s wake patience live in the
body, where the legacy robot fixed them (`hal/drivers/voice.py` in the
mirror).

The other seam is the body contract: observations (speaker evidence,
presence, the mute state, the stop state, power and thermal, the
admission budget), host calls the runtime makes to the body (a still
image later, the head's attention target), the expression cues, and
cancellation with deadlines. It is declared once, in `body/contract/`,
as a versioned schema from which both sides' types are generated, with
a version handshake on connect that refuses a mismatch; a message the
receiver does not know answers an error and never disconnects, the
link's own rule applied locally.

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
private shape and never fills a field with a lie to pass a fixture. The
rule has no temporary exception: a value the pinned spec cannot carry
(a speaker's evidence before the turn record has the field) travels in
memory to the engine for that turn and is not persisted anywhere, so a
later spec bump is an addition, never a migration of a robot-only table.

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
  stay local by explicit choice on the adoption screen. Precedence when
  ops race (the property tests in LINK-03 drive every interleaving): a
  forget or a tombstone on either id survives the alias and applies to
  the merged id; the receiver keeps the alias table forever and maps a
  later op that still names the old id, never rejecting it; a delete of
  the person being adopted aborts the adoption job and leaves the local
  person as it was; two aliases for one id are a `409` the adoption
  screen resolves. The reference inventory the counts are checked
  against is generated from the spec's own id-bearing fields, never a
  hand-kept list.
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
| chat | llama-server on the Pi's CPU, `taskset` to four cores, Q4_K_M, `--cache-reuse 256`, the prefix cache primed with the same stable prefix as the hub. Candidate models in order: Qwen3-1.7B, then Qwen3-4B if it fits the budget. | **M-02:** the hub's real rendered prompt (stable prefix plus a volatile zone of the bench's own turns, the ordinary tool set) on the owned Pi, three seeded runs of the conversation fixture per model, first delta p50 and p95, generation tokens per second, RSS, and the quality gates in the same run: every hard row of the fixture (credential, cross-person, unsafe-and-crisis, consequential-once) green, the guard corpus at the hub's floor, and the legacy honesty method (raw and guarded columns on real turns) recorded as a score. Decision rule: the largest model whose first delta p95 is under 2.5 s with the prefix cached and whose hard rows are green ships; the honesty score is recorded for the owner's confirmation (question 13); if the 1.7B misses the latency rule, M-03 is promoted into v0.1. |
| a Hailo chat provider | Not an engine. If it is ever used it is a local OpenAI-compatible provider under plan 4.11's own rule ("any OpenAI-compatible endpoint is a provider"), a `platforms: [bot]` sidecar the household runtime addresses by URL exactly as `MAIPAI_LLAMA_SERVER_URL` works today, with its own `ModelCapabilities` record and the same safety floor outside it. Not in v0.1 by default. | **M-03:** the rendered prompt's token count against the HEF's 2,048-token ceiling (CHAT-12's budget applies; nothing required is dropped to fit), the legacy 0.62 s first reply with retained context re-measured on the current HailoRT, and the cost of sharing the HAT with vision (one LLM or VLM resident, a 3.5 to 7.6 s swap). If the prompt does not fit, the option closes. |
| embed | The hub's nomic-embed-text-v1.5 Q4_K_M (84 MB, 768 dimensions) through llama-server, so the robot is in the hub's vector space: the routing corpus embeds once, ACT-02's heads load, and `embedding_space` reads `hub-nomic` on both nodes. The plan's "MiniLM on the robot" line is superseded by this measurement unless it fails. Embeddings are still regenerated on receipt and never sync. | **M-04:** embed latency per utterance on the Pi (the routing path pays one embed on a literal miss); acceptance under 60 ms warm. |
| judge and background | The 4B (Jesse's decision, MEM-05), its own llama-server process on the CPU. Preemption is real, not a priority hint (amended on the outside review: a scheduler cannot stop a decode already running): on an interactive arrival the runtime aborts the judge's in-flight HTTP request, which llama-server answers by freeing the slot, and the judge's per-fact checkpoint (the hub's own design) makes the aborted turn resume later without duplicate facts; the judge process also runs at a lower CPU weight so a decode that has not been aborted yet yields the cores. It drains only the robot's own offline turns when paired (the hub judges hub-owned turns) and every turn when robot-only. | **M-05:** the cancellation verified in the installed llama-server source and the line cited before anything relies on it; the chat engine's first-token delay with a judge decode aborted at arrival against an idle judge (acceptance: within 100 ms of idle); seconds per judged turn with the prompt cache; the RSS with `--cache-ram 0`; the drain of a household day (about 300 turns) against the robot's idle hours on the dock. If it does not fit, the queue is bounded and reported as a Repair, never a smaller judge chosen silently. |
| stt and vad | Moonshine tiny and Silero through `sherpa-onnx` in the body's one speech process, served to the runtime over `spec/voice/` (the hub's own `stt.ts` is a client-side binding of the same contract and the same models). | **M-06:** endpoint-to-transcript latency on the array, p50 and p95, on the robot-only bench rows (same-breath command, long pause, tail-syllable wake, empty transcript). |
| tts | A voice package with a Piper backend through `sherpa-onnx` in the body's speech process, behind the same `spec/voice/` contract as the hub's Pocket TTS sidecar. The companion's `voice` binding names a voice package; if that package is not installable on the bot platform, the robot uses its default voice and shows "voice not available on this robot" on the companion's settings row, never a silent substitution and never a different companion. | **M-09:** time to first audio sample for a one-sentence reply per voice, and Pocket TTS on the Pi as the measured candidate. |
| speaker id | `sherpa-onnx`'s CAM++ speaker embedding, local, in the body's speech process (the legacy pin, 512-d as read off the graph 2026-09-28; the one voice model household-wide, run wherever the audio already is: here locally, on the hub's STT session for Reachy Mini and the PWA, per `docs/dev/design-face-recognition-models-2026-09-28.md`). | **M-07:** the SPEAK-01 acceptance on the array with three enrolled roster voices; the threshold and margin are set by that run, never the legacy defaults (0.6 and 0.10). |
| wake | Our own trained model only, in the openWakeWord format both trainers produce (the legacy robot shipped its own `hey_maipai.onnx`, v2 calibrated at 0.8, with an in-source claim of zero false accepts per hour at 85 percent recall on real audio whose recording set must be re-verified before the number is trusted), scored in the body through the ONNX runtime with the feature front-end the trainer used. The stock `hey_jarvis` (the hub's phase-1 detector, non-commercial) never ships on the robot; the license of the shared front-end models the artifact needs is verified by the coordinator before v0.1. `sherpa-onnx`'s keyword spotter (Apache 2.0, a phrase from text, no training) is the measured alternative if the trained model misses the gate. | **M-08:** false accepts per hour and false rejects on held-out real-microphone recordings through the array, at the runtime threshold, plus the near-miss set ("hey my bike"); the artifact ships only with those numbers recorded. |
| vision | The Hailo's YOLO, SCRFD and pose pipelines lifted from legacy (measured 19, 20 and 28 ms), one capture owner, derived observations only. The still-image request the hub can make is a v0.2 host call. **Amended 2026-09-28:** the legacy ArcFace HEF (2 ms) is retired for face identity: it is Hailo's `arcface_mobilefacenet`, whose InsightFace weights are non-commercial by InsightFace's own README, and whose embedding space cannot share the household's prints. Face identity on every body uses OpenCV Zoo's SFace (Apache-2.0), on this build's Pi 5 CPU or compiled to a HEF later behind a recorded fp32-versus-HEF drift measurement; `docs/dev/design-face-recognition-models-2026-09-28.md`. | **M-10:** the full concurrent load (capture and tracking, wake, an interactive turn, playback) on the Pi: CPU, RSS, thermal over an hour, so the concurrency numbers are real before the head moves. |
| generation | Unavailable on the robot; a request is answered honestly and, when paired, offered to the hub. | none |

Process and memory budget: **M-01** measures the body, the household
runtime, the Deno host, the three llama-server processes and the vision
pipeline together on the 16 GB Pi with the chosen chat model, for one
hour, and records in `budgets.json`'s robot row: the resident set and
the headroom, CPU utilization per process and in total, the sustained
power draw (from the UPS HAT's and the INA228's own telemetry, and a
bench meter where one is owned), the SoC temperature, and the throttle
flags the firmware raises (`get_throttled`), with zero throttling as the
acceptance. No robot code that depends on the runtime split lands
before M-01 is recorded. One resource governor spans every process:
the body computes the admission budget from the power and thermal
state and the runtime's governor reads it, so Bun, Python, Deno,
llama-server and the Hailo pipelines are admitted by one policy
(GOV-01), never each by its own.

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
| tilt | signal `question`, or plan `ask_back` | a small pitch change with a slight yaw and an eye pose; there is no roll axis on the MaiPai build, so the "curious tilt" is pitch and eyes there, never a promised lateral tilt (the Reachy Mini profile has roll and renders a real tilt: the bodies design, section 5) | the question is a safety refusal or a confirmation ask (a steady look instead) |
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

Paths outside the engine, mapped to the same contract so "every path"
has no gap:

| Situation | What the body shows and the cue it raises |
|---|---|
| Boot: the runtime not yet up, or an artifact missing | the state machine shows "starting" or the Repair; no turn exists, so no turn cue; wake and stop work |
| The socket between the processes lost | every open turn gets `cancel` (reason `ipc_lost`); the head settles; the eyes show "thinking stopped"; speech in flight finishes the sentence from the ledger and stops |
| The link lost in connected mode | `cancel` for the wire turn; the local continuation's own cues (section 7) |
| Playback failure (device gone, underrun) | `cancel` (reason `playback_failed`); the reply is logged as unspoken from the ledger; the screen shows the text |
| A body-originated stop (e-stop, touch, near face, tip) | `stop` immediately in the body, then `cancel` to the runtime with the reason |
| Thermal or power admission refused | no cue; the idle policy and the envelope shrink, the state machine shows the reduction, the runtime's governor reads the budget |
| Safe shutdown | `cancel` for every turn, the settle primitive at the slow rate, the goodbye grace, then power off |

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

**Timing.** Every stamp is `CLOCK_MONOTONIC` on the one Pi, so the body
and the runtime share a clock; the hub's stamps in connected mode are
on another clock and are recorded but never used for ordering. The
stamps: `t_heard`, `t_cue_emitted` (the runtime, before the socket),
`t_cue_received` (the body, after it), `t_motion_command`,
`t_encoder_onset` (the first AS5600 delta above the noise floor),
`t_first_audio_out` (the first sample handed to the playback device) and
`t_acoustic_onset` (the sound actually leaving the speaker, measured in
the physical bench by the array's own capture of the playback, with the
device's output latency between the two recorded once per bench).
Acceptance: cue to command under 50 ms p95, measured in the body from
`t_cue_received`, with the socket leg (`t_cue_emitted` to
`t_cue_received`) reported beside it; encoder onset before the acoustic
onset on every eligible row, with p50 and p95 of cue to onset reported,
never a mean. A suppressed row is a failed row unless the bench asserts
the suppression reason was one of the safety reasons in the primitive
table and that condition was actually present; speech continuing over
an unexplained suppression is a failure, not a pass with a note. The
audio scheduler may hold a ready first word for at most 100 ms waiting
for a safe onset. An urgent safety utterance is never held for an
animation. Negative rows exist for a dropped cue, a duplicated cue, a
cue after `done`, a playback device with a deep buffer, a socket loss
between the two processes, and a hub stamp that disagrees with the
local clock.

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
  Sage". Before the answer nothing personal is read (the unknown rule
  below); the answer is what establishes the identity the pass's
  section 13 names ("identified by ... the who-is-speaking ask"). A
  claim selects the person for personalization: their own companion
  binding, their person-scope recall of ordinary records, and the
  attribution of what they said. A claim is never access: the
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
  in the whole list, at `confirmed`, and it is the speaker: a second
  person at any level, known, tentative or unknown, means not alone
  (amended on the outside review, which found the earlier wording let a
  tentative second person through); `sensitive` records enter the
  context only then, and the audience is rechecked at speech delivery,
  not only at turn start: a new face during a sensitive sentence stops
  the sentence and the settle primitive plays.
- Face and voice templates are enrolled with consent on the robot's
  screen, sealed locally, never replicated, never updated from an
  uncertain match, deleted with the person on every robot. A guest's
  voice is never enrolled silently. (Amended 2026-09-28, the owner's
  call in `design-reachy-mini-2026-09-27.md` section 4: enrollment
  is owned by the hub, and a reference print is replicated only from
  the hub's encrypted store to the household's paired devices that
  run that print's model, sealed, tombstoned on revocation; "never
  replicated" now means never past the household. The model per
  modality and the per-print model id that makes replication safe are
  in `docs/dev/design-face-recognition-models-2026-09-28.md`.)

The device token is a doorkey; the wake word is a slot; the person is
the evidence. A PIN on the screen or the hub's approval is the authority
for anything consequential.

What leaves the robot, exactly: on the turn record, `speaker_evidence`
(the person id or null, the basis, the level) and `present` (ids and
levels); in the `robot.state` frame, the same `present` list and the
activity. Never a score, an embedding, a track's geometry or a face
crop. Readers: the engine for that turn, and admins on the hub's Robots
page; a child's or a guest's turn shows no `present` list to anyone but
an admin. Retention: with the turn, under the conversation retention
setting (ninety days by default, then the summary, which carries no
presence), and in the state projection only as "last seen"; `present`
is one of the declared state fields the household may switch off (plan
7.5), and switching it off withholds `sensitive` records on the robot
entirely rather than guessing.

The v0.1-standalone identity floor needs no hub work: the screen sign-in
and the enrolled voice print are the body's own; face evidence and its
fusion with voice join after the standalone proofs are green (SPEAK-04),
and until then a face is at most a track for the head to look at.

### 7. Pairing and sync semantics

Plan 7.1 to 7.4 are the design; this section decides what they leave
open.

- **HLC.** One implementation, the hub's `hlc.ts`, on both nodes.
  Compare numerically on `wall_ms`, then `counter`; the node component
  is never compared lexically for authority. **Tie authority:** ties on
  identical `wall_ms` and `counter` are resolved by a `node_rank` the
  link assigns (the hub is 0, each robot its pairing sequence), looked
  up from the device table, so "the hub wins ties" is a policy in the
  merge, not an accident of device id strings. This is the plan's own
  policy ("ties by node id with the hub lowest", 7.3) made
  deterministic: the rank is the node id's ordering, assigned rather
  than hoped for. The hub's comparator gains the rank lookup in
  `spec/link/`'s item. Rank lifecycle: the hub is rank 0 for the life
  of its instance id; a robot's rank is assigned at pairing from the
  hub's device sequence and kept across reconnects; a re-pairing is a
  new device row and a new rank (the spec's own rule); a replacement
  hub is a new pairing, so every rank is reassigned by it; an op from a
  node with no device row is refused, never merged; a restored device
  table restores the ranks with it, since they live on the rows. On
  receipt, the local clock advances to `max(local, remote) + 1` per the
  HLC algorithm, but never past the receiver's trusted time plus one
  hour: an op stamped further ahead is quarantined (held, not applied)
  with a Repair naming the sender and the drift, so a wrong or hostile
  clock cannot own the ordering (amended on the outside review). The
  sender learns the receiver's time on the link, corrects its clock,
  and re-stamps only the ops in its outbox that no other node has ever
  seen, which is safe because an unsent op has no reader; a sent stamp
  is immutable. The hub is the time authority on the link; a robot with
  no time source since boot keeps stamping from its RTC, marks time
  unsynced, and syncs from the hub before its first push; relative
  timers work, absolute ones say so.
- **The bootstrap snapshot** is taken inside one read transaction on
  the hub at a log position, and the pull starts at that position, so
  nothing written during the snapshot is lost between snapshot and
  tail.
- **Tombstones** stay in the log forever on both sides; the outbox
  spool never drops a durable op (the legacy queue's "max 500, drop
  oldest" is rejected). Under disk pressure the robot raises a Repair
  and pauses non-durable telemetry, never the outbox. A forget on
  either side wins against any stale replica or restore.
- **Side effects.** Every consequential action has an operation id and
  an effect ledger entry with one of five states: `requested`, `sent`,
  `confirmed`, `unknown`, `failed`. After a disconnect with an unknown
  outcome the robot asks the executor before anything is retried: the
  hub for a hub-run turn's status on reconnect, and the integration's
  own state where it can be read (a lock reports locked or not; a light
  reports on or off), which turns `unknown` into `confirmed` or `failed`
  without a second execution. If the executor is unreachable the entry
  stays `unknown`, a consequential action is never re-executed to
  finish a sentence, and the person hears the state in words ("I asked
  for the garage to close but never heard back; it reads closed now",
  or "I can't tell yet"), never a confident claim. An idempotent op (a
  list add, a memory) is safe to resend by id. An `unknown` older than
  an hour becomes a Repair.
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
guess. The robot does not host a search server itself in v0.1; that is not a
rejection, it is unmeasured: M-01's recorded headroom decides whether
v0.2 offers one as a package. A direct keyless search provider is rejected outright:
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
expression until the whole gate is met: the calibration run below, the
servo rail measured under a two-servo stall and found to hold its
voltage on the compute and audio rails (question 3), the e-stop chain
proven to cut that rail (question 6), the mute mechanism answered
(question 1), and the pinch clearances measured on the final shell.
Charging control stays disabled until the owner's answers on the pack,
the charger, the gate and the interlocks (question 4) are recorded.
Until the gate is met the product makes no claim of expressive motion
and no claim of a physical mute.

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

Gates with numbers, as starting values the first physical run confirms
and the owner may move: speaker evidence (M-07) at most one false accept
in a hundred stranger utterances and at most one false reject in ten
household utterances on the roster recordings, an unenrolled voice
reported unknown every time; the wake word (M-08) at most one false
accept per two hours on the negative bank at real room levels, at least
nine wakes in ten at one meter in a quiet room and eight in ten at three
meters with a television on, and the near-miss set never waking; the
concurrent load (M-10) with zero capture dropouts and zero playback
underruns over the hour, and the sustained power draw recorded; the
judge (M-05) with the abort-at-arrival test.

Adoption, replacement, restore and forget, row by row, the expected
identity and tombstone outcome stated so the runs are judged and not
read:

| Row | Expected |
|---|---|
| A robot-only household with three roster people pairs; two are linked to existing hub people, one is created on the hub | every referencing record carries the hub id afterward on both sides; the counts match; the local templates relink; the created person carries `source: hub` with the robot's HLC node; no record is duplicated |
| A local-only guest at adoption | stays local, never appears in a sync payload, shows read-only on the hub |
| A forget on the robot while offline, then reconnect | the tombstone wins on the hub; the text and embedding are gone on both; a hub restore from before the forget cannot resurrect it (`409 rewind` reconciles the log) |
| A person deleted on the hub while the robot is offline | on reconnect the robot tombstones the person and every person-scope record, deletes the templates, and the robot-side memories about them held by others are kept |
| A replacement hub with the old name and address | refused until re-paired; the robot keeps working locally; adoption runs into the replacement; every rank reassigned |
| A robot restored from a USB backup taken before an adoption | the alias table restores with the backup; ops that named the old id are mapped; the restore reports the count of records behind the hub's watermark |
| The hub restored from a backup behind the robot's watermark | `409 rewind`; the robot re-pushes from the hub's new watermark; nothing forgotten comes back |

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

Because the tag waits on the link while the standalone work does not,
v0.1 has a named milestone before the tag (amended on the outside
review): **Robot v0.1-standalone**, demonstrable and not a release. Its
proof: on the bench Pi with no hub, a roster household authored on the
screen; wake, a turn, a reply spoken, a fact remembered across a
reboot, the safety floor refusing its corpus, a timer that fires, the
expression cues from the local engine with onset before the acoustic
onset on the eligible rows, the software mute honestly labeled, and
M-01, M-02, M-05, M-06, M-07, M-08 and M-10 recorded. What waits until
those proofs are green, in this order: the Deno host and the Tier 1
packages (RT-06), face evidence and its fusion (SPEAK-04), the room
sensors beyond the head (BODY-09), self-update with rollback (UPD-01),
the Hailo provider measurement (M-03), and, with the link, pairing,
adoption and replacement (LINK-01 to LINK-06). Contracts come before
code: the runtime API (RT-00) and the body contract (IPC-01) are
declared and reviewed before either process is written.

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
stays the public conformance oracle, its equivalence proven on every
hub commit by the shared recipe fixtures `home`'s `check.sh` runs through
both interpreters. The draft's implication that a
Python port of the safety floor is required for v0.1: the floor runs
on the robot as the same code. The direct keyless search provider, in
any form. A separate robot mood or emotion inference of any kind.

## Outside review, 2026-09-14, reconciled

An outside reading of f719a03 arrived the same day (six sections:
coherence, the three modes, cost and physical behavior, sync and
identity, sequencing and testability). Each amendment is taken with the
change made in place above, or rejected here with the reason, the way
the hub's chat design pass handled its outside reviews.

**Taken, and changed in place.**

- *RUNTIME-01 must produce an explicit package API and an injection
  boundary before the robot builds on it.* Section 2 now names the
  injected ports and the exposed calls, the robot consumes only the API,
  and RT-00 in the backlog is the contract item before any code.
- *A manifest-to-runtime compatibility check proving the robot consumes
  the exact tagged package.* Section 2: the lockfile pins version and
  digest, the boot check refuses a mismatch and a path dependency (RT-01's
  acceptance).
- *One speech-process ownership model.* The review was right that STT
  and TTS in the runtime with capture in the body was a second speech
  path against plan chapter 8. Section 2 now makes the body the robot's
  one speech process, serving `spec/voice/` to the runtime as the hub's
  own sidecar does; audio never crosses the socket; M-06 no longer
  waits on the runtime. The hub's in-process STT binding is a hub
  implementation detail behind the same contract, not a second
  definition.
- *Document the IPC if it stays split.* The body contract is declared
  once in `body/contract/` as a versioned schema with generated types
  and a handshake (section 2, IPC-01).
- *Move the proposed turn fields into the spec first; do not write them
  privately.* Section 3 now states the rule with no temporary
  exception: a value the pinned spec cannot carry travels in memory for
  the turn and is not persisted. The evidence is passed to the engine
  in memory until `speaker_evidence` lands.
- *The interpreters' equivalence must be continuously proven.* It is,
  in `home`'s `check.sh`, which runs the recipe fixtures through both;
  stated in section 2's "Rejected" note on the draft and here.
- *A capability matrix in the record with connected, paired-unreachable,
  robot-only, network-required, credential-required and not-in-v0.1
  cells, and the robot-only fallback per row.* Added to section 1, with
  the `platforms` marks verified in the hub's bundled packages (weather,
  define, joke, trivia, math, convert, remember and recall are marked
  for the robot; the almanac, timer, remind, list, media, knowledge and
  websearch packages are home-only today, which the hub dependency table
  carries).
- *"Merge" must not imply parity.* The review queue's intro now says a
  Merge names the capability and the matrix says the availability. The
  verdict word itself is kept (below).
- *CPU, power, temperature, throttling and judge-interruption
  acceptance.* M-01 gains CPU per process, sustained power from the
  owned telemetry, SoC temperature and the throttle flags with zero
  throttling as acceptance; M-10 gains capture dropouts, playback
  underruns and power; M-05 gains the abort-at-arrival test, and the
  judge's preemption is now a real mechanism (abort the in-flight
  request, verified in the installed llama-server source before
  anything relies on it) rather than a priority hint.
- *Model quality in M-02.* The fixture's hard rows, the guard corpus
  and the legacy honesty method are in the same run, and the decision
  rule requires the hard rows green.
- *Measure to acoustic output, define the 50 ms leg, make suppression
  plus speech an explicit failure.* Section 5's timing paragraph now has
  `t_cue_emitted`, `t_acoustic_onset` from the array's own capture, the
  50 ms measured after the socket with the socket leg beside it, one
  monotonic clock on the Pi with hub stamps never used for ordering,
  suppressed rows failing unless a listed safety reason was actually
  present, and the negative rows (dropped, duplicated and late cues, a
  deep audio buffer, a socket loss, a disagreeing hub stamp).
- *The non-model and infrastructure paths mapped to the cue contract.*
  Section 5 gains the table for boot, socket loss, link loss, playback
  failure, body-originated stops, thermal admission and safe shutdown.
- *Block expression and charging claims until the rail, the e-stop, the
  mute and the clearances are proven.* Section 10's gate now lists all
  five, and the product claims nothing before it.
- *Reconcile the HLC tie policy with the plan and specify the rank
  lifecycle.* Section 7: the rank is the plan's "node id with the hub
  lowest" made deterministic, with the lifecycle for pairing,
  re-pairing, replacement, unknown devices and restored tables.
- *Future-dated clocks must not dominate.* Section 7: quarantine past
  one hour ahead with a Repair, the hub as time authority, unsent
  outbox ops re-stamped after a correction, sent stamps immutable.
- *Alias, delete and forget precedence with property tests.* Section 3,
  with the reference inventory generated from the spec's id-bearing
  fields.
- *Effect-status states for consequential integrations and the user-
  facing resolution.* Section 7: the five-state ledger, the executor
  queried, the state said out loud, a stale unknown as a Repair.
- *The alone predicate must exclude every additional person.* Section
  6: exactly one entry in the whole list, at confirmed, the speaker.
- *State which derived speaker and presence fields leave the robot, who
  reads them, how long they persist.* Section 6's new paragraph.
- *Split v0.1 into a demonstrable standalone milestone and the pairing
  milestone; defer adoption, replacement, biometric fusion, the Deno
  host and the Hailo provider until the standalone proofs are green.*
  Section 12 names Robot v0.1-standalone with its proof and the order
  of what follows; the backlog splits BODY-02, RT-04 and SPEAK-01
  accordingly and adds RT-06, SPEAK-04, BODY-09.
- *Missing items.* RT-00 (the runtime API contract), IPC-01 (the body
  contract), the pin check (RT-01), the store's recovery semantics
  (SETUP-03: the store key lives on the device, a USB restore needs the
  key file, and what is lost without it is stated), UPD-01 (self-update
  with stage, swap, health check and rollback per UPDATES.md), GOV-01
  (one governor across the processes), and the model-quality gates
  (M-02) are all in the backlog now.
- *Adoption, replacement, restore and forget rows with expected
  outcomes.* Section 11's new table.
- *The robot-local search server is unmeasured, not rejected.* Section
  8's wording now says so.

**Rejected, with the reason.**

- *Rename "Merge" to "future shared capability" where the package is
  not yet available.* The four verdicts (rebuild as designed, redesign,
  merge, drop) are the platform's one vocabulary (plan 5.8) and the
  hub's review queue uses the same four; availability is a separate
  fact the matrix carries. Two vocabularies for one column is the drift
  the pass exists to prevent.
- *The claimed-identity rule contradicts the unknown-speaker rule.* It
  does not: the unknown rule withholds personal memory until identity is
  established, and the pass's section 13 part 6 lists the who-is-
  speaking ask as one of the three ways identity is established. A
  claim reads ordinary person-scope records and never the ceiling,
  disclosure, sensitive records or an action; section 6's wording is
  tightened to say the ask's answer is the establishing step.
- *Robot-only conversation may degrade to anonymous child-band behavior
  without the hub's speaker work.* The screen sign-in and the enrolled
  voice print are the body's own and need no hub work; the v0.1-
  standalone identity floor is stated in section 6. What waits on the
  hub is the persistence of the evidence and the bindings, not the
  identification.
- *"Complete episode recall" and "all 83 legacy verdicts" as v0.1
  over-design.* Episode recall is part of the runtime the robot pins
  and is not separable; the 83 verdicts are a record, not work, and
  the org rule requires them before anything is built.
- *A concrete resource governor spanning every process as a missing
  design.* It was under-stated, not missing: section 4 now names GOV-01
  and the one admission policy, but it is the hub's governor reading
  the body's budget, not a new governor.

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
having existed. A "Merge" verdict names the shared capability and says
nothing about when it is available on the robot: the capability matrix
in section 1 says which shared packages are on the robot today, which
wait on a `platforms` mark, a hub item or the Deno host, and what the
robot-only fallback is meanwhile (an honest "I can't do that here" once,
in the register guard's voice, never a stub).

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

Answered 2026-09-14 (Jesse, through the coordinator): 11, the seven
rows stay on the backlog as their own items, decided when each is
reached, none dropped now; 12, `spec-v0.1.0` is cut after SPEC-02
lands (one tag with the companions and manifest changes), and
RUNTIME-01 sits after CHAT-16 in Session A's queue; the ear gates in
section 6 (speaker evidence and wake) stand as starting values, moved
only with a measurement and a recorded reason. 13 stays open until
M-02 reports.

## The Stack (2026-09-17; refocused 2026-09-20)

The hub's engine layer became MaiPai Stack on 2026-09-17, and on
2026-09-20 the owner refocused it (`.github/docs/DECISIONS.md`): the
Stack is the engine foundation of MaiPai Home, the headless service
that installs, sizes, runs, watches, updates and tests the engines and
models behind Home and gives Home one stable address by role. It has
no interface and no users of its own; Home is its only caller. Home's
installer installs the Stack; a person never installs the Stack by
itself. For the robot that means: Bot runs Home's platform code, so the
robot's own Linux ARM Stack (STACK-17) is installed by that code the
same way, and the robot is Home's replica calling it on loopback. Its
place in this design leaves sections 2 and 4 intact: the three language
roles (`chat`, `embed`, `judge`, the same llama-server pins and flags
as section 4) are Stack roles on the robot; the body keeps speech over
`spec/voice/` and is registered with the Stack as a managed engine so
the identity contract holds on both nodes; GOV-01's one governor is
the Stack's, fed by the body's power and thermal budget; RUNTIME-01's
"engine supervisors and their launch adapter" port is satisfied by the
Stack client Home already carries (`stack/docs/plans/
home-adoption-2026-09-20.md`, HOME-STACK-02), never an in-process
supervisor. The robot builds on the Stack and never requires the hub.
The wire shapes (role request and reply headers, the event feed, the
health item, the settings and precious-state declarations) are the
Stack's `backend/src/spec/` schemas, moving to `shared/spec`, and the
Python body pins that package at Home's version. This design pass
confirms or amends that reading before STACK-17 starts; M-01 through
M-10 are unchanged by it.

## Bodies (2026-09-27)

The owner ordered a Reachy Mini Wireless and asked for it to be an
officially supported body. The design is
[`dev/design-reachy-mini-2026-09-27.md`](dev/design-reachy-mini-2026-09-27.md):
`bot` is the robot companion on any supported body; `body/bodies/`
holds one profile per body (the MaiPai build of the build record, and
Reachy Mini) behind the HAL seam BODY-02 names, each declaring its
capabilities in the spec vocabulary so a hub with several robots of
different kinds is several device rows and every renderer reads the
list. On Reachy Mini, MaiPai is the daemon's own app; the hub runs
every turn (a connected body, the first non-browser client of the
hub's routes); speech is placed by measurement (the `pod` tier as the
baseline, the `robot` tier if the Compute Module carries it); the
primitive table gains a column with roll, the antennas and body yaw;
the vendor's recorded emotions and dances are a catalog package on the
plan's `react` slot; privacy is measured on an isolated network before
the unit joins the household's; and everything the body cannot show or
sense is labelled rather than claimed. Sections 1, 5, 9 and 10 above
are unchanged for the MaiPai build; the design says where each applies
to the second body. What "officially supported" means is its section
13, and the work is the "Reachy Mini body" area of the backlog.

**Landed 2026-09-27 (RM-01):** `body/bodies/reachy_mini/` wraps the
`reachy-mini` SDK (pinned `1.11.0`) behind the HAL seam declared in
`body/hal/seam.py`, with `profile.py` as the one place this body's
numeric limits appear (pitch and roll +/-40 degrees, head yaw +/-180
degrees, body yaw +/-160 degrees, the head-to-body delta 65 degrees,
all from the design record's section 1; the antenna range +/-pi radians,
read live from the daemon's own `/api/kinematics/urdf`) and a fake
(`fake.py`) that replays a real goto-then-hold trace recorded against
the MuJoCo simulator (`fixtures/`). The suite runs on the fake always
and on the live simulator when `MAIPAI_BODY_LIVE=1`; both passed on
this commit. The `maipai-spec` pin AGENTS.md names is not yet in
`body/pyproject.toml`: `commons/spec/pyproject.toml` has no
`[build-system]` table, so a git-installed build fails on setuptools'
flat-layout autodiscovery across the whole spec workspace, and RM-01
needs no spec shapes to proceed (see the comment in
`body/pyproject.toml`).

**Landed 2026-09-27 (EXPR-01, RM-02):**
`body/maipai_body/expression/` maps a cue to a primitive
(`cue.py`), checks the suppression table (`suppression.py`), and
renders the primitive on the Reachy Mini profile through the HAL seam
(`reachy_mini_renderer.py`), scaled by fractions of the profile's
declared axis limits (`envelope.py`). Both items stay unchecked in
`docs/BACKLOG.md`: there is no arbitration or blending limiter yet
(each primitive issues its own commands independently), body yaw does
not yet follow the head past its delta limit, and there is no `muted`
pose (this profile has no mute mechanism at all yet). `EXPR-01`'s own
pointer names `body/head/controller.py` (BODY-04) as the actuator;
BODY-04 does not exist (it needs the MaiPai build's own physical
calibration run), so this was built against the seam's generic
`HeadActuator` instead, the reading recorded here rather than guessed
silently. M-R2's simulator rows (cue-to-onset, amplitude, peak
velocity, settling time, all eleven primitives) were recorded from a
real run against `reachy-mini-daemon` 1.11.0, in
`docs/dev/measurements.md`.

**Privacy finding, 2026-09-27 (worth carrying into RM-07):** running
the simulator on a dev Mac, the daemon's own media pipeline falls back
to the host machine's real microphone as its audio input source
whenever no Reachy Mini audio hardware is found ("No Reachy Mini Audio
Source card found... using default audio source" on every sim start),
with no consent prompt. Nothing in `body/`'s own code reads that
stream (`get_audio_sample()` is never called outside the seam's own
pass-through), but the daemon itself holds the input open. `--no-media`
avoids it entirely for testing that does not need audio. On the real
unit this is moot (the array is the only input device), but it is
exactly the kind of vendor behavior `dev.md` section 9 already says
must be measured before trust, and belongs in RM-07's isolated-network
capture.

**Landed 2026-09-27 (RM-06):** the HAL seam gains a `FaceTracker`
protocol (`enable_tracking`, `disable_tracking`, `get_face_target`,
never an identity); `body/maipai_body/presence/` declares the
arbitration priority (`arbitration.py`) and the tip and freefall reads
from the IMU (`safety.py`, design-default thresholds pending a
physical run). This item's own backlog wording had the arbitration
order backwards from the design record section 6 it names as its
source: section 6 states tracking outranks expression ("consented
tracking sits below inhibit, reflex and service, above expression and
idle"), and that reading is what is built and tested, recorded here
per the corrected backlog note. BODY-05's own funnel state machine
does not exist yet (it needs a turn-aware runtime); this item lands
that funnel's inputs, not the state machine itself.

**Landed 2026-09-27 (a Fable-model audit's defects, fixed): the muted
pose is edge-triggered, `stop` actually cancels, vendor removal has a
post-condition.** The muted pose above (this section's own earlier
"there is no `muted` pose" line, and RM-02's stale BACKLOG note, are
corrected by this entry) was first built to re-render from cue
suppression on every suppressed `listen`/`breathe` cue, contradicting
`primitives.py`'s own contract ("muted is a state, not a cue-driven
primitive") and fighting the daemon's own tracker every tick with no
arbitration check and no unmute transition. `ExpressionEngine.set_muted()`
replaces that: an edge-triggered state (`muted` in the class), gated by
`presence.arbitration.expression_may_drive()`, that renders the pose
once on the rising edge and `settle` once on the falling edge;
`handle()` goes back to plain `rendered=False` suppression, exactly as
the generic table says. A same-day `code-review` skill run (the proper
kind, not the prior ad-hoc pass) caught one more: the edge was consumed
even when arbitration deferred the render, so a mute requested while
tracking owned the head never rendered even after tracking ended, with
nothing left to trigger it. `self._muted` now only updates once a
render actually happens, so a deferred edge stays pending and catches
up on the next call with the same value once arbitration allows it.
Separately, the render lock added the same day
made `stop` queue behind an in-flight goto (inverting `dev.md`'s own
"stop is never suppressed" rule the moment a second thread exists), and
`hold()` never sent the daemon's `StopMoveCmd`, so a goto's own task
kept winning the pose until its duration elapsed regardless. `stop` now
bypasses the render lock and is issued immediately; `hold()` sends
`StopMoveCmd()` before re-holding the present pose. Note this does not
help a `stop` cue arriving on the *same* thread as a blocking goto - the
real fix for that is gotos issued from a worker the engine never blocks
on, EXPR-04's shape, not something a lock can do. Also fixed:
`scripts/install-reachy.sh`'s vendor-app removal now re-lists installed
apps after the loop and fails if anything but `maipai_bot` remains
(the daemon's own `pip`/`uv` uninstall exits 0 even when nothing was
removed, so the prior version could report success while an app
survived); the muted pose was added to `test_expression_renderer.py`'s
clamp-check parametrization, which excludes it from `PRIMITIVE_NAMES`
on purpose and so was silently never checking it. Not fixed here,
recorded for RM-07: the antenna sign convention (down is negative),
which only a physical unit's own state feed can confirm.

**Landed 2026-09-28 (G12, packaging for the unit):** the
entry-point/distribution name mismatch this section's own earlier note
flagged (`maipai_bot` vs `maipai-body`) is fixed - the distribution is
now `maipai-bot`, matching both the entry point and the design record's
own section 3 naming, verified by a real `uv build --wheel`. `mujoco`
moved to an opt-in `sim` extra so the robot's own `pip install` of the
wheel (and a bare `uv sync`) pulls neither it nor its native
dependencies; the dev bench needs `uv sync --extra sim` or `uv run
--extra sim reachy-mini-daemon --sim ...` now. Not verified: installing
the built wheel in a fresh Linux aarch64 venv (no container runtime in
this environment) - low risk, since the wheel is pure Python with no
platform-specific code, but recorded rather than assumed.

**Landed 2026-09-28 (G1, audio capture and playback):** the `AudioIO`
seam gained recording/playback lifecycle and sample-rate methods
alongside the existing `get_doa`, typed `npt.NDArray[np.float32]`
throughout instead of `object`; both the real client (delegating to
`self._reachy.media.*`) and the fake (a WAV-backed mic that hands back
fixed-size chunks, plus a pushed-audio ledger) implement the full
Protocol. A new body-agnostic `maipai_body/speech/` package sits above
the seam: `AudioCapture` downmixes the daemon's stereo feed to mono by
taking channel 0 (documented as a judgment call, not a documented fact
about the array - nothing says which physical element either channel
is, so averaging risked silently blending in an undocumented second
source) and re-chunks into fixed 512-sample/32 ms blocks with a 0.3 s
pre-roll ring for G3's future wake-word lookback; `AudioPlayback` opens
the output stream once across repeated pushes and keeps a timestamped
ledger, cleared on `stop()`, for G8's future barge-in accounting. 12 new
deterministic tests (exact 93-block count from a synthetic 3 s WAV,
exact 0.3 s pre-roll sizing, idempotent stream-open, ledger duration,
raises-after-disconnect) pass alongside the full suite (142 passed, 7
skipped). A `code-review` medium pass on this diff found six real gaps,
all fixed before commit: the seam's own completeness test
(`test_hal_seam.py`) hadn't been extended for the six new `AudioIO`
methods, so it silently stopped guarding the exact contract it exists
to check; `AudioCapture.start()`/`stop()` had no idempotency guard,
unlike `AudioPlayback`'s, so a second `start()` mid-recording would
have discarded the pre-roll ring; `poll_blocks()` re-concatenated the
whole growing buffer on every loop iteration, O(n^2) against a real
queue backlog, now collected into a list and concatenated once;
`BLOCK_SAMPLES` was hardcoded despite the seam's own "never assume
16 kHz" contract, now derived from the stream's real reported rate in
`start()`; the fake's replay-from-start semantics on a second
`start_recording()` were undocumented, now a docstring says why; and
three tests reached into the fake's private `_mic_cursor`/`_mic_samples`
instead of asserting on `poll_blocks()`'s own public return value, now
fixed. A third `low` pass on that follow-up's own diff caught two more:
deriving `_block_samples` from the stream's reported rate with no floor
meant a `0` from `get_input_audio_samplerate()` raised
`ZeroDivisionError` inside every later `poll_blocks()` instead of
failing at its actual source, now a `ValueError` in `start()` itself;
`_recording` flipped `True` before sizing was known to succeed, now
only after, so a failed `start()` isn't silently swallowed by its own
idempotency guard on retry. 144 tests total. Live-verified against the
real `reachy-mini-daemon --sim`:
captured 3.46 s of real queued audio to a 16 kHz mono WAV over a 5 s
window, pushed a 1 kHz tone with no exceptions or underrun warnings.
Found and fixed along the way, not previously documented: a cached
Hugging Face token at `~/.cache/huggingface/token` makes
`ReachyMini.__init__` raise `KeyError: 'Producer reachymini not
found.'` inside `MediaManager._init_webrtc()`
(`reachy_mini/media/webrtc_utils.py`'s `find_producer_peer_id_by_name`),
breaking local audio connection entirely - not just adding the
already-documented unwanted outbound relay connection - regardless of
`connection_mode` ("auto" and "localhost_only" fail identically).
Worked around for this session's testing by moving the token aside and
restoring it after; recorded in `docs/BACKLOG.md`'s G1 entry as a known
dev-bench gotcha for whoever hits it next, not scoped as a fix since it
only affects a machine with a cached token, not a shipped robot.

**G2 (2026-09-28), fully landed and live-verified:** the
wake scorer (`speech/wake.py`) and the pinned-asset fetcher
(`speech/models.py`) are built, tested (19 deterministic tests against
a scripted fake engine and a real local HTTP server, no model files
needed), and separately verified against the real extracted
`trained_hey_maipai_v2.onnx` and openWakeWord's real front-end (gated
tests, `MAIPAI_WAKEWORD_MODELS_DIR`). Two findings worth carrying
forward: the gap-audit's own near-miss fixture, "hey my bike," is a
documented, permanent false-accept on real speech per `home` issue #5
(closed, not a bug - "MaiPai" is phonetically "my pie"), so the real
near-miss test uses "hey my car" instead; and `reachy-mini==1.11.0`'s
hard pin to `onnxruntime==1.27.0` silently mis-scored every wake
inference on this machine (near-zero on a clear "hey maipai" sample
that 1.30.0 scored at 0.94, no error either way) - verified safe to
override before doing so, not just forced, by confirming
`reachy-mini`'s own bundled kinematics models score byte-identical
under both versions. `docs/BACKLOG.md`'s G2 entry has the full
breakdown, including a separate bug found and filed upstream in `home`
(`wakewordAssets.ts`'s checksums are each one hex character short,
home#185) rather than fixed there since this session was working in
`bot`. **Shipped the org's way (Jesse's word):** `v0.1.0` cut, the
trained model attached as a release asset and round-tripped (uploaded,
downloaded back, checksum matched). Its URL 404s anonymously against a
private repo - a real robot has no GitHub credentials - so `bot` was
made public after a full-history `gitleaks`/PII scan came back clean;
`models.py`'s `WAKE_PHRASE` now carries the real URL.

**A critical bug that only live testing found:** `AudioCapture.
poll_blocks()`'s "drain until `None`" loop (added by the second review
pass on G1's own commit) hangs forever against a real continuously-
recording microphone - the real appsink's pull blocks up to 20 ms per
call, and a live mic almost always has a buffer ready within that
window, so `None` essentially never happens while recording. Every
deterministic test passed, every gate ran green, because the fake's
own finite fixture legitimately returns `None` on exhaustion, a
completely different reason than the real appsink's backpressure
behavior - the two never diverged until a real daemon connection was in
the loop, which is exactly why G2's own acceptance needed a live
microphone test, not just green tests. Fixed: `poll_blocks()` pulls one
buffer per call, matching the original, actually-live-verified G1
design, with the real appsink's timeout behavior recorded in its own
docstring so this doesn't get "fixed" the same wrong way again.

**The live acceptance itself, run after the fix:** this dev Mac's own
speaker played a synthetic "hey maipai" clip, its built-in mic captured
it through the real `reachy-mini-daemon --sim`'s real audio pipeline,
and G1's real `AudioCapture` plus G2's real `WakeScorer` (the actual
production classes, not a fake) fired exactly once at score 0.9346
(threshold 0.8), with `DoA` correctly `None` since this Mac has no real
direction-of-arrival array to read from.

**G4 (2026-09-28), landed:** the robot's own hub link - `link/discovery.py`
(mDNS via `zeroconf`, TXT parsing split pure for testing),
`link/store.py` (a sealed `0o600` pairing file, atomic, fail-soft),
`link/client.py` (the real quick-connect code/poll/redeem flow, split
into `request_code()`/`await_approval()` so a code is visible before
the blocking wait - the one real bug this session's own design caught
before shipping: a first-cut single-call `pair()` left the settings
page with nothing to show until pairing had already finished),
`link/lifecycle.py` (resume-or-discover-and-pair, then a 24h
re-redeem heartbeat). `app.py` now serves a real settings page
(`custom_app_url`, `static/index.html`) instead of `None`. 34
deterministic tests, including a real local HTTP server standing in
for the hub (not mocked at the `requests` layer) exercising the
actual 401/403 refusal paths - 403 is ROBOT-DEVICE-01's own
unrotated-credential gate, confirmed surfaced as a clear
`PairingRefused`, not a raw HTTP error. Live-verified: the real
`MaiPaiBody` class constructed and its actual `settings_app` served
correctly under a real `uvicorn` server on port 8042 (`GET
/api/state` and `GET /` both real HTTP round trips). Not run this
pass: a full live pairing against a real `home` dev server (`home`
may have other sessions active in it; the deterministic stand-in
already exercises the identical contract read from `home`'s own
route source).

A `/code-review medium` pass caught a real, critical gap: fingerprint
pinning was computed and stored but nothing ever checked it - the
device token went to whoever answered at the pairing's own address
with zero identity verification. Fixed: `_redeem()` now calls a new
`_verify_identity()` first, which refuses only on a *confirmed*
mismatch (a live TLS certificate that doesn't match for https, or a
fresh mDNS answer at the same host:port with a different instance id
for plain http) and treats an inconclusive check (mDNS answering
nothing) as exactly that, not a mismatch - refusing the robot's own
credential on an ordinary network hiccup would be worse than the
narrow risk this honestly-scoped check accepts. Two more real
findings fixed the same pass: `LinkLifecycle.state` returned the live
object instead of a copy (a torn read across the settings page's own
several field accesses was possible mid-write), and `_heartbeat()`
recursed into `run()` on every failed re-redeem instead of looping
(unbounded stack growth over a robot's own months-long uptime).

A re-review of that fix (medium) caught three more real gaps: the
plain-http identity check's own docs overstated what it catches -
a real attacker who took over the address simply won't run an mDNS
responder, so the check finds nothing and correctly proceeds anyway
(its own inconclusive-is-not-a-mismatch rule); it only catches the
implausible case of a second responder answering at the identical
address. Both docstrings now say plainly that https is the only path
with real protection, http's check is honest best-effort. The https
branch itself - the security-critical half - had zero test coverage;
`test_link_client_https.py` now drives it against a real self-signed
certificate (via the system's own `openssl` CLI, no new dependency)
and a real TLS handshake, trusted through `requests`' own `verify=
<cert path>`, never `verify=False`.

That same pass also tried to skip a "redundant" ~3s mDNS re-discovery
in `await_approval()`, reasoning `request_code()` had "just discovered
this address moments ago." A third, low-effort pass (the last one -
the org's "a third pass never happens" rule) caught that the premise
was false: `_poll_until_approved()` sits between them and can block up
to five minutes, not moments, and the skip had reopened the exact gap
`_verify_identity()` exists to close, for the first and highest-stakes
redeem of all. Reverted outright rather than patched further:
`_redeem()` always verifies, the parameter that let a caller skip it
is gone entirely. No further review round was dispatched for this
revert; verified by the full gate staying green (196 tests) and a
careful hand read of the diff.

`design-resolver` resolved the audit's own flagged ambiguity (does the
robot speak the pairing code, or does the app page carry it alone):
pre-rendered clips are the right long-term answer, but building that
asset pipeline is separable from G4's own pairing mechanics, so this
pass ships the app-page-only interim the resolver confirmed is
legitimate, recorded as one line in section 9 of
`docs/dev/design-reachy-mini-2026-09-27.md` and as its own backlog item
(G4b, blocking family use) rather than left as a silent gap.

**G3+G6 (2026-09-28), landed:** the streaming turn round trip, per the
revised design that folds G3 entirely into G6's own send side - no
local VAD, no endpointer, no local `Utterance`, just a 6s wake-
patience timer cancelled by a real `vad` event from the hub's own STT
session. `speech/stt_stream.py`'s `SttStreamClient` opens the WS with
`websockets`' sync client (already a dependency), forwards G1 blocks
from the wake instant. `speech/turn_client.py`'s `TurnClient` posts
the transcript, parses real NDJSON (not SSE), and turns `signal`
events into `Cue`s through the `expression/cue.py` mapping EXPR-01
already built - no new cue logic invented here. 16 tests, all against
real local stand-in servers (a real `websockets.sync.server`, a real
`http.server` streaming real NDJSON), which caught two real bugs a
mock would have missed: the give-up path didn't handle the hub
closing the connection without ever answering `{t:"end"}`, and a
leftover unused constant implied a per-error-code cue mapping that
was never wired up. Not yet built: G9's own run loop, which calls
these two clients back to back and actually renders the cues.

A second review pass (medium) found three more: the same give-up
path's own `send()` call, right before the guarded `recv()`, wasn't
itself guarded, so a hub closing the connection at that exact instant
still raised unhandled - both calls now share one guard. `TurnClient`
conflated an auth failure (401/403) with a genuine dropped connection,
both becoming `TurnLinkLost` - a caller has no way to know from that
alone whether to reconnect or re-redeem through `HubLinkClient`; a new
`TurnAuthFailed` covers the auth case specifically. And both clients
now raise a clear error immediately if constructed with an empty
session cookie, instead of silently sending `Cookie: session=None`
when a caller reads `HubLinkClient.session_cookie` before pairing has
ever succeeded.

**G7 (2026-09-28), landed and live-verified:** `speech/tts_playback.py`'s
`TtsPlaybackClient` streams the hub's own `POST /api/tts` WAV into G1's
`AudioPlayback`, mirroring the browser's own reference player
(`streamingWavPlayer.ts`): parse only the 44-byte header, never trust
its declared data-chunk size, resample with `scipy.signal.resample_poly`
(now an explicit `voice` dependency, not left to openwakeword's own
transitive pin). The design record's section 5 already settled the
vendor-wobbler-vs-our-own-primitive question before this session
started - nothing to re-decide, the wobbler stays off. 8 tests against
a real local server streaming a real WAV; live-verified against the
real `reachy-mini-daemon --sim` - a real 24kHz stream resampled to
16kHz and pushed through the real daemon, 36 chunks, zero errors,
pushed duration within 1 ms of the source.

A review caught four more real defects: three separate exit paths (a
401, a general non-2xx, an unsupported `bits_per_sample`) each left
the HTTP response unclosed - `speak()` now wraps the request in a
`with` block so every exit path closes it. The downmix assumed a
chunk boundary always lands on a whole multi-channel frame; a
stereo-or-wider stream could raise on `reshape()` at a genuinely
misaligned trailing partial frame - fixed with the same leftover-byte
carry pattern G1's own capture.py uses. Worth naming: the first
regression test for this, driven through a real stand-in server,
passed whether or not the fix was present - `requests`' own
`iter_content()` always re-buffers to a clean multiple of 4, so no
real HTTP round trip can actually reach the bug. Caught before
landing and replaced with a hand-crafted-chunk unit test, verified to
genuinely fail without the fix.

**G8+G9+G11 floor (2026-09-28), landed:** `run_loop.py`'s
`ConversationLoop` replaces `app.py`'s own `run_body` idle wait with
the real funnel - `idle`/`listening`/`thinking`/`speaking`, driven by
G6's turn events and G8's mute, a presence tick on its own thread
enabling the daemon's own face tracker whenever a face is present and
the funnel isn't `speaking` (the one carve-out `presence/
arbitration.py`'s general priority table doesn't model by itself,
since tracking otherwise outranks expression there - checked
explicitly, not left to the generic `tracking_may_drive()`/
`expression_may_drive()` pair). G8's barge-in folds in rather than
building a second detector: the revised streaming design left no local
VAD or endpointer to attach one to, so a wake firing again during
`speaking` is the stop signal, reusing G2's own `WakeScorer`. The
software mute (`set_muted()`) is real and tested - edge-triggered,
gates `_poll_wake()`, renders the muted pose - but nothing calls it
yet; that trigger is G10's own device-state frame, not built this
pass. `TurnClient` gained `cancel()` for barge-in's own hub call, and a
`with`-wrapped `stream()` request (the same leak class G7's review had
just caught in `tts_playback.py`, fixed here proactively before a
review had to find it twice).

The tests themselves found a real bug, not just inspection: `_run_turn`
was rendering every cue the turn stream emitted, including its own
terminal `DONE` - which means "the reply text is fully known," not
"done speaking it" - firing the settle primitive before speech even
started. Fixed by only rendering `CANCEL` and non-`DONE` cues from
that loop; `_speak()` alone owns the real `SPEAK` (before the first
audio push) and `DONE` (after playback actually finishes, or `CANCEL`
on barge-in). 10 tests against scripted stand-ins for every
network-facing dependency and a real `ExpressionEngine` rendering onto
`FakeReachyMiniClient`.

A medium review then caught four real concurrency defects in the
barge-in path: `_next_cue_seq()`'s unprotected `+= 1` raced between the
main thread and the speak worker's `on_first_chunk` callback (now
lock-protected); the barge-in loop kept polling wake for as long as the
worker thread stayed alive instead of stopping the instant barge-in
fired, so a slow-to-exit worker could score a second block and
double-cancel (now gated on the barge-in flag too); `speak_thread
.join(timeout=5.0)` let `_speak()` return while the worker might still
be pushing to the shared, unlocked `AudioPlayback`, risking two speak
threads overlapping on a fast-following turn (now an unbounded
`join()` - correctness over latency, bounded in practice by the TTS
client's own (10, 120)s timeout); a dead, never-read `speak_cue_rendered`
event was removed. The duplicate-cancel fix has its own regression
test, hand-verified to fail without the fix and pass with it. A
low-effort follow-up pass on just the fix hunks found nothing further.

**Not yet done:** live verification against the real
`reachy-mini-daemon --sim` (RM-05's own acceptance - a three-turn
conversation with cues rendered before the first audio sample); it
needs a combined stand-in hub server (STT WS + turn NDJSON + TTS WAV
together) or the existing per-module stand-ins wired to one address,
not attempted this pass. `SETTLE_GATE_S` (the 0.5 s flash-guard from
BODY-05) is defined but not enforced anywhere yet - the funnel's real
transition times are recorded in `RunLoopState.trace` regardless, so a
future test can measure the gap. G11 beyond its presence/tracking floor
(the still-image call, the consent prompt, the hub route, the Stack's
`vision` role) remains its own undesigned item, not started.

## Outbound connections

The org's privacy rule is in [PRIVACY.md](https://github.com/getmaipai/.github/blob/main/PRIVACY.md) (not reachable from this session; confirm the wording at review). Each connection this repo adds is listed here.

- **Recorded moves library (MOVES-01).** What: the emotions library's move files (JSON). From where: huggingface.co, a public dataset, no account or token. When: only when an admin runs `body/scripts/pin_moves_library.py` or installs the package; never at runtime without that. What is sent: an ordinary file request (URL and standard HTTP headers), no household data. Every file is pinned by full commit revision and sha256 checksum before use: `ensure_move` refuses an unpinned or checksum-mismatched file.

## Research notes

- [`dev/research-minicpm5-reachy-mini-2026-09-27.md`](dev/research-minicpm5-reachy-mini-2026-09-27.md):
  MiniCPM5-1B (a third M-02 candidate, blocked on its tool-call format
  parsing through llama-server) and Reachy Mini (the closest prebuilt
  match to the section 5 expression layer; a hub-attached body, not a
  standalone robot, on its 4 GB CM4). The Reachy half became the bodies
  design above the same day; the MiniCPM5 half is undecided.

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

## Robot device state (2026-09-29, design-resolver, G10/ROBOT-CARD-01)

Full record and rationale: `home`'s own `docs/dev.md`, "Robot device
state" (2026-09-29) - this is the bot-side pointer, not a duplicate.

The robot pushes a `robot.state` frame (`commons/spec/schemas/
robot-state.schema.json`: activity including `starting`, muted,
tracking, on_battery/battery_level as nullable-unknown for this body,
daemon_version, and app_version: the `maipai-bot` release the robot
runs, since daemon_version is the vendor SDK's) to
`PUT /api/devices/me/state` on every change and a
15s heartbeat otherwise, from `link/state.py`'s `StateReporter`
(modelled on `link/prints.py`'s `PrintSync`), started in
`run_paired_body` at pairing, before the conversation-loop build. The
hub never polls; only the robot holds a hub credential. See G10-BODY
in `docs/BACKLOG.md` for the work order.

The mute command (hub to robot) is explicitly NOT this frame - it's
read-only telemetry, robot to hub. Filed separately as `home`'s
ROBOT-MUTE-01, undecided (a settings key vs. a device-command channel,
and whether Home offers a mute button at all - the design-resolver's
own report flags the last as possibly Jesse's call, not an engineering
one).
