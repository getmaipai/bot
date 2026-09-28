# Face and voice recognition: feasibility for the robot and the hub (2026-09-28)

Jesse asked directly, after a disambiguating question: he wants actual
recognition (which specific family member), not just presence/activity
detection, and wants it on both the robot (`bot`) and the home hub
(`home`). This reverses an explicit exclusion in
[`design-reachy-mini-2026-09-27.md`](design-reachy-mini-2026-09-27.md)
section 4: "No identity is inferred from it [tracking]" and "Face
identity is explicitly out ... the CM4 has no room beside speech."

Every claim below was checked in the code or doc named, not assumed.

## 1. The privacy and safety constraints (checked first, per the rules)

[`.github/docs/PRIVACY.md`](https://github.com/getmaipai/.github/blob/main/docs/PRIVACY.md):
"Zero phone-home, ever," "No MaiPai-operated service ever sits in a user
data path." This settles the *shape* the feature must take: recognition
has to run entirely inside the household (on the robot/pod device doing
the capture, and/or on the hub), using models the household downloads
once, never a cloud face/voice API, and never leaves any biometric data
transiting outside the house.

[`.github/docs/SAFETY.md`](https://github.com/getmaipai/.github/blob/main/docs/SAFETY.md)
is about generation/chat content gating (child-safe defaults, the
reasoning-stream rule) - it doesn't speak to biometric enrollment
directly, but its spirit (child protections are architecture, not a
setting; consent and revocability matter) applies squarely to enrolling
a *child's* face or voice. Any design here needs an explicit,
adult-granted, revocable enrollment step per person - never automatic,
never inferred from "a face showed up on camera enough times."

## 2. `home` already has the wire contract for this - not the recognition itself

`backend/src/lib/turnEngine.ts:384`:

```ts
export type SpeakerEvidence = { person: string | null; basis: "signed_in" | "voice" | "face" | "voice_and_face" | "claimed" | "unknown"; level: "confirmed" | "tentative" | "unknown" };
```

`"voice"`, `"face"`, and `"voice_and_face"` are already valid `basis`
values, and `routes/turn.ts:221` already validates an incoming
`speakerEvidence` object with exactly this enum via Zod. `turnContext.ts`'s
`effectiveBand()` and `sensitiveAllowed()` (lines 44-57) already treat a
`confirmed` `voice`/`face` basis the same as `signed_in` for age-band and
sensitive-content gating - the consuming logic is already correct and
already tested against these values.

**But nothing produces them.** A repo-wide search for an actual face or
voice embedding model, an enrollment table, or any code that ever
constructs `basis: "voice"` or `basis: "face"` (not just the type union)
turns up nothing. The `people` table (`backend/src/db/schema.ts:8-42`)
has no embedding column of any kind. This is a wire contract someone
already designed correctly for a producer that was never built - almost
certainly written with exactly a robot/pod device in mind (the surface
types already include `"pod"` and `"robot"`, `turnEngine.ts:118`), not
speculative. **Conclusion: the robot's job is to produce this evidence
on-device and report the *result*, not raw biometric data, to the hub -
the hub's job is to own the enrolled reference embeddings and consume
the result, not to run its own from-scratch recognition pipeline.**

## 3. Where the actual matching should happen

Given (2), the sane split is:

- **Enrollment is centralized at the hub**, once per person, via a
  setup/settings flow: capture a photo (the PWA's own camera,
  `getUserMedia`, already how any browser-based capture in `home` would
  work - no evidence of an existing one for this purpose) and/or a voice
  sample, run the *same* embedding model any robot/pod will use, store
  the resulting vector encrypted at rest (`lib/secrets.ts`'s existing
  pattern - a face/voice embedding is exactly the kind of "reversible
  secret" that pattern was written for, even though a raw embedding
  isn't reversible to an image the same way a password is reversible to
  itself, it is still a durable biometric identifier and should get the
  same encryption-at-rest treatment as anything else sensitive).
- **The robot (or pod) capture and match locally.** A household's
  reference embeddings are a handful of small vectors (a few hundred
  floats each) - trivially small to sync down to a paired device.
  Matching a fresh embedding against them (cosine similarity over a
  handful of vectors) costs microseconds; the expensive part is the
  embedding extraction itself, which has to happen on the device with
  the camera/mic regardless of where the match happens. Doing the match
  on-device means only the *result* (`{person, basis: "face",
  level: "confirmed"}` shape) ever needs to cross the network, not raw
  video or a fresh embedding - the smaller, more private payload, and it
  already matches the wire type wire-for-wire.

## 4. Hardware feasibility: the robot vs. the hub are very different budgets

**The robot (CM4/Wireless).** The design record's own exclusion was
written with real awareness that the CPU is already committed: the
daemon's ~50 Hz control loop, always-on audio (echo cancellation,
soon-to-be wake word per G2), and now a camera pipeline running
alongside it. A lightweight face-embedding model in the MobileFaceNet
class (roughly 1M parameters, ~4 MB quantized) is well-documented as
running in the 5-15 ms range per face on Raspberry Pi 4/CM4-class
Cortex-A72 hardware via ONNX Runtime or TFLite with int8 quantization -
that part is genuinely cheap per-inference. The real cost is *frequency*:
running this continuously at even 5-10 fps, plus a speaker-embedding
pass on every utterance, competing with wake-word detection that also
wants to run continuously, is a real contention risk on a device this
constrained - this is not a "no idea if the CM4 can do this," it's a "it
can do it as an occasional check, not as a continuous always-on stream
without a measurement to prove otherwise." **Recommendation for the
robot: face recognition runs opportunistically** - triggered by the
existing presence system noticing a face at all (RM-06's own
`get_face_target()`), at a low, capped rate (e.g., once every few
seconds while a face is present, not per frame) - and speaker-embedding
extraction runs once per confirmed utterance (already bounded by how
often people talk), never as a continuous background stream. This needs
a real measurement on the simulator or the unit before being called
done, the same as every other primitive's envelope in this repo.

**The hub.** Whatever machine runs `home` (the dev machine alone spans
an M4 Pro 24 GB to an M5 Max 128 GB per `home/docs/dev.md`'s own
measurement headers) has an order of magnitude more headroom than a Pi
CM4. Running the identical embedding models used for enrollment, or even
running recognition against a PWA-captured webcam frame during a chat
turn, is not a real feasibility question on this hardware - it is
trivial. The hub is unlikely to have its own attached camera/microphone
in most real deployments (it's a server-class machine, not a device with
sensors) - "the home hub needs this" most likely means the hub needs to
*own the shared enrollment registry and consume evidence from whatever
surface captured it* (the PWA's own camera/mic for a browser-based chat
turn, the robot or a pod device for those surfaces), not that the hub
itself needs a camera bolted on. Confirm this reading with Jesse before
building anything hub-camera-specific - if he genuinely means the
physical hub machine should have its own camera, that is a new hardware
assumption `home`'s docs don't currently make anywhere.

## 5. Enrollment, concretely

Not built anywhere today; needs its own design pass, but the shape is
constrained by what's above: an adult-only settings flow ("Recognize
`[displayName]`'s face/voice"), one enrollment per person, explicit
per-person consent captured and revocable (a delete removes the stored
embedding and pushes the removal to every paired device, mirroring the
credential-revocation posture `ROBOT-DEVICE-01`'s own rotation work
already established for a different kind of secret). For a child's
profile specifically, this needs the enrolling adult's own consent, not
the child's - the same posture as everything else `SAFETY.md` treats as
architecture rather than a setting.

## 6. Recommendation

**Buildable within the existing privacy architecture and wire contract**
- this is not blocked on anything structural, and part of the hard work
(the wire shape, the age-band/sensitivity consumption logic) is already
done and already tested. **But it is not a quick add**, and it does
reverse a documented design decision:

1. **The design record needs a formal amendment to section 4** before
   this is built against the robot, per the org's own "every feature is
   reviewed... a one-line verdict recorded before it is built" rule -
   this doc is evidence for that amendment, not a substitute for
   writing it. The amendment should state plainly that identity
   inference is now in scope, why (the owner's own call, dated), and
   under what constraint (on-device only, opportunistic capture rate,
   explicit consent).
2. **Two real backlog items, not one**, since the two bodies have
   different jobs and different constraints: a hub-side item
   (enrollment UI, encrypted embedding storage, sync to paired
   devices) and a robot-side item (camera capture at a capped rate,
   the embedding model, local matching, reporting `SpeakerEvidence`
   over the existing wire shape) - they share a model format and a
   consent posture but are separately scoped work.
3. **Open question only Jesse can answer**: does "the home hub needs
   this" mean the hub consumes evidence from connected surfaces
   (robot, pod, the PWA's own browser camera) - the reading this doc
   assumes - or does he want the physical hub machine itself to have
   its own camera/mic as a first-class sensor. That changes whether
   there's a third, hub-hardware-specific piece of work here at all.
4. **A CPU budget question for the robot specifically**: opportunistic,
   capped-rate face checks plus per-utterance speaker embedding is the
   recommended shape to avoid starving wake-word/audio, but this is a
   recommendation pending a real measurement, not a proven number - flag
   this to whoever picks up the robot-side item so it gets an M-R-style
   measurement row before being called done, the same standard every
   other primitive here already holds itself to.
