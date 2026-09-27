<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/getmaipai/.github/main/brand/maipai-bot-logo-dark.png">
    <img src="https://raw.githubusercontent.com/getmaipai/.github/main/brand/maipai-bot-logo-light.png" alt="MaiPai Bot" width="360">
  </picture>
</p>

<h3 align="center">A robot friend with its own onboard AI.</h3>

<p align="center">Documentation</p>

It sees, hears, talks, thinks, moves, self-charges, and guards your home
in sentry mode. It recognizes each person by face and voice, keeps its own
memories of people, facts, and experiences, and learns and evolves with
your family.

## Status

Fresh rebuild in progress. This repo was reset to a clean history on
2026-09-03 to start over on the platform design (see
[docs/dev.md](docs/dev.md)); nothing runs yet. The prior version was
bench-proven on real hardware and is preserved locally as a reference,
never as a requirement of what gets rebuilt.

MaiPai Bot runs on more than one body. The MaiPai build (the robot in
the build guide) is in build; Reachy Mini by Pollen Robotics is in
design ([docs/dev/design-reachy-mini-2026-09-27.md](docs/dev/design-reachy-mini-2026-09-27.md)),
and neither is supported until every row of that design's section 13
is true.

## Development

See [docs/dev.md](docs/dev.md) for the design record and
[docs/BACKLOG.md](docs/BACKLOG.md) for what's built and what's missing. `scripts/check.sh` runs the pinned `@maipai/standards`
core; it needs a sibling checkout of `getmaipai/.github`.

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
