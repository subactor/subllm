# Changelog

- Reproduced loss of provider cooldown between Supervisor completion processes.
- Added a closed `subllm.provider-health/v1` state projection with a 0600
  atomic state file and process-shared lock.
- Switched cooldown deadlines from process-local monotonic time to bounded wall
  clock timestamps that remain comparable after a process exit.
- Added fresh-process, malformed-state, secret-redaction and six-writer
  concurrency tests.
- Verified 206 tests plus lint, build, wheel and source-distribution gates.
