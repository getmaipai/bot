# StackChan voice path: what to measure (2026-10-20)

Purpose: settle "stutters", "does not hear me" and "is slow" with numbers instead of guesses, and let a
review's ranked plan be checked against data. This note changes nothing; "Exists" means the host or
firmware already emits it, "Add" means a small instrument to write once the hold on new work lifts.

## Method rules

- One trial = one spoken turn at a stated distance from a stated unit, on the live hub, same room, same Wi-Fi.
- At least 20 trials per condition; report p50, p95 and the worst value, never the mean alone.
- Record the firmware and host versions, Wi-Fi signal (RSSI), the unit's power state (USB or battery) and the time.
- Change one thing between runs (distance, power save level, volume, a patch) and keep the rest fixed.
- Raw numbers go in `data-scratch/` (private); a summary table goes in the plan.

## 1. Hearing (the unit does not hear me, or hears itself)

| What | How | Exists |
|---|---|---|
| Wake word rate | Say the wake word N times at 0.5, 1, 2 and 3 m, 20 each; count `Wake word detected` lines in the serial log and `listen detect` lines in the host log | Exists (both logs) |
| Uplink loudness per turn | Peak and RMS of the decoded audio of each turn, in dBFS, plus the noise floor in the half second before speech | Peak exists (`capture.peak`); add RMS and noise floor to the per-turn summary line |
| Uplink frame arrival | Gap between consecutive 60 ms Opus frames on the host: p50, p95, max, and the count of gaps over 120 ms; frames per turn vs turn length | Add (timestamp in `on_audio`); `UplinkStats` has counts only |
| Pop-up tone and echo bleed | Peak of the first 0.5 s after listen start, and peak during and just after a reply, against the speech peak | Add (the same capture hook) |
| Speech recogniser view | `speech_s` (voiced seconds the hub heard) and the final text length per turn, against what was said | Exists in the STT result; add to the INFO line |
| Device-side AFE | Serial log: `MODEL_LOADER` lines at boot (wake model loaded), wake score if the build logs it | Exists (boot log) |

Decision: if the wake rate falls with distance while uplink RMS stays low, it is gain or microphone placement (firmware/audio front end); if frame gaps over 120 ms cluster, it is the network; if `speech_s` is low but RMS is fine, it is endpointing at the hub.

## 2. Stutter (the reply breaks up)

| What | How | Exists |
|---|---|---|
| Send lateness | For each downlink frame: scheduled send time minus actual `websocket.send` completion; p50, p95, max per reply | Add in `paced_send` and `send_audio` |
| Send time per frame | Duration of each `websocket.send`; large values mean backpressure (the unit reads slowly) | Add |
| Frames per second of reply | Frames sent over the reply's media seconds (should be 16.7 per second at 60 ms frames) | Derivable from the INFO lines |
| Device playback gaps | Serial: `speech: tts stop applied ... gaps (max N ms)` and `frames dropped before it`, plus the decode and playback queue depths | Exists in the firmware log (patch 016 line) |
| Wi-Fi quality | RSSI, retry count and the power save level (`LOW_POWER` vs `PERFORMANCE`) at idle and while speaking | RSSI/retries: add an MCP read; power save: set by firmware (patch 014) |
| Event loop health | A probe that sleeps 10 ms and records how late it wakes (should stay under 50 ms); any value over 100 ms is a blocked loop | Add (also a headless test) |
| Reply audio itself | Peak and clipping count of the synthesized PCM before Opus | Add (cheap) |

Decision: late sends with a healthy loop and low RSSI point at Wi-Fi; late sends with a lagging loop point at the host; gaps on the unit with on-time sends point at the unit (decode, power save).

## 3. Slowness

Per turn, one INFO line with these stages (the host already logs most of them separately):

1. End of speech to speech-to-text final (the last uplink frame time against the final).
2. Final to chat done (`chat ended in X s`; built-in answers should be under 0.3 s).
3. Chat done to first reply audio sent (`synthesized in`, then `sent to the device in`).
4. First audio sent to the unit starting to play (serial `tts start applied` against the host send time; needs clock offset, or use a loopback test).
5. Total from end of speech to the first audible sound.

Also: MCP round trip (`self.battery.get_status`, `self.robot.get_head_angles`) at idle, during uplink and during a reply, p50 and p95; the hub's model prompt size and decode speed for the slow chat turns (hub side). Decision: report the stage that owns the largest share of the p95 turn.

## 4. The unit's headroom

| What | How | Exists |
|---|---|---|
| Free heap and minimum free heap | `esp_get_free_heap_size`, `esp_get_minimum_free_heap_size`, internal vs PSRAM, logged every 10 s during a turn | Add (firmware) |
| CPU use per core | FreeRTOS run-time stats (idle task share) every 10 s during a turn | Add (firmware) |
| Task stack headroom | High-water marks of the audio, websocket and LVGL tasks | Add (firmware) |
| MCP handler time | Time from receiving a tools/call to sending the reply, per tool, while audio streams | Add (firmware) |

Decision: a tool reply slower than 1 s while the audio tasks are busy means the main loop is shared; a falling minimum free heap during long replies means a leak or a queue that grows.

## 5. The headless harness (already in progress)

The stand-in hub and the firmware simulator can reproduce items 2 and 3 without the unit: loop lag probe, frame
timing against a stand-in with controlled latency, no-speech and silence cases, and tool replies delayed or dropped.
It cannot show Wi-Fi, microphone gain, echo or the unit's CPU; those need the unit.
