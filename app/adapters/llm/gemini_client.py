"""Google Gemini JSON client."""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import errors, types

from app.domain.errors import AdvisorError

log = logging.getLogger(__name__)


TIMEOUT_MS = 180_000  # a hung call would otherwise hold the per-user analysis lock forever


class GeminiClient:
    def __init__(self, model: str, api_key: str) -> None:
        self.name = f"gemini:{model}"
        self._model = model
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                ),
            )
        except errors.ClientError as exc:
            if exc.code in (401, 403):
                raise AdvisorError("Gemini API key is missing or invalid") from exc
            if exc.code == 429:
                raise AdvisorError("Gemini rate limit / quota hit, try again shortly") from exc
            raise AdvisorError(f"Gemini API error {exc.code}: {exc.message}") from exc
        except errors.APIError as exc:
            raise AdvisorError(f"Gemini API error {exc.code}: {exc.message}") from exc
        except Exception as exc:  # timeouts and network errors from the HTTP layer
            raise AdvisorError(f"Gemini request failed: {type(exc).__name__}: {exc}") from exc

        text = response.text
        if not text:
            reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
            raise AdvisorError(f"Gemini returned no text (finish reason: {reason})")
        usage = response.usage_metadata
        if usage:
            log.info("Gemini usage: in=%s out=%s", usage.prompt_token_count, usage.candidates_token_count)
        return text
