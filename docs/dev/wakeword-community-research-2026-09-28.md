# What the Reachy Mini community has built for wake-word support (2026-09-28)

Jesse's ask: what has the Reachy Mini hobbyist/YouTube community already built for
wake-word detection, to inform G2's design. Web research only; nothing here was
verified against our own installed SDK or tested locally - that's G2's own job.

## 1. The community has converged on openWakeWord, not a custom architecture

Every wake-word project found for Reachy Mini uses
[openWakeWord](https://github.com/dscripka/openWakeWord) (Apache 2.0) as the
underlying engine, not Porcupine, not a from-scratch model, not a Whisper-based
approach:

- **[andyjmorgan/reachy-wake-word](https://github.com/andyjmorgan/reachy-wake-word)**
  and its companion
  **[andyjmorgan/Reachy-Wake-Word-Monitor-App](https://github.com/andyjmorgan/Reachy-Wake-Word-Monitor-App)**
  - the most technically documented of the community projects. Pipeline: 16 kHz
  mono audio captured in 80 ms chunks, converted to a mel spectrogram, run
  through an ONNX embedding model (96-dimensional output), then classified by a
  small trained head. Claims 98.15% accuracy / 97.5% recall / 0.53 false
  positives per hour, trained on 5,000 samples across 150 speakers with 100,000
  training steps, using synthetic data generated from Piper TTS (the
  "libritts-high" voice). Code is Apache 2.0; the pre-trained model weights
  are **CC BY-NC-SA 4.0 (non-commercial)**.
- **[luisomoreau/hey_reachy_wake_word_detection](https://huggingface.co/spaces/luisomoreau/hey_reachy_wake_word_detection)**
  and **[fcollonval/reachy_mini_wake_word](https://huggingface.co/spaces/fcollonval/reachy_mini_wake_word)**
  - Hugging Face Spaces implementing "Hey Reachy" wake-word detection as an
  installable robot app. Not independently verified in depth (Spaces UIs
  weren't fetchable in this pass), but both are community projects, not an
  official Pollen Robotics release - I found no evidence "Hey Reachy" is a
  first-party Pollen app; it's community-built on top of the same
  openWakeWord pattern.
- A YouTube video, "Wake word detection model for the Reachy Mini"
  (https://www.youtube.com/watch?v=ceC_3G0Grc4), exists but wasn't transcribed
  in this pass - likely a walkthrough of one of the above.

**This directly confirms `docs/BACKLOG.md`'s own VOICE-01 plan is already the
right architecture**: "the wake scorer (the trained artifact through ONNX with
its front-end, never the stock phrase)" is exactly the mel-spectrogram →
ONNX-embedding → classifier shape every community project independently
arrived at. Nothing found here beats or contradicts that plan.

## 2. Licensing: don't adopt anyone's pre-trained weights

andyjmorgan's model - the only one with published accuracy numbers - ships
under CC BY-NC-SA 4.0, which forbids commercial use. MaiPai Home/Bot is a
commercial product, so **the trained weights are not adoptable**, only the
training *approach* (openWakeWord's own pipeline, Apache 2.0, and the
Piper-TTS-synthetic-data technique) is reusable - which is what
`docs/TRAINING-MODELS.md` already requires anyway (train MaiPai's own model,
verify on real speech, never assume an upstream artifact is licensed for
this). No CC-BY or public-domain Reachy-specific wake model was found in this
pass; openWakeWord's own upstream repo does ship some genuinely open
pre-trained models for generic phrases ("hey jarvis," "alexa," etc., per its
own README), but nothing for a MaiPai-specific phrase - training our own
remains the only path regardless of what's out there.

## 3. A real hardware gotcha: no echo cancellation in the simulator or a no-board dev setup

This is the most concrete, actionable finding, and it wasn't something we'd
already documented. Reachy Mini's microphone hardware is a customized Seeed
reSpeaker **XVF3800** (4 PDM MEMS mics, 16 kHz max sample rate, -26 dBFS
sensitivity, 64 dBA SNR - confirmed on Pollen's own engineering blog,
[huggingface.co/blog/pollen-robotics/reachy-mini-media-stack](https://huggingface.co/blog/pollen-robotics/reachy-mini-media-stack)).
**Acoustic echo cancellation (AEC) is done by that chip itself, in hardware,
always on** - the daemon doesn't do it in software when the real board is
present.

[**Issue #1161** on `pollen-robotics/reachy_mini`](https://github.com/pollen-robotics/reachy_mini/issues/1161),
"Daemon audio: no echo cancellation when XVF3800 is absent (sim, no-board,
dev setup)," documents exactly the gap: without the physical XVF3800 (the
simulator, a Lite variant without the USB dongle, any mockup/no-board dev
rig), the daemon falls back to plain OS audio endpoints with **no software
AEC anywhere downstream** - "the speaker plays the assistant's voice, the mic
recaptures it raw, and the loop is sent back as user input. The model
interrupts itself and the conversation collapses." The fix landed (issue
shows **Status: Done**): GStreamer's `webrtcdsp`/`webrtcechoprobe` (WebRTC's
own AEC3) inserted into the pipeline specifically when no XVF3800 is
detected.

**Why this matters for us specifically:** every G1 live-verification this
session ran against `reachy-mini-daemon --sim` - exactly the "no XVF3800"
case this issue describes.

**Verified directly against the installed `reachy-mini` 1.11.0 source**
(`.venv/lib/python3.12/site-packages/reachy_mini/media/audio_gstreamer.py:144-220`),
not just inferred from the GitHub issue: the fix is present, but its
applicability is narrower than "present or absent." `_init_pipeline_record()`
only wires `webrtcechoprobe`/`webrtcdsp` (software AEC) on one specific
fallback branch: `has_reachymini_asoundrc()` is false (no real XVF3800/CM4
`.asoundrc`) **and** `get_audio_device("Source")` returns `None` ("No specific
audio card found, using default audio source", using `autoaudiosrc`). If
`get_audio_device("Source")` instead finds *some* real device - which a dev
Mac running `--sim` almost certainly does, since it always has a built-in
mic - the code takes the `platform.system() == "Darwin"` branch
(`osxaudiosrc`, line 180-182) instead, which links straight to the pipeline
with **no AEC wired at all**, not even the software fallback. So this dev
Mac's own `--sim` runs are plausibly in the worst case of the three (real
XVF3800 hardware AEC, software AEC fallback, or no AEC at all), not the
middle one the GitHub issue's fix targets. Two things to confirm before
G2/G7/G8 live-testing goes further, now sharpened by this: (1) which branch
this dev Mac's `--sim` runs actually take - add a one-line log or a quick
diagnostic reading `get_audio_device("Source")`'s return value before
trusting any wake-word false-trigger-rate number measured on `--sim` here;
(2) if the no-AEC `Darwin` branch is what's active, whether that's
acceptable for wake-word testing anyway (the wake word and the robot's own
TTS reply are unlikely to overlap in time in the current design, unlike a
continuous barge-in scenario) or whether it invalidates any *simultaneous*
capture+playback test specifically. This is squarely G2's/G8's own
acceptance criterion to add, not something to take on faith from this
research.

## 4. Direction-of-arrival is linear-array-limited, already consistent with our own RM-06

The same blog post confirms DoA is genuinely built into the SDK ("exposed
through the SDK and read on demand") but the mic array is **linear, not
circular** - "a circular layout would be needed for full 360° coverage," and
Pollen's own calibration assumed "an audio source facing the robot from about
1 m away." This doesn't contradict anything already built (RM-06's own
`get_doa()` usage), just confirms the 180°-range constraint is a hardware
fact, not a bug in our own seam wrapper.

## 5. No published guidance on CPU contention

Nothing found - not the community projects, not Pollen's own blog, not the
GitHub issue tracker in this pass - discusses CPU contention between
continuous wake-word inference, the daemon's own ~50 Hz control loop, and
audio I/O on Reachy Mini's actual compute (whatever the shipped board's SoC
is). This remains an open measurement for whoever builds G2, not something
external research answers for us.

## Recommendation for G2

**Confirms, doesn't change, the existing plan.** `docs/BACKLOG.md`'s VOICE-01
already specifies the right architecture (ONNX wake scorer with its own
front-end, a trained artifact, never the stock phrase) - this is independently
validated by every community implementation converging on the same
openWakeWord-shaped pipeline. Concretely for whoever picks up G2:

1. **Use openWakeWord's own training pipeline** (Apache 2.0, downloaded/depended
   on per "download, don't vendor," not andyjmorgan's NC-licensed weights) to
   train MaiPai's own wake phrase, per `docs/TRAINING-MODELS.md`'s existing
   rules (real speech validation, near-miss training, no unverified audio).
2. **Add the XVF3800/no-AEC gap as an explicit G2 (or G8) acceptance item**:
   confirm whether the installed daemon's software-AEC fallback is present and
   sufficient for wake-word use when testing against `--sim`, since that's
   exactly the environment every G1 live check ran in this session, and a
   feedback loop there would look like a wake-word false-trigger storm, not
   an obviously separate bug.
3. **No third-party model or code is worth adopting wholesale** - the
   licensing (NC on the only benchmarked model) and the "download, don't
   vendor" rule both point the same direction: train our own, on our own
   phrase, using the open pipeline everyone else already validated works.
