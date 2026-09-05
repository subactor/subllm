# Ticket 043: Documentation placement

- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-09-06
- **Issue**: https://github.com/subactor/subllm/issues/43

SESSION_EXECUTION_AUTHORIZATION: user requested continuing all-repository documentation placement updates and publication. Preserve existing routing/security agent instructions and append canonical documentation rules, index and pin. No provider/model catalog, operator policy, source or credentials change. Accepted base f1d2951bf0856b6b23ebbd9e3a1a8bfbe130c435. No managed allocator/manifest exists; issue43 allocated this legacy identity. No full new-project or documentation CI enforcement claim. Publish through independent Validator.

Validation: ./scripts/verify passed in an isolated export of the tracked files: Ruff, compileall, 223 tests and sdist/wheel build. No live credentials were copied; the initial /dev/null override was rejected by credential-path/discovery tests and replaced by ordinary discovery in the isolated export. Original AGENTS.md prefix is byte-preserved; docs index metadata and pinned docs checker pass. Artifact build/check retains 21 prior docs governance findings outside this change; current registry roots omit this index.
