from __future__ import annotations

import asyncio

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from strat_trade.domain.errors import GeminiInvocationError, GeminiQuotaExceededError
from strat_trade.ports.llm_market_analysis import LlmMarketAnalysisPort


def _text_from_response(response: types.GenerateContentResponse) -> str:
    if not response.candidates:
        return ""
    parts: list[str] = []
    for cand in response.candidates:
        content = cand.content
        if content is None or not content.parts:
            continue
        for part in content.parts:
            if part.text:
                parts.append(part.text)
    return "".join(parts).strip()


class GeminiLlmMarketAnalysis(LlmMarketAnalysisPort):
    """google-genai client implementing `LlmMarketAnalysisPort`."""

    def __init__(self, *, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def analyze(
        self,
        *,
        system_instruction: str,
        user_content: str,
        model: str,
    ) -> str:
        def _sync_call() -> str:
            try:
                resp = self._client.models.generate_content(
                    model=model,
                    contents=user_content,
                    config=types.GenerateContentConfig(system_instruction=system_instruction),
                )
            except genai_errors.ClientError as e:
                if e.code == 429:
                    raise GeminiQuotaExceededError(
                        "Gemini API rate limit or quota exceeded. Check your plan, billing, and "
                        "https://ai.google.dev/gemini-api/docs/rate-limits (free tier may be "
                        "disabled or exhausted for this model).",
                    ) from e
                raise GeminiInvocationError(
                    f"Gemini API client error (HTTP {e.code}).",
                ) from e
            except genai_errors.ServerError as e:
                raise GeminiInvocationError(
                    f"Gemini API server error (HTTP {e.code}).",
                ) from e
            return _text_from_response(resp)

        return await asyncio.to_thread(_sync_call)
