# Ticket 024: Persist provider health across completion processes

- Status: IN_PROGRESS
- Workstream: runtime

## Goal

Preserve secret-free provider cooldown evidence between independent
`subllm-complete` processes so recurring Supervisor assessments do not retry a
recently unavailable provider as if no failure had occurred.

## Acceptance criteria

- [x] Provider health uses an atomically written, process-shared state file.
- [x] Persisted data contains only bounded provider diagnostics and no request,
      response, prompt or credential material.
- [x] Concurrent writers are serialized and malformed state recovers safely.
- [x] A fresh process prefers a healthy fallback while the failed provider is
      cooling down, then restores policy order after expiry.
- [ ] Full `./scripts/verify` passes and a live Supervisor readback shows the
      persisted routing decision.
