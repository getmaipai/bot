# MaiPai Bot: design record

Seeded 2026-09-03 from the platform plan (`purring-chasing-noodle.md`).
This repo is a fresh start on that design: chapter 0 explains why (build
fresh, do not migrate; decision 11), chapters 3, 7, and 8 are the robot's
architecture, chapter 13 is the release roadmap. This file is the dev-tier
design doc; it grows as the robot is built.

## What happened to the old repo

The pre-rebuild robot's full history (the bench-proven Pi 5 build: wake
word, sherpa-onnx-adjacent speech stack, Hailo-10H model, memory schema,
`hublink` pairing, roughly 90 skills) is preserved outside GitHub: a full
git mirror at `legacy-backups/bot-legacy.git` next to this repo on the dev
machine. It had no releases to preserve. Nothing was migrated into this
repo. Per platform plan principle 8, legacy code is a read-only reference
for hard-won logic only (drivers, trainers, measurements, the wake-word
lessons in `.github/CLAUDE.md`), never for feature scope or UI; every
legacy skill gets a one-line review verdict here before anything is
rebuilt (section 5.8).

## What this repo is

The robot companion: a body that pairs with the hub like a pod, keeping a
full replica of the household, running the same packages under the same
rules, using the hub as its brain when reachable and its own model when
not. Standalone it is a complete product, never a stub. Full architecture:
platform plan chapters 1, 3, 7, and 8.

## Step 0 status

- [x] Repo reset to a clean history, with LICENSE (AGPL-3.0), NOTICE, this
      design record, and `scripts/check.sh` pinned to `@maipai/standards`
      std-v0.2.0.
- [ ] Everything else. Robot v0.1 starts once `home/spec/` v0.1 exists (the
      robot pins it as `maipai-spec @ git+...@spec-v0.1.0#subdirectory=spec`).
      Until then this repo stays a skeleton.
- [x] [`docs/BACKLOG.md`](BACKLOG.md) added (2026-09-06) - the scannable
      what's-built/what's-missing list per `getmaipai/CLAUDE.md`'s Backlog
      and status standard; feeds the org's status dashboard.

## Review queue

Every legacy robot skill gets a one-line verdict here before it becomes
part of the fresh build: rebuild as designed, redesign, merge, or drop,
with the reason (platform plan section 5.8, open item in section 15).
Empty until that review pass runs.

| Legacy skill | Verdict | Reason |
|---|---|---|
| _(none reviewed yet)_ | | |

## Roadmap

See platform plan chapter 13. Robot v0.1 (prepare the Pi, the head, the
voice loop, the local engine, the safety layer, Tier 0 packages, memory in
spec shape, Wi-Fi provisioning, standalone) is tagged when Hub v0.3 ships
the link, which adds pairing, memory and settings sync, the robot-owned
Home Assistant key, and the ESPHome API to HA.

## Notes for later

Not actionable yet: Robot v0.1 hasn't started (waiting on `home/spec/`
v0.1). Captured here so the pre-rebuild robot's hard-won numbers
(`bot-legacy.git`) aren't lost between now and when voice and the local
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
  bench 2026-09-01 in `bot-legacy.git`). The pre-rebuild robot validated
  its mic array with stock openWakeWord's `hey_jarvis` phrase, not a
  custom-trained "hey maipai" model. It also found its own half of the
  wake-to-STT gap: a natural pause after "hey maipai" left Moonshine STT a
  buffer whose head was silence, and Moonshine transcribed that to
  nothing. The fix caps how much of that post-wake, pre-speech silence the
  buffer keeps to 0.3s (whatever the pause was, the head stays short),
  plus a retry from the byte where the VAD first heard speech. **This is
  not the same mechanism as the hub's 1.5s figure** (`home/docs/dev.md`'s
  Notes for later), and the two aren't in tension: the hub's buffer
  captures audio continuously *before* the wake word fires, so a command
  said in the same breath as the wake phrase isn't clipped by wake-
  detection latency; this robot's 0.3s figure trims silence accumulated
  *after* the wake word fires, while waiting on VAD following a pause. A
  real implementation plausibly needs both. Nothing found in this robot's
  legacy docs addresses the hub's same-breath case specifically, so verify
  whether it was ever hit here (a bench Pi in a quiet room may simply not
  have produced it) before assuming it doesn't apply. A second, shallower
  bug (the wake word firing on a phrase's tail syllable, then a
  leftover-syllable "turn" going back to sleep on an empty transcript)
  compounded the pause case and needed its own fix.
  **Separately, a real hardware gotcha, not a software one:**
  the XVF3800 mic array shipped with firmware that silently corrupted
  audio - LEDs, levels and playback all looked correct - while
  `hey_jarvis` scored 0.0007 instead of 0.998; traced to a USB/firmware
  bug and fixed by flashing v2.1.0. Worth checking again on any new mic
  array unit before assuming it's fine.
  - No FA/FR numbers or a trained-model threshold exist for a custom "hey
    maipai" phrase on this hardware. If the rebuild trains one, the hub's
    wake-word note (0.47 threshold, 2/4-frame hysteresis, FA-per-hour
    numbers) is the closest prior art, not a robot-side number to reuse
    directly - it was measured on different hardware and a browser/server
    runtime, not this board.

- **STT/TTS choices carried from the same lineage:** Moonshine tiny (STT)
  and Piper (TTS) on Pi CPU, alongside speaker-ID via sherpa CAM++. These
  were the actual compute-placement choice that shipped, not the
  dokibot-era `[measure]`-tagged plan that preceded them, but no
  Moonshine/Piper latency bench numbers survived in the docs pulled from
  `bot-legacy.git` beyond the pre-roll finding above - measure fresh
  before assuming a number.

- **Audio hardware requirement, worth re-verifying on new hardware:** any
  speaker driving the robot's voice must take 3.5mm analog input, never
  USB-audio or Bluetooth-only - a USB/BT speaker bypasses the XVF3800's
  line-out reference and blinds its hardware echo canceller, so the robot
  can't hear "stop" while talking. Confirmed working 2026-09-02:
  quiet-room double-talk through the array showed zero self-triggered
  wakes, and a real "stop talking" said over playback was heard and
  transcribed.
