# ticket-052: Keep explicit paths when prose directory words overflow context

Status: IN_PROGRESS
Workflow state: EDIT

SESSION_EXECUTION_AUTHORIZATION: Founder authorized bounded Layer A delivery
and protected publication. Live PLF-13618 failed
`code edit context exceeds its file or byte budget` because Polish/English
prose tokens `docs` and `test` (including the prefix of `testów`) expanded
whole trees. Keep Unicode word boundaries and, on over-budget, retry with
slash-containing paths only. Fail closed when those explicit paths still
overflow. Do not change Aider ignore projection, credentials or routes.

Evidence: live coding-agent artifact
`subllm-aider-result.json` for PLF-13618.
