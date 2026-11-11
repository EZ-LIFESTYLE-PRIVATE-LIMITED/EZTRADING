"""Anthropic Claude JSON client."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.domain.errors import AdvisorError

log = logging.getLogger(__name__)

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeClient:
    def __init__(self, model: str, api_key: str, effort: str = "high") -> None:
        self.name = f"claude:{model}"
        self._model = model
        self._effort = effort
        self._client = anthropic.Anthropic(api_key=api_key, timeout=300.0)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                betas=[_FALLBACK_BETA],
                fallbacks="default",  # if a safety classifier declines, the API retries on a fallback model
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AuthenticationError as exc:
            raise AdvisorError("Anthropic API key is missing or invalid") from exc
        except anthropic.RateLimitError as exc:
            raise AdvisorError("Anthropic rate limit hit, try again shortly") from exc
        except anthropic.APIStatusError as exc:
            raise AdvisorError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AdvisorError("Could not reach the Anthropic API") from exc

        if response.stop_reason == "refusal":
            raise AdvisorError("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise AdvisorError("The model ran out of output tokens; try a smaller watchlist")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise AdvisorError("The model returned no text")
        log.info("Claude usage: in=%s out=%s", response.usage.input_tokens, response.usage.output_tokens)
        return text
