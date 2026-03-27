from __future__ import annotations

from typing import Protocol


class LlmMarketAnalysisPort(Protocol):
    """Outbound LLM for market snapshot analysis (Gemini or test doubles)."""

    async def analyze(
        self,
        *,
        system_instruction: str,
        user_content: str,
        model: str,
    ) -> str:
        """Send system instruction + user text; return model text output."""
        ...
