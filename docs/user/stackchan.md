# Your StackChan

StackChan is a small desk robot with a screen for a face, a head that turns and nods, a camera, a microphone and a speaker. With MaiPai's firmware it works as your home assistant. It answers by voice, shows how it feels on its face, and keeps everything on your own network.

<!-- picture: a photo of the StackChan on a desk, front view, screen on -->

This guide is for the people who live with the robot. To install it, see [Set up a StackChan](stackchan-setup.md). Home's own screens for the robot are in Home's Robots guide.

## Why the MaiPai firmware

The robot ships with the maker's own software, which sends voice and pictures to the maker's cloud. MaiPai's firmware replaces it.

- **Nothing leaves your home.** Voice, pictures and replies stay on your network and go only to your Home computer. The robot has no vendor server addresses built in.
- **It answers with your Home.** The same assistant, memory, voices and companions you use in the app speak through the robot.
- **You control it.** Admins set its companion, voice, camera and night behavior in Home. Updates are signed and installed from Home in one step, and Home can save a backup first.
- **It shows its senses.** The ring light tells you when sound or a picture is in use, and no setting can hide that.
- **You can read it.** The firmware changes are small, public patches on top of the maker's open source code.

## Wake it up

Say **"Hi, StackChan"**, or tap its face. The ring turns blue while it listens. Talk normally and pause when you are done.

You can ask it anything you would ask Home: questions, timers, the weather, reminders, jokes. It answers aloud and keeps the answer short.

<!-- picture: the face while listening, with the blue ring -->

## What the lights and faces mean

The ring is dark most of the time. It lights only when it needs you or when it is listening or taking a picture.

| You see | It means |
|---|---|
| Blue ring, steady | It is your turn: it is listening to you |
| Green ring | Your voice is being sent to your Home to be understood |
| Pink flashes, then steady pink | The camera is taking a picture |
| Cyan ring, slow pulse | It needs you: setup or pairing is waiting for a person |
| Amber ring, one short pulse every 10 seconds | Look at the screen: Home is not reachable, something is wrong, or the battery is low (not shown at night) |
| No ring | Everything else: waiting, thinking, speaking, charging, sleeping, night |

Thinking and speaking show on the face and in the voice, never on the ring. While it charges, the small red light on the back is on and the screen shows the battery.

The ring is never red. A calm face is the normal look. A smile or a wink shows when it is happy. A surprised face shows when it is shaken or lifted. A small heart shows only when you pet its head, say something kind to it, or show it something sweet.

<!-- picture: the faces side by side: calm, happy, surprised, wink, sleepy, heart -->

## Touch

- **Tap the face** to start listening. Tap it again while it listens or talks to make it stop.
- **Pet its head** and it reacts. The heart goes away after a few seconds.
- **Shake it or lift it** and it makes a surprised face and says something short.
- **Swipe up from the face** for quick settings: volume and brightness sliders.

<!-- picture: the quick settings sliders on the screen -->

## Things you can say

| Say | It does |
|---|---|
| "Louder", "quieter", "set your volume to 60" | Changes the volume |
| "Brightness to 50", "make it dimmer" | Changes the screen brightness |
| "Look left", "look up a little", "look around", "look at me" | Moves its head |
| "Nod", "shake your head" | Nods or shakes |
| "Dance", "do a dance", "can you dance", "dance for me" | Does its little dance |
| "Can you see me?" | Tells you if it sees a face right now |
| "What are you looking at?" | Tells you why its head is where it is |
| "Stop", "be quiet", "never mind", "that's enough" | Stops and goes idle |
| "Say that again", "what did you say", "repeat that", "come again", "pardon" | Plays its last answer again, word for word |
| "Say that louder" | Plays its last answer again, one volume step louder for that play |
| "What did I miss?", "Did I miss anything?" | Tells you what it could not say in time, then forgets it |

A stop only counts when the whole sentence is the stop word. "Stop the presses" and "she ran through a stop sign" are ordinary sentences and go to your Home as usual. While it is talking, say "Hi, StackChan" to interrupt it.

Left and right are the robot's own left and right.

## The little dance

It lasts about 12 seconds: the head sways and turns, the face changes between happy, a wink and surprised, and the light ring shows gold, lime and mint colours. Ask by voice, or use the Dance button in Settings (the robot's page).

- It ends at once if you touch it, speak to it, shake or tilt it, or take a picture with it. Then the face and the ring go back to normal.
- It does not dance while its battery is at 20 percent or lower (it can while charging), while it is offline, or if you turned dancing off.
- It rests for a minute between dances.
- At night, if you ask, it dances with its head and face only: no lights, no sound.
- Settings: **Dance** (on by default) and **Dance light show** (on by default) are in the robot's settings.

## Dancing to music (off until you turn it on)

With **Dance to music** on in the robot's settings, StackChan listens for clear music with a steady beat. After about five seconds it nods twice and smiles or winks. If the song goes on for about twenty more seconds it sways for about ten seconds, then dances for up to twenty with the light ring. It stops a few seconds after the music stops, or at once if you touch it, talk to it, shake it or take a picture.

- It only sends a few numbers about the sound to the hub, never the sound itself, and only when the room is loud.
- It does nothing at night, while asleep, while it listens or talks, or in quiet mode. It waits at least 10 minutes between dances, at most 3 an hour and 10 a day.
- On battery it dances at 40 percent or more, only nods from 20 to 39 percent, and does nothing under 20 percent. Plugged in, the battery level does not matter.
- Talk and TV usually do not count, but a TV theme tune sometimes does. If it nods at the wrong things, set the sensitivity to low.

### Repeating and what you missed

The robot keeps its last five answers, as sound, in its memory only. Nothing is saved to a disk and everything is gone when it restarts. "Say that again" plays the last answer exactly as it was said; it does not ask Home, so it also works when Home is away. Only short asks count: "what did you say about dinner yesterday" goes to Home like any other question. A second "say that again" plays the same answer again. If it has not said anything yet, it says so. It plays back only what it said in the same connection, and it will not play an answer it gave to a different person it recognizes. "Slower" plays the same sound; it does not say it again more slowly.

When a timer, alarm or announcement comes while it is muted, in quiet hours or full quiet, or while nobody is in front of it, the robot keeps a short note for 24 hours (the last 20, in memory only). Ask "what did I miss" and it reads them in one sentence ("While you were away: dinner is ready at 6:02 and your timer finished at 6:10."), then clears them. While muted it stays silent and keeps the notes. Turn this off with the setting "Repeat and missed" (robot.repeat.enabled); the questions then go to Home and nothing is kept.

## Day and night

At night the robot dims its screen, plays quieter and keeps still. Night starts in quiet hours, 9 pm to 7 am by default, and also when the room is dark for a couple of minutes. It goes back to day when the room is bright again or quiet hours end. Your normal volume and brightness come back exactly as you set them.

## The camera and your privacy

- **It watches for faces on the robot itself.** It uses a small program that finds a face and where it is. It keeps a number, not a picture. This lets it wake when you walk up, turn toward you when you talk, and say hello.
- **Nothing is saved or sent away.** Pictures are checked and thrown away. They never go to the maker or the internet.
- **You can turn it off.** An admin sets the robot's camera watch level to **off** in Settings, Home, Devices.
- **The pink flash** tells you when a picture is taken that you should know about.

## Companions and voice

An admin picks a companion for the robot in Settings, Home, Devices. The companion sets how it talks: bubbly and curious, plain and short, or something else. The robot's controls (child, teen or adult) decide what it may say. The robot speaks in Home's default voice unless an admin picks another voice for it.

## If something is wrong

- **It does not wake up.** Check that the ring is not amber. Say "Hi, StackChan" clearly from about a meter away, or tap the face.
- **It will not connect.** The robot and the Home computer must be on the same Wi-Fi. Power the robot off and on.
- **The face looks dark in the daytime.** Night mode may think the room is dark. Wait two minutes in a bright room. If it stays dark, tell an admin.
- **It keeps moving its head.** Update Home. Idle motion is off by default.
- **A swipe starts it listening.** A swipe that begins at the very top edge can read as a tap. Start the swipe a little lower on the screen. A firmware update fixes this.

The robot cannot be stopped from software alone. To stop its motors, use its power switch.
