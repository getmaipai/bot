# Home and owner checks for Bot 0.2.71 (2026-11-13)

This note records the Home contract for StackChan batch 4. Home settings are requests; the unit's privacy read-back is authoritative. Until the unit reports, check-in facts are null.

## Home settings

| Key | Type | Default | Scope / behavior |
|---|---|---|---|
| `robot.muted` | boolean | false | Robot scope. Requests the unit's hard microphone mute. Show Muted only after the unit reports `muted=true` and `mic_off_verified=true`. |
| `robot.vision_off` | boolean | false | Robot scope. Stops camera capture and analysis. |
| `robot.quiet` | boolean | false | Robot scope. Full quiet: no listening, sound output, or movement. |
| `mute.local_unmute` | boolean | true | Robot scope. When false, the face can mute but cannot unmute or leave full quiet; Home can. |
| `robot.sounds.enabled` | boolean | true | Device scope. Enables ordinary unit sounds. |
| `robot.sounds.night` | boolean | false | Device scope. Allows sounds during night hours. Privacy and safety cues retain their policy exceptions. |

Mirror mute, vision-off and quiet toggles from the unit's check-in state, including changes made on the face. While a Home mute request awaits confirmation, show “Asking the robot”; on failure show “The robot has not confirmed.” Do not set `deviceStates.muted` until the mute command returns `status == "confirmed"`.

## Commands

- `mute {}` requests a hard mute. Treat the response as confirmed only when its `status` is `confirmed` and `mic_off_verified` is true.
- `unmute {"confirm": true}` requires an explicit admin confirmation in Home. Without it, the unit returns `{"status":"needs_confirm"}` and makes no change. A confirmed response also includes the mute state and microphone verification.
- `sound_test {}` starts a background playback of the twelve fixed sounds and answers immediately with `{"sound_test":"started","sounds":[...]}` or a refusal such as `{"sound_test":"refused","why":"muted"}`. Add a “Test the sounds” button to Settings → Lights and Sounds.

The sounds page exposes `robot.sounds.enabled` (“Sounds from the robot”) and `robot.sounds.night` (“Sounds at night too”). Mute and full quiet silence all sounds. `sound_test` bypasses the ordinary off and night filters for diagnosis, but never bypasses mute.

## Owner test list (after flashing the unit)

1. Test face mute and unmute holds, quick mouth taps, the 400–500 ms dead band, drags that move more than 10 px, drags that return to the start, and gestures begun in edge margins. Drags must not toggle a state; swipes for settings, volume and stop must still work.
2. Test eye taps toggle vision off and on, and forehead holds toggle full quiet without changing vision. Check combined states and that each state survives a power cycle.
3. Test the power button with USB attached and again on battery: short press, hold through power-off, and release after the visual blank but before the PMIC cut. Confirm ring and face behavior and note whether USB causes a restart.
4. Run Home's “Test the sounds” button and the `sound_test` command. Confirm all twelve sounds, mute refusal, and the night policy.
5. With Home unavailable, test the offline phrases: no Wi-Fi, connecting, no host, refused approval, and return after an outage. Confirm rate limits, no repeated adjacent phrase, tone-only behavior at night or with sounds disabled, and silence while muted.
6. Verify mute on the unit: wake word and speech do nothing; Home reports “Muted” only after the unit confirms microphone register read-back. Verify remote unmute asks an admin to confirm and a confirmed unmute restores listening.
