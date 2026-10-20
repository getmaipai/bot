# StackChan: the robot voice (2026-10-20)

Status: CHOSEN by ear on the first unit (2026-10-20). Raised by Jesse on the first unit bench: "we need a cute robot voice".

## Verdict

The robot speaks with a household voice cloned in the hub's own engine (Chatterbox Turbo, the pinned
`mlx-community/chatterbox-turbo-fp16` revision) from a 10 second reference clip. Sampling temperature is 1.05 and the robot
persona writes playful lines (exclamations, a drawn-out "Soooo...", questions, an optional `[chuckle]` tag). The bot needs no
change: Home picks the voice for the robot's device session (`robot.voice.id`, DEVICES-02) and the Stack renders it once
per-voice conditioning lands (VOICES-02, VOICES-04 in Home's backlog).

The reference clip is the owner's own recording and never goes into git or a release. A household makes its robot voice the
same way, through VOICES-04 (an admin creates a voice from any clip).

## How we chose it

All candidates were played on the unit's speaker through the bench service, never the Mac speaker.

| Round | Candidates | Result |
|---|---|---|
| 1 | Mac system voice with pitch, formant and shimmer effects | Rejected: the robot never speaks a Mac voice |
| 2 | Hub default Chatterbox voice, plain and with effects | Rejected: "different voice" |
| 3 | Six CC0 donated voices cloned in Chatterbox | Rejected: none sound like the stock robot |
| 4 | Clone of the stock firmware's playful English voice, 10 s reference | Right voice, flat inflection |
| 5 | Same, 27 s reference (three takes joined) | Lost the original's sound |
| 6 | 10 s reference, playful wording, temperature 0.8 / 1.05 / 1.05 plus `[chuckle]` | Last two picked: voice and bounce kept |

## What we learned

1. Turbo ignores `exaggeration` and `cfg_weight`. Inflection comes from the reference clip, the words and the temperature.
2. A longer reference is not better: joining three takes of the same phrase moved the timbre away from the original.
3. Wording carries most of the bounce. The robot persona's prompt asks for short, exclamatory, question-ending lines.
4. Effects on top of a voice do not make it a different voice; Jesse heard every effect round as "the same voice".

## A second voice: the clone ran high

A second household voice was cloned the same way from a 12 s clip, played from a phone into the MacBook mic.

| Round | Candidates | Result |
|---|---|---|
| 1 | 12 s reference, temperature 0.8 and 1.05 | "Higher pitch": measured 385 Hz against the clip's 348 Hz, about 2 semitones up |
| 2 | 25 s reference; round 1's 1.05 take shifted down 2 semitones (formants kept) | Shifted take close, "a little too low" |
| 3 | 1.05 take shifted down 1 semitone; temperature 1.25 takes shifted down 1 | The 1.05 take at -1 semitone picked |

1. A clone can land 1 to 2 semitones off its reference. A voice record needs an optional pitch offset in semitones, applied
   after generation with formants kept, set by ear.
2. Raising the temperature to 1.25 raised the pitch too; 1.05 is the ceiling for liveliness without drift.
3. Autocorrelation pitch reading is unreliable on lively takes (octave jumps); judge by ear on the robot.

## Open

- VOICES-02 (per-voice conditioning in the Stack) and VOICES-04 (create a voice from a clip) are Home's; until they land the
  robot speaks the hub default.
- The persona wording rule belongs with the robot persona in Home, not in the bot.
