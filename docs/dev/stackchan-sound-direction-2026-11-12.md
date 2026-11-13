# StackChan sound direction (2026-11-12)

Owner mission: can the StackChan tell which side a sound comes from, and if so, turn toward the
person who speaks. This note holds the hardware facts, what the firmware did with the two
microphone channels before, what patch 082 adds, the measurement on the unit, and the host side.

## Hardware facts (sources named)

- **Two microphones.** The CoreS3 head has an ES7210 four-channel ADC with "dual-microphone
  input" (M5Stack CoreS3 product page). The v1.0 schematic
  (`Sch_M5_CoreS3_v1.0.pdf` from the M5 docs page) names two MEMS microphones, MSM381A3729H9BPC,
  U12 on ES7210 MIC1P/N (pins 16/15) and U13 on MIC2P/N (pins 19/20), both biased from MICBIAS12.
- **MIC3 is the speaker loopback.** Nets `AEC_P`/`AEC_N` go from the AW88298 speaker outputs
  (`SPK_VOP`/`SPK_VON`, through 150 K and 1 uF) to ES7210 MIC3P/N (pins 31/32): the acoustic
  echo cancellation reference. MIC4 is unconnected. (Same schematic, read from its text layer.)
- **M5's own library reads only MIC1 and MIC2** (M5Unified `M5Unified.inl`, CoreS3 ES7210 init:
  MIC1/2 gain 0x1B, MIC3/4 powered down).
- **Physical placement and spacing: not in any document found.** The CoreS3 is 54 mm wide; the
  measurement below bounds the spacing from the largest time difference seen.

## What the firmware did with the channels before patch 082

`firmware/main/hal/board/cores3_audio_codec.cc` (M5's board driver, pinned StackChan commit
`1b57655`): the ES7210 is opened with `mic_selected = MIC1 | MIC2 | MIC3`, which puts the codec
in TDM mode (`es7210.c`, three or more mics), the I2S receiver reads four TDM slots, and
`EnableInput` opens the codec device with `channel = 2` and `channel_mask = slot 0 | slot 1`,
so the firmware reads **MIC1 and MIC2 as its two input channels** at 24 kHz
(`config.h`: `AUDIO_INPUT_REFERENCE true`, `AUDIO_INPUT_SAMPLE_RATE 24000`). `input_channels_`
is 2 because `input_reference` is true. The xiaozhi audio service resamples both channels to
16 kHz (`audio_service.cc`, `ReadAudioData`) and feeds them to esp-sr's AFE with the input
format string "MR" (`afe_wake_word.cc`, `afe_audio_processor.cc`): channel 0 as the microphone,
channel 1 as the echo reference, `aec_init = true`. The Opus encoder gets the AFE's single
output channel. The mic test in `hal/audio.cpp` also calls channel 1 "reference".

Side finding, not changed here: because slot 1 is MIC2 (a microphone), not MIC3 (the real
loopback), the AFE's echo canceller today gets the second microphone as its "reference". The AFE
is not fed the speaker signal at all. Whether that is why barge-in is hard is a separate
question for the voice session; the fix would be `channel_mask = slot 0 | slot 2` (MIC1 and
MIC3) for the AFE, or a three-channel read ("MMR") with both mics and the loopback.

## Does esp-sr offer direction of arrival?

Yes, in the pinned esp-sr 2.3.1 (`managed_components/espressif__esp-sr`): `esp_doa.h` and
`esp_afe_doa.h` exist for the esp32s3 target and the symbols `esp_doa_create/process/destroy`
and `afe_doa_create/process/destroy` are in `libesp_audio_processor.a` and
`libesp_audio_front_end.a`. It is an SRP-PHAT estimator for two microphones that takes the
sample rate, an angular resolution, the microphone spacing in metres and a frame size, and
returns a 0 to 180 degree angle. It is **not enabled** in xiaozhi or StackChan. Patch 082 does
not use it: the spacing is unknown and its memory cost on the unit is not, and a plain
cross-correlation gives the raw lag the measurement needs. It is the natural next step once the
spacing is known.

## Physical limits

At 24 kHz one sample is 41.7 us, or 14.3 mm of sound path. With the mics `d` apart the
time difference ranges over plus or minus `d / 343 s`: for 45 mm that is 131 us, 3.1 samples at
24 kHz (2.1 at 16 kHz). The angle follows `sin(angle) = lag * 343 / (rate * d)`, so one whole
sample at 24 kHz is about 18 degrees near the front and the steps grow toward the sides;
sub-sample interpolation of the correlation peak (patch 082 does a parabolic fit) gives finer
steps when the sound is broadband (speech, a clap). Front and behind read the same: a two-mic
line cannot tell them apart. Level difference alone: the two mics sit a few centimetres apart
on the same face, so the shadow of the head gives at most a few dB off to a side; it can
confirm a side at the lag limit, not measure an angle.

## Patch 082 (measuring and production firmware)

`082-sound-tap.patch` (xiaozhi `audio_service.cc`): every chunk read from the codec, before the
resampler, is handed to `maipai_sound_tap`. `082-sound-direction.patch` (StackChan): new
`hal/hal_sound_dir.cpp` sums each channel's energy and their cross-correlation over lags of
-8..8 samples in the audio input task (static buffers, about 0.4 M multiply-adds a second), and
a small worker task turns the sums into features every 100 ms: RMS of each channel, the lag of
the correlation peak (sub-sample), a confidence (normalised peak, 0..1) and the level difference
in dB. For the first half hour after boot every window above the quiet floor (RMS 40) prints
`SD <ms> <rms0> <rms1> <lag_x100> <conf_x100> <db_x10>` on the serial console. A `sound_dir`
device event with the same numbers (and `rate`) goes to the host at most every 1.5 s while a
confident (0.5) sound louder than RMS 120 is heard; a `sound_stats` diagnostic once a minute
counts windows, loud and confident ones, the lag range and dropped windows.

## Measurement on the unit (2026-11-12, builds 082 to 082d)

Serial trace read on the Mac Studio over USB (`SD` lines, 10 a second), host-timestamped; the
owner moved a phone playing music and spoke; the unit stood still. Lag is in samples at 24 kHz,
positive when channel 0 (ES7210 MIC1) heard the sound first; dB is channel 0 over channel 1.

1. **Gain.** On the stock settings channel 1 reads 37.6 dB below channel 0 (owner speaking from
   the unit's right, 19:26:50 to 19:27:30: median RMS 502 against 8), because
   `cores3_audio_codec.cc` applies the 60 dB input gain to channel 0 only. At that level the lag
   is quantisation noise (it flipped between +7 and -2 within a second). With both mics at 60 dB
   (082b) the quiet room reads RMS 85 against 80 and speech 224 against 160.
2. **Estimator.** Plain cross-correlation was fooled by hum (a steady +0.9 lag in the quiet
   room) and by voiced speech (peaks a pitch period apart: this Mac's speech read -1.8 and +2.1
   by turns). Correlating the first difference alone made the sibilants decide (+/-2 ambiguity
   from a four-sample period). The shipped estimator (082d) correlates the first difference
   summed over six samples (a band-pass, null at 4 kHz): this Mac's speech then reads one steady
   lag (-0.6 to -1.0, confidence 0.9).
3. **Music, four positions in one 44 s run** (19:47:49 to 19:48:33, no gaps, split into four
   equal parts): lag medians -0.8, -1.75, -0.1 and +0.6; channel 0 louder by 0.6, 2.5, 1.2 and
   2.2 dB; 89 to 109 confident windows of 110 in each part. The lag does change with where the
   sound is, and the third part (front) reads straight ahead.
4. **Music, left then right, timed** (left 19:54:41 to 19:54:56, right 19:55:20 to 19:55:34,
   phone about 30 cm away at head height): left lag -0.3 median (107 of 152 confident windows
   within half a sample of zero), channel 0 louder 1.0 dB; right lag -1.0 median (-0.6 to -1.6
   by the second, 143 of 150 confident), channel 0 louder 3.5 dB. **Same sign on both sides:**
   the time difference does not separate left from right as the phone was held. The level
   difference leans the right way (3.5 dB against 1.0) but is thin and distance-dependent.
5. **Speech** (three 3 s bursts, left, right, front, 19:48:34 to 19:48:45): medians -0.7,
   +0.5 and -0.2 with wide spread; too short and too quiet to call.
6. **Quiet room**: both channels RMS 80 to 110 with a steady +0.95 lag at confidence 0.9: a
   correlated background (the Studio's fan or codec noise), harmless under a real sound (music
   read RMS 2,000 to 10,000) but it is what a low-level window reports.

7. **The deciding pass, phone almost touching the head, 10 to 15 s each, very loud (RMS
   5,000 to 24,000), 9 to 11 confident windows of 10 every second:**

   | Placement | Lag median (samples) | Second-by-second range | Level, ch 0 over ch 1 |
   |---|---|---|---|
   | (a) left ear, level with the screen | -0.37 (113 confident of 129) | -0.0 to -0.8 | -0.5 dB |
   | (b) right ear, level with the screen | -0.86 (130 of 130) | +0.2 to -1.6 | +0.9 dB |
   | (c) 10 cm above the head | +0.9 | +0.7 to +1.1, every second positive | 0.0 dB |
   | (d) 10 cm below the screen | -0.45 | -0.28 to -0.58, every second negative | 0.0 dB |

   Above and below split cleanly and steadily (1.35 samples apart, 19 mm of path). Left and
   right do not: both negative, 0.5 samples apart (7 mm of path), with second-by-second
   spread of the same size. The level difference flips with the side at the ear (-0.5 against
   +0.9 dB) but at 30 cm it was +1.0 (left) against +3.5 (right), the same sign.

**Conclusion.** The two microphones are stacked, not side by side: the time difference
responds to up and down (19 mm of path across the full vertical sweep) and almost not at all
to left and right (7 mm, inside the per-second noise). A head turn needs left against right,
and neither the lag (same sign on both sides) nor the level (under 1 dB at the ear, sign not
stable with distance) gives it. **Sound direction is not usable for turning the head with
this hardware.** Up against down is measurable but of no use for a speaker turn. What would
be needed: two microphones at least 5 cm apart on a horizontal line across the face (then
one sample at 24 kHz is about 16 degrees near the front and the esp-sr DOA in the pinned
esp-sr could run on the unit), or a microphone array on the Bot host (for example a four-mic
USB array that reports its own angle, which is what `presence/doa.py` was written for).

What was kept: this note, the sensor-map row, and the measuring patches
(`082-sound-direction.patch`, `082-sound-tap.patch`), which are **not in the recipe**. To
measure again: add their two `apply_repo_patch` lines after 081 in `recipe.sh`, set
`kMatchSecondMicGain` to true in the patch, build, flash the app image only, and read the
`SD` lines on the serial console for the first half hour. The host estimator and the
speaker-turn hook built for the success case were removed with the result (they were in
commit fa1cf01 of this branch's history, never landed).

## Host side

None shipped: the measurement does not support a bearing. The speaker turn stays as it is
(turn toward the last face seen, else a glance up and a look around after the reply).
