# FACE-05: honor stop_event during the first-boot model download

Lane: codex-b, worktree `~/Developer/github.com/getmaipai/bot-codex`.
Model floor: Codex, `low`-to-`medium` reasoning (the shape is decided
below; implementing a background-thread-with-polling pattern this
codebase already uses elsewhere, not inventing a new one).

## Ready handshake

Before touching anything, reply with: the model named in your own
system prompt, your checkout path and branch, and "ready for FACE-05".
Wait for "start" before editing. Confirm you're on a fresh branch
based on current `origin/main` (which now includes FACE-04, landed
earlier today) before starting - `git log --oneline -3` should show
`Merge codex/face-04: refresh hub clients after cookie rotation` in
your history.

## Why

`app.py`'s own module docstring already names this gap in its own
words (read it first, lines 13-21 as of this writing - re-read, don't
trust the line number): once `run_paired_body` observes
`link.state.paired`, it calls `_build_conversation_loop(...)` directly
on its own thread, which downloads the wake-word models and SFace
(`ensure_wakeword_models`, `ensure_embedder`) synchronously over the
network the very first time an install ever reaches a paired state.
`stop_event` is not polled again until that whole call returns, so a
stop or SIGINT landing mid-download can take as long as the download
does (seconds to tens of seconds on a slow connection), not the
one-second contract the rest of this module honors. Every later boot
finds the models cached (`model_assets.py`'s own `is_installed` check)
and returns immediately, so this is real but narrow: it only matters
on the very first paired boot of a fresh install, or after a cache
wipe.

**The decided shape**: run `_build_conversation_loop(...)` on its own
daemon thread, and poll `stop_event` in a tight loop while waiting for
it, the same `threading.Thread` + bounded-wait pattern
`ConversationLoop._speak()` already uses in `run_loop.py` (read that
method first for the house style: start a thread, poll a stop signal
in a loop, `join()` once the loop exits). If `stop_event` fires before
the build thread finishes, `run_paired_body` returns immediately
(logging that it's abandoning the in-progress build) rather than
waiting for the download to finish - the build thread is a daemon
thread, so it dies with the process when this function returns and the
process actually exits, per `app.py`'s own `__main__` block. If the
build thread finishes normally (success or exception) before
`stop_event` fires, behavior is completely unchanged from today: the
existing `try/except Exception` around the build call (already in
`run_paired_body`, don't remove it) still catches a download failure
the same way it does now.

## Files you own

- `body/maipai_body/app.py` (`run_paired_body` only - do not touch
  `_build_conversation_loop` itself, its signature and body are
  unchanged by this item)
- `body/tests/test_app.py` (new tests)
- `docs/BACKLOG.md` (tick FACE-05, see step 5)

Do not touch `run_loop.py`, the three speech client classes, or
anything else FACE-04 just landed - this item is narrowly about the
one blocking call site in `run_paired_body`.

## Steps

1. Read `run_paired_body` in full (current shape, `body/maipai_body/
   app.py`, the `try: loop = _build_conversation_loop(...)` block) and
   `ConversationLoop._speak()` in `run_loop.py` for the thread+poll
   pattern to mirror.
2. Replace the direct `loop = _build_conversation_loop(...)` call with:
   start a `threading.Thread(target=..., daemon=True)` that calls
   `_build_conversation_loop` and stashes its result (or the exception
   it raised) somewhere the main thread can read after the fact (a
   small mutable container - a single-element list, or a tiny local
   class - your call, matching whatever this file's own style prefers;
   check if `run_loop.py` already has a precedent for "run a thread,
   capture its result/exception" to mirror exactly). Poll
   `stop_event.wait(_STOP_POLL_INTERVAL_S)` (the existing module
   constant, already used elsewhere in this same function) in a loop
   while the build thread is alive; if `stop_event` becomes set while
   the thread is still running, log at `info` level that a stop was
   requested mid-download and the build is being abandoned, then
   `return` immediately (do not `join()` an abandoned daemon thread -
   the process is exiting anyway per the existing `__main__` shutdown
   path). If the build thread finishes on its own before `stop_event`
   fires, `join()` it (should return instantly since it's already
   done) and proceed exactly as today: check for a stashed exception
   (log + return, the existing behavior) or use the stashed
   `ConversationLoop` result.
3. Keep every existing log line, state transition
   (`_log_state(_STATE_CONVERSATION_LOOP)`), and the existing
   `except Exception` handling's exact log message and behavior -
   this item changes *when* `stop_event` gets checked, not what
   happens on success or on a build failure.
4. Update the module docstring's caveat (lines 13-21) to describe the
   fix instead of the gap - state plainly that a stop mid-download is
   now honored within one poll interval, abandoning the in-progress
   download (which finishes or not on its own daemon thread, moot
   since the process is exiting).
5. Add one line to `docs/BACKLOG.md` ticking FACE-05 (search `grep -n
   "FACE-05" docs/BACKLOG.md` first, change its `- [ ]` to `- [x]` and
   add a short "Landed 2026-09-28: ..." note describing the fix,
   matching a neighboring landed item's exact convention).
6. Write tests in `body/tests/test_app.py` (read the existing
   `run_paired_body`-testing tests first - `_FakeLink`, the
   `test_run_paired_body_builds_and_runs_the_conversation_loop_once_paired`
   test already mocks `_build_conversation_loop`, mirror that pattern).
   At minimum:
   - A `_build_conversation_loop` replacement that blocks (e.g. waits
     on a `threading.Event` you control from the test) until the test
     itself releases it: confirm that setting `stop_event` while the
     mocked build is still blocked makes `run_paired_body` return
     within about one second (assert on elapsed wall-clock time, the
     same style the existing
     `test_run_paired_body_stops_within_one_second_of_the_stop_event_while_waiting`
     test already uses for the pre-pairing case - mirror it for the
     post-pairing, mid-download case).
   - A `_build_conversation_loop` replacement that returns quickly
     (or raises) BEFORE `stop_event` is ever set: confirm
     `run_paired_body` behaves exactly as it does today (reaches
     `state: conversation_loop` and runs the loop on success; logs and
     returns cleanly on a raised exception) - your regression guard
     that the existing two behaviors (from FACE-01's own construction
     pass) are completely unchanged.
7. Run `uv run pytest tests/test_app.py -v` from `body/` until green,
   then the full `uv run pytest` to confirm nothing else broke.
8. Stage `body/maipai_body/app.py`, `body/tests/test_app.py`,
   `docs/BACKLOG.md` by name (never `-A`). One commit.

## Acceptance evidence

- The two new test scenarios above, passing (paste the `pytest`
  summary line for `test_app.py`).
- Full `body/` test suite still green (paste the summary line).
- The two pre-existing behaviors (success path builds and runs the
  loop; a build-time exception is logged and returns cleanly) are
  unchanged - confirmed by the existing tests for those cases still
  passing without modification (or with only mechanical updates for
  the new threading wrapper, not behavior changes - say which if you
  had to touch either existing test at all).

## Exit checks

- `bash scripts/check.sh` from the `bot-codex` worktree root, green
  (paste the pass line and scope - this touches `body/maipai_body/`,
  so it should run the body leg).
- Code review at `medium` effort (a real behavior change to
  `run_paired_body`'s own control flow, even though it's narrowly
  scoped to timing during one specific window).
- One commit. Stage by name.
- Push `bot-codex`'s branch, or say you left it for the coordinator to
  merge.

## Reporting

Report **ready** first and wait for "start". Report **done** with: the
commit hash, the `check.sh` pass line and scope, both test scenarios'
pass confirmation, and the elapsed-time number your first test actually
measured (should be comfortably under a few seconds, matching the
"honored within one poll interval" claim - `_STOP_POLL_INTERVAL_S`'s
own value, check what it currently is). Report **blocked** with the
exact failing assertion or error. Report **question** if
`ConversationLoop._speak()`'s own thread+poll pattern doesn't
translate cleanly to this call site for a reason this brief didn't
anticipate (e.g., if capturing a thread's return value cleanly needs a
different mechanism than what `_speak()` itself uses, since `_speak()`
doesn't need to capture a return value, only know when the thread is
done) - say what's different and how you resolved it, don't silently
invent a shape this brief didn't ask for.
