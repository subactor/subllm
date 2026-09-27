# Ticket 107: Link Planfile tasks in subllm usage table

- **ID**: ticket-107
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-27

## Goal and scope

1. Detect and parse Planfile task references (`PLF-XXX`, `ticket-XXX`, `GITHUB-XXX`) and project repository context (`semcod/koru`, `semcod/nxdo`, `semcod/prefact`, `semcod/repatch`, `semcod/tagi`, `maskservice/c2004`) from LLM request content in SubLLM usage panel (`http://127.0.0.1:18988/`).
2. Add a dedicated "Zadanie (Planfile)" column in the usage history table with interactive badges and GitHub issue search links.
3. Add a dedicated Planfile task card in the attempt detail view (`#detail`) showing task identifier, repository, extracted title, and `planfile ticket show` CLI command.
4. Support filtering by ticket ID in the UI search field.
5. Verify tests and repository governance check pass.

## Acceptance criteria

- [x] AC-01: Usage table includes "Zadanie (Planfile)" column displaying extracted Planfile ticket identifiers and project badges.
- [x] AC-02: Clicking ticket badge filters the table or navigates to the associated GitHub issue search.
- [x] AC-03: Attempt detail view renders a dedicated Planfile task section when a ticket reference is present in the prompt.
- [x] AC-04: SubLLM test suite and `./project/governance-check.sh` pass cleanly.

## Session authorization

User request: "Czy wszystkie requesty, zadania sa widoczne tutaj? chciaalbym aby były linki poiwazane w tabeli do konrketnych zadan z planfile, aby mozna bylo sledzic co było wykonywane na podstawie jakich zadan jesli to robil koru http://127.0.0.1:18988/"

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
