# MaiPai Bot

The robot companion: a body that pairs with the hub like a pod, keeping a
full replica of the household and running the same packages under the
same rules, using the hub as its brain when reachable and its own model
when not. Standalone it is a complete product, never a stub. It runs on
any supported body: the MaiPai build of `docs/dev/build-record.md`
carries the standalone promise; Reachy Mini (Pollen Robotics) is the
second body, a connected one whose turns the hub runs, designed in
`docs/dev/design-reachy-mini-2026-09-27.md`. A body is a profile under
`body/bodies/` behind one HAL seam, never a fork of anything above it.

Org standards apply and are auto-loaded from the parent directory
CLAUDE.md (source:
[getmaipai/.github](https://github.com/getmaipai/.github)).

Fresh rebuild on the platform design, started 2026-09-03: see
[docs/dev.md](docs/dev.md) for the design record and
[docs/BACKLOG.md](docs/BACKLOG.md) for what's built and what's missing.
The shared record shapes live in `getmaipai/commons`'s `spec/` workspace
(tagged `spec-v0.1.73` as of this writing, the tag Home pins; it adds
`reconnecting` and `sleeping` to `robot.state.activity`); this
repo's Python body does not pin `maipai-spec` yet, since
`commons/spec/pyproject.toml` has no `[build-system]` table and a
git-installed build fails on setuptools' flat-layout autodiscovery
across the whole spec workspace (a comment in `body/pyproject.toml`
names the exact error). Nothing in `body/` needs spec shapes before the
runtime work in `docs/BACKLOG.md` starts, so this is not yet a blocker;
add the pin back once `commons/spec` ships real packaging metadata. The
pre-rebuild
robot (bench-proven on Pi 5 hardware: wake word, sherpa-onnx speech stack,
Hailo-10H model, ~90 skills) is preserved locally as
`legacy-backups/bot-legacy.git`, reference only for hard-won logic, never
a requirement of feature scope.

Stack: Python managed with uv, lint/format with Ruff, tests with pytest,
for the body (everything that touches hardware). The household runtime
(the turn engine, memory, guards, the link) is the hub's own TypeScript
code, pinned and run on Bun as the same package, per the design record's
section 2, a written deviation from the stack standard. Full stack
standard:
[STACK.md](https://github.com/getmaipai/.github/blob/main/STACK.md) in
`.github`.

Commands: `bash scripts/check.sh` from the repo root before every commit.
It runs Ruff, `ruff format --check` and pytest under `body/` (Python
3.12, managed with uv; `uv sync` from `body/` to set up the venv) before
the pinned `@maipai/standards` core, and the gate resolves std-v0.3.0
into `../.github-tags/std-v0.3.0` through `.github`'s `ensure-tag.sh`
(`MAIPAI_STANDARDS_DIR` names where the `.github` repo is). The
deterministic suite runs against a fake built from recorded fixtures on
every commit; the same suite also runs against Pollen's MuJoCo simulator
when `MAIPAI_BODY_LIVE=1` is set and a `reachy-mini-daemon --sim` answers
on port 8000. G2's real-model wake-word tests are gated the same way:
they run only when `MAIPAI_WAKEWORD_MODELS_DIR` points at a local
directory holding `melspectrogram.onnx`, `embedding_model.onnx`, and
`trained_hey_maipai_v2.onnx` (fetchable via `speech.models`, except the
last, which has no release asset yet), and skip otherwise; two of them
also want `MAIPAI_WAKEWORD_FIXTURES_DIR` pointing at real or synthesized
speech samples (`hey_maipai.wav`, `hey_my_car.wav`), skipping cleanly
without it. `uv sync --extra voice` pulls the wake-word runtime
(`openwakeword`, with `onnxruntime` forced to 1.30.0 via
`[tool.uv] override-dependencies` - `body/pyproject.toml`'s own comment
explains why `reachy-mini`'s exact `onnxruntime==1.27.0` pin is
overridden). Check `docs/BACKLOG.md` before assuming a given piece of
Python tooling (the household runtime, a package) is already wired up.
