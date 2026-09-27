# Research note: MiniCPM5-1B and Reachy Mini Wireless (2026-09-27)

A quick read of two outside parts against the robot design in
[`../dev.md`](../dev.md) and the Stack's role pins
(`stack/docs/components.md`). Neither is a decision. Each ends with
where it would fit, what blocks it, and the one cheap check that
settles it. Facts come from the vendors' own pages on the date above;
anything not verified is marked so.

## MiniCPM5-1B (OpenBMB)

**What it is.** A dense 1.08 B parameter causal language model
(679.6 M non-embedding) on the plain Llama architecture: 24 layers,
16 query heads, 2 key-value heads. Context 131,072 tokens. Apache-2.0.
Released 2026-05-19; a 2 B sibling on the same recipe followed on
2026-09-07. Post-trained with SFT, RL and on-policy distillation.
English and Chinese are the languages the card names. Two modes in one
chat template, toggled with `enable_thinking` (the same switch Qwen3
uses, so the robot's standing `enable_thinking: false` rule applies as
is). Tool calls are XML-style; the vendor's parser ships for SGLang,
and llama.cpp tool-call parsing for this format is not documented.
Official artifacts: GGUF (Q4_K_M 688 MB, Q8_0 1.15 GB, F16 2.17 GB),
an MLX 4-bit build for Apple silicon, and Ollama and LM Studio
listings. The card's claim is "1B-class open-source SOTA" against
Qwen3-0.6B, Qwen3.5-0.8B and LFM2.5-1.2B-Thinking, strongest on tool
use, code and reasoning; the numeric table was not in the page text
fetched, so the claim is the vendor's, unmeasured here. The vendor's
llama.cpp notes: `-c 8192`, and `min_p` at 0 to stop repetition.

**Where it would fit.**

1. *The robot's own chat model (M-02).* Section 4 of the design names
   Qwen3-1.7B then Qwen3-4B as the candidates for llama-server on the
   Pi's CPU. The legacy bench sits exactly around this size: Qwen3-0.6B
   was fast (1.05 s) but 79 percent guarded, Qwen3-1.7B was 95 percent
   guarded. A 1.08 B model with two key-value heads has a KV cache a
   fraction of the 1.7B's, so its first-delta latency should land
   between the two; whether its guarded score does is the whole
   question, and only M-02's harness answers it. This note adds it as
   the third candidate under M-02's unchanged decision rule (largest
   model whose first delta p95 is under 2.5 s with the prefix cached
   and whose hard rows are green).
2. *The Stack's `router` and `judge` roles on the p16 tier.* Both pin
   Qwen3-1.7B Q8_0 (1.71 GB) today; MiniCPM5-1B Q8_0 is 1.15 GB. The
   judge's default is the 4B by MEM-05's eval, so the judge is not a
   swap candidate; the router shares chat's model unless sized
   otherwise, and a smaller resident router on a 16 GB machine is a
   real saving. Same rule: a candidate on the Stack's candidate list,
   never a pin change without the role's readiness bench.
3. *Not the hub's chat model.* Nothing in the card argues a 1 B model
   replaces the hub's chat role on any tier.

**What blocks it.** The tool-call format. Home's turn engine drives
OpenAI-shape tool calls through llama-server (ENGINE-CONTRACT-02's
verify-and-fallback exists because even `tool_choice: required` is
advisory there). If llama-server cannot parse this model's XML calls
into OpenAI tool calls, the model is a plain-chat candidate only, and
on the robot every turn with a tool would fall back. That is the first
thing to check, before any latency run. Second, the languages: English
and Chinese named, nothing else, which matters the day i18n is more
than a standard.

**The cheap check.** One llama-server run of the Q4_K_M on the bench
Pi with the hub's rendered prompt and one tool in the set, confirming
a parsed `tool_calls` array comes back; then the existing M-02 harness
with a third column. No new harness, no new fixture.

## Reachy Mini Wireless (Pollen Robotics, sold through Hugging Face)

**What it is.** A desk-sized expressive robot sold as a kit (two to
three hours of assembly, no printing or soldering). 30 by 20 by
15.5 cm extended, 1.475 kg. Wireless €435 (US $499); the Lite, which
runs its daemon on a tethered computer over USB and has no battery or
compute, US $399. Lead time up to 90 days, import duties at checkout.

| Part | Wireless |
|---|---|
| Compute | Raspberry Pi Compute Module 4, CM4104016: 4 GB RAM, 16 GB eMMC, dual-band Wi-Fi |
| Motors | Nine Dynamixel: six XL330-M288-T on a Stewart platform (head, 6 DoF: roll, pitch, yaw, x, y, z), one XC330-M288 for body yaw (±160°), two XL330-M077 antennas |
| Head limits | pitch and roll ±40°, head yaw ±180°, at most 65° between head and body yaw; the SDK clamps |
| Camera | Raspberry Pi Camera Module 3 wide, IMX708, 12 MP, 120°, autofocus |
| Microphones | four PDM MEMS mics on a board built on Seeed's reSpeaker XMOS XVF3800, 16 kHz |
| Speaker | 5 W at 4 Ω |
| IMU | accelerometer (Wireless only) |
| Battery | LiFePO4 2,000 mAh, 6.4 V, 12.8 Wh, with protection; runtime not stated |
| Ports | one USB-C out (does not charge through it) |
| Licences | SDK and daemon Apache-2.0; hardware design files CC BY-SA-NC |

**Software.** Client-server. A daemon on the robot (on the CM4 for
Wireless, on the tethered computer for Lite) owns the serial bus, the
safety clamps and the sensors and serves REST plus WebSocket on port
8000 (`/docs`, `/api/state/full`, `/api/state/ws/full`); media goes
over WebRTC. Clients are a Python SDK (`goto_target`, `set_target`,
`look_at_world`, motor stiff, limp and gravity-compensation modes), a
JavaScript SDK for browser apps, and a MuJoCo simulation with no
hardware. Apps are Hugging Face Spaces installed with one click from
the robot's control page; the reference conversation app chains VAD, an
LLM and TTS. A `no_media` backend hands the camera and microphones to
your own pipeline directly. Whether the OS image phones home, and what
the app store and the conversation app send off the robot, is not
verified here.

**Where it would fit.** This is the closest off-the-shelf match to the
design's expression layer (section 5) that has come up. Every
primitive the design defines (listen, glance, tilt, nod, perk, attend,
settle, breathe, track, stop) maps onto the Stewart-platform head and
the antennas, and the design's stated compromise that "there is no roll
axis, so the curious tilt is pitch and eyes" goes away: this head has
roll. The microphone board is the same XMOS XVF3800 family the robot's
own ears use (section 6's direction-of-arrival and AEC behaviour
transfers). And org principle 6, prebuilt over hand-built, argues for a
maintained head over the pan-tilt kit the build record still lists
with open questions (2, 3 and 10).

The body contract already has a place for it: section 5's robot
package (`platforms: [bot]`, category "Robot body") is the layer that
would drive the daemon at port 8000, submitting typed observations
upward and receiving expression cues, with the Python body owning
nothing the daemon already owns. Two shapes:

1. *Lite tethered to the Studio as the hub's face.* The daemon runs on
   the hub machine, every engine is the hub's, and the robot is a USB
   peripheral: the expression primitives proven on real servos for
   US $399 with no drive, no e-stop chain, no second compute, before
   the robot's own head is built. Placement is limited to the hub's
   desk by the cable. This is the cheap proof and fits "hub first".
2. *Wireless as a connected-mode robot.* Mode 1 of section 1 (the hub
   runs the turn, the robot does wake, endpointing, speech to text,
   speaker evidence, expression and playback) is realistic on a CM4.
   Mode 2 (paired, unreachable) and mode 3 (never paired) are not,
   which is the block below.

**What blocks it.**

- *Principle 2, the robot is complete without a hub.* The design's
  standalone mode wants llama-server, the judge, the embed model,
  sherpa-onnx speech and vision on a 16 GB Pi 5 with a Hailo-10H. A
  4 GB CM4 on a Cortex-A72 cannot hold that set, and its CPU is two to
  three times slower than the Pi 5's for the same model. The one model
  in this note that fits a 4 GB CM4 beside speech is MiniCPM5-1B at
  Q4_K_M (688 MB), which is why the two parts are researched together:
  a Reachy Mini could only be complete without a hub on a model of
  that class, at a latency the bench has not measured, with no vision
  model resident. Honest reading: Reachy Mini is a hub-attached
  companion pod, not the MaiPai Bot, whose drive base, e-stop chain,
  16 GB Pi and accelerator exist for the standalone and moving cases.
- *Hardware licence.* CC BY-SA-NC covers the design files: MaiPai can
  use, modify and document a purchased unit and ship software for it,
  but cannot sell a derived body. The SDK's Apache-2.0 is fine beside
  AGPL.
- *Privacy.* A Wi-Fi robot with a hosted app store and an LLM demo
  app. A MaiPai package never installs the store's apps, and the OS
  image's outbound connections need the PRIVACY.md read before the
  robot joins the household network. Unverified.
- *Battery runtime and the daemon's replaceability on the Wireless
  image.* Neither is stated; both matter for shape 2 only.

**The cheap check.** Shape 1: the Lite, the daemon on the Studio, and
the section 5 primitives scripted through the Python SDK against the
MuJoCo simulation first (free, no hardware, today) and then the unit.
The simulation alone tells us whether the primitives' timing envelopes
(section 10) are expressible in `goto_target` durations before a
purchase. The purchase, and which shape, is the owner's call.

## Sources

- https://huggingface.co/openbmb/MiniCPM5-1B and `-GGUF`, `-MLX`
- https://github.com/OpenBMB/MiniCPM
- https://store.pollen-robotics.com/products/reachy-mini-wireless-version
- https://pollen-robotics.com/reachy-mini/
- https://huggingface.co/docs/reachy_mini (index, hardware datasheet,
  core concepts, integrations)
- https://github.com/pollen-robotics/reachy_mini
