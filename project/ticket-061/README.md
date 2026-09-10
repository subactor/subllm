# Ticket 061: Doctor profile pilot

Status: IN_PROGRESS
Workflow state: EDIT

SESSION_EXECUTION_AUTHORIZATION: user requested continuation of implementation, tests and protected publication after R2. GitHub issue 61 allocates this legacy ticket; no managed allocator exists in this repository.

Scope: declare a Python library profile, hash-pin public test wheels and expose doctor-test. Run the published Doctor executor on an exact clean revision. Preserve provider policy and operator configuration.

Acceptance: the isolated diagnostic runs the full existing test suite without provider credentials; scripts/verify and protected OneDev/Validator publication pass.

Canonical result: https://github.com/subactor/docs/blob/main/architecture/refactoring/doctor-diagnostic-reliability.md
