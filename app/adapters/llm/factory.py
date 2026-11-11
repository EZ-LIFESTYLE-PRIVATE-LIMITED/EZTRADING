"""LLM client factory + registry.

To add a provider (e.g. OpenAI):
  1. create ``openai_client.py`` with a class exposing ``name`` and
     ``complete_json(system, user, schema) -> str``
  2. register a builder below with ``@register("openai")``
  3. add catalog rows in ``app.config.ADVISOR_CATALOG``
No service or UI code changes are needed.
"""

from __future__ import annotations

from typing import Callable

from app.config import Settings
from app.domain.ports import LLMClientPort

ClientBuilder = Callable[[str, str, Settings], LLMClientPort]  # (model, api_key, settings)
_REGISTRY: dict[str, ClientBuilder] = {}


def register(provider: str) -> Callable[[ClientBuilder], ClientBuilder]:
    def decorator(builder: ClientBuilder) -> ClientBuilder:
        _REGISTRY[provider] = builder
        return builder

    return decorator


def registered_providers() -> set[str]:
    return set(_REGISTRY)


def create_llm_client(provider: str, model: str, api_key: str, settings: Settings) -> LLMClientPort:
    try:
        builder = _REGISTRY[provider]
    except KeyError:
        raise ValueError(f"Unknown LLM provider '{provider}'. Available: {sorted(_REGISTRY)}") from None
    return builder(model, api_key, settings)


@register("claude")
def _claude(model: str, api_key: str, settings: Settings) -> LLMClientPort:
    from app.adapters.llm.claude_client import ClaudeClient  # lazy: SDK only needed if selected

    return ClaudeClient(model=model, api_key=api_key, effort=settings.llm_effort)


@register("gemini")
def _gemini(model: str, api_key: str, settings: Settings) -> LLMClientPort:
    from app.adapters.llm.gemini_client import GeminiClient

    return GeminiClient(model=model, api_key=api_key)
