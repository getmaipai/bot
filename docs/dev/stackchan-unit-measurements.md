# StackChan unit-arrival measurements

Hardware has not arrived. This runbook is ready for a paired unit; current
tests exercise the JSON path against simulator fixture data only. No result
from `--sim` is a unit measurement.

## Before connecting the unit

1. Put the robot and Bot host on a trusted isolated LAN. Use a documentation
   address such as `192.0.2.10` in examples and replace it with the host's
   actual LAN address at setup time.
2. Confirm the device is paired and its identity is approved by the local
   StackChan service. Do not record the pairing token in the result file.
3. Confirm motion is clear, keep a hand near the power switch, and use small
   moves first. The current recommended pitch range is 5..85 degrees, from
   M5's source; treat it as a recommendation until this unit is measured.

## Record

Save one JSON result after the paired-unit client has been connected to the
service. The measurement record needs:

- Servo limits in degrees for yaw and pitch, including the tested endpoint
  procedure and whether the move was under load. Pitch recommendation: 5..85.
- Camera frame rate and request-to-frame latency at 320x240, with the number
  of frames/trials and lighting noted.
- AEC enabled/disabled state and a short paired comparison at low, normal and
  high speaker volume. Note audible echo or dropped uplink.
- Battery level and charging state read through the firmware path. Repeat
  while charging and on battery. Stop if the firmware reports an I2C error.
- The exact MCP `tools/list` names returned by the base firmware.

The script entry point is `body/maipai_body/bodies/stackchan/measure/run.py`.
Once a paired-unit `MeasurementClient` is implemented, use
`write_results(client, Path("stackchan-measurements.json"),
source="paired-unit")`. The source must be `paired-unit` only for a live
paired connection. Today the command supports `--sim` solely to rehearse the
output schema:

```sh
cd body
uv run python -m maipai_body.bodies.stackchan.measure.run --sim \
  --output /tmp/stackchan-measurements.json
```

The simulator fixture includes representative values to prove collection and
serialization, labels the source `simulator`, and writes
`"unit_verified": false`. It does not exercise physical servos, camera,
AEC, battery reads, or a live MCP tool list. The test therefore verifies the
kit's code path only, not the hardware behavior.
