# Face and voice identity: the models, and where each one runs (2026-09-28)

This resolves the one question FACE-01 left open after the feasibility
study ([`face-voice-recognition-design-2026-09-28.md`](face-voice-recognition-design-2026-09-28.md))
and the design record's amendment
([`design-reachy-mini-2026-09-27.md`](design-reachy-mini-2026-09-27.md)
section 4): which embedding model each modality uses across the whole
household, and where each one runs. `dev.md` section 6 ("Speaker
evidence on a shared device") stays the canonical spec for the wire
shape, the fusion rules and the privacy line; nothing here re-derives
it. This document is the decision, dated, with the checks that back it.
Every claim was checked in the code, the doc, or the artifact named;
the two published latency numbers are cited to their page, and the
model dimensions were read off the ONNX graphs themselves with this
body's own pinned runtime (`onnxruntime` 1.30.0), not taken from a
README.

## 1. The decision in four lines

1. **Face: OpenCV Zoo's SFace** (`face_recognition_sface_2021dec.onnx`,
   Apache-2.0, a MobileFaceNet backbone, 112x112 in, 128-d out). One
   file, one sha256, on every surface that matches a face: this body,
   the hub's PWA in the browser, Go on the device. The hub stores and
   syncs face prints; it never runs the face model itself in v1.
2. **Voice: 3D-Speaker CAM++** (`3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx`,
   Apache-2.0, 512-d), the legacy pin, byte-identical. It runs where the
   audio already is: **inside the hub's existing `sherpa-onnx` STT
   session** for this body and for the PWA, and inside the MaiPai
   build's own local speech process. This body never runs it.
3. **Consistency by construction, not by convention:** every reference
   print carries the model id and sha256 that made it, a matcher
   refuses a print from any other model with a Repair, and a model
   change is a re-enrollment, never a silent re-score.
4. **No legacy code is lifted into this repo now.** The hard-won pieces
   (the guided enrollment sessions, the centroid-plus-margin galleries)
   belong beside their consumers, which are `home` items; this repo's
   FACE-01 code is the capture, the alignment, the embed, the local
   match and the report, and needs none of them.

## 2. What changed since FACE-01's entry was written

Three facts the entry did not have, each checked today:

- **The legacy face model was already MobileFaceNet-class.** The
  mirror's packs manifest (`robot/robot/packs/manifest.py`, the
  `vision` pack) pins `hef/arcface.hef` to Hailo Model Zoo v5.1.0's
  `arcface_mobilefacenet.hef` (2.66 MB, "512-d" in its own note). The
  zoo's HAILO10H face-recognition table gives it 2.04M parameters and
  0.88 GOPs at 112x112, source `deepinsight/insightface`. FACE-01's
  worry that "ArcFace's usual backbones are ResNet-scale" does not
  apply to the artifact the other build actually pinned. That model is
  still unusable here for two reasons that stand: a `.hef` is a
  Hailo-compiled binary and runs on no CPU at all, and its weights are
  InsightFace's, which the InsightFace README licenses for
  "non-commercial research purposes only" (both its auto-downloaded
  and manually downloaded models). The second reason is a finding for
  the MaiPai build too, recorded in section 8.
- **This body already streams audio to the hub after the wake word.**
  G3+G6 (`robot-streaming-turn-2026-09-28.md`, landed) opens the hub's
  own `wss://.../api/stt/stream` from the wake instant and sends the
  capture blocks; the hub's `sttSession.ts` holds the utterance's
  samples (`speech: Float32Array[]`) until the endpoint. Any voice
  embedding computed on the hub from that stream costs the robot
  nothing and moves no new data.
- **The hub's STT runtime already contains the speaker embedder.**
  `home/backend/src/lib/stt.ts` loads `sherpa-onnx-node` (1.13.8 in
  `node_modules`), and that package exports `SpeakerEmbeddingExtractor`
  and `SpeakerEmbeddingManager` (`sherpa-onnx.js` lines 35 to 36;
  `speaker-identification.js`). The Stack's `speech/sherpa.ts` is the
  same binding behind the `stt` role. CAM++ on the hub is a model file
  and a config object, not a new dependency.

## 3. Face: SFace, checked

**The artifact.** `opencv/opencv_zoo`, `models/face_recognition_sface/`,
"All files in this directory are licensed under Apache 2.0 License";
"Model files encode MobileFaceNet instances trained on the SFace loss
function" (Zhong et al., arXiv 2205.12010). Downloaded and inspected
today:

| File | Bytes | sha256 | Graph |
|---|---|---|---|
| `face_recognition_sface_2021dec.onnx` | 38,696,353 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | in `data` `[1,3,112,112]` float, out `fc1` `[1,128]` |
| `face_recognition_sface_2021dec_int8.onnx` | 9,896,933 | (LFS `2b0e941e...`) | same shapes |

The fp32 file is the canonical artifact everywhere, pinned by that
sha256 and a commit-pinned LFS URL in the model pack. The int8 sibling
is a measured option only: a quantized graph does not produce the
same vector as the fp32 one, so a device may switch to it only after a
recorded cross-variant cosine drift on the enrollment fixtures shows
the drift sits well inside the margin rule. Mixing variants without
that measurement is the silent-mismatch failure this decision exists
to prevent.

**CPU feasibility on a CM4.** The Wireless runs on a Raspberry Pi CM4
(the SDK's own README in `reachy_mini-1.11.0.dist-info/METADATA`:
"Raspberry Pi CM4 + Battery + WiFi"), the same BCM2711 quad Cortex-A72
as a Raspberry Pi 4B. OpenCV Zoo's benchmark page publishes, for
`face_recognition_sface_2021dec.onnx` on "Raspberry Pi 4B (CPU)":
68.82 ms mean, 69.06 median, 68.45 min (OpenCV DNN backend, CPU
target), and for YuNet 6.23 ms mean at 160x120 on the same board. On
this laptop, single-threaded under `onnxruntime` 1.30.0, the fp32
graph ran in 5.95 ms per inference (int8 6.34 ms), which is a sanity
check that the file loads and runs under the runtime this body already
pins, not a robot number. At the design's capped rate (one check every
few seconds while a face is tracked, never per frame) a 70 ms embed
plus a detector pass is a fraction of one percent of one core. The
M-R-style measurement FACE-01 already requires still happens, on the
unit, with the daemon's loop, wake word and the audio stream running;
the point here is that the number it will produce is not in doubt.

**Why not the alternatives.**

- InsightFace's packs (`buffalo_sc`'s `w600k_mbf.onnx` and the rest):
  the closest thing to the legacy model, and non-commercial research
  only by InsightFace's own README. Out.
- EdgeFace (Idiap, 1.24M to 3.65M parameters, the IJCB 2023 compact
  winner): the repository states model sizes and FLOPs but no weights
  license or ONNX export on its page, and Idiap's face models are
  released for research. Not clear enough to pin. Out until its
  license says otherwise.
- FaceNet (Inception-ResNet-v1, MIT weights via facenet-pytorch): about
  23M parameters, an order of magnitude heavier than SFace for no gain
  a family would notice. Out.
- A per-device choice (a lighter model here, the Hailo model there):
  embedding spaces are model-specific, so every device that matches
  would need every model's prints, and the hub could not enroll once.
  This is the "second copy" the org's first principle forbids. Out.

**Detection and alignment on this body.** The vendored
`reachy_mini.vision.face_detector.FaceDetector` (YuNet on ONNX
Runtime, confined to one thread) is the face finder; nothing new is
added for detection. SFace expects a 112x112 crop aligned by five
landmarks (the standard two-eyes, nose, two-mouth-corners template
OpenCV's `FaceRecognizerSF::alignCrop` uses; verify the template
values in the installed OpenCV source when implementing, do not
retype them from memory). YuNet emits all five (`kps_*` outputs carry
ten values per anchor, read off the graph), but the vendored `Face`
dataclass keeps only the eyes and the nose. FACE-01 therefore
subclasses `FaceDetector` and overrides `_decode` to keep the two
mouth corners (composition over the shipped class, never an edit to
the vendored file), and the alignment is a similarity transform from
those five points to the template in `numpy` (a least-squares fit, a
few lines; OpenCV is not added as a dependency for one affine warp).
The legacy driver's "plain resized crop, no alignment" shortcut is not
carried: its own docstring records that it "degrades match scores".

**Threshold.** OpenCV's SFace sample ships a cosine threshold near
0.36 (and the legacy `FaceGallery` default was 0.36, almost certainly
from the same source). Per section 6 and M-07's rule, the threshold
and the margin are set by the measurement on the enrollment fixtures,
never the sample's default; the default is only the starting value.

## 4. Voice: CAM++, on the hub, checked

**The artifact.** `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx`
from the `k2-fsa/sherpa-onnx` `speaker-recongition-models` release
(the upstream tag really is misspelled), 29,596,978 bytes, sha256
`357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b`,
downloaded today and equal to the legacy pin byte for byte.
**License, checked precisely (a review, 2026-09-28, caught that the
first draft's citation here was weaker than section 3's for SFace and
InsightFace):** `sherpa-onnx`'s own release page hedges ("each model
has its own license... see the corresponding repository"), and
3D-Speaker's GitHub README states Apache-2.0 for the code, not
explicitly for the weights - the same gap that ruled out ArcFace, so
it had to be closed, not assumed closed. The source model registry's
own structured metadata settles it: ModelScope's API for this exact
model (`https://modelscope.cn/api/v1/models/iic/speech_campplus_sv_en_voxceleb_16k`,
fetched today) returns `"Name":"speech_campplus_sv_en_voxceleb_16k"`
(an exact match) and `"License":"Apache License 2.0"` in its own
license field, not inferred from a README's prose. Apache-2.0,
confirmed at the weights, not just the code. Graph: in `x`
`[N, T, 80]` float (Kaldi-style fbank frames, which sherpa-onnx
computes; the legacy driver's docstring names exactly why the feature
chain is never hand-rolled), out `embedding` `[N, 512]`. Note the
dimension: 512, read off the file, not the 192 CAM++'s smaller
variants use. Single-threaded on this laptop, a three-second utterance
embeds in 15.5 ms; on the hub this is noise.

**Where it runs, and why not on this body.** This body has no local
speech process (G3+G6 replaced the gap audit's local pipeline with the
hub's streaming STT), so hosting CAM++ here means adding the whole
`sherpa-onnx` runtime, a second copy of ONNX Runtime beside the one
`reachy-mini` already pins, for one model. Meanwhile the hub already
has the audio (from the wake instant, by the owner's own ask), already
holds the utterance's samples at the endpoint, and already links the
extractor. So the voice print is computed in the hub's STT session,
once per finished utterance, matched there against the hub's own
prints, and the resulting `voice` evidence joins the turn on the hub.
The fresh embedding is ephemeral and never stored; the audio buffer
already had a lifetime of one utterance. The same session serves the
PWA's microphone, so browser chat gets voice identity with zero
browser-side model. The MaiPai build keeps its own local speech
process and runs the identical file locally (its audio never leaves
the robot), matching the same synced prints: one model, one space,
two hosts.

`dev.md` section 6's line "never a score, an embedding, a track's
geometry or a face crop" leaves the robot still holds on this body:
what crosses the link is the post-wake audio the streaming design
already sends and the face match result, nothing else. Standalone,
this body runs no turn at all (section 4's table), so no voice
identity is lost by not having the model on board. The legacy
`MIN_SPEECH_S = 2.0` floor (no claim on under two seconds of speech,
with its cited reason) carries into the hub's session as the rule it
is.

**Prebuilt matching, and the one thing it lacks.** `sherpa-onnx-node`'s
`SpeakerEmbeddingManager` gives `add`, `addMulti`, `remove`, `search`
and `verify`, and `search` returns only the best name over a
threshold. Section 6's close-tie rule needs the runner-up's score to
call two family members `unknown` with candidates instead of picking
the parent over the child. The manager cannot express that, so the
matching is the legacy `SpeakerGallery`'s shape (per-person centroid,
threshold, margin, three-way verdict), ported to the hub in TypeScript
with its tests, over the extractor the package already provides. This
is the one place a maintained component does not do the job the spec
names, and the gap is recorded here before the code, as the UI rule
requires of any hand-built piece.

## 5. How the household stays consistent

**One print record, in the spec first.** A reference print is a shared
record (`commons/spec`, before any hub or body code, per the org's
spec-first rule): the person, the modality (`face` or `voice`), the
model id and the artifact sha256 that produced it, the dimension, the
accepted sample vectors from the enrollment (the guided sessions
produce several per person on purpose; the centroid is derived, never
the only thing stored), who approved it as a role, the consent
timestamp, provenance and an HLC. The hub stores it encrypted at rest
under `lib/secrets.ts`'s existing pattern, syncs it to paired devices
as a sealed record over the link, and revokes it with a tombstone the
same way the legacy JSONL galleries did, so a replay cannot resurrect
a deleted face or voice. Revocation reaches every device within one
sync (FACE-01's own acceptance line).

**Every matcher checks the model id before it compares.** A device
loads only prints whose model id and sha256 equal the one it runs; a
print from any other model raises a Repair ("re-enroll Sage's face for
the new model") and is skipped. Cross-model comparison is impossible
by construction, which is the whole answer to FACE-01's "matches
silently fail" concern. A future model swap is a deliberate,
documented re-enrollment, and the record's model id is what makes the
stale prints visible.

**Who computes the reference print.** The surface that captures the
enrollment, with the same model file: the PWA in the browser for a
face (the enrollment UI lives there; `onnxruntime-web` runs the 38.7 MB
fp32 file, or the int8 sibling once the drift measurement above allows
it), the hub's STT session for a voice (from the PWA's microphone or
from a robot streaming a guided take). The hub receives the reference
vectors once, at enrollment, which is the one crossing the amendment
already allows. Enrollment ownership is the hub's; the capture surface
can be any device that runs the model. The robot's guided in-person
face enrollment (the legacy coverage-grid ceremony driven by voice)
is a later item on top of the same record; it is not needed to ship
matching.

**Which prints go where.** Face prints sync to every surface that
matches faces (this body, the PWA for the signed-in session, Go).
Voice prints stay on the hosts that run the voice model (the hub, the
MaiPai build's body); a Reachy Mini or a browser never receives one.

**Fusion has one implementation.** Per-modality scoring (threshold,
margin, the three-way verdict with candidates) runs on whichever
device holds the fresh embedding, in that device's language: this body
in Python for a face, the hub in TypeScript for a voice, the browser in
TypeScript for a face. The cross-modality fusion into one
`speaker_evidence` (section 6's confirmed, tentative, close-tie and
far-miss rules) runs in the household runtime's turn engine, once, in
TypeScript: on the hub for this body and the PWA, and on the MaiPai
robot's own copy of that runtime when standalone, since that runtime
is the hub's code on Bun. The hub's turn route already validates an
incoming `speakerEvidence` (`routes/turn.ts:221`); what changes is
that it becomes the caller's per-modality evidence, which the engine
fuses with its own voice result before the band and sensitivity
checks run. Both per-modality implementations are proven by one
fixture set in the spec (known prints, a close pair, a far miss), so
the rule cannot drift between them.

## 6. What this body builds (FACE-01, narrowed)

Capture trigger from the presence system (`read_presence()` and the
tracker's `detected`), a YuNet subclass keeping five landmarks, the
similarity-transform crop, an SFace session (one thread, like the
vendored detector) at a capped rate, the local gallery of synced face
prints with the model-id guard, the per-modality verdict, and the
result on the turn request. Dependencies added: none (`onnxruntime`
and `numpy` are already base dependencies through `reachy-mini`; the
model file arrives through the same pinned-URL-and-checksum pack
pattern the wake word uses). Tests: the deterministic suite against
the fixture-backed fake with recorded crops and known prints, plus the
spec's fusion fixtures. Measurement: the capped-rate check's CPU on
the unit beside the daemon, the wake scorer and the audio stream,
recorded in `measurements.md`.

Not this body's: the print record (spec), the enrollment UI and the
encrypted store and sync (hub), the voice print in the STT session and
the fusion in the turn engine (hub), the browser matcher (hub PWA).
Each is named here so `home` and `commons` can file them; none is
filed from this repo.

## 7. The legacy code: lifted or not

Not now, and not into this repo. The reasons, per piece:

- `perception/enroll.py`'s `EnrollmentSession`, `QualityConfig`, the
  pose buckets and the retake logic: hard-won and pure, but its
  consumer is the enrollment flow, a hub PWA item in TypeScript. It
  is ported there, beside that UI, with its test file carried, when
  that item is built; a Python copy here would sit unused.
- `perception/enroll.py`'s `FaceGallery.identify` (best score per
  person, margin against the runner-up) and `voice/speakers.py`'s
  `SpeakerGallery.match` (centroids, threshold, margin, the
  below-threshold versus ambiguous distinction): these are section 6's
  per-modality verdict in code, already reviewed against real family
  voices. They are the reference for the spec fixtures and for both
  ports (Python on this body for faces, TypeScript on the hub for
  voices). Their thresholds are starting values only.
- `hal/drivers/speaker_id.py`'s `SpeakerIdentifier` (never raises,
  `MIN_SPEECH_S`, the session sketch): the never-raise contract and
  the two-second floor carry into the hub's session; the RAM-only
  session sketch is superseded by section 6's `claimed` basis and is
  not carried.
- `voice/enroll.py`'s `VoiceEnrollment` ceremony (consent in dad-test
  words, three varied takes, the attempt budget): the shape of the
  guided voice enrollment on any surface, ported to the hub with the
  enrollment item.
- `hal/drivers/hailo_vision.py`: nothing. Its embed path is Hailo-only
  and skips alignment; its box math and stride logic serve a YOLO
  pipeline this body does not run.

## 8. Findings for the other build and the standing docs

- `dev.md`'s stack table (`vision` row) lifts "ArcFace" from legacy
  for the MaiPai build. That artifact's weights are InsightFace's,
  non-commercial by InsightFace's README, and its embedding space
  differs from SFace's, so it cannot share the household's prints.
  The MaiPai build moves to the same SFace file on its Pi 5 CPU
  (faster than the CM4 measured above), or to SFace compiled to a HEF
  later, gated on a recorded fp32-versus-HEF drift measurement. The
  row carries a pointer here; the row's SCRFD, YOLO and pose entries
  are untouched by this decision.
- `dev.md`'s `speaker id` row stands (CAM++ in the body's speech
  process is right for that build); the dimension is 512.
- Section 6's "never replicated" for templates predates the owner's
  amendment (enrollment at the hub, prints synced to paired devices);
  a dated note there points at the amendment so the two do not
  disagree silently.
- The amendment's "raw image, video and audio never leave the
  capturing device" is true for image and video on this body and, for
  audio, true only before the wake word: after it, G3+G6 streams to
  the hub's STT by design. A dated sentence there says so, and says
  the voice print rides that stream and nothing more.
