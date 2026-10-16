# Bot link layer: hub address book and hand-joined tailnet (2026-10-15)

ROBOT-TAILSCALE-01's bot half lives in `body/maipai_body/link/`, shared by
Reachy and the StackChan translator host through the existing
`LinkLifecycle`. Pairing remains the same: the saved device token is redeemed
at each candidate, the LAN pairing address is retained, and a tailnet address
never replaces it.

## Walk and authentication

After a successful redeem, `HubLinkClient` reads
`GET /api/devices/me/hub-endpoints` with the session cookie established by
that redeem. It caches enabled `lan` and `overlay` rows and their `instanceId`
values in the lifecycle. A failed refresh keeps the last usable book and logs
that it will reuse the cached addresses after the hub becomes reachable again.

A reconnect tries the saved LAN URL, then cached LAN rows in server priority
order, then a fresh mDNS LAN answer, then overlay rows in server priority
order. Duplicate URLs are tried once. Each redeem request has a two-second
network timeout. An overlay row is considered only when local
`tailscale status --json` returns a running backend with a local Tailscale IP.
This invokes the installed CLI against its local daemon; it makes no call to a
Tailscale service. A paired URL classified as overlay is subject to the same
membership check. The hub's key-off route response contains no overlay rows;
the bot also refuses to try overlay when the host is not joined.

The address book is refreshed after every successful connection. The list is
kept in process memory, so after a process restart the bot must first reach an
address with a valid session before it can fetch the book again. No Tailscale
installation, configuration, key creation, or account credential handling is
part of this change.

## Measured walk time

A deterministic fake walk was run 200 times on the development host. Each of
the four scripted attempts (saved LAN, book LAN, mDNS LAN, overlay success)
waited 10 ms; discovery and response processing used fakes. The complete walk took
48.72 ms p50 and 50.22 ms p95 (44.54 ms minimum, 50.37 ms maximum). This
measures local walker and test-harness overhead around the scripted delays. It
does not measure a real tailnet, hub response, TLS handshake, or a robot's
turn latency, so it is not a production latency budget.

## Failure behavior

Network failures move to the next address. A mismatched or unproven identity
never receives the saved device token and moves to the next address. A hub
401 or 403 means the pairing was refused; the walk stops and the existing
offline ladder handles the lost link. If every candidate fails, the existing
reconnect and offline ladder continue without asking the owner to pair again.
For address-book refresh failures, reconnect to a reachable hub so the bot can
refresh its cached addresses.
