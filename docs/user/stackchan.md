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

| You see | It means |
|---|---|
| Blue ring, steady | It is listening to you |
| Green ring | Sound is being sent to your Home to be understood |
| Purple ring, slow breathing | It is thinking |
| White ring | It is speaking |
| Dim white ring | Awake and waiting |
| Pink flashes | The camera took a picture |
| Amber ring | Something needs attention, for example the Home computer is not reachable |

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
| "Can you see me?" | Tells you if it sees a face right now |
| "What are you looking at?" | Tells you why its head is where it is |
| "Stop", "be quiet", "never mind", "that's enough" | Stops and goes idle |

A stop only counts when the whole sentence is the stop word. "Stop the presses" and "she ran through a stop sign" are ordinary sentences and go to your Home as usual. While it is talking, say "Hi, StackChan" to interrupt it.

Left and right are the robot's own left and right.

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
