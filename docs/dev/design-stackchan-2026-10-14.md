# Design record: M5Stack StackChan as a MaiPai Bot body (2026-10-14)

Status: DRAFT, research only. Not reviewed by the architect, not committed, not a plan change.
Backlog item it serves: BODY-STACKCHAN-01 (`docs/BACKLOG.md`, "StackChan body"). Nothing here is built.
Hardware has not arrived, so every row marked UNVERIFIED must be settled on the unit.

**Correction (later the same day):** the "stock firmware" assumption in section 3 and 5.2a is wrong. The stock build contacts vendor hosts
(an M5Stack server by IP, a third-party xiaozhi OTA host, public NTP) and runs a second protocol, the `/stackChan/ws` avatar channel.
Zero vendor contact needs one reproducible custom firmware build. See `design-stackchan-pieces-and-gaps-2026-10-14.md`, which supersedes
those sections where they differ.

## 1. Answers in one place

| Question | Answer |
|---|---|
| Can it be a MaiPai Bot body? | Yes, under the one-body-layer rule: a `bodies/stackchan/` profile beside `bodies/reachy_mini/`. |
| Can it use our home LLM instead of a StackChan cloud? | Yes, and no live third party is involved anywhere (section 5.2a). The stock firmware only needs a server that speaks the xiaozhi WebSocket protocol. We write that server's turn handler to call Home's turn engine, so persona, memory, age gates and the output gate all apply. No MaiPai code runs on the device. |
| Can it do face recognition? | Yes in principle, with a limit. Detection and matching run on the host, never on the ESP32. The camera is a 0.3 MP GC0308 (320x240 JPEG), so recognition works only for a face close to the lens. Treat it as "greet the person at the desk by name", never as a door or security check. UNVERIFIED until measured on the unit. |
| Is warble the right base? | As the protocol specification, yes. As code to carry over, no. See section 4. |
| Is something more complete than warble? | The xiaozhi ecosystem has bigger servers, but none fits our rules better. See section 3. |

## 2. What the hardware is

Cited from M5Stack's `m5stack/StackChan` README and BrettKinny/dotty-stackchan `docs/hardware.md`; neither was run on a unit.

- Head unit: M5Stack CoreS3, ESP32-S3 at 240 MHz, 16 MB flash, 8 MB PSRAM, Wi-Fi 2.4 GHz and BLE 5.
- Display 2.0 inch, 320x240, capacitive touch. Camera GC0308, 0.3 MP. Two microphones, 1 W speaker, IMU, proximity and ambient light.
- Body adds: two feedback servos (yaw continuous, pitch 90 degrees, pitch limited to 5 to 85 degrees by M5Stack's own advice), 12 RGB LEDs, three-zone touch panel, NFC, IR pair, 550 mAh battery.
- The camera has no shutter. Any capture needs a distinct, hardware-bound indicator (section 8).
- It cannot run the bot stack. It is a thin body: it senses, it renders a face, it moves two servos, it plays audio. Everything else runs on a host.

Conflict to settle on the unit: `m5stack/StackChan` firmware's `self.robot.set_head_angles` documents yaw -128 to 128 and pitch 0 to 90 degrees, while the hardware table says the yaw servo rotates continuously. `bodies/stackchan/profile.py` takes the firmware figures with a source and date, and the unit measurement replaces them.

## 3. What exists, and what each is worth to us

Licenses read from each repo's license file; stars and dates from the GitHub API on 2026-10-14.

| Project | License | What it is | Verdict |
|---|---|---|---|
| `rebelthor/warble` | MIT (Piper image GPL-3.0) | About 3,200 lines of Go speaking the xiaozhi protocol; whisper.cpp, Silero, Ollama, Piper behind it. `server/PROTOCOL.md` cites firmware line numbers. Voice and face only. Last push 2026-06-16. | Best specification of the wire. Rebuild the server in our language; do not carry its pipeline. |
| `xinnan-tech/xiaozhi-esp32-server` | MIT, 10.8k stars, active | The community standard server: ASR, LLM, TTS, MCP, admin UI. Large Python and Java stack. | Too large and too many moving parts for principle 1 and 6; its provider plug-in model is the reason dotty works. Read for protocol edge cases, do not run. |
| `BrettKinny/dotty-stackchan` | MIT, active, self-described unstable | A complete self-hosted stack on top of the xiaozhi server and `m5stack/StackChan` firmware: kid mode, face-detected events, state mutex with LED ring, privacy LEDs, dashboard. | Most complete product-level reference. Take ideas, not code: its kid filter is a blocked-word list, which our rules forbid (RULES-AND-LEARNED-COMPONENTS), and it is explicit that the filter is bypassable. |
| `zziying/stackchan-openapi` | MIT | Arduino firmware exposing HTTP endpoints for camera, servo, face, record, stream, play; host-side face finding and tracking with MediaPipe and InsightFace. | Best evidence that host-side face tracking at 320x240 works, and a clean small-endpoint design to compare against MCP. Different firmware lineage; not the base. |
| `migratorywhale/stackchan-mcp` | MIT | PlatformIO firmware plus an MCP server (see, listen, say, move, nod, shake, face, sense) and optional host face tracking. | Useful tool vocabulary. It exists to give an outside AI a body, the reverse of our need. |
| `kisaragi-mochi/stackchan-mcp` | license NOASSERTION | Gateway that talks MCP over WebSocket to xiaozhi-based StackChan firmware and receives camera JPEGs by HTTP POST. | Confirms the photo path (section 5). No usable license, so reference only. |
| `schroneko/stackchan-nukoevi` | MIT root, upstream files keep their own | One person's custom firmware: replaces the face with character art, MQTT text, websocket TTS. | Reference only. Its finding that audio over MQTT stutters badly is worth keeping. |
| `m5stack/StackChan` | MIT (firmware, server and remote each carry an MIT license file) | The official firmware: avatar, servos, LEDs, camera, and xiaozhi client with MCP tools. | The firmware we run. Not the legacy `stack-chan/stack-chan` JavaScript project (Apache-2.0), which is a different lineage. |
| `78/xiaozhi-esp32` | MIT | Generic voice-assistant firmware; the protocol source. | Cited by warble and M5Stack. Our protocol reference for the base layer. |

No candidate is a better base than "stock M5Stack firmware plus our own thin protocol server". The deciding fact is that the firmware is MIT, already has the servo, LED, avatar and camera tools, and needs only a server on the other end. Writing the server ourselves costs about the size of warble's Go server and removes every second turn pipeline (principle 1).

## 4. What we take from warble, piece by piece

Principle 8: each row is a recorded verdict. Anything we use is downloaded or reimplemented from the spec, never vendored.

| warble piece | Verdict | Why |
|---|---|---|
| `server/PROTOCOL.md` (OTA, hello, listen, abort, binary framing, tts frames) | Use as the specification, check each claim against `78/xiaozhi-esp32` and `m5stack/StackChan` before coding | It is the single best written account of the wire, with citations. |
| OTA endpoint answering with our WebSocket URL, `firmware.url` empty | Rebuild | The OTA reply must never trigger an update on its own (firmware updates stay under our UPDATES.md rules). |
| WebSocket session, hello reply, session id, 60 ms Opus framing, 16 kHz up and 24 kHz down | Rebuild from the spec | Needs an Opus codec; choose a maintained library, do not hand-roll. |
| Emotion tag at the start of a reply, stripped before speech | Do not carry | Principle 6 and the rules file: the model decides, and a prompt hack for a tag is the long-prompt anti-pattern. Our expression layer already chooses a cue; map the cue to the firmware's face set (section 6). |
| whisper.cpp, Silero VAD, Piper, Ollama | Do not carry | Home already has `/api/stt/stream`, `/api/tts` and the turn route. The Stack owns engines (rule 11). Piper is GPL-3.0 and has no place in the path. |
| Live prompt and runtime JSON files | Do not carry | Persona and settings come from Home's own records. |
| `./warble connect` (reflash NVS over USB to point at the host) | Port the idea | A pairing step must exist; ours goes through the Devices page and the existing pairing flow, not USB flashing of a server address for every install. |
| `transcript` command | Do not carry | Turns already trace in Home (`turnTrace`). |

## 5. Architecture

### 5.1 Where things run

Speech placement is `pod` (the host does speech), as the HAL seam already allows: `speech_placement: Literal["pod", "robot"]`.

```
StackChan (stock M5Stack firmware, ESP32-S3)
   |  Wi-Fi, xiaozhi WebSocket: Opus up, Opus + face/emotion down, MCP JSON-RPC
   v
StackChan translator (bot repo code, the bot service Home pairs with)
   bodies/stackchan/client.py   xiaozhi protocol server, Opus codec, MCP client
   bodies/stackchan/profile.py  limits, capabilities, sensors, cuts (one place)
   presence, expression, vision  (existing bot layers, body-agnostic)
   |
   v  existing paired link
MaiPai Home hub   /api/stt/stream, turn route, /api/tts, biometric prints
   (or the bot's offline ladder when the hub is unreachable)
```

- The protocol server lives in the bot repo, in the one body layer, because the bot is the thing that must be complete without a hub (principle 2). A StackChan with a bot host and no hub still talks, using the offline ladder the bot already has. The StackChan alone, with no host, cannot: that is a stated limit, not a stub.
- Home never learns a vendor name. It sees a paired bot with capabilities.
- Correction from Jesse, 2026-10-14: the bot repo is the framework for every kind of bot; a StackChan is one robot type, so its translator code lives in the bot repo. The StackChan needs no Raspberry Pi and runs on its native hardware. The Reachy Mini is a separate bot with its own embedded Pi, and Jesse's third, unbuilt robot will use a Pi 5. None of them shares a host with another. Because the stock firmware only speaks the xiaozhi protocol, the bot project supplies the translator that stands in for the vendor cloud. Jesse's framing: the bot project is to robots what the Stack is to local AI. It is a headless service that Home pairs with and uses, never code inside Home. Home pairs with the bot service over the existing paired link, and the bot service's StackChan translator speaks xiaozhi to the device. Where that bot service is installed (the same machine as Home, or another box on the home network) is a deployment choice, not a design one; the code and its release cadence belong to the bot repo either way. Whether a firmware that talks to the bot service directly is worth building later is an open question.

### 5.2 One turn

1. Wake or touch: the device sends `listen` with a mode, then 60 ms Opus frames.
2. Host decodes to 16 kHz mono PCM, streams to Home's `/api/stt/stream` (same wire the Reachy design uses: Float32 frames, `vad`, `partial`, `final`).
3. The final transcript goes to the hub turn route as a normal turn for the identified person or the household.
4. The reply streams back sentence by sentence into `/api/tts`, is encoded to Opus at 24 kHz, and sent with `tts` start, sentence and stop frames. A device `abort` cancels the turn, flushes audio and sends `tts` stop, as `PROTOCOL.md` requires.
5. Expression cues from the expression layer become a face emotion frame plus optional head moves. Face frames never carry model free text.

Failure shape: a failed tool never fails the answer (rule). If the hub is unreachable, the host falls to the offline ladder with a spoken line saying so in plain words.

### 5.2a Owner requirement: no live third party, no data funnel (2026-10-14)

Jesse's standing requirement for this body: the project never depends on a live third-party service, and no data flows to one. The StackChan sits on the home Tailscale network, and our home replaces everything the stock setup gets from M5Stack and xiaozhi servers, with full functionality kept and improved.

What the stock device reaches for, and what replaces it:

| Stock dependency | Replacement | Status |
|---|---|---|
| xiaozhi cloud WebSocket (speech, LLM, TTS) | Our protocol server on the bot host, wired to Home's STT, turn engine and TTS | Designed (5.1, 5.2) |
| xiaozhi OTA and activation check | Our OTA endpoint, never offers a firmware URL, no activation code | Designed (section 8) |
| M5Stack StackChan app and cloud (world sharing, remote control) | Home's own app and Devices page over Tailscale; no M5Stack account | UNVERIFIED which firmware features need the cloud; list them from the firmware at bring-up |
| Cloud LLM, cloud ASR, cloud TTS | Home's local models only | Designed |
| Firmware and model downloads | Fetched once, pinned and checksummed (RELEASES-AND-DEPENDENCIES), flashed by us | Rule |

Network shape:

- The ESP32-S3 cannot run a Tailscale client (no official build; running WireGuard on it is a project of its own). So the device joins the home Wi-Fi and talks to the bot host on the LAN. The bot host, and Home, are Tailscale nodes.
- Away from home, the person reaches the robot through the host over Tailscale (app, chat, status). The device itself never needs a public address and has no inbound path from the internet. A Tailscale subnet router at home covers any case where the device must be reachable from the tailnet. UNVERIFIED: whether we want the device reachable at all from outside the LAN.
- The device's DNS and default route are limited to the LAN host by an access rule at the router if possible. Section 8's capture proves it.

Same or better than stock, from what the research shows:

- Same: voice conversation, face and emotion display, head motion, LEDs, reminders, camera "what is this" questions, touch.
- Better: the home LLM and household memory (it knows the family and the day); person-aware answers by face and voice; age gates and the output gate; the offline ladder when the hub is down; one household record store instead of a vendor cloud; no account, no usage limit, no outage when a vendor changes terms.
- Only in the stock cloud and not replaced: anything that is a shared service by nature (a public gallery of other people's StackChans). We do not replace it, by design.

### 5.3 Servo, LED and display control

The official firmware exposes MCP tools over the same WebSocket. Read from `m5stack/StackChan` `firmware/main/hal/hal_mcp.cpp`:

- `self.robot.get_head_angles`, `self.robot.set_head_angles` (yaw, pitch, speed 100 to 1000; documented ranges yaw -128 to 128, pitch 0 to 90)
- `self.robot.set_led_color` (0 to 168 per channel)
- `self.robot.create_reminder`
- from xiaozhi: `self.audio_speaker.set_volume`, `self.get_device_status`, `self.camera.take_photo`

UNVERIFIED: the full live `tools/list` on a real unit. Capturing it is step 1 on arrival (dotty's docs call out the same gap).

Safety rule for motion: the bot clamps every target against `profile.py` before sending (the HAL promise). The pitch clamp is the vendor's 5 to 85 degrees. Our clamp is the first line; the firmware's is the second.

Expression mapping: the seam's primitives (listen, glance, tilt, nod, perk, attend, settle, breathe, track, speak) render on this body as small head moves, face changes and LED states. Which primitives are honest on a 2-DOF head is a table in `bodies/stackchan/` and a measurement row, as for Reachy.

## 6. Face and emotion

The firmware has a fixed face set. warble uses seven tags (neutral, happy, laughing, angry, sad, crying, doubtful); zziying's HTTP firmware lists eight (neutral, happy, sad, angry, sleepy, doubt, love, eyeroll). The set on the M5Stack firmware is UNVERIFIED and is read from its avatar code at bring-up.

Rule: the model never emits a face token. The expression layer picks a cue from the turn's state (listening, thinking, speaking, mood of the reply from the existing cue path), and the profile maps cues to the firmware's faces. One definition, one place (principle 4). The Eyes mapping step in BODY-STACKCHAN-01 is this table.

## 7. Face recognition

What exists on the hub side: `FACE-01` biometric print store (encrypted embeddings, consent invariants, child never self-consents), `FACE-02` guided enrollment in the browser, SFace and YuNet models, measured quality bars (minimum face box fraction 0.08, sharpness 90). Enrollment is always hub-owned.

What this body adds: a camera frame, nothing else. Design:

1. Frames reach the host through the MCP `take_photo` path (the device uploads a JPEG to a URL the host supplied in `initialize`, multipart with a `question` field) or through a streamed capture if the unit supports it. UNVERIFIED which the M5Stack firmware keeps.
2. The host runs the bot's existing vision pipeline (`detect`, `align`, `embed`, `recognize`, `gallery`). Frames never leave the host except as a hub still-image call the person consented to. The ESP32 runs no model.
3. A match returns a person id with a confidence, used only to choose which household member the turn belongs to. Child and teen floors apply before anything is said (SAFETY.md). A face never unlocks adult content; adult unlock keeps its own gate.
4. Face tracking (head follows the person) is a separate, anonymous behavior: it needs detection only, no identity, as in the Reachy design section 6. zziying and migratorywhale both prove host-side tracking is workable at 320x240 with slow, bounded corrections.

Open measurement (must be done on the unit before any promise): at 320x240, the SFace crop is 112x112; a face smaller than about 80 pixels across gives poor embeddings. At the 0.08 box-fraction bar a face must fill roughly 26 pixels of the 320 width as a bare minimum for detection, but recognition needs far more. Expect a working range of well under a meter to about one meter. Plan a measurement row: match rate and false-accept rate against the enrolled demo household at 0.5, 1.0 and 1.5 meters, in room light and dim light, with the hub's thresholds. If it fails, the body ships with tracking and "who is talking" from voice, and face recognition stays a browser and Reachy feature.

## 8. Safety and privacy on this body

- Age and surface gates outrank everything: the host applies the same output gate as any bot; the StackChan has no separate filter. Dotty's word-list filter is an example of what not to copy.
- Zero phone-home: the stock firmware's default is the M5Stack and xiaozhi cloud. Pairing must leave the device pointed at the host only. A checked step in bring-up proves no traffic leaves for any other address (packet capture on the host, recorded).
- No cloud OTA: our OTA reply never offers a firmware URL. Firmware updates are a deliberate, signed, user-approved step.
- Camera indicator: the StackChan has multicolor RGB LEDs, so the indicator exists. The translator turns a fixed camera color on before every photo request and off after, and never captures without it. That is a software guarantee: it holds as long as the only capture path is the translator's request. UNVERIFIED: whether the stock firmware captures on its own (wake-word vision, M5Stack features); the bring-up check is to read the firmware's camera call sites and watch the camera while idle. If it can capture without the translator asking, the options are a minimal tracked firmware patch or disabling that feature. A hardware-bound light stays a later option.
- Credentials: the pairing token lives in the device's NVS and in the host's store, never in a URL or log (CREDENTIALS.md).
- Child profiles: no capture-to-hub of a child's face without the consent flow the print store already enforces.

## 9. Pairing and setup

- The device is provisioned by its normal Wi-Fi setup, then pointed at the host through the same OTA-URL setting warble uses (NVS `ota_url`). The Devices page shows it as a body with capabilities and a pairing state.
- The host advertises itself by name on the LAN; the device's OTA URL is set once with a short, documented step. Detail waits for the unit.
- Each body has its own id and profile; no body depends on another body's host.

## 10. Order of work (proposal, not a plan change)

This restates BODY-STACKCHAN-01's own steps with what the research adds. It does not edit the backlog or the plan.

1. On arrival: record model, firmware version and pinout; capture the live `tools/list`; capture a device-to-server hello and an OTA exchange as fixtures (`scripts/record_fixtures.py` pattern).
2. Body-capability vocabulary entry for this body (commons).
3. `profile.py` with measured limits; `fake.py` replaying the fixtures; the full suite runs against the fake always, the unit when present.
4. Protocol server slice: OTA, hello, one voice turn with a canned reply, abort handling.
5. LLM bridge: STT stream to the hub, turn route, TTS back, with the offline ladder as fallback.
6. Expression table: cue to face and head move.
7. Camera: photo to host, tracking, then the recognition measurement of section 7.
8. Privacy proofs: no outbound traffic, indicators, OTA refusal.

## 11. Open questions for Jesse

1. Settled by Jesse 2026-10-14: no Raspberry Pi for the StackChan; translator code lives in the bot repo, runs on the hub machine.
2. Face recognition scope if the measurement is poor: ship tracking and voice identity only, or hold the body until recognition works?
3. Camera indicator: the RGB LEDs lit by the translator are the v1 indicator (Jesse, 2026-10-14). Revisit a firmware patch only if bring-up finds the firmware can capture on its own.
4. Settled by Jesse 2026-10-14: no live third party and no data funnel; M5Stack and xiaozhi cloud features are replaced by Home over Tailscale (section 5.2a), not left as an option.
5. Remote reach: should the robot be controllable from outside the home through the host over Tailscale, or only on the home network?

## Sources

- https://github.com/rebelthor/warble (MIT; `server/PROTOCOL.md`, `README.md`, `THIRD_PARTY_LICENSES.md`)
- https://github.com/m5stack/StackChan (README; `firmware/main/hal/hal_mcp.cpp`; license files under `firmware/`, `server/`, `remote/code/`)
- https://github.com/78/xiaozhi-esp32 (MIT; `docs/websocket.md`, `docs/mcp-protocol.md`, `docs/mcp-usage.md`; camera `Explain` upload in `main/boards/common/esp32_camera.cc`)
- https://github.com/xinnan-tech/xiaozhi-esp32-server (MIT; GitHub API, 10.8k stars)
- https://github.com/BrettKinny/dotty-stackchan (MIT; `README.md`, `docs/hardware.md`, `docs/architecture.md`)
- https://github.com/zziying/stackchan-openapi (MIT; `README.md`)
- https://github.com/migratorywhale/stackchan-mcp (MIT; `README.md`)
- https://github.com/kisaragi-mochi/stackchan-mcp (license NOASSERTION; `README.md`)
- https://github.com/schroneko/stackchan-nukoevi (MIT root; `README.md`, `docs/nukoevi-status.md`)
- https://github.com/stack-chan/stack-chan (Apache-2.0; the original JavaScript project, a different lineage)
- In this repo: `docs/dev/design-reachy-mini-2026-09-27.md`, `docs/dev/hal-seam.md`, `docs/dev/robot-streaming-turn-2026-09-28.md`, `docs/dev/face-voice-recognition-design-2026-09-28.md`
