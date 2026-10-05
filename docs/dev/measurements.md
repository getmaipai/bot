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

| primitive | runs | onset p50 (ms) | onset p95 (ms) | cue→command p50 (ms) | command→onset p50 (ms) | settled p50 (ms) | amplitude p50 (rad) | peak velocity p95 (rad/s) | commanded peak (rad) | no onset | errors | over limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| listen | 20 | 120.2 | 122.7 | 0.1 | 120.1 | 990.9 | 0.4488 | 2.8019 | 0.4712 | 0 | 0 | 0 |
| glance | 20 | 85.0 | 86.9 | 0.1 | 84.9 | 1158.1 | 0.5616 | 5.2921 | 0.7854 | 0 | 0 | 0 |
| tilt | 20 | 119.3 | 122.1 | 0.1 | 119.2 | 882.3 | 0.6284 | 2.9765 | 0.6283 | 0 | 0 | 0 |
| nod | 20 | 224.6 | 227.2 | 0.1 | 224.6 | 501.5 | 0.0657 | 0.5975 | 0.1396 | 0 | 0 | 0 |
| perk | 20 | 85.3 | 87.5 | 0.1 | 85.2 | 609.9 | 0.7852 | 6.4245 | 0.7854 | 0 | 0 | 0 |
| attend | 20 | 188.9 | 191.8 | 0.1 | 188.8 | 1126.5 | 0.2513 | 0.8370 | 0.2513 | 0 | 0 | 0 |
| settle | 20 | 1018.1 | 1018.1 | 0.0 | 1018.0 | 1157.2 | 0.0002 | 0.0015 | 0.0000 | 19 | 0 | 0 |
| breathe | 20 | 17.9 | 53.3 | 0.1 | 17.8 | 295.3 | 0.1571 | 3.2130 | 0.1571 | 0 | 0 | 0 |
| track | 20 | 51.0 | 53.8 | 0.0 | 51.0 | 813.0 | 0.3772 | 4.3408 | 0.4000 | 0 | 0 | 0 |
| speak | 20 | 17.9 | 52.8 | 0.1 | 17.9 | 295.8 | 0.1571 | 3.0636 | 0.1571 | 0 | 0 | 0 |
| stop | 20 | n/a | n/a | 0.0 | n/a | n/a | 0.0002 | 0.0029 | 0.0000 | 20 | 0 | 0 |

## M-R2: stall probe (sim), 2026-10-05

- mode: `sim` (Pollen's MuJoCo daemon, `--sim`)
- daemon version: `1.11.0`
- image release: n/a
- profile: `reachy_mini`
- fraction: share of the axis's declared limit commanded by one `goto`

| axis | fraction | held | commanded (rad) | achieved (rad) | verdict | residual after release (rad) |
|---|---|---|---|---|---|---|
| head_pitch | 0.05 | no | 0.0349 | 0.0325 | reached | 0.0103 |
| head_pitch | 0.10 | no | 0.0698 | 0.0633 | reached | 0.0183 |
| head_pitch | 0.20 | no | 0.1396 | 0.1293 | reached | 0.0299 |
| head_pitch | 0.30 | no | 0.2094 | 0.1953 | reached | 0.0305 |
| head_roll | 0.05 | no | 0.0349 | 0.0306 | reached | 0.0089 |
| head_roll | 0.10 | no | 0.0698 | 0.0641 | reached | 0.0160 |
| head_roll | 0.20 | no | 0.1396 | 0.1295 | reached | 0.0290 |
| head_roll | 0.30 | no | 0.2094 | 0.1955 | reached | 0.0306 |
| head_yaw | 0.05 | no | 0.1571 | 0.1502 | reached | 0.0211 |
| head_yaw | 0.10 | no | 0.3142 | 0.3078 | reached | 0.0295 |
| head_yaw | 0.20 | no | 0.6283 | 0.6156 | reached | 0.0302 |
| head_yaw | 0.30 | no | 0.9425 | 0.9030 | reached | 0.0326 |

## M-R5: the link (sim), 2026-10-05

- mode: `sim` (Pollen's MuJoCo daemon, `--sim`)
- daemon version: `1.11.0`
- image release: n/a
- profile: `reachy_mini`
- cancel: from the link going down to the CANCEL cue reaching the expression engine
- still: from the cancel to the first run of still frames in the state feed
- reconnect: from the link returning to the next successful state report
- line: the lost turn announced once on the next turn, and not on the one after

| scenario | fault | trials | cancel p50 (ms) | cancel p95 (ms) | still p50 (ms) | still p95 (ms) | reconnect p50 (ms) | reconnect p95 (ms) | max cancels per turn | line next | line after | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| listening | reset | 8 | 2.1 | 2.7 | 179.0 | 292.0 | 13997.1 | 14009.0 | 1 | 8/8 | 0/8 | 0 |
| mid_turn | reset | 8 | 185.9 | 188.6 | 388.0 | 457.4 | 13999.9 | 14006.8 | 1 | 8/8 | 0/8 | 0 |
| mid_sentence | reset | 8 | 8.2 | 10.0 | 75.9 | 117.3 | 13994.2 | 14005.1 | 1 | 8/8 | 0/8 | 0 |
| listening | blackhole | 1 | 10002.8 | 10002.8 | 5.8 | 5.8 | 15003.8 | 15003.8 | 1 | 1/1 | 0/1 | 0 |
| mid_turn | blackhole | 1 | 120276.9 | 120276.9 | 33.3 | 33.3 | 15005.7 | 15005.7 | 1 | 1/1 | 0/1 | 0 |
| mid_sentence | blackhole | 1 | 119994.6 | 119994.6 | 25.9 | 25.9 | 15006.3 | 15006.3 | 1 | 1/1 | 0/1 | 0 |
