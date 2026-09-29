# G10-BODY: push the robot.state frame to the hub

Lane: codex-b, worktree `~/Developer/github.com/getmaipai/bot-codex`.
Model floor: Codex, `medium` reasoning (new threading + HTTP client
module mirroring an already-landed, already-verified pattern from
tonight's own `link/prints.py`).

## Ready handshake

Reply with model, checkout path and branch, "ready for G10-BODY". Wait
for "start". Start from a fresh branch off current `origin/main`:

```
git fetch origin && git checkout -b codex/g10-body origin/main
```

## Read this first

`docs/BACKLOG.md`'s own **G10-BODY** entry (grep for it) IS your full
work order, already written in detail: the exact file to create
(`body/maipai_body/link/state.py`), the exact pattern to mirror
(`link/prints.py`'s `PrintSync`, already landed tonight - read it in
full first), the exact hook points in `run_loop.py`
(`_enter()` line ~204, `set_muted()` line ~247, `_presence_loop()`
line ~445 - confirmed present, read each), the frame shape, the timing
(15s heartbeat, immediate send on change), and the full acceptance
criteria. This brief only adds a few things that entry doesn't spell
out mechanically.

`home`'s hub-half route (`PUT /api/devices/me/state`, gated by
`requireDeviceSession("robot")`) is now live on `home`'s main - this
item is no longer blocked. Full design reasoning if you want more
context: `home`'s `docs/dev.md`, "Robot device state" (2026-09-29).

## The frame shape, exactly (from `commons/spec/schemas/robot-state.schema.json`,
## spec-v0.1.55, already tagged)

```json
{
  "activity": "starting" | "idle" | "listening" | "thinking" | "speaking",
  "muted": boolean,
  "tracking": boolean,
  "on_battery": boolean | null,
  "battery_level": number | null,
  "daemon_version": string | null
}
```

This body (Reachy Mini) always sends `on_battery: null, battery_level: null`
(design §7 - it cannot read either). For `daemon_version`: check what
the SDK/daemon actually exposes (grep the vendored `reachy_mini`
package or its own client for a version string); if nothing is
exposed, send `null` and note it in your done report as a real,
accepted gap - do not invent a value. **This repo does not currently
pin `commons/spec`'s Python package** (a known, already-documented
condition in this repo's own `AGENTS.md` - `maipai_body`'s own
`pyproject.toml` has a comment explaining why) - so build the frame as
a plain `dict`/typed structure matching the shape above by hand, do
not add a new spec dependency to unblock this item; that's a separate,
already-tracked gap.

## Files you own

- `body/maipai_body/link/state.py` (NEW): `StateReporter`, modelled on
  `link/prints.py`'s `PrintSync` - same constructor shape
  (`hub_credentials: Callable[[], tuple[str, str]]`, `stop_event`, an
  optional `requests.Session`, `interval_s: float = 15.0`, `timeout=5`).
  `run()`: on each wake (an `on_change` event firing, or the interval
  elapsing, whichever first), build the current frame from a snapshot
  provider you pass in, PUT it to `{base_url}/api/devices/me/state`
  with the `Cookie: session=<cookie>` header (mirror `turn_client.py`'s
  own header construction exactly, same as `link/prints.py` already
  does), 5s timeout. On any failure (connection error, non-2xx): log a
  warning and wait for the next wake - never retry-loop, never crash.
  A 401/403 is not special-cased here (unlike `PrintSync`'s own gallery-clearing
  behavior on 401/403 - there's no local state to clear for an
  outbound-only reporter); just log and continue, the credentials
  reader will pick up a rotated cookie on its own next call.
- `body/maipai_body/run_loop.py`: `ConversationLoop` gains an
  `on_change: Callable[[], None] | None = None` constructor param
  (optional, matching `hub_credentials`'s own optional-param
  precedent), called at the end of `_enter()`, at the end of
  `set_muted()`, and at the tracking-state-change edge inside
  `_presence_loop()` (read that method first to find the exact edge -
  it already has SOME edge-detection logic for other purposes, mirror
  its own pattern rather than adding a second one). This callback's
  only job is to signal the `StateReporter`'s own `threading.Event` -
  `ConversationLoop` itself does not know about `StateReporter` or
  HTTP at all, keeping the dependency one-directional (the reporter
  reads the loop's state via a snapshot method, the loop just fires a
  plain callback with no knowledge of what's listening).
- `ConversationLoop` also needs a `snapshot()` method (or similar) the
  `StateReporter` can call to read current `activity`/`muted`/`tracking` -
  check what state is already tracked as instance attributes
  (`FunnelState`, the mute flag, presence tracking) and expose a small
  read-only method rather than making every field public.
- `body/maipai_body/app.py`: `run_paired_body` starts the
  `StateReporter` thread as soon as `link.state.paired` is confirmed
  true (the same point `_hub_credentials_reader` is already
  constructed), BEFORE the conversation-loop build thread starts -
  this is what makes `starting` reportable during the (possibly
  minutes-long) first-boot model download. Its snapshot provider
  returns a fixed `starting` frame until `_build_conversation_loop`
  actually returns a real `ConversationLoop`, then switches to reading
  that loop's own `snapshot()`. Read the current `run_paired_body`/
  `_build_conversation_loop` structure in full first (FACE-05's own
  build-thread-plus-poll wrapper is already there - this item adds a
  parallel, independent thread alongside it, not inside it).
- `body/tests/test_state_reporter.py` (NEW, mirror `test_prints.py`'s
  own fake-HTTP-response test style exactly).
- `body/tests/test_run_loop.py`, `body/tests/test_app.py`: mechanical
  updates only for the new constructor param / new thread, matching
  whatever FACE-05's/G10's own prior test updates already did for
  similar additions.
- `docs/BACKLOG.md`: tick G10-BODY with a "Landed 2026-09-29: ..." note
  matching this file's own established convention.

Do not touch anything in `home` or `commons` - the hub route and the
spec schema are both already landed.

## Tests (mirror `test_prints.py`'s scenarios, adapted for a push
## reporter instead of a pull sync)

- A frame is sent on `_enter()` (a funnel state change).
- A frame is sent on `set_muted()`.
- A frame is sent on a tracking-state edge.
- A heartbeat fires after the interval elapses with no change (inject
  a short interval in the test, don't wait a real 15s).
- `starting` is sent before a real `ConversationLoop` exists.
- A connection failure logs and does not crash or busy-loop (mock
  `requests.Session.put` raising `requests.RequestException`).
- `stop_event` being set makes the reporter's `run()` return promptly.

## Exit checks

- `bash scripts/check.sh`, green, paste the pass line and scope.
- Code review at `medium` effort (new threading, a new HTTP client,
  real control-flow additions to `ConversationLoop`/`run_paired_body`).
- One commit, staged by name.
- Push `codex/g10-body`, or say you left it for the coordinator.

## Reporting

Report **ready**, wait for **start**. Report **done** with: commit
hash, `check.sh`'s pass line and scope, confirmation each test scenario
passes, and what you found for `daemon_version` (a real value, or `null`
with the gap noted). Report **blocked** with the exact failure. Report
**question** if `_presence_loop()`'s tracking-edge detection doesn't
have an obvious hook point to reuse - don't invent a second
edge-detection mechanism silently.
