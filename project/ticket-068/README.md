# Ticket 068: Complete canonical CRLF edit evidence

- **ID**: ticket-068
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-10

SESSION_EXECUTION_AUTHORIZATION: napraw, zmerguj, przetestuj; bounded repair and independent publication. GitHub allocation: issue #68.

## Goal and scope

A complete three-line TypeScript function with CRLF has its canonical AST record, exact excerpt and file hash, yet editing_records reports editable=false. The source-side splitlines normalization is not applied consistently to canonical evidence. Repair that comparison while retaining exact source hashes, bounded complete excerpts and line-range validation.

## Acceptance criteria

- [ ] AC-01: A complete CRLF excerpt is editable; LF-normalized canonical evidence for the same CRLF source remains supported.
- [ ] AC-02: Whole-node replacement preserves unrelated bytes and stale-source replay fails. Partial or different-content excerpts stay noneditable.
- [ ] AC-03: ./scripts/verify and protected exact-head publication pass. Independent Validator owns merge. Coding Agent authorship remains a separate unfulfilled R8 criterion: PLF-13911 failed its first attempt on provider availability; the operator completes this bounded source repair.

The initial draft contained failing regressions only. Do not remove or weaken them. No model route, provider, credential, attempt or spending budget changes. Evidence belongs in the [canonical autonomy receipt](https://github.com/subactor/docs/blob/main/architecture/analysis/autonomy-execution-receipt.md).
