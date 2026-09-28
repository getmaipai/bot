# The robot's turn should stream both ways (2026-09-28)

Jesse's ask: audio goes to the hub as the person talks, not after they
stop; the reply is spoken as it arrives, not after the whole reply
exists. Latency isn't the concern ("we can have the mini be slow") - the
interaction *shape* is. This revises G3 and G6 from
`docs/dev/reachy-mini-gap-audit-2026-09-27.md`, which designed the send
direction around a batch upload. Everything else in that doc (G1, G2,
G4, G5, G7 onward) is unaffected and not repeated here.

## What's new: a streaming STT session already exists and does its own endpointing

`home/backend/src/routes/stt.ts:22-68` is a WebSocket route,
`GET /api/stt/stream` (`requireAuth`), that the gap-audit's G6 section
never considered - it only cited the batch `POST /api/stt/transcribe`
(`stt.ts:78-113`). The wire contract is
`commons/spec/voice/ts/sttTypes.ts`'s own `SttWireEvent`:

- Client → server: binary frames, each one a little-endian
  `Float32Array` of **16 kHz mono PCM**, no envelope - one frame is one
  chunk of audio, sent continuously. One JSON control frame,
  `{"t":"end"}`, flushes whatever utterance is in progress without
  waiting for silence (push-to-talk's button-up case).
- Server → client, JSON text frames only: `{t:"ready"}` once on connect,
  `{t:"vad", speaking, rms}` on every voice-activity edge, `{t:"partial",
  v}` periodically while speaking (every `partialIntervalS`, 1.5 s),
  `{t:"final", v}` once an utterance ends, `{t:"no_speech"}` if nothing
  voiced was ever detected, `{t:"error", v}`.

Critically, `SttSession` (`home/backend/src/lib/sttSession.ts:75-316`)
does its **own** VAD and endpointing server-side: Silero (neural,
`getSileroStream()`) gated by a cheap RMS pre-check, falling back to
pure RMS thresholds if Silero isn't loaded; 0.32 s of pre-roll prepended
at voice onset (`PREROLL_S`, line 47); `silenceTimeoutS` (0.8 s,
`SESSION_CONFIG` in `stt.ts:16`) of trailing silence auto-finalizes; a
30 s hard cap (`MAX_SPEECH_SECONDS`, line 52) force-flushes runaway
noise. The client does not need to do any of this itself to use the
session - it can just stream raw PCM and let the session decide where
the utterance starts and ends.

The frontend's own reference client for the *reply* side,
`home/frontend/src/apps/chat/chatSpeechAdapter.ts`, confirms G7's design
is already correct and needs no change: `speak(text)` is called once
per **complete** assistant message (assistant-ui's own adapter
semantics - text has already fully streamed in via `turn.ts`'s `delta`
events by the time this fires), then `api.streamSpeech()` is read
chunk-by-chunk and each chunk is pushed to `StreamingWavPlayer` as it
arrives (`player.addChunk(value)` inside the read loop,
`onFirstAudio` fires on the very first chunk). "Speak each word as it
gets it" is satisfied by TTS's own audio streaming as it renders, not by
calling TTS once per word or per sentence - there is no existing
incremental-per-sentence TTS pattern anywhere in this codebase to adopt,
and G7's own plan (`the SPEAK cue's stamp precedes the first push`)
already matches this. One thing to *not* confuse this with:
`spoken_cue` events (`home/backend/src/lib/wire.ts:536`) are a separate,
unrelated mechanism - a spoken filler line ("let me think about that")
emitted only when the model's real first token is slow, never the
reply's own text.

## Revised G3: from "port legacy's VAD pipeline" to "a wake-patience timer"

The gap-audit's original G3 called for porting Silero VAD and an
endpointer into `bot/maipai_body/speech/` so the robot decides locally
where an utterance starts and ends before ever talking to the hub. That
whole VAD/endpointing job is now the hub's, for free, the moment the
robot streams to `/api/stt/stream` instead of uploading a batch WAV. G3
shrinks to exactly one piece of local logic the hub's session cannot
provide, because it lives entirely on the robot's side of the wake
moment:

**A wake-patience timer.** After G2's wake word fires, the robot opens
the WS stream and starts forwarding G1's mono 16 kHz blocks immediately
(no local endpointing needed first - the hub's own pre-roll handling
means the robot doesn't even need to hold back what it captured before
the stream opened, though sending from the wake instant onward is
simplest and already correct: real speech won't have started for at
least a few hundred ms after a spoken wake phrase ends anyway). A local
timer (the legacy value, `WAKE_PATIENCE_S = 6.0`, per the original
gap-audit's own G2 citation of `legacy voice.py:40-67`) starts at the
same moment. If a `{t:"vad", speaking: true}` event arrives before it
expires, cancel the timer - someone is talking, the hub's own
`silenceTimeoutS` will finalize the utterance on its own. If the timer
expires with no `vad speaking:true` ever received, send `{"t":"end"}`
(cheap, and correct even though nothing was ever voiced - the session's
own `finalize()` at `sttSession.ts:243-248` responds `no_speech` for an
empty buffer) and close the stream: back to sleep, no false utterance
kept the connection open forever.

That is the entire local endpointing job. No VAD model to port, no RMS
thresholds to tune, no pre-roll ring to manage beyond what G1 already
built for capture. The rest of what the original G3 acceptance
described (an emitted `Utterance` with exact start/end stamps, a
fixture proving the emitted span excludes pre-wake noise) is superseded
- there is no local `Utterance` object at all now; the robot just
streams frames and reacts to the session's own JSON events.

**Acceptance (revised):** a scripted stand-in WS server (the same
in-process-fixture pattern `RM-03`'s fake sshd and the daemon stand-in
HTTP server already established in this repo) sends `{t:"vad",
speaking:true}` 200 ms after connect in one test - assert the
wake-patience timer was cancelled and the stream stays open past 6 s;
in a second test the stand-in sends nothing - assert `{"t":"end"}` is
sent at 6.0 s and the connection closes. No live daemon needed for
either; MAIPAI_BODY_LIVE=1 is not required for this piece since nothing
here talks to the Reachy Mini daemon at all - only to the (mocked, then
real) hub.

## Revised G6: the turn round trip, streaming send

Replace the "encode as WAV, `POST /api/stt/transcribe`" step with: open
`wss://<hub>/api/stt/stream` (the redeemed session cookie from G4
authenticates the WS upgrade the same way it authenticates any other
hub route - `requireAuth` in `stt.ts:24` is the same middleware every
other authenticated route uses, nothing robot-specific to add there),
forward each G1 capture block as a binary frame the moment it's
produced, run G3's wake-patience timer alongside, and wait for exactly
one of `{t:"final", v}` / `{t:"no_speech"}` / `{t:"error", v}` before
closing the stream. `{t:"final", v}` is the text `POST
/api/turn/stream` (G5) is called with, precisely as the original G6
described - nothing about the turn call itself changes, only what
supplies its `text` argument. `{t:"partial", v}` events arriving in the
meantime are not needed for the turn call and can be ignored for the
floor (a future "the robot's own transcript so far" indicator on the
card, G10, is the only reason to keep them at all).

The original G6's batch path (`POST /api/stt/transcribe`) is not a
fallback to keep in the robot's own code: it exists for push-to-talk
clients that already have the whole recording in memory before
upload, which describes the browser, not a robot that captures
continuously from wake to end-of-utterance. If the WS connection itself
fails to open (network hiccup, hub unreachable), that's the existing
`link_lost`/`cancel` path G6 already specifies, not a reason to fall
back to a different STT route.

**Acceptance (revised):** a stand-in WS server in the test receives a
sequence of binary frames (assert their byte length and float32
decoding match G1's fixture blocks exactly, in order), replies with a
scripted `{t:"vad",speaking:true}` then `{t:"final",v:"..."}`, and the
test asserts `POST /api/turn/stream` was then called with that exact
text. A second test's stand-in never sends `vad` or `final` - assert
the wake-patience timeout fires the `{"t":"end"}` frame and no turn call
happens.

## Summary of what changed from the original gap-audit

| | Original (gap-audit) | Revised (this doc) |
|---|---|---|
| G3 scope | Port Silero VAD + a full endpointer, emit a local `Utterance` | One wake-patience timer; no VAD, no endpointer, no local `Utterance` |
| G6 send path | Buffer, encode WAV, `POST /api/stt/transcribe` | Stream raw PCM frames over `GET /api/stt/stream` from the wake instant |
| G6 receive | `{text}` JSON body | `{t:"final", v}` WS event (same text, used identically after this point) |
| G7 (reply) | Unchanged | Unchanged - already correct, confirmed against `chatSpeechAdapter.ts` |
| G2 (wake word) | Unchanged, local, required | Unchanged - this is the privacy boundary (`dev.md` section 9: "after the wake word, what you say goes to your Home... and nowhere else"), streaming to the hub's STT session only starts here, never before |
