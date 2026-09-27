# Reachy Mini fixtures

Recorded against Pollen's MuJoCo simulator, never the physical unit (not yet
owned).

- Daemon version: **1.11.0** (`reachy-mini` PyPI package, the same version
  pinned in `body/pyproject.toml`).
- Command: `MUJOCO_GL=egl reachy-mini-daemon --sim --headless --scene empty
  --no-media --fastapi-port 8000`.
- Recorded 2026-09-27 by `scripts/record_fixtures.py`.

| File | sha256 |
|---|---|
| `openapi.json` | `0af9ad8a7f54bfe05e516670be36f38e502b691bcd48ce2837a07e07b98c80b8` |
| `daemon_status.json` | `e6676950d4482d24273e2bc9552826cf8e64b57ddd2800524785b3dc6c03fb76` |
| `state_frames.jsonl` | `ea5b43636a2b965eb53fd618d2d03a0551f8fbe765afaf0539154c302a2110c2` |

`state_frames.jsonl` is 40 frames from `ws://localhost:8000/api/state/ws/full`
(`with_doa=true&with_imu=true`): ten at rest, then thirty while a
`/api/move/goto` request moved the head to pitch 0.2 rad, yaw 0.3 rad, body
yaw 0.1 rad and the antennas to +/-0.1 rad over one second. The daemon ran
with `--no-media`, so `doa` and `imu` are `null` in every frame; the fake
replays them as such. Each line also carries a `_t_monotonic_ns` field from
the recording run itself, which the fake ignores and re-stamps on replay.
