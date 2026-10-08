# Ticket 117: Wellman advisory route

- **ID**: ticket-117
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requested structure-aware Wellman standards analysis through SubLLM. This disjoint dependency of wellmanifest/wellman ticket-025 registers its actual identity; existing protected publication authorization applies.

- [x] AC-01: Own wellman/standard-selection route resolves using the existing default provider policy.
- [x] AC-02: Policy/resolver tests and governance pass before protected publication.

## Validation

- 156 policy/resolver/config tests passed.
- Full suite in the existing project virtualenv: 575 passed, 2 dependency deprecation warnings, 83.18 s.
- Older operator policies acquire the new application metadata in memory; no operator file or provider settings changed.
- Protected review/merge pending.
