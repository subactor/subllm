# Ticket 092: Update MCP and test dependency pins

- **ID**: ticket-092
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Owner**: codex / sdk-update-20260920
- **Workstream**: integration
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION; user requested continuation and protected delivery.

Issue 92 allocates STARTER-023. Pin the gateway and test MCP SDK to patched 1.28.1, raise pytest minimum to 9.0.3 and update the hash-locked Doctor test wheel. Verify existing caller/session isolation, bidirectional RPC, generated error delivery, full default suite and PostgreSQL integration in a private environment. Publish via protected OneDev and independent Validator before replacing the runtime. Preserve client configurations and private archives.

Canonical result: [Unified proxy](../../docs/information/unified-proxy.md).

Acceptance: AC-01 dependency compatibility, archive readback and protected publication.
