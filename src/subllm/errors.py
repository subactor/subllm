from __future__ import annotations

CURSOR_WORKER_TIMEOUT_CODE = "SUBLLM-CURSOR-WORKER-TIMEOUT"
PROVIDER_CHAIN_EXHAUSTED_CODE = "SUBLLM-PROVIDER-CHAIN-EXHAUSTED"
PROVIDER_RATE_LIMIT_CODE = "SUBLLM-PROVIDER-RATE-LIMIT"
PROVIDER_UNAVAILABLE_CODE = "SUBLLM-PROVIDER-UNAVAILABLE"
RESPONSE_QUALITY_CODE = "SUBLLM-RESPONSE-QUALITY-REJECTED"
QUALITY_VALIDATOR_ERROR_CODE = "SUBLLM-QUALITY-VALIDATOR-ERROR"


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


class CursorRunError(CompletionError):
    """The SDK started a model run which failed; another model may remain usable."""


class InvalidResponseContractError(CompletionError):
    """The caller supplied a malformed or unsupported response contract."""
