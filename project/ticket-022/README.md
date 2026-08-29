# Ticket 022: Add vision modality and nexu/nlp2cmd/vql vision routes

- **ID**: ticket-022
- **Owner**: grok
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Workstream**: vision
- **Created**: 2026-08-29

## Goal and scope

Nexu (and later nlp2cmd CAPTCHA / VQL screenshots) need image+text completions.
SubLLM `complete()` already forwarded message dicts, but every route selected
text models including Cursor SDK. Add a `vision` modality, vision-capable
catalog models, and exact application/function vision routes. Do not make paid
requests.

## Acceptance criteria

- [ ] AC-01: Vision routes never include Cursor SDK candidates.
- [ ] AC-02: `complete()` sends `image_url` parts on `autogrammar-nexu/vision`.
- [ ] AC-03: Text routes reject image parts; vision routes reject missing or
      `file:`/`http:` images.
- [ ] AC-04: `./scripts/verify` passes without paid provider calls.
