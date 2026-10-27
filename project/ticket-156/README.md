# Ticket 156: Archive history and cached token accounting

- **ID**: ticket-156
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-27

SESSION_EXECUTION_AUTHORIZATION: user requested continued investigation and repair of missing request/response details and disproportionate token counts in localhost8788. Continued after the reviewable deployment plan; this source follow-up addresses independently selected archive history and the confirmed cache-count loss. Protected publication is authorized; runtime promotion follows actual independent approval.

- [x] AC-01: Select journal or private archive explicitly without dropping metadata history or guessing historical associations. Archive list pages omit raw bodies and fail visibly when unavailable.
- [x] AC-02: Paginate archive rows without skipping equal timestamps; validate cursors and use exact day/id detail lookup through the existing origin boundary.
- [x] AC-03: Preserve valid cached-input counts across OpenAI-compatible responses and show known cache counts in details; absent or malformed counts never become invented zero.
- [ ] AC-04: Pass meaningful HTTP, paging, privacy and shipped UI tests, stack/governance checks and independent exact-head publication.

Read-only production evidence: genuine attempt36194 has two archived messages totaling5603 characters and a627-character JSON APPROVE reply ending normally with stop. Its outer usage is14945/177; a diagnostic canonical-message comparison in the private proxy archive reports14945 input,11008 cached input and177 output. The deployed proxy drops cached counts while constructing OpenAI usage. This comparison does not grant an outer-to-proxy identity binding and no journal association was rewritten.

Validation: full stack checks passed1017 tests (two existing deprecation warnings), lint, compilation and wheel/sdist builds against an isolated PostgreSQL fixture. Testless collected101 affected tests with coverage. A separate real PostgreSQL qualification verified four records sharing one timestamp, complete stable pagination, unchanged page-independent totals, preserved known zero/unknown token counts, cache counts0/3/6, payload-free list/search output, exact day-bound HTTP detail and origin/filter rejection. Pending captures retain unknown latency and token usage. The existing manifest correctly pins Procache7fe316c9; local checks used the identical protected OneDev wheel with SHA256f26946c4a7adc86c900b4d8f77fceaeee4cbfe07abead0c12da354d4d666476a. No installed project venv, production archive or provider call was changed by this source qualification.
