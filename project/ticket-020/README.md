# Ticket 020: Unify Koru multi-provider transports

- **Status**: IN_PROGRESS
- **Workstream**: runtime

## Goal

Make the public SubLLM completion API execute every provider accepted by a
Koru route, so Koru consumes one central provider/model policy instead of a
private Cursor-only transport.

## Acceptance

- `complete()` executes both OpenAI-compatible and Cursor SDK routes.
- Cursor receives no tools and uses the caller-provided working directory.
- Koru planning, queue and reflection share the central Z.AI → Cursor →
  OpenRouter policy chain.
- A started request is never replayed through another paid provider.
