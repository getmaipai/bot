<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/getmaipai/.github/main/brand/maipai-bot-logo-dark.png">
    <img src="https://raw.githubusercontent.com/getmaipai/.github/main/brand/maipai-bot-logo-light.png" alt="MaiPai Bot" width="360">
  </picture>
</p>

<h3 align="center">A robot friend with its own onboard AI.</h3>

<p align="center">Documentation</p>

[StackChan setup](docs/user/stackchan-setup.md) · [StackChan service for developers](docs/dev/stackchan-service.md)

It sees, hears, talks, thinks, moves, self-charges, and guards your home
in sentry mode. It recognizes each person by face and voice, keeps its own
memories of people, facts, and experiences, and learns and evolves with
your family.

## Status

Fresh rebuild in progress. This repo was reset to a clean history on
2026-09-03 to start over on the platform design (see
[docs/dev.md](docs/dev.md)). As of v0.1.0, Reachy Mini moves, expresses
itself, tracks a face, captures and plays audio, and listens for its
own wake word ("hey maipai") - not yet a complete conversational robot;
see [docs/BACKLOG.md](docs/BACKLOG.md) for what's still missing. The
prior version was bench-proven on real hardware and is preserved
locally as a reference, never as a requirement of what gets rebuilt.

MaiPai Bot runs on more than one body. The MaiPai build (the robot in
the build guide) is in build; Reachy Mini by Pollen Robotics
([docs/dev/design-reachy-mini-2026-09-27.md](docs/dev/design-reachy-mini-2026-09-27.md))
is in build too, behind the same HAL seam, and neither is supported
until every row of that design's section 13 is true.

## Development

See [docs/dev.md](docs/dev.md) for the design record and
[docs/BACKLOG.md](docs/BACKLOG.md) for what's built and what's missing. `scripts/check.sh` runs the pinned `@maipai/standards`
core; it needs a sibling checkout of `getmaipai/.github`.

### StackChan firmware toolchain (macOS, Apple silicon)

Building the StackChan firmware (design: [docs/dev/design-stackchan-firmware-build-2026-10-14.md](docs/dev/design-stackchan-firmware-build-2026-10-14.md))
needs ESP-IDF 5.5.4. ESP-IDF 6.x does not build M5's tree. This machine uses a local install, not Docker. Tested 2026-10-14 on macOS 27, arm64;
a stock `hello_world` built for the ESP32-S3 with it.

Install, one command per line:

```bash
brew install ninja ccache dfu-util python@3.12 cmake
```

```bash
mkdir -p ~/esp
```

```bash
git clone --depth 1 --branch v5.5.4 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git ~/esp/esp-idf
```

```bash
PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH" ~/esp/esp-idf/install.sh esp32s3
```

Python 3.12 is used on purpose: the system Python is 3.14, newer than ESP-IDF 5.5 supports. The install is about 0.7 GB of source
plus 3.9 GB of tools in `~/.espressif`.

Use it in each new shell (the install does not change your shell profile):

```bash
export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"
```

```bash
. ~/esp/esp-idf/export.sh
```

Check: `idf.py --version` prints `ESP-IDF v5.5.4`. Flashing a unit later needs the head USB-C port; see the build design note, section 8.
To remove it all: delete `~/esp` and `~/.espressif`.

---

MaiPai is open-source software for personal, self-hosted, non-commercial
use by you and your household. It is not affiliated with, endorsed by, or
sponsored by any platform it can connect to. All product names and
trademarks belong to their respective owners. You are responsible for
complying with the terms and laws that apply to you and the services you
access.

The AI in this product runs on third-party models you choose to
download. What they say can be wrong, offensive, or harmful; it is not
medical, legal, or professional advice; and you are responsible for
how you use it. Parents decide what children in the household can
reach.

Licensed under [AGPL-3.0](LICENSE).
