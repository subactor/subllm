from __future__ import annotations

CURSOR_WORKER_TIMEOUT_CODE = "SUBLLM-CURSOR-WORKER-TIMEOUT"
PROVIDER_CHAIN_EXHAUSTED_CODE = "SUBLLM-PROVIDER-CHAIN-EXHAUSTED"
PROVIDER_RATE_LIMIT_CODE = "SUBLLM-PROVIDER-RATE-LIMIT"
PROVIDER_UNAVAILABLE_CODE = "SUBLLM-PROVIDER-UNAVAILABLE"


class SubLLMError(RuntimeError):
    """Base error for deterministic policy or credential resolution failures."""


class UnknownRouteError(SubLLMError):
    pass


class InvalidPolicyError(SubLLMError):
    pass


class MissingCredentialError(SubLLMError):
    pass


class CredentialFileError(SubLLMError):
    pass


class CompletionError(SubLLMError):
    """A policy-resolved completion could not be executed safely."""

    def __init__(self, message: str, *, diagnostic_code: str | None = None) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
