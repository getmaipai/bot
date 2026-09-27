# Reachy Mini: what leaves your robot, and how to turn it off

This page is about the robot itself, straight from Pollen Robotics
(the company that makes it), before MaiPai ever gets involved. Some of
this MaiPai turns off automatically when it sets your robot up; some
of it you can turn off yourself right now. Every fact on this page was
checked directly, either by reading Pollen's own daemon software or by
running it and watching what it actually does.

## The short version

Out of the box, the robot can quietly connect out to the internet in a
few ways. None of it is hidden or malicious, but none of it is asked
about either. The two that matter most:

1. **Remote access to your robot from anywhere**, through a Pollen
   Robotics server, turns on automatically the moment your computer is
   signed in to a Hugging Face account. If you have never signed in to
   Hugging Face, this never turns on. MaiPai's own setup never signs
   in, on purpose.
2. **Your computer's own microphone gets used as a stand-in** when the
   robot software cannot find real Reachy Mini audio hardware (this
   happens on the simulator, and would happen on a Lite plugged into
   your own computer). Nothing reads that microphone unless something
   asks it to, but the software opens it anyway.

## What actually connects out, and why

| What | Where it goes | When it happens | How to stop it |
|---|---|---|---|
| Remote access (so you or Pollen's own conversation app could reach the robot from outside your house) | `pollen-robotics-reachy-mini-central.hf.space`, a Pollen-run address on Hugging Face | Only if a Hugging Face account is signed in on the machine running the robot software | Never sign in to Hugging Face on the robot. Or start the software with `--no-media`, which turns off all of the robot's network media features at once. |
| The video/voice connection itself, once remote access is on | Cloudflare's `turn.cloudflare.com` servers, used to get audio and video through home networks and firewalls | Every time the software starts, as setup for the remote access above | Same as above: no Hugging Face sign-in, or `--no-media`. |
| Browsing for other apps to install | `huggingface.co`'s own app-listing page | Only when someone actually opens the "browse apps" screen | Don't open it. MaiPai's own software never does. |
| Checking for new recorded moves (the built-in dances and expressions) | Hugging Face's dataset hosting | Automatically every 24 hours by default | Start the software with `--no-preload-datasets`, or `--dataset-update-interval 0`. |
| Your computer's own microphone | Nowhere by itself - this is a local fallback, not a network connection | Whenever the software can't find real Reachy Mini audio hardware | Nothing to turn off; nothing reads the microphone unless another feature explicitly asks it to. Worth knowing about, not something to panic over. |

## What MaiPai does about this for you

Once MaiPai sets up your robot (a step that is not built yet as of this
writing), it:

- **Never signs in to Hugging Face.** MaiPai installs your robot's
  software over a direct connection from your own hub, not through
  Hugging Face's store, so there is never an account to sign in with in
  the first place, and the remote-access feature above never turns on.
- **Changes the robot's starting password.** Every Reachy Mini ships
  with the same published password for its own computer. MaiPai
  changes it to a random one the moment your robot is paired, and never
  shows or writes down the old one anywhere.
- **Never installs Pollen's own conversation app** or any other app
  from their store unless you specifically ask for one.

## What this page cannot promise yet

MaiPai's own privacy page for this robot, built into the app itself,
does not exist yet. This document is the honest stand-in until it does.
Two things it will need that this page cannot give you: a real capture
of every connection the robot makes over a full day (planned as
`RM-07` in the project's backlog), and confirmation of these facts
against a physical unit rather than only the software simulator (the
real robot has not arrived yet as of this writing).
