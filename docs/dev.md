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
      std-v0.1.0.
- [ ] Everything else. Robot v0.1 starts once `home/spec/` v0.1 exists (the
      robot pins it as `maipai-spec @ git+...@spec-v0.1.0#subdirectory=spec`).
      Until then this repo stays a skeleton.

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
