# Ticket 014: Register NFO analysis route

- **ID**: ticket-014
- **Owner**: founder
- **Status**: ACTIVE
- **Workflow state**: IMPLEMENTATION
- **Created**: 2026-08-26

## Goal and scope

Let the public `nfo` package call the centrally governed SubLLM transport as
application `semcod-nfo` for
log analysis. The preferred route is direct Z.AI `glm-5.3`; alternative
providers remain pre-request fallbacks only.

## Acceptance criteria

- [x] `semcod-nfo/analyze` is an exact registered application/function pair.
- [x] The application has a stable public repository identity.
- [x] Direct Z.AI `glm-5.3` remains the first deterministic candidate.
- [x] Tests cover policy resolution and the public completion transport.
- [ ] Validator merges the exact frozen revision.
