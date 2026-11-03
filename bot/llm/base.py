from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(Exception):
    """Safe error codes only; never upstream response bodies or credentials."""


@dataclass(frozen=True)
class ProviderResult:
    """One independent provider result; never use shared usage as identity."""

    text: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    attempts: int = 1
    provider_status: str = "success"

    @property
    def truncated(self):
        return self.finish_reason in {"length", "max_tokens", "content_filter"}


class LLMProvider(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, attempts: int | None = None,
                       max_tokens: int | None = None) -> str: ...

    async def complete_result(self, messages: list[dict[str, str]], *, attempts: int | None = None,
                              max_tokens: int | None = None) -> ProviderResult: ...
