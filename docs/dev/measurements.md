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
