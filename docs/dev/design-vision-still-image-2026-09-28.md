# Vision: the still-image call (2026-09-28)

G11's floor (presence and tracking - "a face is tracked," no identity)
landed with G9. This is the next rung the gap audit names and asks for
its own design pass first (`docs/dev/reachy-mini-gap-audit-2026-09-27.md`,
G11): "a still image for the hub is the v0.2 host call the design
already names, consented and explicit" (`design-reachy-mini-2026-09-27.md`
section 6). Scope here is **general scene understanding** - what the
robot sees, described in words, for a request like "what am I holding"
or "look at the table and tell me what's there." It is deliberately
**not** face/voice identity or gesture recognition: that is a separate
line of work (`docs/dev/face-voice-recognition-design-2026-09-28.md`,
now confirmed by Jesse directly, 2026-09-28) with its own design
amendment, and nothing below depends on it or feeds it.

Every claim below was checked in the code or doc named, not assumed.

## 1. The blocker this design cannot route around

The Stack declares a `vision` role id (`home/backend/src/wire.ts:722`,
`stack/backend/src/roles.ts`) and `home`'s `llm.ts:61` lists it in the
`LlmRole` union - but `llm.ts:69`'s `IMPLEMENTED_ROLES` is `{"chat"}`
only. Calling role `"vision"` today hits a 400 (`unsupported_role`,
`llm.ts:244-249`, "the vision model role is not implemented on this
host build yet"). No model is pinned to it anywhere in the Stack's
`modelCatalog.ts`/`engineCatalog.ts`; it appears only in per-tier
availability tables as a future possibility.

**This means: there is no end-to-end path today, and none of the
bot-side work below closes that gap.** Wiring an actual vision-capable
model to the `vision` role is a Stack/home item, out of scope for this
repo and this session. What follows designs the full shape so the
bot-side half is ready the day that role is real, and builds the one
piece of it that is genuinely useful on its own regardless of timing.

## 2. Consent: why a modal doesn't fit this body

Section 5 of the design record is explicit: this body "has no eye,
mouth, ring or screen." A confirm-dialog pattern (the org's "no
hand-built UI" rule points at `commons/ui`'s vendored
`alert-dialog.tsx`, wrapped the way `ConfirmDialog.tsx` already does)
is the right primitive for a *screened* surface - the PWA, a future
Go client - asking "let the robot use your camera for this?" once,
per the org's adult-unlock ceremony (`SAFETY.md`: "a single clear
dialog... one confirmation, no legalese ceremony, never repeated").
It is the wrong shape for this body: there is nothing to render it on.

The design record's own word is "consented **and explicit**," not
"confirmed via a dialog." The natural reading for a screenless,
voice-first device: **the spoken request itself is the consent
event.** A person says "look at this" or "what do you see" - an
action they take on purpose, the same way saying the wake word is
already consent to be heard. No robot capture is ever passive,
scheduled, or triggered by presence alone; it only happens inside a
turn the person started by asking for it (one frame, not a stream).
This needs no new UI, no round trip, and no component this body
cannot show. It also matches the "software mute" posture already
established for audio (G8): capture is opt-in per use, not
opt-in-once-then-forgotten.

**A review caught a real gap in that analogy (2026-09-28), not fixed
by the paragraph above alone:** the wake word is a fixed acoustic
pattern the person controls deterministically - it either fired or it
didn't, nothing probabilistic about *intent*. A vision request is
recognized by the turn engine's own intent classification, which is
not deterministic: an ASR mishearing, or a figurative remark ("I
never really look at this the way you do"), could be read as a photo
request the person never actually meant, and a capture would fire
with no real ask behind it - exactly the "consented and explicit" bar
this design claims to clear, not actually met by intent inference
alone. Closing this for real is `home`'s own job (the turn engine's
intent classifier, not this repo), but the requirement belongs here,
named plainly rather than left implicit: a vision-capture intent needs
a materially higher confidence bar than an ordinary turn action before
it fires at all (a misread "tell me a joke" costs nothing; a misread
photo request costs a real capture), and the robot's own `SIGNAL` cue
for a recognized vision request should render *before* the capture
happens, not after - the same "cue precedes the audio sample" ordering
G9 already holds itself to, giving a person a chance to hear it start
and correct a misread ask before a frame is taken, not just after the
fact. Whoever implements the hub-side capture-request event should
treat this as part of that event's own acceptance, not an assumption
this note gets to make for them.

**Where a screen exists** (the PWA or a future Go client, per Jesse's
own confirmation that browser/device cameras - not a camera on the
hub server itself - are how the hub and Go do their own recognition
work), the standing `ConfirmDialog` pattern applies normally and is
out of scope here (a `home`/`go` item).

## 3. The capture and hub-route shape

Reusing what already exists, not inventing a parallel channel:

- **The turn engine recognizes the intent.** A vision request is not
  a new wire primitive; it is a normal turn whose reply plan calls
  for a robot-side capture, the same way any other tool call is
  recognized today. This is entirely `home`-side (`turnEngine.ts`)
  and not attempted from this repo.
- **The hub asks the robot for one frame.** `turn.ts` already has a
  request-shaped call for something in flight
  (`POST /api/turn/{id}/cancel`, no body, robot-authenticated) - a
  capture request is the same shape in the other direction: the hub
  needs a short-lived way to ask the paired robot for a frame *during*
  a turn, get one back, and continue the same turn with a description
  in hand. The turn stream's own event union (already carrying
  `turn_meta`, `signal`, `delta`, `done`, `error`) is the natural home
  for this rather than a second connection: a `capture_request` event
  down the existing stream, answered by a robot-initiated
  `POST /api/turn/{id}/frame` (mirroring `cancel`'s own shape:
  authenticated by the robot's session, no new transport). This is a
  `home` wire-shape decision (the exact event names, the route), named
  here as the shape that reuses what's already proven, not decided
  unilaterally from the bot repo.
- **The frame reuses the existing attachment shape.** `turn.ts:697-733`
  already accepts `document_attachments: {name, media_type, data}[]`,
  `data` a `data:image/...;base64,...` URI, validated by a real regex,
  capped at 70MB. A robot-captured frame is not a document, but the
  wire shape (a named, typed, base64 image) is identical to what a
  capture needs to send back - reusing it means no new validation
  logic, no new size/type ceremony, just a robot-authenticated
  producer instead of a person's own upload. Whether that is literally
  the same field or a sibling one with the same shape is `home`'s call
  at implementation time, not fixed here.
- **The robot's own job is exactly one thing: capture one frame,
  encode it, send it, and speak the reply's own cue-driven summary
  once the hub responds** - all of it inside the run loop's existing
  `THINKING` state (no new funnel state), since a vision request is
  just a turn whose thinking takes a little longer, waiting on a
  frame round trip instead of only a model call.

## 4. What's real on the bot side today, and what isn't

`Camera.get_frame()` (`hal/seam.py:239-245`) is already wired end to
end on the real client (`bodies/reachy_mini/client.py:227-229` calls
straight through to `self._reachy.media.get_frame()`, the vendor
SDK). Its docstring claims "RM-06 is its real consumer" - checked,
and false: RM-06 only ever consumes `FaceTracker`
(`enable_tracking`/`disable_tracking`/`get_face_target`), never
`Camera`. Nothing in this repo has ever called `get_frame()`. Fixed
as part of this pass (see below) since a docstring naming a consumer
that doesn't exist is exactly the kind of stale claim the org's
own "checked in the code, not assumed" habit exists to catch.

`FakeReachyMiniClient.get_frame()` (`fake.py`) unconditionally returns
`None` - no fixture-backed image exists in the fake at all, unlike
audio (`_load_wav_as_stereo_16k` loads a real WAV fixture). Any
deterministic test of a capture flow needs that fixture path built
first, mirroring the audio pattern exactly: a real small JPEG fixture
on disk, loaded once, returned as a real `NDArray[uint8]` frame - not
a mock, matching the org's "against real stand-in servers/fakes" habit
for every other module in this repo.

The vendored SDK also ships `reachy_mini.vision.face_detector.FaceDetector`
(YuNet on ONNX Runtime, downloaded from `pollen-robotics/
face_detection_yunet_2026may` via `hf_hub_download` - a bounding box,
eye and nose keypoints per face, **no embedding, no identity, checked
in the installed source**). This is pure detection, already present as
a dependency, unused anywhere in this repo. It is not needed for the
floor already landed (the daemon's own tracker does its own internal
detection for `enable_tracking`), but it is the obvious building block
if a future capture flow wants "how many faces, roughly where" without
waiting on the hub's vision role at all, and may also be useful as a
face-crop step feeding the robot-side embedding model FACE-01 will
need - named here for the record, not built, since nothing in this
pass calls for it yet.

## 5. What this pass builds

Only the piece that is real regardless of the hub-side blocker and
needed by any future capture flow: a fixture-backed `get_frame()` on
`FakeReachyMiniClient` (a real small JPEG on disk, loaded once,
returned as a real uint8 array - the same "real bytes, not a mock"
habit `capture.py`'s own WAV fixture already established), and the
`Camera` seam docstring's stale "RM-06 is its real consumer" claim
corrected to name what's actually true today (nothing yet - this
design note is its first named future consumer). No turn-loop wiring,
no hub route, no consent-flow code: those all wait on the `vision`
role existing on the hub side, which is not this repo's work to do.

## 6. Open question

None that needs Jesse specifically - the design questions above were
all resolvable from existing code and docs (the consent shape from
section 5's own "no screen" fact plus the existing wake-word-is-
consent precedent; the wire shape from `document_attachments` and the
`cancel` route's own pattern). The one real dependency, the hub's
`vision` role having an actual model behind it, is a Stack/home
prerequisite, not a design ambiguity - tracked as a blocker in
`docs/BACKLOG.md`, not an open question here.
