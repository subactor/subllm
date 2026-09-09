# ticket-049: Bounded source context for Aider

Status: IN_PROGRESS
Workflow state: EDIT

PLF-13518 exposed a noninteractive adapter with repository mapping disabled and no source files. Select bounded tracked UTF-8 source files explicitly referenced by the task, reject unsafe paths, and pass them to Aider without expanding execution or publication authority. Preserve no-auto-commit/test rails. Verify selection and secrecy limits, then run scripts/verify and protected local publication.

Cross-repository evidence: [autonomy acceptance](https://github.com/subactor/docs/blob/main/architecture/analysis/autonomy-acceptance.md).
