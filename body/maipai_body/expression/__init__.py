"""The expression package: the primitive vocabulary, rendered on a body's HAL seam.

``dev.md`` section 5 names this a catalog package under ``packages/``
(``platforms: [bot]``, category "Robot body"), consumed by the household
runtime once it exists. No runtime, package host, or engine exists in
this repo yet (``docs/BACKLOG.md``'s RT-00 through RT-06 are unstarted,
gated on hub work this repo waits on), so this package lives in
``body/`` instead: the same reasoning AGENTS.md already gives for
running the household runtime on Bun applies here in reverse, since
this code directly drives the seam's actuator, not household records.
It moves under ``packages/`` the day a runtime can host it; nothing
about its own design changes when it does.

Importing this package registers every body's own renderer
(``renderers.register_renderer``) so ``ExpressionEngine`` can look one
up by profile id without hardcoding a single body's module.
"""

from . import reachy_mini_renderer as _reachy_mini_renderer  # noqa: F401  (registers "reachy_mini")
