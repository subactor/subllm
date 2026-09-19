# Ticket 090: Safe MCP failure causes
- **Status**: DONE
Owner: codex / mcp-causes-20260919
Workstream: observability

Issue 90 allocates this legacy repository ticket. Continue STARTER-021: MCP session failures discard nested transport causes, preventing users from distinguishing refused connections, timeout, TLS, DNS and upstream HTTP rejection. Preserve bounded safe diagnostic fields without raw exception text, credentials or endpoint URLs. Do not retry tool calls. Add transport and privacy regressions, verify Logs/Docs and publish through protected local CI and independent Validator.

Canonical result: [Unified proxy](../../docs/information/unified-proxy.md).
