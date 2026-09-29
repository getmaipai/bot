# FACE-04: pick up a rotated hub session cookie between turns

Lane: codex-b, worktree `~/Developer/github.com/getmaipai/bot-codex`
(a different repo than this lane's other recent work - confirm you're
actually in `bot-codex`, not `home-codex-2`, before starting: `pwd` and
`git remote -v` should show `getmaipai/bot`). Model floor: Codex,
`low`-to-`medium` reasoning (one real design decision already made
below - where the refresh check happens and how it's threaded through -
so this is closer to "implement the decided shape" than "design it").

## Ready handshake

Before touching anything, reply with: the model named in your own
system prompt, your checkout path and branch, and "ready for FACE-04".
Wait for "start" before editing.

## Why

`app.py`'s `run_paired_body` docstring already names this gap in its
own words (read it first: `body/maipai_body/app.py`, the
`run_paired_body` function's docstring, and `_build_conversation_loop`
just above it): `TurnClient`, `SttStreamClient` and `TtsPlaybackClient`
each capture `session_cookie` as a plain string at construction time,
once, when `_build_conversation_loop` builds them right after pairing.
G4's own `LinkLifecycle.run()` re-redeems the hub session every 24
hours (`REFRESH_INTERVAL_S` in `body/maipai_body/link/lifecycle.py`)
and that re-redeem may issue a new session cookie - none of the three
clients would ever see it, so a robot paired and running past that
boundary risks every hub call starting to fail with a stale credential
until the process restarts.

**The decided shape**: check for a rotated cookie once per turn, at the
very start of `ConversationLoop._run_turn()` (`body/maipai_body/
run_loop.py`) - never mid-turn, since a turn already in flight must not
have its clients swapped out from under it. `ConversationLoop` gains an
optional constructor parameter, a callable that returns the current
`(session_cookie, base_url)`; if given, `_run_turn()` calls it at entry
and, if the cookie differs from what the loop currently holds,
reconstructs `self._stt`/`self._turn`/`self._tts` in place (three
private attributes already set once in `__init__` - nothing else about
`ConversationLoop`'s shape changes). `app.py` supplies the callable as
a closure reading `link.hub_client.session_cookie` and
`link.pairing_store.load().base_url` live, the same two facts
`_build_conversation_loop` already reads once at construction.

This does **not** touch `TurnClient`, `SttStreamClient`, or
`TtsPlaybackClient` themselves - their own constructors, tests, and
public shape are completely unchanged. The refresh happens entirely by
reconstructing new instances of the same classes, which is why this is
lower-risk than it might sound: no existing class's contract changes.

## Files you own

- `body/maipai_body/run_loop.py` (`ConversationLoop.__init__`,
  `_run_turn`)
- `body/maipai_body/app.py` (`_build_conversation_loop`,
  `run_paired_body`)
- `body/tests/test_run_loop.py` (new tests)
- `docs/BACKLOG.md` (tick FACE-04, see step 6)

Do not touch `body/maipai_body/speech/turn_client.py`,
`stt_stream.py`, or `tts_playback.py` - this item's whole point is that
those three files don't need to change.

## Steps

1. Read `ConversationLoop.__init__` (`run_loop.py`, around line 123 as
   of this writing - re-read, don't trust the line number) and
   `_run_turn` (around line 292) to confirm the current shape before
   editing.
2. Add a new optional constructor parameter to `ConversationLoop`:
   `hub_credentials: Callable[[], tuple[str, str]] | None = None`
   (returns `(session_cookie, base_url)`). Store it as
   `self._hub_credentials`. Also store the `(session_cookie, base_url)`
   pair the loop was actually built with, so `_run_turn` has something
   to compare against - e.g. `self._current_hub_credentials:
   tuple[str, str] | None = None`, set once in `__init__` from whatever
   `stt_client`/`turn_client`/`tts_client` were actually constructed
   with if you can recover that cleanly, or simply left `None` until
   the first `_run_turn` call establishes a baseline (your call which
   is cleaner - state which you picked and why in your done report).
3. At the very start of `_run_turn` (before `self._enter(FunnelState.
   LISTENING)`), add: if `self._hub_credentials` is not `None`, call
   it, compare the result to `self._current_hub_credentials`; if
   different, reconstruct `self._stt = SttStreamClient(base_url,
   session_cookie)`, `self._turn = TurnClient(base_url,
   session_cookie)`, `self._tts = TtsPlaybackClient(base_url,
   session_cookie, self._playback)` (reusing the existing
   `self._playback`, never constructing a new `AudioPlayback`), and
   update `self._current_hub_credentials` to the new pair. Log at
   `info` level when this happens (`logger.info("hub session cookie
   rotated, reconstructing hub clients")` or similar - this is a rare,
   worth-knowing-about event, not a routine tick). If
   `self._hub_credentials` is `None` (the parameter wasn't given -
   e.g. every existing test in `test_run_loop.py` that constructs
   `ConversationLoop` directly without it), skip this check entirely -
   zero behavior change for every caller that doesn't opt in.
4. In `app.py`'s `_build_conversation_loop`, add a `link:
   LinkLifecycle` parameter (it already has `client`, `session_cookie`,
   `base_url`, `cache_dir` - add `link` alongside them) and pass
   `hub_credentials=lambda: (link.hub_client.session_cookie or "",
   _current_base_url(link) or base_url)` into the `ConversationLoop(...)`
   call - you'll need a small helper (or inline expression) that reads
   `link.pairing_store.load()` and returns its `base_url`, falling back
   to the `base_url` already passed in if the read ever returns `None`
   (it shouldn't, since pairing already succeeded once to get here, but
   never let this closure raise - a failed credential refresh should
   log and keep using the last-known-good pair, not crash the turn).
   Update `run_paired_body`'s own call to `_build_conversation_loop` to
   pass `link` through (it already has `link` in scope).
5. Write tests in `body/tests/test_run_loop.py` (read the existing
   `_ScriptedTurnClient`/`_ScriptedSttStreamClient`/
   `_ScriptedTtsPlaybackClient` stand-ins near the top of that file
   first - your new tests should construct `ConversationLoop` the same
   way the existing happy-path test does, just adding
   `hub_credentials=`). At minimum:
   - A `hub_credentials` callable that returns the SAME pair on every
     call: after two full turns, confirm the scripted clients were
     never reconstructed (whatever signal you can observe - e.g. wrap
     the client classes' constructors with a counter, or check `id()`
     stays the same across turns via a reference captured before/after).
   - A `hub_credentials` callable that returns a DIFFERENT pair
     starting on the second call: after the first turn, confirm
     `self._stt`/`_turn`/`_tts` are different objects than they were
     for the first turn (same technique), and that the second turn's
     own network activity went through clients built with the NEW
     cookie (assert on whatever the scripted stand-ins record about
     their own construction args - check what they already expose).
   - No `hub_credentials` given at all (the default `None`): confirm
     existing behavior is completely unchanged - this is your
     regression guard that every current caller and every currently
     passing test in this file still works exactly as before.
6. Add one line to `bot/docs/BACKLOG.md` ticking FACE-04's own entry
   (search `grep -n "FACE-04" docs/BACKLOG.md` first, change its
   `- [ ]` to `- [x]` and add a short "Landed 2026-09-28: ..." note in
   its own body describing the per-turn refresh check, matching this
   repo's existing style for a landed item - read a neighboring `[x]`
   item first for the exact convention).
7. Run `uv run pytest tests/test_run_loop.py -v` from `body/` until
   green, then the full `uv run pytest` to confirm nothing else broke.
8. Stage `body/maipai_body/run_loop.py`, `body/maipai_body/app.py`,
   `body/tests/test_run_loop.py`, `docs/BACKLOG.md` by name (never
   `-A`). One commit.

## Acceptance evidence

- The three new/updated test scenarios above, passing (paste the
  `pytest` summary line for `test_run_loop.py`).
- Full `body/` test suite still green (paste the summary line).
- A caller that never passes `hub_credentials` (every existing test,
  and any future caller that doesn't need this) sees zero behavior
  change - confirmed by the full suite passing unchanged, not just
  asserted.
- The refresh check only ever fires at the start of `_run_turn`, never
  mid-turn or during `_speak` - confirmed by reading your own diff
  once more before reporting done: there should be exactly one call
  site for `self._hub_credentials()`.

## Exit checks

- `bash scripts/check.sh` from the `bot-codex` worktree root, green
  (paste the pass line and the scope it picked - this touches
  `body/maipai_body/`, so it should run the body leg).
- Code review at `medium` effort (a real behavior change to
  `ConversationLoop`'s own turn lifecycle, even though it's additive
  and opt-in).
- One commit. Stage by name.
- Push `bot-codex`'s branch, or say you left it for the coordinator to
  merge.

## Reporting

Report **ready** first and wait for "start". Report **done** with: the
commit hash, the `check.sh` pass line and scope, the three test
scenarios' pass confirmation, and which choice you made in step 2 (how
`self._current_hub_credentials` gets its initial baseline) with your
reasoning. Report **blocked** with the exact failing assertion or
error. Report **question** if `link.pairing_store.load()`'s exact
return shape isn't what this brief assumes (re-read
`body/maipai_body/link/store.py`'s `HubPairing` model yourself rather
than trusting this brief's memory of its `base_url` field), or if
`LinkLifecycle`'s public surface doesn't expose what step 4 assumes
(`hub_client`, `pairing_store` - both were added earlier today per
`docs/dev.md`/`docs/BACKLOG.md`'s own FACE-01 construction-wiring
entry; re-read `body/maipai_body/link/lifecycle.py` directly to
confirm their exact current shape before relying on this brief's
description of them).
