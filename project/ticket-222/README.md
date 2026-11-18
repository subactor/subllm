# Ticket 222: SUB-01 proxy: replace CORS wildcard with an origin allowlist and optional bearer token

- **ID**: ticket-222
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Repair plan SUB-01 (claude-review 2026-11-18): `subllm proxy` sent
`Access-Control-Allow-Origin: *` on every response without authentication, so
any web page open in the operator's browser could spend paid cloud routes and
read local models.

- Foreign browser origins get `403 PROXY-ORIGIN` (preflight and simple requests)
  before any provider or upstream attempt; no CORS headers are sent to them.
- Allowed: loopback pages (`127.0.0.1`, `localhost`, `[::1]`, any port) and the
  comma-separated `SUBLLM_PROXY_ALLOWED_ORIGINS`; the origin is echoed with
  `Vary: Origin`. Loopback stays allowed by default (deviation from the plan's
  empty default) because the willmux web UI uses the proxy from the browser.
- Requests without `Origin` (CLI, curl, agents) are unchanged.
- With `SUBLLM_PROXY_TOKEN`, routed completions require
  `Authorization: Bearer <token>` (`401 PROXY-AUTH`); the direct local Ollama
  forward stays available.
- README and `docs/operations.md` follow in a separate ticket.

## Acceptance criteria

- [x] AC-01: `tests/test_proxy.py` passes, including origin and token cases.
- [ ] AC-02: Governance check and exact-head review pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 52/100 |
| Complexity | M |
| Estimated effort | 51 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
