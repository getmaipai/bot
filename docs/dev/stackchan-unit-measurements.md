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
The physical measurement runner still needs a paired-unit `MeasurementClient`;
when implemented, use `write_results(client, Path("stackchan-measurements.json"),
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
## Protocol fixtures and privacy checks

With the unit paired to the local service, record its live hello and MCP tool
list plus the local OTA exchange. Supply every address and credential explicitly;
the recorder refuses to run without `--unit`, strips bearer credentials and
redacts MAC addresses, UUIDs and serial-number fields before writing. Review
`body/tests/fixtures/stackchan/unit-arrival.json` before committing a refreshed
fixture. Example (replace the documentation address with the host's LAN address):

```sh
cd body
uv run python scripts/record_stackchan_fixtures.py \
  --unit ws://192.0.2.10:8765 --ota-url http://192.0.2.10:8765/ota \
  --device-id '<paired-device-id>' --client-id '<paired-client-id>' \
  --token '<paired-token>'
```

For the egress proof, capture traffic while the unit is idle and while exercising
its features, then pass the pcap/pcapng and the host address to
`scripts/stackchan-egress-proof.sh`. Text files with one destination IP per line
can rehearse the check. Any destination other than the host is reported and
fails the check. This strict proof may expose expected local router traffic;
those results still require investigation, since the acceptance criterion is
that the device only contacts the host.

## Idle-camera watch checklist

1. Point the device camera away from people and cover the lens during setup.
2. Keep the paired device powered and connected with the service idle. Observe
   the camera and any camera status LEDs for several minutes without calling a
   camera tool; record visible activity and the duration.
3. Repeat while waking the device, after a voice turn, and after disconnecting
   the host. Do not infer inactivity from network silence alone.
4. Capture the device camera call sites from the exact firmware build and note
   any autonomous capture feature or trigger.
5. If any capture occurs without a host request, stop the trial and record the
   trigger and indicator state. This remains an unresolved firmware privacy gap
   until disabled or covered by a minimal tracked firmware patch.

The checklist is ready for the unit; no camera watch or hardware verification
has been performed.
