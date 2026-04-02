import json
from typing import Any

from google import genai
from google.genai import types

from strat_trade.domain.errors import LlmParsingError
from strat_trade.ports.llm_gateway import LlmGateway

SYSTEM_INSTRUCTION = """\
You are an Elite Institutional Quant Model. Analyze the pre-calculated Market State Vector and
make a trading decision.
RULES:
1. If 'is_choppy' is true, heavily favor NEUTRAL.
2. FVG (Fair Value Gaps) act as magnets.
3. 'rsi_divergence' is the STRONGEST reversal signal.
4. EXPIRATION RULE: 'expiration_in_seconds' MUST be strictly between 1 to 5 times the provided
   timeframe_seconds. (e.g., if timeframe is 60, expiration must be 60, 120, 180, 240, or 300).

OUTPUT SCHEMA (Return strictly raw JSON):
{
  "chain_of_thought": {
    "step_1_regime": "string (MAX 5 WORDS)",
    "step_2_smc": "string (MAX 5 WORDS)",
    "step_3_confluence": "string (MAX 5 WORDS)",
    "step_4_verdict": "string (MAX 5 WORDS)"
  },
  "direction": "BUY" | "SELL" | "NEUTRAL",
  "expiration_in_seconds": int,
  "win_probability_percentage": int,
  "strategy_name": "string"
}
"""


class GeminiAdapter(LlmGateway):
    """Adapter for Google Gemini using the google-genai SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def analyze_market_state(self, state_json: str) -> dict[str, Any]:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.0,
            max_output_tokens=500,
            response_mime_type="application/json",
        )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=state_json,
            config=config,
        )

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = f"Failed to parse JSON from LLM adapter: {exc.msg}"
            raise LlmParsingError(msg) from exc
