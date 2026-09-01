# Ticket 025: Skip cooling providers

- Status: IN_PROGRESS
- Workstream: runtime

## Goal

Make the shared provider cooldown an effective circuit breaker so recurring
short-lived completion processes do not immediately repeat a known timeout
chain.

## Acceptance criteria

- [x] Providers with an active cooldown are excluded from a completion call.
- [x] A call fails closed without network attempts when all candidates cool.
- [x] Policy order and eligibility return automatically after cooldown expiry.
- [x] The full verification suite passes; live readback follows protected publication.
