# TODO

- [ ] [`ticket-005`](project/ticket-005/README.md) - publish a zero-dependency
  OpenAI-compatible client so Semcod and Autogrammar consumers use one SubLLM
  execution boundary. Status: `IN_PROGRESS / PUBLICATION`; workstream:
  `application`.

- [ ] Add an optional credential-vault resolver without changing the public
  route policy or exposing leased values.
- [ ] Add provider health receipts so runtime failover can distinguish missing
  credentials from a transient provider outage.
- [ ] Configure trusted PyPI publishing before distributing
  `subactor-subllm` outside immutable Git commit dependencies.
