from __future__ import annotations


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
