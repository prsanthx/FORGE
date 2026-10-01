"""Provider interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    provider: str
    model: str
    estimated_tokens: bool = False
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class LLMError(RuntimeError):
    pass


def messages_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in messages)
