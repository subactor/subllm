# TODO

- [x] [`ticket-023`](project/ticket-023/README.md) — bounded runtime failover for
  slow or transiently unavailable LLM providers, with process-local health
  receipts and operator-owned execution thresholds. Status: `IN_PROGRESS / EDIT`;
  workstream: `runtime`. Delivered in `1.9.0`.

- [ ] [`ticket-022`](project/ticket-022/README.md) — vision modality and
  `autogrammar-nexu/vision` (plus nlp2cmd/vql vision). Status:
  `IN_PROGRESS / EDIT`; workstream: `vision`.

- [ ] [`ticket-005`](project/ticket-005/README.md) - publish a zero-dependency
  OpenAI-compatible client so Semcod and Autogrammar consumers use one SubLLM
  execution boundary. Status: `IN_PROGRESS / PUBLICATION`; workstream:
  `application`.

- [ ] Add an optional credential-vault resolver without changing the public
  route policy or exposing leased values.
- [ ] Configure trusted PyPI publishing before distributing
  `subactor-subllm` outside immutable Git commit dependencies.
- [x] [`ticket-008`](project/ticket-008/README.md) — allow bounded runtime
  tuning of provider attempt deadlines without copying the policy catalog.
