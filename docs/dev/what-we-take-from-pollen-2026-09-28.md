# What we take from Pollen's SDK mechanisms (2026-09-28)

Jesse asked directly: "what can we take from the reachy mini (the way
they load apps, skills, expression, etc) and bring to our bots." Section
11 of [`design-reachy-mini-2026-09-27.md`](design-reachy-mini-2026-09-27.md)
already answers this for the store's *content* (which third-party apps
do, and MaiPai's product verdict on each). This doc answers the
different, narrower question: which of Pollen's own SDK *mechanisms* -
how their code loads an app, represents a move, scaffolds a new project -
are worth adopting into `maipai_body`, independent of any app content.
Every claim below is read from the installed `reachy-mini` 1.11.0
package at `body/.venv/lib/python3.12/site-packages/reachy_mini/`, not
assumed.

## 1. The Move abstraction and the recorded-move JSON format - adopt as-is

**What Pollen does.** `motion/move.py`: `Move` is a two-method ABC -
`duration -> float` and `evaluate(t) -> (head_4x4_matrix, antennas_rad,
body_yaw)`, called at high frequency (their own docstring says ~100 Hz).
`motion/recorded_move.py`'s `RecordedMove(Move)` reads a move as one JSON
object: `{"description": str, "time": [float, ...], "set_target_data":
[{"head": [[...]], "antennas": [...], "body_yaw": float}, ...]}`, with an
even fixed `dt` derived from the timestamp array, and does its own
head-pose interpolation (`linear_pose_interpolation`) plus a plain
`lerp` for antennas and body yaw between the two bracketing samples
(`recorded_move.py:110-165`). `RecordedMoves` (plural) loads a whole
library from a downloaded HuggingFace dataset directory: every `*.json`
file (also checked under a `data/` subdirectory for newer datasets) is
one named move, with an optional same-stem sidecar sound file resolved
against a fixed extension list (`recorded_move.py:201-222`).

**Do we have this?** No. `body/maipai_body/expression/` has primitives
(`listen`, `nod`, `settle`, …) rendered procedurally from fractions of
the profile's axis limits - there is no way today to store or replay an
arbitrary recorded trajectory. MOVES-01/MOVES-02 in the design record's
section 11 table already anticipate needing exactly this, but neither
is built.

**Verdict: adopt as-is, not adapt.** The format is minimal, body-agnostic
(a 4x4 head pose plus antenna joints plus one yaw float has no vendor
concept baked in beyond "this body has a head, antennas, and a yaw
axis" - which our own `HeadPose`/`AntennaPositions` types already are),
and solves exactly the interpolation problem MOVES-02 needs (a
hand-taught trajectory replayed smoothly). Re-inventing an interpolation
scheme here would be precisely the hand-built-instead-of-prebuilt
mistake principle 6 warns against - this is a solved problem with a
working reference implementation sitting in a package we already
depend on.

**Where it lands.** A new `body/maipai_body/expression/recorded_move.py`:
port `Move`/`RecordedMove`'s shape (not vendor the file - CLAUDE.md's
"download, don't vendor" rule; a small reimplementation against the
seam's own `HeadPose`/`AntennaPositions` types, MIT-equivalent logic,
short enough that a licensed dependency isn't warranted, credited in a
comment) as MOVES-01's own primitive registration:
`register_renderer`-style entry so a recorded move plays through the
exact same `ExpressionEngine.handle()`/`set_muted()` path every other
primitive does, gated by the same arbitration and render lock. The JSON
shape itself is worth keeping byte-compatible with Pollen's own
`{description, time, set_target_data}` fields specifically because
MOVES-01's objective (section 11's table) is to *fetch the existing
Apache-2.0 emotions and dances libraries*, not author a new format for
data that already exists in this one.

## 2. Entry-point-based app loading (`reachy_mini_apps` group) - already adopted, keep as the only mechanism

**What Pollen does.** `apps/manager.py`'s `AppManager` treats an
installed app as one `importlib.metadata.entry_points(group=
"reachy_mini_apps")` entry (confirmed at `apps/sources/
local_common_venv.py:307`, `:716`, `:726` - already cited in RM-03's own
verification). No registry file, no manifest on disk beyond the
entry-point's own `pyproject.toml` stanza; `AppInfo.extra: Dict[str,
Any]` exists as a free-form field but grep across the whole `apps/`
package shows zero writers or readers of it (`extra[...]` appears
nowhere) - it is not a capability channel, just an unused generic slot.

**Do we have this?** Yes, already: `body/pyproject.toml`'s own
`[project.entry-points."reachy_mini_apps"] maipai_bot = "maipai_body.app:
MaiPaiBody"` (RM-01/RM-03) uses Pollen's own loading mechanism directly,
because the daemon *is* what runs the app - there was never a choice to
make here, and none is needed for a second body profile either, since a
non-Reachy body wouldn't run under this daemon's app-loading mechanism
at all.

**Verdict: already adopted (for this body specifically), no further
action.** Worth naming so it's not "discovered" again later as a gap:
Pollen's own `AppInfo.extra` being genuinely empty confirms MaiPai's
catalog manifest (declared capability ids, `data_sources`, permissions)
is *more* than what Pollen's own entry-point mechanism carries, not
less - there is nothing granular to borrow from their side for
capability declaration, because they don't have one beyond a free-text
description shown in their app-store listing.

## 3. `bg_job_register`'s async job pattern - adopt for any slow daemon-side action, not just app installs

**What Pollen does.** `daemon/app/bg_job_register.py`: a `JobStatus` enum
(`pending | in_progress | done | failed`), a `JobInfo` pydantic model
(`command`, `status`, `logs: list[str]`), a plain in-process `dict[str,
JobHandler]` registry, `run_command(command, coro_func, *args)` starting
a background task and returning a job id, `GET /job-status/{id}` to
poll, and a WebSocket (`/ws/apps-manager/{job_id}`) that streams new log
lines as they arrive rather than only final status. Already the exact
mechanism `scripts/install-reachy.sh`'s vendor-app-removal step polls
against (`/api/apps/remove/{name}` → job id → `/api/apps/job-status/
{id}`, verified directly against this file during 1.3's fix).

**Do we have this?** No general-purpose version. We only ever *consume*
this pattern as a client of the daemon's own app-management API
(install-reachy.sh); nothing in `maipai_body` or Home *offers* the same
pattern for our own slow operations.

**Verdict: adapt, when a need appears - not a pre-built abstraction
today.** This is a genuinely well-shaped pattern (poll-or-stream, a
small enum, structured logs) worth reaching for the next time something
in Home or the body needs "kick off something slow, report progress" -
model downloads already have their own version of this shape
(`model_download_jobs`, per the schema read during ROBOT-DEVICE-01
work) so the *pattern* is already independently present in Home; no
action needed until a *third* slow-job class shows up, at which point
generalizing Home's existing `model_download_jobs` shape (not copying
Pollen's dataclass-based one wholesale) is the right move, since Home
already owns a job-status table in the household's own database rather
than an in-process dict that dies on restart - a strictly better
property for anything user-facing.

## 4. `reachy-mini-app-assistant`'s scaffolding - already used once, not worth generalizing yet

**What Pollen does.** `apps/assistant.py` is a `questionary`+`rich` CLI
that prompts for an app name (validated: no spaces, dashes, slashes,
wildcards), a language, and a target directory (must not already be
inside a git repo), then renders Jinja2 templates
(`apps/templates/*.j2`) into a fresh project: `pyproject.toml.j2`
registers the SAME `reachy_mini_apps` entry point (item 2 above) under
`setuptools`, plus a `main.py.j2` app class stub, a `README.md.j2`, and
(for the web-UI flavor) `index.html.j2`/`style.css.j2`/`main.js.j2`. No
manifest beyond that `pyproject.toml` stanza - confirming again (see
item 2) that Pollen's own "app declaration" is exactly one entry point
and nothing else.

**Do we have this?** RM-01 was scaffolded once by running this exact
tool by hand (AGENTS.md's own record); nothing in this repo wraps or
re-invokes it programmatically.

**Verdict: reject generalizing it, keep using it by hand.** MaiPai has
exactly one Reachy Mini app (`maipai_bot` itself) and no plan to ship a
second one on this body - there is no "scaffold N apps" workflow to
templatize a wrapper around. If a second Reachy-Mini-hosted app ever
becomes real product scope (unlikely per the design record: MaiPai's
own app is the only thing that should run on a paired unit outside
GUEST-01's reviewed store apps), running `reachy-mini-app-assistant`
by hand again is the right amount of tooling, not a MaiPai-authored
wrapper around someone else's scaffolder.

## 5. Skill/capability declaration - confirmed: Pollen doesn't have one worth copying

Explicitly checked and worth recording as a negative result: no file
under `reachy_mini/` mentions "skill" at all (a repo-wide grep for the
word returns nothing), and `AppInfo`'s only fields are `name`,
`source_kind`, `description`, `url`, and the empty `extra` dict (item 2).
Pollen's app store discoverability is a README tag plus a free-text
description, nothing structured. MaiPai's own catalog manifest (a
package's `platforms`, `category`, declared capability ids validated
against commons' vocabulary once RM-00 lands, `data_sources`,
`permissions`) is already a stricter, more useful design than anything
in this SDK - there is nothing to import here, only confirmation that
the design record's own path (build our own, RM-00/BODY-VOCAB-01) is
correct rather than an unexamined gap.

## What this doesn't cover

Section 11's own table already renders a verdict on every third-party
*app's content* (dance libraries, marionette-style move recording as a
product feature, camera-reactive apps, telepresence, the store itself) -
this doc is additive to that table (MOVES-01/MOVES-02's own *format*,
item 1 above), not a replacement for it. Nothing here recommends
adopting the store, the marketplace listing mechanism, or the central
relay - section 8's privacy rejection of those already stands and isn't
re-litigated.
