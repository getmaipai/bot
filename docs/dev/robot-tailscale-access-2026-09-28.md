# Can the robot reach its hub over Tailscale, from anywhere? (2026-09-28)

Answering Jesse's question directly: **the address-book pattern is already
built and G4 should use it as-is; the robot reaching it "from anywhere"
needs the robot to join the tailnet as its own node, which is a real
owner-facing decision, not something to wire up silently.**

## What `home` already has (verified in the actual source)

`home/backend/src/lib/tailscale.ts` detects an existing Tailscale
install on the hub machine via `tailscale status --json` (line 48) -
**never installs one** (the file's own header, lines 1-7). Opt-in,
exactly like BACKLOG.md's own first-run wizard item calls it
("Tailscale as an optional step", `docs/BACKLOG.md:9571`). When running,
it returns the MagicDNS name (`foo.tailnetname.ts.net`) and tailnet IPs
(`hubEndpoints.ts:37-39`).

`home/backend/src/lib/hubEndpoints.ts` merges three address sources into
one book a client can walk in priority order: detected LAN IPs
(`detectLanIps()`, line 123), the detected Tailscale address
(`detectTailnetUrls()`, line 142), and admin-typed rows from the
`hub_endpoints` table. Detected LAN sorts first (priority 10), Tailscale
next (priority 60, line 42) - "on the home network the LAN IP is the
fastest path" (line 38). `guessEndpointKind()` (line 63) classifies a
`.ts.net` hostname or a CGNAT `100.64.0.0/10` address as `"overlay"`
specifically so it's never mistaken for a LAN address.

**The gap: nothing consumes this yet.** `listHubEndpoints()` has exactly
one caller, `routes/setup.ts`'s `GET /api/setup/ca` (line 80) - an
**unauthenticated**, rate-limited, LAN-purpose route for the one-time
household-CA trust step. It deliberately returns *only* a LAN address in
its QR payload, never the Tailscale one (lines 75-84, a second code
review's own fix: "a device on the physical LAN but off the tailnet
could scan a URL it can never reach"). No route exposes the full book
(including the Tailscale entry) to an *already-paired* device for
ongoing reconnection, and nothing in `home/frontend/src` implements
"try LAN, fall back to Tailscale" at all - grepped, zero matches. **G4
would be the first real client of this pattern**, with a server-side
address book already built and correctly reasoned about, but no
authenticated route to fetch it and no client-side precedent to mirror.

## The crux: can the robot use it without joining the tailnet?

No. A `.ts.net` MagicDNS name and a `100.64.0.0/10` tailnet IP are only
resolvable/routable from inside the tailnet - by design, this is exactly
what keeps them off the public internet. A device that isn't itself
running an authenticated `tailscaled` client cannot reach either, from
anywhere, regardless of what address it's given. This is true whether
the robot is on the household Wi-Fi, a coffee shop's Wi-Fi, or cellular:
being handed the hub's tailnet address does nothing unless the robot
*is* a tailnet member.

So "the reachy mini works over Tailscale from anywhere" concretely means
**the robot's own daemon-hosting Linux box runs its own Tailscale
client, authenticated onto the household's tailnet as its own node** -
not a proxy, not a relay, an actual second device on the tailnet next to
the hub. Two ways to get there, both real, neither wired up today:

1. **Owner sets it up manually.** Tailscale ships a real Linux client
   (`tailscale up` on Debian, which the Wireless's CM4 runs). The owner
   installs it on the robot themselves and approves it in their own
   Tailscale admin console, the same "the owner already has this, MaiPai
   only uses it" posture `tailscale.ts` already takes for the hub. Zero
   new integration surface in `home` or `bot`; the tradeoff is it's a
   manual step for the owner, not part of the zero-touch pairing flow
   G4's own design assumes.
2. **MaiPai provisions it during pairing.** The hub calls Tailscale's own
   API to mint a pre-authorized key scoped to the household's tailnet,
   hands it to the robot as part of G4's pairing handshake, and the
   robot runs `tailscale up --authkey=...` once, unattended. This *is*
   zero-touch, but it requires the owner to grant the hub an API key or
   OAuth client credential for their own Tailscale account - a new
   credential class `home` doesn't manage today (CREDENTIALS.md has
   nothing about it, and `tailscale.ts`'s entire design point was
   "detect, never touch/configure" - this would be the first place
   `home` actively manages a third-party account on the owner's behalf,
   not just reads local state).

Neither is technically hard; the decision is **which posture the product
wants** (manual parity with the hub's own opt-in Tailscale story, vs. a
new automated-provisioning surface), and that's the owner's call, not a
default to guess into G4 silently - the same class of decision the
gap-audit's own G4 section already flagged for the "how does an unpaired
robot speak its code" question.

## What G4 should build regardless of that decision

The address-book *consumption* pattern is correct today and worth
building into G4 either way, since option 1 (manual) needs it just as
much as option 2 (automated) - a robot that's already a tailnet member
still needs to *learn* the hub's current tailnet address and *prefer*
LAN when both work:

- **A new authenticated route**, alongside G5's own ROBOT-ROUTES-01 work
  (or standalone, it's small): something like `GET
  /api/devices/me/hub-endpoints`, gated the same way `redeem` already
  authenticates a device token, returning `listHubEndpoints()`'s full
  result unfiltered (unlike the CA route, a paired device reconnecting
  from elsewhere legitimately needs the Tailscale entry). Reuses the
  library function verbatim; no new address-detection logic.
- **G4's `body/maipai_body/link/` package** caches that list and walks it
  in the priority order the server already assigns (LAN first, Tailscale
  as fallback), re-fetching it on every successful connection (a DHCP
  lease change or a tailnet reconnect shouldn't strand the robot the
  same way `hubEndpoints.ts`'s own header already reasons about for
  other clients, line 5-6).
- **Pairing itself does not change.** `_maipai._tcp` mDNS discovery
  stays LAN-only (the robot is being unboxed at home); Tailscale is
  purely a post-pairing reconnection fallback, never part of the
  bootstrap. This matches the design record's own framing and needs no
  new decision.

## Recommendation

Build the address-book consumption piece (the new route plus G4's own
fallback-walking client) now - it's needed under either Tailscale
posture and has zero downside. Escalate the "manual vs. automated
tailnet join" question to Jesse before writing any code that installs,
configures, or authenticates Tailscale on the robot itself; that half is
a real product/credential-management decision, not something to default
into.

**Owner's call (2026-09-28): both.** Jesse's answer was "ideally
automatic and manual" - not a choice between the two paths above, both
of them: an owner who already runs Tailscale can pair the robot onto
their existing tailnet by hand (the hub's own "detect, never install"
posture, zero new integration surface), and the hub can also
auto-provision an auth key during pairing for an owner who doesn't want
to touch Tailscale's own admin console at all. This means G4's link
package needs to detect a hand-configured tailnet membership as one
path (nothing to build beyond noticing `tailscaled` already has an
identity) and, separately, `home` needs the auto-provisioning path:
Tailscale's own OAuth client credentials or an admin-scoped API token,
stored through `lib/secrets.ts`'s existing encrypted-at-rest treatment,
used to mint a single-use, tagged, pre-authorized auth key per robot at
pairing time (Tailscale's own API supports exactly this: an
ephemeral-or-persistent, single-use key scoped by ACL tag). That
credential-management piece - the OAuth/API token setup, the key-minting
call, and the household's own consent/setup flow for granting it - is
real, separately-scoped work belonging to `home`, not something to fold
into G4 as a side effect; it should become its own BACKLOG item
(tentatively ROBOT-TAILSCALE-01) once G4 itself is underway, not before.
