from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from strat_trade.api.market_indicators_mapping import (
    build_market_indicators_batch_response,
    resolve_indicator_keys,
)
from strat_trade.api.schemas import GeminiLlmJsonPayload, GeminiMarketIndicatorsRequest
from strat_trade.domain.errors import GeminiInvocationError, GeminiNotConfiguredError
from strat_trade.ports.candles import CandleFeed
from strat_trade.ports.llm_market_analysis import LlmMarketAnalysisPort
from strat_trade.use_cases.market_indicators_batch import (
    IndicatorRunSpec,
    compute_market_indicators_batch,
)
from strat_trade.use_cases.prompts.pro_trader_gemini import PRO_TRADER_SYSTEM_INSTRUCTION


def _strip_markdown_json_fence(raw: str) -> str:
    t = raw.strip()
    if not t.startswith("```"):
        return t
    t = re.sub(r"^```(?:json)?\s*", "", t, count=1, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def parse_gemini_structured_json(raw: str) -> GeminiLlmJsonPayload:
    text = _strip_markdown_json_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise GeminiInvocationError(f"Gemini response is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise GeminiInvocationError("Gemini response JSON must be an object.")
    try:
        return GeminiLlmJsonPayload.model_validate(data)
    except ValidationError as e:
        raise GeminiInvocationError(
            f"Gemini response JSON does not match expected schema: {e}",
        ) from e


@dataclass(frozen=True, slots=True)
class GeminiMarketAnalysisResult:
    direction: str
    expiration: str
    win_probability: str
    analysis: str
    entry_time: str
    close_time: str
    model: str
    asset: str
    timeframe_seconds: int


async def run_gemini_market_analysis(
    feed: CandleFeed,
    *,
    body: GeminiMarketIndicatorsRequest,
    max_candles_per_request: int,
    max_indicator_runs: int,
    llm: LlmMarketAnalysisPort | None,
    gemini_model: str,
) -> GeminiMarketAnalysisResult:
    if llm is None:
        raise GeminiNotConfiguredError(
            "Set STRAT_TRADE_GOOGLE_GEMINI_API_KEY or GOOGLE_API_KEY (or GEMINI_API_KEY) "
            "to use Gemini market analysis.",
        )

    keys = resolve_indicator_keys(body)
    runs = [
        IndicatorRunSpec(
            indicator_id=r.indicator_id.strip(),
            params=dict(r.params),
            response_key=k,
        )
        for r, k in zip(body.indicators, keys, strict=True)
    ]
    result = await compute_market_indicators_batch(
        feed,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
        count=body.count,
        max_count=max_candles_per_request,
        max_indicator_runs=max_indicator_runs,
        runs=runs,
        end_at=body.end_at,
        cursor=body.cursor,
    )
    batch = build_market_indicators_batch_response(
        result=result,
        runs=runs,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
    )
    payload: dict[str, object] = {
        "candles": [c.model_dump(mode="json") for c in batch.candles],
        "indicators": [i.model_dump(mode="json") for i in batch.indicators],
    }
    if body.expiration_time_seconds is not None:
        payload["expiration_time_seconds"] = body.expiration_time_seconds
    user_content = json.dumps(payload, ensure_ascii=False)
    raw = await llm.analyze(
        system_instruction=PRO_TRADER_SYSTEM_INSTRUCTION,
        user_content=user_content,
        model=gemini_model,
    )
    parsed = parse_gemini_structured_json(raw)
    return GeminiMarketAnalysisResult(
        direction=parsed.direction,
        expiration=parsed.expiration,
        win_probability=parsed.win_probability,
        analysis=parsed.analysis,
        entry_time=parsed.entry_time,
        close_time=parsed.close_time,
        model=gemini_model,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
    )
