import abc
from typing import Any


class LlmGateway(abc.ABC):
    """Port defining the interface for LLM operations."""

    @abc.abstractmethod
    async def analyze_market_state(self, state_json: str) -> dict[str, Any]:
        """Analyzes the market state vector JSON and returns a structured AI verdict."""
        pass
