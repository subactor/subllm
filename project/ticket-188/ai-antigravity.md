# AI Antigravity Log: Ticket 188

## Objective
Admit `gpt-6-luna` and `gpt-6.1-terra` for OpenAI API provider `codex`, set `gpt-6-luna` as default codex model in `subllm.toml`, and configure `_SZEPTNIK` routes to prioritize `codex` / `gpt-6-luna` and `gpt-6.1-terra` for heyasa.

## Implemented
1. Added `codex` ProviderModelSpec to `gpt-6-luna` and added `gpt-6.1-terra` to `_BASE_MODELS` in `src/subllm/policy.py`.
2. Added `codex/gpt-6-luna` and `codex/gpt-6.1-terra` to `_SZEPTNIK` candidates.
3. Updated `subllm.toml` to default `[providers.codex]` to `gpt-6-luna`.
4. Updated `credential_template.py` and regression test expectations in `test_policy.py` and `test_policy_config.py`.
