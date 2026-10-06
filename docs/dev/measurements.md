# Bench measurements

Recorded per `dev.md` section 11's header: mode, daemon version, profile id, date.
Never a hostname, never a household recording.

## M-R2: cue to motion (sim), 2026-09-27

- mode: `sim` (Pollen's MuJoCo daemon, `--sim`, headless or GUI viewer, no unit yet)
- daemon version: `1.11.0`
- profile: `reachy_mini`
- onset threshold: 0.01 rad; settle threshold: 0.003 rad over 5 consecutive frames

| primitive | cue→onset (ms) | amplitude (rad) | peak velocity (rad/s) | cue→settled (ms) | frames |
|---|---|---|---|---|---|
| listen | 118.5 | 0.4545 | 2.4864 | 1124.9 | 53 |
| glance | 116.9 | 0.5355 | 4.7742 | 1260.3 | 60 |
| tilt | 119.2 | 0.6284 | 2.9396 | 949.6 | 56 |
| nod | 216.9 | 0.0686 | 0.6114 | 869.8 | 62 |
| perk | 83.8 | 0.7851 | 6.7413 | 738.4 | 51 |
| attend | 183.5 | 0.2516 | 0.9321 | 1113.2 | 62 |
| settle | 840.2 | 0.0181 | 0.0530 | 978.2 | 68 |
| breathe | 45.6 | 0.1571 | 2.0111 | 319.5 | 45 |
| track | 74.7 | 0.3915 | 4.5932 | 865.6 | 45 |
| speak | 10.5 | 0.1571 | 2.8369 | 286.2 | 45 |
| stop | n/a | 0.0009 | 0.0145 | n/a | 45 |

## M-R2: cue to motion, repeated (sim), 2026-10-05

- mode: `sim` (Pollen's MuJoCo daemon, `--sim`)
- daemon version: `1.11.0`
- image release: n/a
- profile: `reachy_mini`
- onset threshold and settle rule: `maipai_body/measure/motion.py`
- settle is measured from the pose a tilt leaves (from neutral it has nothing to settle)

| primitive | runs | onset p50 (ms) | onset p95 (ms) | cue→command p50 (ms) | command→onset p50 (ms) | settled p50 (ms) | amplitude p50 (rad) | peak velocity p95 (rad/s) | commanded peak (rad) | no onset | errors | over limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| listen | 20 | 119.4 | 122.3 | 0.1 | 119.3 | 1017.8 | 0.4481 | 2.7699 | 0.4712 | 0 | 0 | 0 |
| glance | 20 | 85.4 | 87.9 | 0.1 | 85.3 | 1160.0 | 0.5616 | 5.1976 | 0.7854 | 0 | 0 | 0 |
| tilt | 20 | 120.0 | 122.9 | 0.1 | 119.9 | 883.3 | 0.6284 | 3.0950 | 0.6283 | 0 | 0 | 0 |
| nod | 20 | 224.2 | 228.7 | 0.1 | 224.1 | 504.7 | 0.0652 | 0.5976 | 0.1396 | 0 | 0 | 0 |
| perk | 20 | 85.3 | 88.5 | 0.1 | 85.3 | 640.9 | 0.7851 | 7.3555 | 0.7854 | 0 | 0 | 0 |
| attend | 20 | 188.6 | 190.8 | 0.1 | 188.6 | 1123.2 | 0.2513 | 0.8240 | 0.2513 | 0 | 0 | 0 |
| settle | 20 | 188.6 | 192.1 | 0.0 | 188.6 | 1154.5 | 0.6284 | 1.6416 | 0.6284 | 0 | 0 | 0 |
| breathe | 20 | 49.9 | 51.9 | 0.1 | 49.8 | 293.4 | 0.1571 | 3.2029 | 0.1571 | 0 | 0 | 0 |
| track | 20 | 51.0 | 53.1 | 0.0 | 51.0 | 811.3 | 0.3767 | 4.3100 | 0.4000 | 0 | 0 | 0 |
| speak | 20 | 17.5 | 50.9 | 0.1 | 17.5 | 294.1 | 0.1571 | 3.0783 | 0.1571 | 0 | 0 | 0 |
| stop | 20 | n/a | n/a | 0.0 | n/a | n/a | 0.0002 | 0.0033 | 0.0000 | 20 | 0 | 0 |

## M-R2: stall probe (sim), 2026-10-05

- mode: `sim` (Pollen's MuJoCo daemon, `--sim`)
- daemon version: `1.11.0`
- image release: n/a
- profile: `reachy_mini`
- fraction: share of the axis's declared limit commanded by one `goto`

| axis | fraction | held | commanded (rad) | achieved (rad) | verdict | residual after release (rad) |
|---|---|---|---|---|---|---|
| head_pitch | 0.05 | no | 0.0349 | 0.0325 | reached | 0.0099 |
| head_pitch | 0.10 | no | 0.0698 | 0.0632 | reached | 0.0187 |
| head_pitch | 0.20 | no | 0.1396 | 0.1291 | reached | 0.0294 |
| head_pitch | 0.30 | no | 0.2094 | 0.1951 | reached | 0.0318 |
| head_roll | 0.05 | no | 0.0349 | 0.0302 | reached | 0.0094 |
| head_roll | 0.10 | no | 0.0698 | 0.0640 | reached | 0.0165 |
| head_roll | 0.20 | no | 0.1396 | 0.1290 | reached | 0.0305 |
| head_roll | 0.30 | no | 0.2094 | 0.1945 | reached | 0.0325 |
| head_yaw | 0.05 | no | 0.1571 | 0.1498 | reached | 0.0201 |
| head_yaw | 0.10 | no | 0.3142 | 0.3078 | reached | 0.0277 |
| head_yaw | 0.20 | no | 0.6283 | 0.6149 | reached | 0.0308 |
| head_yaw | 0.30 | no | 0.9425 | 0.9015 | reached | 0.0329 |

## M-R5: the link (sim), 2026-10-05

- mode: `sim` (Pollen's MuJoCo daemon, `--sim`)
- daemon version: `1.11.0`
- image release: n/a
- profile: `reachy_mini`
- cancel: from the link going down to the CANCEL cue reaching the expression engine
- still: from the cancel to the first run of still frames in the state feed
- reconnect: from the link returning to the next successful state report; reset trials use outages spread evenly across the report interval
- line: the lost turn announced once on the next turn, and not on the one after

| scenario | fault | trials | cancel p50 (ms) | cancel p95 (ms) | still p50 (ms) | still p95 (ms) | reconnect p50 (ms) | reconnect p95 (ms) | max cancels per turn | line next | line after | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| listening | reset | 8 | 2.3 | 2.8 | 47.0 | 222.3 | 6580.2 | 14000.9 | 1 | 8/8 | 0/8 | 0 |
| mid_turn | reset | 8 | 186.9 | 188.5 | 333.8 | 460.9 | 6765.7 | 14001.6 | 1 | 8/8 | 0/8 | 0 |
| mid_sentence | reset | 8 | 8.0 | 9.4 | 72.5 | 114.6 | 6586.4 | 13965.9 | 1 | 8/8 | 0/8 | 0 |
| listening | blackhole | 1 | 10002.9 | 10002.9 | 16.4 | 16.4 | 15004.0 | 15004.0 | 1 | 1/1 | 0/1 | 0 |
| mid_turn | blackhole | 1 | 120283.5 | 120283.5 | 22.7 | 22.7 | 15005.4 | 15005.4 | 1 | 1/1 | 0/1 | 0 |
| mid_sentence | blackhole | 1 | 120023.2 | 120023.2 | 32.9 | 32.9 | 15004.5 | 15004.5 | 1 | 1/1 | 0/1 | 0 |

## S-EXPR-02: motion onset stamps

- simulator rows: not run, sandbox cannot run the daemon; to be recorded locally on a Mac with `reachy-mini-daemon --sim`


## RM-07: what leaves the robot (unit), not run yet

- mode: `unit` (the physical Reachy Mini; it has not arrived)
- not run: the unit is not here, so there is no capture. Nothing below is measured.
- tooling: `body/scripts/measure_rm07_egress.py` reads a `tcpdump` capture, groups the
  connections the robot opened by destination and port, and labels each against the
  design's allowed list. The pipeline is rehearsed on loopback (`--rehearse`, a fake hub
  and a fake stray endpoint) and tested on hand-built captures; those prove the tool, not the robot.
- to record, on the isolated network, 24 hours before the MaiPai install and 24 hours after:
  run the script with `--capture`, `--phase before-install` then `--phase after-install`,
  `--mode unit` and `--record --write-page` (command in the script's docstring).
- delete this section when the first capture is recorded; the recorder writes one section per phase.

## Rung 1 keyword spotter, 2026-10-05

LINK-STATE-01 rung 1 (`maipai_body/speech/kws.py`): sherpa-onnx 1.13.8, the
`sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01` int8 model, six keywords,
threshold 0.25 and score 1.0 (sherpa-onnx's defaults), window 4 s after the wake.

**UNVERIFIED on the Compute Module.** Nothing below ran on the unit and none of it
is real microphone audio; no number here may stand in for the M-R1 and M-R3 rows.
False accepts are counted per independent 4-second post-wake window, then projected
per hour using the explicitly supplied wake-events-per-hour assumption; this is not
an estimate of the wake detector's own false-wake rate.

| row | status | how it is filled |
|---|---|---|
| CPU beside the wake model, Compute Module | UNVERIFIED | `scripts/measure_kws.py cpu`, as its own process, with M-R1's sampler (`--process kws=measure_kws.py`) |
| false accepts per hour on room audio | UNVERIFIED | `scripts/measure_kws.py false-accepts` on a long non-command recording; estimates false accepts/window x the explicit wake-events-per-hour assumption |
| recall and near misses on real speech through the array | UNVERIFIED | `scripts/measure_kws.py accuracy` on recorded clips |
| share of the microphone stream with the wake model | UNVERIFIED | `docs/dev/offline-ladder-unit-checks.md`, item 4 |

What was run, in the sandbox (x86, no daemon, no unit), mode `sim`:

| what | result |
|---|---|
| committed fixtures, synthesized speech, 2 Piper voices | 17 of 22 command clips heard, 0 heard as another command, 0 of 48 near-miss clips accepted |
| wider synthesized sweep, 2 voices at 3 speeds, 32 command and 78 near-miss utterances each | 68 of 96 command clips heard (71 percent), 9 of 234 near-miss clips accepted (3.8 percent) |
| CPU, one core of a 2.1 GHz Xeon, 120 s of audio unpaced | 0.019 CPU s per audio s (not the Compute Module, not paced, no wake model beside it) |

Findings from the sweep: the single-word commands (`timer`, `stop`, `louder`)
are heard least often; near misses that were accepted at least once are `top`
(as stop), `clouder` (louder), `are you collected` (are you connected) and
`what time was it` (what time is it). Raising the threshold or the score cut
recall faster than false accepts (at threshold 0.55 and score 1.0: 42 of 96 and
3 of 234), so the defaults stay until real recordings say otherwise. A phrase
inside a longer sentence ("stopping by the shop") still fires its keyword: the
spotter matches a keyword anywhere in its 4 s window, and only the closed list
and the window keep that to a rung 1 command.

## EYES-02: the Eyes director (Reachy Mini)

Every row needs the unit. None ran: the sandbox cannot run the daemon and there
is no unit, so each line below is "not run: sandbox cannot run the daemon".

| row | status | how it is filled |
|---|---|---|
| live cue visible in a lit room at the floor level (0.5) | not run: sandbox cannot run the daemon | on the unit, speak a turn, watch the green; raise the floor if it is not seen from 2 m |
| camera cue visible at its floor (0.5) | not run: sandbox cannot run the daemon | enable tracking with a face in view, watch the cyan |
| the wire lines behind each colour and level | not run: sandbox cannot run the daemon | `docs/dev/eyes-wire-protocol.md`, still UNVERIFIED |
| the day, night and lowest-night levels | not run: sandbox cannot run the daemon | judged in a dark room; the numbers in `indicator/looks.py` are design defaults |
| the amber alarm at its period (1 s) | not run: sandbox cannot run the daemon | tip the body past the tilt limit and watch the blink |
| the daemon's own camera use, seen by the tap through `enable_tracking` only | not run: sandbox cannot run the daemon | confirm the daemon opens no camera stream outside tracking |
