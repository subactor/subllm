# ticket-053: LLM selection over code2dsl context
- **Status**: DONE
- **Workflow state**: PUBLICATION

Replace lexical path inference with a policy-routed LLM query over canonical todo2code code2dsl records. Send DSL instead of entire source files. Validate selection and edits against the exact local source snapshot. Preserve outer coding-agent governance.

Result: [DSL coding context](../../docs/information/code2dsl-context.md).
