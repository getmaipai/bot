# MaiPai Bot

The robot companion: a body that pairs with the hub like a pod, keeping a
full replica of the household and running the same packages under the
same rules, using the hub as its brain when reachable and its own model
when not. Standalone it is a complete product, never a stub.

Org standards apply and are auto-loaded from the parent directory
CLAUDE.md (source:
[getmaipai/.github](https://github.com/getmaipai/.github)).

Fresh rebuild on the platform design, started 2026-09-03: see
[docs/dev.md](docs/dev.md) for the design record and
[docs/BACKLOG.md](docs/BACKLOG.md) for what's built and what's missing.
This repo stays a skeleton until `home/spec/` reaches v0.1, which it pins
as `maipai-spec @ git+...@spec-v0.1.0#subdirectory=spec`. The pre-rebuild
robot (bench-proven on Pi 5 hardware: wake word, sherpa-onnx speech stack,
Hailo-10H model, ~90 skills) is preserved locally as
`legacy-backups/bot-legacy.git`, reference only for hard-won logic, never
a requirement of feature scope.

Stack: Python managed with uv, lint/format with Ruff, tests with pytest.
Full stack standard:
[STACK.md](https://github.com/getmaipai/.github/blob/main/STACK.md) in
`.github`.
