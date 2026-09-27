# Reachy Mini fixtures

Recorded 2026-09-27 against
`reachy-mini-daemon` version `1.11.0` in simulation mode
(`--sim --headless --scene empty`), by `scripts/record_fixtures.py`.

- `openapi.json`: the daemon's OpenAPI schema. sha256: `1b138815b4ae8c1542230d38b68661242fff9668e030c5e1c856fcbee604d2fd`
- `daemon_status.json`: one `/api/daemon/status` response.
- `state_frames.jsonl`: real state-feed samples from `/api/state/ws/full`,
  recorded across a scripted goto-then-hold sequence (baseline, moving,
  held), one JSON sample per line in the shape
  `client.daemon_state_to_sample` produces.

Never hand-edited. Re-run `record_fixtures.py` against a running daemon to
refresh.
