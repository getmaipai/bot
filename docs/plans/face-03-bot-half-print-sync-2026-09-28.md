# FACE-03 (bot half): pull hub-synced face prints into the gallery

Lane: codex-b, worktree `~/Developer/github.com/getmaipai/bot-codex`.
Model floor: Codex, `medium` reasoning (new threading + HTTP client
module, mirroring two already-established patterns in this codebase,
not inventing new shapes).

## Ready handshake

Before touching anything, reply with: the model named in your own
system prompt, your checkout path and branch, and "ready for FACE-03
bot half". Wait for "start" before editing. Start from a fresh branch
based on current `origin/main`:

```
git fetch origin && git checkout -b codex/face-03-bot-half origin/main
```

## Why

`home`'s own FACE-03 hub half (a device-gated `GET
/api/biometric-prints/sync` route, `{as_of, prints}`, prints being the
full spec `BiometricPrint` record with `embedding`) is landing now -
read `home`'s `docs/dev.md`, "FACE-03: hub-synced face prints on the
robot" for the full design record (that repo is a sibling checkout at
`../home` if you need to read it directly). This body's own FACE-01
entry (`docs/BACKLOG.md`, search "the gallery starts empty") already
names the gap this item closes: `app.py`'s `_build_conversation_loop`
constructs a real `FaceGallery` that never gets any prints, so every
face check reports `unknown` forever. This item makes it pull from the
hub's new route instead.

**You do not need the hub route to actually be live to build and test
this** - this repo's own testing standard (`CLAUDE.md`'s Testing
standards: "deterministic and offline by default... a scripted
stand-in") means your suite runs against a fake HTTP server or a mocked
`requests.Session`, never a real network call, matching how
`test_turn_client.py`/`test_tts_playback.py` already test their own
hub clients. The wire shape below is already fully specified by the
design record, so there is nothing to guess.

## Files you own

- `body/maipai_body/link/prints.py` (NEW) - the sync client and its
  background thread.
- `body/maipai_body/vision/gallery.py` - `FacePrint` gains an `id`
  field; `FaceGallery` gains `replace_all()` (see Steps).
- `body/maipai_body/app.py` - `run_paired_body`/`_build_conversation_loop`
  wiring only (see Steps 4-5). Do not touch anything else in this file
  (FACE-04's cookie-rotation logic, FACE-05's build-thread-plus-poll
  logic, both already landed, stay exactly as they are).
- `body/tests/test_prints.py` (NEW).
- `body/tests/test_app.py` - new/updated tests for the wiring only.
- `docs/BACKLOG.md` (tick FACE-03 bot half, see step 7).

Do not touch `home` or `commons` - this item only reads a document from
`home` (`docs/dev.md`) and never a hub-repo source file.

## Steps

1. Read `body/maipai_body/vision/gallery.py` in full (`FacePrint`,
   `FaceGallery.add`/`remove`/`identify`, `ForeignModelPrint`) and
   `body/maipai_body/speech/turn_client.py` in full (the HTTP-client
   pattern to mirror: a `requests.Session`, a `Cookie: session=<value>`
   header built by hand - `headers={"Cookie": f"session={self._cookie}"}`,
   line ~119/145 in that file - never `requests`' own cookie jar, and
   the auth-failure-vs-connection-failure exception split). Also read
   `body/maipai_body/app.py`'s `_build_conversation_loop` and
   `run_paired_body` in full (the gallery is constructed inline today
   at `face_gallery=FaceGallery(model_id=_FACE_MODEL_ID,
   model_sha256=SFACE.sha256)` inside `_build_conversation_loop`) and
   `_hub_credentials_reader` (the existing "retains the last good URL"
   closure pattern, already used by FACE-04's cookie-rotation logic -
   your sync client needs the same live cookie/URL, not a snapshot
   taken once at pairing time).

2. `vision/gallery.py`: add `id: str` to `FacePrint` (it has no default -
   every print synced from the hub has a real id; nothing in this repo
   constructs a `FacePrint` without one today, so this is not a
   backward-compat concern, but grep `FacePrint(` across `body/` and
   fix any construction site this touches, including tests). Add
   `FaceGallery.replace_all(self, prints: Iterable[FacePrint]) -> None`:
   swaps `self._prints` for a new list built from `prints`, filtering
   out (not raising on) any print whose `model_id`/`model_sha256`
   doesn't match this gallery's own model - reuse the exact check
   `add()` already does, but this method logs a warning per skipped
   print (`"skipping <person_id>'s print: enrolled for a different
   model, re-enroll for the current model"` or similar) and continues,
   since a wholesale sync naturally mixes models across a fleet/history
   and one foreign print must never abort the rest (the design record's
   own acceptance criterion). Guard the swap with a `threading.Lock`
   (new `self._lock` in `__init__`) since `identify()`/`add()`/`remove()`
   run on the recognition thread while `replace_all()` will run on
   `PrintSync`'s own thread - wrap the read in `identify()` and the
   write in `replace_all()` (and the other existing mutators, `add`/
   `remove`, for the same reason) with that lock. This is the one
   change to already-landed methods; keep their behavior identical,
   only add the lock.

3. Write `body/maipai_body/link/prints.py`:
   - `PrintSyncError(RuntimeError)` - the connection itself failed
     (mirrors `TurnLinkLost`'s own distinction: a real transport/DNS/
     timeout failure, not a normal HTTP error status).
   - A `PrintSync` class, `__init__(self, gallery: FaceGallery,
     hub_credentials: Callable[[], tuple[str, str]], stop_event:
     threading.Event, *, interval_s: float = 60.0, session:
     requests.Session | None = None)`. `hub_credentials` is exactly the
     same `Callable[[], tuple[str, str]]` shape `ConversationLoop`
     already takes (cookie, base_url) - read `_hub_credentials_reader`'s
     return type to confirm the tuple order matches.
   - `run(self) -> None`: the thread's target. Loop: call
     `hub_credentials()` inside a try/except (mirror
     `run_loop.py`'s own hub_credentials-refresh try/except - a
     transient read failure logs a warning and keeps the gallery as it
     was, never clears it just because one refresh call failed), GET
     `{base_url}/api/biometric-prints/sync` with the
     `Cookie: session=<cookie>` header (mirror `turn_client.py`'s
     header construction exactly), a short timeout (5s is reasonable -
     this must never block `stop_event` handling for long). On 200:
     parse `{as_of, prints}`, build `FacePrint(id=p["id"],
     person_id=p["person_id"], model_id=p["model_id"],
     model_sha256=p["model_sha256"], embedding=np.array(p["embedding"],
     dtype=np.float32))` for each entry (voice prints never appear per
     the hub's own filter, so no modality check needed here), call
     `gallery.replace_all(...)`. On 401 or 403: log at `info` (an
     expected state right after a revoke, not an error) and call
     `gallery.replace_all([])` - an empty gallery, matching the design
     record's "losing the hub session empties the gallery rather than
     serving stale matches." On any other non-2xx, or a
     `requests.RequestException`: log a warning and leave the gallery
     as it is (a transient hub hiccup must not wipe working state).
     Then `stop_event.wait(interval_s)` - if it returns `True` (stop
     requested), return immediately; otherwise loop back to pull again.
     Pull once immediately on the first iteration (before the first
     wait), so a freshly-paired robot doesn't wait a full interval
     before its first real prints load.
   - No public method beyond `run()` and `__init__` - this is a plain
     `threading.Thread(target=print_sync.run, daemon=True)` target,
     matching this file's own established "a thread, a stop_event, a
     tight poll" idiom (`_STOP_POLL_INTERVAL_S`-style, though this
     class's own poll interval is much longer and is its own constant,
     not that one).

4. `app.py`: `_build_conversation_loop` currently builds
   `FaceGallery(...)` inline as a `ConversationLoop(...)` kwarg. Change
   it to construct `gallery = FaceGallery(model_id=_FACE_MODEL_ID,
   model_sha256=SFACE.sha256)` as a local variable first, pass
   `face_gallery=gallery` to `ConversationLoop` as before, and have
   `_build_conversation_loop` also start a `PrintSync` against that same
   `gallery` instance, using the same `hub_credentials` reader this
   function already builds at its top (`hub_credentials =
   _hub_credentials_reader(link, base_url)` - reuse the existing local,
   do not build a second one), as its own daemon thread, started before
   `_build_conversation_loop` returns. This means `PrintSync` starts
   pulling as soon as the conversation loop is built, on the same
   thread-per-concern model this function already uses for the wake-word
   engine. State this reasoning in a short comment (why `PrintSync`
   starts here rather than in `run_paired_body`: the gallery instance it
   needs to update doesn't exist until this function builds it, and this
   function already owns `hub_credentials`'s construction).

5. `PrintSync`'s thread also needs `run_paired_body`'s own `stop_event`
   to shut down cleanly with the rest of the process - `_build_conversation_loop`
   does not currently receive `stop_event` as a parameter (check its
   current signature - `client, session_cookie, base_url, cache_dir,
   link`). Add `stop_event: threading.Event` as a new parameter, and
   update `run_paired_body`'s one call site (inside `build_loop()`) to
   pass its own `stop_event` through. This is a narrow, mechanical
   signature change - do not touch anything else about how
   `_build_conversation_loop` is invoked (the build-thread-plus-poll
   wrapper around it, FACE-05's own fix, stays exactly as it is; it
   already has access to `stop_event` in its enclosing scope, this
   change only threads it one level deeper).

6. Tests, `body/tests/test_prints.py` (new, mirror
   `test_turn_client.py`'s or `test_tts_playback.py`'s own fake-HTTP-
   response style - check which one uses a simpler mocked-response
   approach and follow that one, not both):
   - A successful pull replaces the gallery's prints (assert via a
     subsequent `identify()` call against a known embedding, not by
     reaching into `_prints` directly - test the real public behavior).
   - A second pull with a person missing from the new snapshot makes
     that person's subsequent `identify()` call return `unknown` (the
     "revocation within one pull cycle" acceptance criterion).
   - A 401/403 response empties the gallery (same identify-returns-
     unknown check, but starting from a populated gallery).
   - A foreign-model print in the response is skipped (a warning
     logged, or just assert it's absent from a subsequent `identify()`
     while a same-model print in the same response still matches) -
     the rest of the batch still loads.
   - A connection failure (mock `requests.Session.get` raising
     `requests.RequestException`) leaves a previously-populated gallery
     untouched.
   - `stop_event` being set makes `run()` return within about one
     `interval_s`-independent bound - since the first pull happens
     immediately and only the *wait* is interval-bound, set
     `stop_event` before starting the thread (or right after) and
     assert the thread joins quickly (this test doesn't need a slow
     real interval - construct `PrintSync` with a short `interval_s`
     for the test, or stub `stop_event.wait` - your call, whichever is
     less brittle).
   `body/tests/test_app.py`: update whatever existing
   `_build_conversation_loop` mock/call-site assertions need the new
   `stop_event` parameter (mechanical - the FACE-04/FACE-05 tests
   already mock this function, they'll need their `assert_called_once_with(...)`
   updated to include it, nothing behavioral).

7. `docs/BACKLOG.md`: `grep -n "FACE-03 (bot half)"`, tick the item and
   its sub-bullets you completed, matching FACE-01/04/05's own
   "Landed 2026-09-28: ..." convention on this same entry.

8. Run `uv run pytest tests/test_prints.py tests/test_app.py -v` from
   `body/` until green, then the full `uv run pytest` to confirm
   nothing else broke.

9. Stage `body/maipai_body/link/prints.py`, `body/maipai_body/vision/gallery.py`,
   `body/maipai_body/app.py`, `body/tests/test_prints.py`,
   `body/tests/test_app.py`, `docs/BACKLOG.md` by name (never `-A`).
   One commit.

## Acceptance evidence

- Every scenario in step 6's test list, passing.
- The gallery's `threading.Lock` genuinely guards concurrent
  `identify()`/`replace_all()` access - say in your done report that
  you added it and to which methods.
- Full `body/` test suite still green.

## Exit checks

- `bash scripts/check.sh` from the `bot-codex` worktree root, green
  (paste the pass line and scope).
- Code review at `medium` effort (new threading, a new HTTP client, a
  gallery mutation under lock - real control-flow, not mechanical).
- One commit, staged by name.
- Push `codex/face-03-bot-half`, or say you left it for the
  coordinator to merge.

## Reporting

Report **ready** first, wait for "start". Report **done** with: the
commit hash, `check.sh`'s pass line and scope, confirmation each test
scenario above passes, and which design choice you made where this
brief said "your call" (the fake-HTTP test style you mirrored, the
exact skip-log wording in `replace_all`). Report **blocked** with the
exact failing assertion or error. Report **question** if `home`'s own
FACE-03 hub half turns out not to be merged/available to read yet when
you look, or if its actual response shape differs from what this brief
describes - do not guess a shape, ask.
