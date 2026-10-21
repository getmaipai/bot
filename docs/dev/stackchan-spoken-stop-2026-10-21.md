# StackChan: "StackChan, stop" while it is talking (design, 2026-10-21)

Owner request: a spoken stop must work while the robot is speaking. The owner approved building
the on-unit stop word (option 1 below) on 2026-10-21 and chose pruning over resizing the
partitions; it is firmware patch 049.

## What happens today

- **At idle and while listening.** Idle arms only the wake word ("Hi, StackChan",
  `wn9_histackchan_tts3`, 292 KB). While listening the host hears everything; since 0.2.20 a whole
  utterance that is a stop phrase ends the turn on the host (`stop_phrases.py`).
- **While speaking.** `Application::SetDeviceState(kDeviceStateSpeaking)` turns voice processing
  off and keeps only the AFE wake word armed (`EnableWakeWordDetection(IsAfeWakeWord())`), and a
  detection in the Speaking state calls `AbortSpeaking(kAbortReasonWakeWordDetected)`
  (`application.cc`, `HandleWakeWordDetectedEvent`). No audio is streamed to the host in that state, so
  a spoken "stop" cannot reach the host.
- **Echo cancellation is on for the wake word.** The serial logs show the AFE pipeline
  `AEC(SR_HIGH_PERF) -> VAD(WebRTC) -> WakeNet(wn9_histackchan_tts3)` with 2 input channels (1
  microphone, 1 playback). `AfeWakeWord::Initialize` sets `aec_init = codec->input_reference()`, and
  the CoreS3 codec provides the reference channel. (An earlier note said AEC was off; that was about
  `CONFIG_USE_DEVICE_AEC` and `CONFIG_USE_SERVER_AEC`, which govern the separate voice-processing path,
  not this one.)

## Measured (serial captures of 2026-10-20, `SystemInfo` lines)

| What | Value |
|---|---|
| Internal SRAM free right after boot | 53.6 to 55.5 KB (minimum 41.4 to 42.1 KB) |
| Internal SRAM free in steady use | 23.4 to 34.2 KB |
| Lowest internal SRAM ever seen in a session | 12.5 KB (three captures: 12.5, 13.4, 17.0 KB) |
| PSRAM | 8 MB found; 2 MB reserved for the image cache; the AFE is set to `AFE_MEMORY_ALLOC_MORE_PSRAM` |
| AFE task | core 1, priority 1; feed and fetch size 512 samples at 16 kHz |
| Model storage | models load from the 4 MB `assets` partition (patch 030); the wake word model is 292 KB; how full the partition is was not measured |
| Candidate command-word models (flash size) | `mn5q8_en` 2,136 KB, `mn7_en` 2,696 KB, `mn6_en` 3,696 KB |

**Not measured, and why.** The firmware logs only internal SRAM, not PSRAM free; there is no
per-task CPU figure (`FREERTOS_GENERATE_RUN_TIME_STATS` is not enabled in the logs I have); and the
wake-word hit rate while speaking has never been counted. All three need one flash of a small
diagnostic and a few minutes with Jesse, described below. The internal-SRAM minimum of 12.5 KB is
the figure to respect: anything that allocates internal RAM at start-up needs to be small.

## Options

0. **Say the wake word, then stop (no new firmware).** "Hi, StackChan" over the robot's voice
   aborts speech today if the wake word hears through the echo canceller. Then the next words go to
   the host, where "stop" ends the turn silently. Cost: nothing to build. Risk: the wake word's
   reliability at the robot's normal volume is unknown. This needs a test, not a patch.
1. **A command-word model beside the wake word (MultiNet).** Add `mn5q8_en` (2.1 MB flash) with a
   short list ("stop", "stop talking", "be quiet", "never mind"), fed from the AFE's echo-cancelled
   output in the same task, active in the Speaking state only. Gives "StackChan, stop" with no wake
   word. Costs: about 2.1 MB of the 4 MB assets partition (headroom unmeasured), PSRAM for the
   model, extra CPU on core 1 for every 32 ms frame, and a Kconfig and asset-packing change. Risk:
   the 12.5 KB internal minimum, and false stops from the robot's own speech.
2. **Keep the uplink open while speaking and let the host listen.** Stream echo-cancelled audio
   to the hub during playback and match stop phrases there. Costs: Wi-Fi traffic during speech, a
   host-side streaming recogniser, about a second of latency, and the half-duplex design the
   firmware uses today. The most work for the slowest stop.

## Recommendation

Test option 0 first, because it costs nothing to build and may already be enough. If its hit rate
is poor, build option 1 (a short MultiNet list), not option 2. Do not write the patch before 047 is
tested.

## The measurement flash (small, to add to the batch when the owner agrees)

- Log PSRAM free and minimum next to the existing SRAM line (`heap_caps_get_free_size`,
  `heap_caps_get_minimum_free_size` for `MALLOC_CAP_SPIRAM`).
- Enable run-time stats and log the AFE task's share of one core once a minute.
- Log "wake word heard while speaking" on the unit (the host already logs `listen detect`).
- Test: with the robot reading a long answer at the normal volume, say "Hi, StackChan" ten times
  from 1 m and 3 m; count how many abort the speech. Repeat with the volume at 40 and at 100.

## Decision needed from the owner

Whether to run the option 0 test now (no flash needed beyond 0.2.20), and whether the measurement
flash may ride the next firmware batch.

## As built: patch 049 (2026-10-21, compiled and apply-checked, not flashed)

- **Model and words.** `mn5q8_en` with seven commands: stop, stackchan stop, be quiet, quiet,
  that's enough, never mind, cancel (phonemes from esp-sr's `multinet_g2p.py`). It listens to the
  AFE's echo-cancelled output, only in the Speaking state. A hit at 0.85 or more aborts the reply;
  the abort message makes the host end the turn silently. The model threshold is 0.5 so near-misses
  can be logged.
- **Assets.** The measured assets image was 2,298,029 bytes. Without the launcher icons and
  artwork (about 0.68 MB that this firmware never starts the apps to show) it is 1,616,863 bytes;
  with `mn5q8_en` packed it is 3,794,083 bytes, 400,221 bytes under the 4 MB partition. The build
  script now fails if the image exceeds 4,194,304 bytes. `assets::get_image` returns an empty image
  and logs when an asset is missing, so a pruned icon cannot crash.
- **Memory guards.** The model is created when the wake word starts and dropped for good if it
  costs more than 6 KB of internal RAM (the lowest free internal RAM seen was 12.5 KB). Arming is
  refused below 16 KB free. Both outcomes are logged and sent to the host. The detection task's stack
  moved to PSRAM (12 KB), so deeper `detect()` calls cost no internal RAM. If the guard drops the
  model, the host log says so with the measured cost, and nothing else changes.
- **Logs.** `unit stop word: heard 'stop', score 91, second 40 (accepted)` for every hit and
  near-miss (command name and score only, never audio or words), and `unit stop word: stop_word
  state=ready cost=...` or `state=off` at start-up.
- **Wake word kept.** xiaozhi used to switch to its custom (multinet) wake word whenever a multinet
  model was present; the patch keeps the AFE wake word when a wakenet model exists.
- **Not verified on a unit.** The model's internal-RAM cost, its CPU cost on the audio core, and
  its false-accept rate with the robot's own voice and a TV are unknown until a flash; the
  start-up line and the hit lines give those numbers.
