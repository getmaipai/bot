# StackChan unit-arrival measurements

The first unit arrived on 2026-10-19. Our firmware is flashed and passed the
basic bench below. The full measurement record (servo limits, camera timing,
AEC, protocol fixtures, egress proof, idle-camera watch) is still to do; the
procedures for it follow the bench record.

## First unit bench, 2026-10-19

Unit: M5Stack StackChan (CoreS3 base), USB-C to a macOS laptop, ESP-IDF 5.5.4.
Real addresses, the MAC and the Wi-Fi name stay out of this file; examples use
`192.0.2.10`.

### Steps that worked

1. Backed up the full 16 MiB flash with `esptool.py -b 2000000 read_flash`.
   The default baud takes about 8 times longer. The flash tool now passes
   `-b 2000000`.
2. Paired before flashing: generated a Client-Id (any UUID), then ran
   `PairingStore.request` and `approve_to_file` for the MAC and that Client-Id.
   There is no user-facing command for this yet (see Findings).
3. Ran `body/scripts/stackchan_flash.py`. It built the pinned firmware,
   generated the NVS image and wrote both with one `esptool write_flash`; every
   hash verified.
4. Wi-Fi without the M5 app: on the first-boot screen, tap **Skip**, open
   **AI Agent**. With no saved network the firmware starts its own hotspot
   (`Xiaozhi-` plus four characters) and shows `http://192.168.4.1`. Join it
   from a phone, pick the home network, type the password. The unit saves it,
   leaves the hotspot and joins the network. Nothing goes to M5.
5. Ran a bench server (xiaozhi on 8765, avatar on 8766, vision on 8767) and
   called tools over the live session.

### Results

| Check | Result |
|---|---|
| Boot | App `maipai-stackchan` 1.5.1-maipai.1 from `ota_0`; 8 MB PSRAM |
| Wi-Fi | Joined through the firmware hotspot page; DHCP address in about 4 s |
| Session | Authenticated; hello features `{"mcp": true}` |
| Battery | `self.battery.get_status` returned `{"percent": 100, "charging": false}` in 13 ms |
| LED | `set_led_color` green 40 then off; owner saw the ring light |
| Head yaw | 3 degree nudges right, left and back at speed 100; owner saw the moves |
| Head pitch | 3 degree nudges up, down and back; owner saw the moves |
| Head readback | `get_head_angles` returned the start angle (yaw -8, pitch 26) after each move; pitch read 25 once |
| Tool latency | 13 to 834 ms per call; `get_head_angles` took up to 2040 ms |

MCP tools registered at boot: `self.battery.get_status`,
`self.robot.get_head_angles`, `self.robot.set_head_angles`,
`self.robot.set_led_color`, `self.robot.set_led_colors`,
`self.robot.create_reminder`, `self.robot.get_reminders`,
`self.robot.stop_reminder`. No camera tool appeared in the boot log.

Chips found at boot: GC0308 camera, AXP2101 power, AW9523 I/O expander,
FT6336 touch, ILI9342C display, Si12T head touch, PCF8563 RTC (timezone GMT0),
BMI270 IMU. Servo zero positions read from settings: id 1 = 460, id 2 = 620.
Power save: sleep after 300 s, shutdown after 600 s.

### Findings

Fixed in this change (each has a regression test):

- **Client-Id lost on flash.** The firmware sends NVS `board:uuid` as its
  Client-Id. Our NVS image replaces the whole partition and did not write that
  key, so the first boot made a random UUID and the server refused the unit as
  unpaired. `provision.generate_image` now writes `board:uuid` from
  `--client-id`.
- **Port clash.** The vision listener and the avatar listener both defaulted
  to 8766. Vision now defaults to 8767.
- **`idf.py flash` failed after the build.** `recipe.sh` deletes its private
  `sdkconfig.defaults.local`, so the reconfigure step in `idf.py flash` stops.
  The flash tool now writes the images from `build/flash_args` with esptool.
- **Token deleted before the flash.** `provision.py` removed the approval token
  file before the flash step ran, so a failed flash could not be retried. The
  flash tool now hands provision a private copy and deletes the original only
  after a successful write.
- **ESP-IDF needs Python 3.12** on `PATH`, and a `uv` virtualenv leaking into
  the build breaks it; the flash tool sets both.
- **Token in error output.** A failed recipe printed its argument list with the
  token. Error output is now redacted; the leaked token was rotated.

Open:

- **No pairing command.** The setup guide said to wait for the robot to appear
  in the pending list, but the stock firmware never contacts the Bot. Pairing
  needs the MAC and a chosen Client-Id before flashing; today that is a
  developer step.
- **Wi-Fi password in the serial log.** The M5 BLE setup path logs
  `get wifi config: <ssid> / <password>` in plain text. Anyone with the USB
  cable sees it. Our bench capture dropped those lines. A firmware patch should
  remove the password from the log.
- **Rewriting NVS wipes Wi-Fi.** Any later NVS-only write (for example a new
  token) erases the saved network, so the hotspot step runs again.
- **Token visible in `ps`.** The recipe receives `--pairing-token` on its
  command line.
- **Head readback lags.** `get_head_angles` did not show a 3 degree move one
  second later. It may report the synced target rather than the servo
  position; measure before relying on it for closed-loop moves.
- **M5 first-boot screen offers the cloud app.** **Start** leads to a QR code
  for the M5 account app. Our setup uses **Skip** and the hotspot instead.
- **Failed hello timeouts.** While unpaired, the unit showed "Waiting for
  response timeout" and retried every 10 to 15 s. The server closes the socket
  without logging why.

## Remote control and speech bench, 2026-10-19

`body/scripts/stackchan_control.py` runs the three robot listeners plus a page
on `http://127.0.0.1:8790` (this computer only) with LED color, head yaw and
pitch, nod, shake, the six faces, volume and a say box. Stop the Bot app
first; both bind 8765 to 8767.

    cd body
    uv run --extra voice python scripts/stackchan_control.py --host 192.0.2.10

`--host` is the address the robot already connects to. Head moves are offsets
from the angle read at the first status and stay within `--limit` degrees
(default 10), so a plugged-in USB cable is not pulled.

| Control | Result |
|---|---|
| LED | Red, green, blue, off; owner saw each. Channels above 168 are refused by the firmware, so the page scales 0 to 255 down to 0 to 168 |
| Head | Nod, shake and an 8 degree turn and back; owner saw each |
| Faces | Neutral, happy, angry, sad, doubt, sleepy; owner saw each change |
| Speech | 4 to 5 s of macOS `say` audio; owner rated the last run "pretty good" |

Findings:

- **Faces need the voice channel in AI Agent mode.** The avatar socket (8766)
  only opens inside the firmware's avatar app. In AI Agent mode the face is
  set with a xiaozhi `{"type": "llm", "emotion": ...}` frame, which the
  StackChan display maps onto the avatar (`doubt` is sent as `doubtful`).
  `XiaozhiServer.send_emotion` sends it; the page uses the avatar socket only
  when it is connected.
- **Speech stuttered for three reasons, fixed in order:**
  1. Frames sent right after `tts start` arrived while the firmware was still
     listening and were dropped (it queues audio only in the speaking state).
     The server now waits 150 ms after `tts start`.
  2. The default Opus music mode sent 64 kbps fullband packets of three CELT
     frames; the robot took 9.6 s to play 4 s of audio. The encoder now sends
     24 kbps SILK wideband, one 60 ms frame per packet (TOC `0x58`); the same
     clip then took 5.3 s.
  3. The robot's Wi-Fi is jittery: ping averaged 280 to 400 ms with peaks of
     1.3 s while the server's own send gaps stayed under 215 ms. Playback now
     leads by 30 frames (1.8 s), under the firmware's 40-frame (2.4 s) decode
     queue, which drops packets once full. A 1 s lead still stuttered.
- **Upstream reports match.** M5's issue tracker has choppy agent speech
  tied to weak Wi-Fi and to firmware 1.3.1 and later (m5stack/StackChan
  issue 54); one reporter heard clean speech near the access point. Place the
  robot near the access point when judging audio.
- **Head readback trails moves.** A status read right after a move returned
  yaw 3, pitch 40 for a 0, 45 target.
- **Owner wants a cuter face.** The six built-in faces work but look plain;
  the look is the firmware's avatar skin.

## Mint face and speech stutter, 2026-10-20

Each run played the same 11.5 s macOS `say` line through `/api/say` while
`ping` sent 40 probes at 0.5 s from the host (`192.0.2.10`) to the robot.
Free SRAM is the firmware's own `SystemInfo` log line.

| Build | Owner heard | Ping during speech (avg / max) | Lost | SRAM low point |
|---|---|---|---|---|
| Original mint skin | stutter | 2.2 s / not recorded | not recorded | 28 KB |
| Mint, redraw fix | stutter | 1.0 s / 3.35 s | not recorded | 43 KB |
| Old face, no patch 013 | stutter "bad" | 1.39 s / 3.04 s | 9 | 51.8 KB |
| Mint plus patch 014 | "a little at the beginning and end" | 0.57 s / 2.49 s | 5 | 43.3 KB |

Findings:

- **The face was not the cause.** The old face stuttered as badly as mint in
  the same spot. One earlier clean old-face run (252 ms average ping) was a
  quiet Wi-Fi moment, not a property of the face.
- **Wi-Fi slept through speech.** After activation the firmware sets
  `MAX_MODEM` power save (serial: `Setting WiFi power save level: LOW_POWER`)
  and only raises it in the audio channel open callback, which our
  persistent-socket host never triggers. No log line ever showed
  `PERFORMANCE` until patch 014, which sets it on entering speaking.
- **Host sends are steady.** The largest gap between frame sends stayed at
  212 ms in every run, so the delays are on the radio side.
- **Start and end stutter, measured.** See the next section.

## Speech edges, 2026-10-20

Patch 015 logs frames lost at a line's edges: frames dropped before the
speaking state, frames cleared by a decoder reset, and playback gaps over
30 ms. The host also polled its own send queue to the robot every 100 ms.
Each run played three numbered lines ("Sentence one of three...") about
10 s apart.

| Run | Owner heard | Serial log | Host send queue |
|---|---|---|---|
| 30-frame burst | lines 2 and 3 stuttered | line 3: reset cleared 12 frames, then an 851 ms gap; line 2: 557 ms gap near the end | 2.9 KB unacknowledged for 1.45 s during line 2 |
| Same, earlier | line 2 played 30 s late, line 3 lost | nothing reached the robot for 30 s | not recorded |
| Spaced burst (15 ms), 38-frame lead | first half of "Sentence" missing on line 1 only | line 1: reset cleared 6 frames; lines 2 and 3: no loss, 78 ms worst gap | drained, no stall |

Findings:

- **Start: a decoder reset cut the first frames.** `tts start` switches the
  robot to speaking on its main task, and the speaking entry clears the
  decode queue 100 to 110 ms later. Audio that arrived in between (6 to 12
  frames, 360 to 720 ms) was thrown away. Nothing was dropped before the
  state change: the host's 150 ms settle covers that.
- **Middle and end: Wi-Fi stalls.** The robot has 9 Wi-Fi receive buffers
  and a 3-packet block-ack window. Thirty tiny frames sent back to back
  overflowed them; the lost packet stalled the stream for about 1.5 s (one
  TCP retransmit), longer than the lead could cover. A worse case backed
  off for 30 s.
- **Host fix, landed:** the lead goes out 15 ms per frame and is 38 frames
  (2.28 s, under the 40-frame decode queue), so about 1.7 s is queued when
  pacing starts. The send-queue stall did not recur.
- **Firmware fix, built, not yet on the robot:** accept a line's audio from
  `tts start` and keep the queue on a reset while the line is open. It
  needs a flash with the owner present, then three clean numbered lines.



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

The checklist is ready for the unit; no camera watch has been performed yet.

## Duplex and speech latency rows

Record these rows for each paired unit and firmware build. Keep `source` as `simulator` for fake-peer runs and use `paired-unit` only for a physical StackChan trial.

| Measurement | Procedure | Result fields |
|---|---|---|
| Abort to silence | Play a multi-frame reply, issue abort at a recorded frame boundary, repeat 10 times | `abort_to_silence_ms` median and maximum; pending frames after abort (must be 0) |
| First audio | Start capture, send the first uplink frame, repeat 10 times | `first_audio_ms` median and maximum |
| AEC duplex | Record device hello `features.aec`; while speaking, send uplink at low, normal and high volume | AEC advertised, live uplink frames, dropped frames, audible echo |
| Mute guard | With AEC false, send uplink during speech and at 100, 180 and 250 ms after stop | frames accepted/dropped at each offset |
| Turn handoff | Exercise auto, manual and realtime listening, then barge in and complete two back-to-back turns | mode, capture count, completed turn count, reply count (one per turn) |

These rows define the measurement procedure; no duplex rows have been recorded on the unit yet.
