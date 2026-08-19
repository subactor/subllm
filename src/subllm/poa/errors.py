from __future__ import annotations

from subllm.errors import SubLLMError


class PoaContractError(SubLLMError):
    """Fail-closed POA diagnostic that never echoes untrusted values."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
