# Ticket 066: Context selection profile

Status: IN_PROGRESS
Workflow state: EDIT

SESSION_EXECUTION_AUTHORIZATION: continue authorized autonomy R8 source fixes and tests. PLF-13887 passed extraction but its third attempt ended with OpenRouter GLM 5.3 code-context timeout. Separate semantic evidence selection from code editing using an existing registered model with provider-supported low reasoning effort. Preserve provider membership, deadlines, extraction and attempt limits. This ticket does not authorize requeue or a fourth PLF attempt.

Canonical result: [code2dsl context](../../docs/information/code2dsl-context.md) and [cross-repository acceptance](https://github.com/subactor/docs/blob/main/architecture/analysis/autonomy-execution-receipt.md).

The compact first-stage inventory retains every file, kind, count and symbol in rows with a shared kind dictionary. Local selection references map to canonical details before any edit. Full verification: 287 tests, lint and package build.

Real current-Core selection qualification passed: 111.358 seconds, 14 calls, compiler and regression evidence selected, under the unchanged 300-second / 16-call qualification cap.
