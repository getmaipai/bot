# Why the StackChan could not see (2026-10-21)

Owner report after the 0.2.25 flash: "it doesn't know what it sees, couldn't describe it". Every
connect logs `StackChan camera stream could not start` (avatar channel not connected), `StackChan
face watching is unavailable`, and each minute `StackChan camera: 0 frames and 0 KB`. Vision,
turning toward the speaker, face wake and "can you see me" all depend on the camera stream.

## Cause

The Home web installer is fine: `backend/src/lib/stackchanInstall.ts` runs the bot's `enroll-image`
with `--ws-url ws://<lan>:<voice port>` and `--avatar-url http://<lan>:<avatar port>`, and
`provision.py` writes both (`avatar_url` and the pairing token) to the unit's `websocket` NVS
namespace; patch 019 makes `secret_logic::get_server_url()` and `generate_auth_token()` read them.

The unit never opens the socket. `hal_ws_avatar.cpp` implements it as a Mooncake ability
(`WebsocketAvatarWorker`), and the only code that creates it is `AppAvatar::onOpen`. `main.cpp`
skips every Mooncake app when `startAiAgentOnBoot` is set (the normal boot) and goes straight to
`startXiaozhi()`. So in the voice-agent firmware the avatar websocket client is never constructed,
and none of the serial captures has a `WS-Avatar` line. The host comment in `xiaozhi/server.py`
already said "AI-agent mode never starts it". Camera streaming, which the host starts by sending
`StartCameraStream` over that socket, has therefore never worked on a unit in this mode.

A second, smaller bug waited behind it: the enroll image stores the avatar address as
`http://host:port`, and the websocket client needs `ws://`.

## Fix

- Firmware patch 054 starts `WebsocketAvatarWorker` from a plain FreeRTOS task
  (`Hal::startAvatarChannel`) the first time the voice agent reports ready, and turns an `http://` or
  `https://` avatar address into `ws://` or `wss://`.
- It starts only when an avatar address is saved and 32 KB of internal RAM is free for the task
  stack and client; otherwise it stays off and reports `avatar_channel state=off why=ram free=N`.
  In 0.2.25 the unit had about 18 KB free with a 10 KB minimum, so **patch 054 stays off until
  internal RAM is freed**: experiment patch 055 (opus stack in PSRAM, stop word off) tests whether
  the 24 KB can be had safely. 055 is kept out of the recipe.
- Host: faces always go over the voice socket (this firmware has no handler for expression frames
  on the avatar socket in agent mode), and the avatar socket carries the camera only.

## Touch and shake, same session

- Pets: the firmware recognised the rub (`presses=1 run_max=19 long_runs=1`), but the host log has
  neither "was petted" nor any head event line. The host now logs one line per head or shake event
  it reads (`unit touch: head_touch held_ms=400`) and one line when a conversation suppresses the
  reaction. The robot is in back-to-back listening turns when it is talked to (a new turn starts
  within 0.2 s of the last), and the host reads events only between turns and treats the first look
  after a turn as old news, so a pet during a conversation is not acted on by design.
- Shake: the IMU path emits `shake` (threshold 16.0, the M5 default) and the host reacts to it; a
  pick-up event exists in the enum but its emitter is commented out. No `shake` line has appeared
  in the host log; the new event log will show whether the unit sent one.
- Memory in the stable build: the internal minimum fell to 9,971 bytes with 6,656 as the largest free block.
  Allocations above that size from internal RAM can fail, and this is below the old 12.5 KB floor.
  It is a real margin risk, not an immediate fault.
