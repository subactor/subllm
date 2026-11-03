# AI Antigravity Log: Ticket 192

## Objective
Register Heyasa application and autonomy routes (`heyasa/command`, `heyasa/decision-routing`) in SubLLM policy and default configuration to eliminate runtime `UnknownRouteError` and unblock autonomous cycle execution.

## Implemented
1. Registered `heyasa` application in `APPLICATIONS` (`src/subllm/policy.py`).
2. Added canonical route policies `heyasa/command` and `heyasa/decision-routing` to `_ROUTE_VALUES` with default fallback candidates.
3. Updated `src/subllm/policy_config.py` to inherit application defaults for `heyasa` without breaking backward compatibility.
4. Added `[applications.heyasa]` and minis fallback route to `subllm.toml`.
5. Added unit test in `tests/test_policy.py` verifying `heyasa` application and route resolution.
