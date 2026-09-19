# Ticket 082: API usage history and panel
- **Status**: DONE
- **Workflow state**: PUBLICATION
Workstream: observability
Owner: codex / api-panel-20260919

SESSION_EXECUTION_AUTHORIZATION: owner requested execution of STARTER-018 on 2026-09-19. GitHub issue 82 allocates this legacy repository ticket; no managed allocator exists here.

Persist secret-free completion attempts, including failures and fallback correlation. Provide a local read-only web panel through PolicyBus, with application, provider, status and time filters, latency and nullable token totals. Cover SDK and proxy model dispatch. Explicitly describe coverage of updated clients and external traffic. Test persistence, concurrency, redaction, fail-open logging, query purity and HTTP security. Publish the verified change and start a local panel.

Scope: usage journal and UI, client attempt instrumentation, request IDs in proxy, PolicyBus query/HTTP, package assets, regression tests, the generated POA process catalog and README usage instructions. Version 1.12.0 joins the material implementation. No provider policy or credentials changes.
