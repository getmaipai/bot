# Backlog

What's missing to go from this skeleton to a working Robot v0.1. This is a
scannable list, not a narrative - full reasoning and decision history for
any item lives in `docs/dev.md`. Update this file whenever a gap closes or
a new one is found; don't let it drift from what `main` actually does.

Rough size tags: **S** (a session or less), **M** (a real slice, days),
**L** (a platform-level capability, needs its own design pass first).

Repo state as of 2026-09-06: `bot/` has no source tree at all yet, only
docs, legal files, and `scripts/check.sh` (confirmed by listing the repo -
no `package.json`, no `deno.json`, no directory referencing
`maipai-spec`). `docs/dev.md`'s own "Step 0 status" says Robot v0.1 starts
once `home/spec/` v0.1 exists; `home`'s spec v0.1 is done (its own dev.md),
but nothing in this repo pins it yet, so Robot v0.1 itself has not started.

## Step 0: repo scaffolding

- [x] Repo reset to a clean history (S) - `LICENSE` (AGPL-3.0), `NOTICE`,
      `README.md`, `docs/dev.md` (the design record), `scripts/check.sh`
      pinned to `@maipai/standards` std-v0.2.0. Verified: `git log`
      (`f217451`, `578c43c`) and the files present in the repo today.
- [x] Port the pre-rebuild bench and wake-word learnings into `docs/dev.md`
      (S) - done 2026-09-06 (`f4e9c9a`, "Notes for later" section): serving
      stack choice (`llama-server`, not Ollama), the two-model
      talk/think split, wake-word firmware and pre-roll findings. Reference
      material for the items below, not code.

## Robot v0.1 (not started)

Per `docs/dev.md`'s Roadmap: prepare the Pi, the head, the voice loop, the
local engine, the safety layer, Tier 0 packages, memory in spec shape,
Wi-Fi provisioning, standalone operation. None of this has a line of code
in this repo yet - confirmed by the empty tree above, not inferred from
the roadmap text. Every item below is therefore `[ ]` and every item is
**L**: each is a platform-level capability needing its own design pass,
not a quick slice, and none can be sized smaller until that pass happens.

- [ ] Pin and consume `home/spec/` v0.1 (`maipai-spec @
      git+...@spec-v0.1.0#subdirectory=spec`, per `docs/dev.md`'s own
      framing) - nothing in the repo references it yet. This is the real
      unblock for everything else below.
- [ ] The voice loop (wake word, VAD, STT, TTS) - legacy's bench used
      `hey_jarvis` (stock openWakeWord, not a trained "hey maipai" model),
      Moonshine tiny (STT), Piper (TTS), sherpa CAM++ (speaker ID); the
      0.3s post-wake silence cap and the XVF3800 firmware v2.1.0 gotcha are
      both recorded in `docs/dev.md` as things to re-verify on new
      hardware, not code that exists here.
- [ ] The local inference engine (talk/think split on the Hailo-10H AI
      HAT+ 2 plus a CPU `llama-server`) - `docs/dev.md`'s Notes for later
      has the full serving-flag and model-choice writeup (Qwen3-1.7B on
      Hailo-10H, 96% guarded) as prior art; none of it is wired up in this
      repo.
- [ ] The safety layer - platform plan chapter 3/7/8 territory; no
      `csamGuard`-equivalent or text safety floor exists in this repo
      (contrast `home`'s `spec/safety/`, which does).
- [ ] Tier 0 packages, running under the same manifest/recipe shapes as
      `home` - no package host, no bundled packages exist here yet.
- [ ] Memory in spec shape (person, entity, episode records matching
      `home/spec/`) - no local store exists in this repo yet.
- [ ] Wi-Fi provisioning for a standalone-first boot - not started.
- [ ] Pairing with the hub (`hublink`-equivalent: pod replica, memory and
      settings sync, using the hub as brain when reachable) - platform plan
      calls this the Hub v0.3 dependency (the link); not started here and
      not shippable before that hub-side work lands either.
- [ ] Standalone operation (own model, own packages, own settings when the
      hub is unreachable) - the core promise of principle 2 in
      `getmaipai/CLAUDE.md`; nothing to point at yet since nothing above it
      exists.

## Legacy review queue

Every legacy robot skill gets a one-line verdict here before it becomes
part of the fresh build (platform plan section 5.8). Empty until that
review pass runs - `docs/dev.md`'s own table confirms this hasn't started
(`_(none reviewed yet)_`).
