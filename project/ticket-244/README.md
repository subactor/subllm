# Ticket 244: Accept fenced JSON from CLI transports instead of locking out the model

- **ID**: ticket-244
- **Owner**: agent:claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-25

## Goal and scope

CLI transports (claude-cli, codex-cli, agy-cli, cursor-cli) have no native JSON
mode, so a `json_object`/`json_schema` request is satisfied only by prompting.
A model that wraps a valid object in one markdown fence (```json ... ```) was
classified `invalid_response`, put on the shared format cooldown and dropped
from the chain, which in production locked validation out of claude-cli.

`client_routes._unfence_cli_json` unwraps exactly one whole fence on the CLI
branch of `_invoke_route` when the body is valid JSON, so the adaptive check,
the quality gate and every later `json.loads` see plain JSON. Prose around a
fence, several fences or an invalid body stay unchanged and are still
rejected by the existing quality gate. Native API transports are unchanged.

Session authorization: the owner asked to repair and deploy the autonomy
workflow defects (2026-11-25, "naprawiaj i wdrazaj").

## Acceptance criteria

- [x] AC-01: A CLI JSON answer in one whole markdown fence is returned as bare JSON and passes the quality gate.
- [x] AC-02: Prose-wrapped, multi-fence or invalid fenced output and text-mode responses are unchanged; invalid JSON is still rejected.

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
