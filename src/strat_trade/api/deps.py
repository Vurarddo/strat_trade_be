from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from strat_trade.ports.candles import CandleFeed
from strat_trade.ports.llm_market_analysis import LlmMarketAnalysisPort
from strat_trade.ports.trading_gateway import TradingGateway
from strat_trade.settings import Settings


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise RuntimeError("Application settings are not configured.")
    return settings


def get_trading_gateway(request: Request) -> TradingGateway:
    gateway = getattr(request.app.state, "trading_gateway", None)
    if gateway is None:
        raise RuntimeError("Trading gateway is not configured on the application.")
    return gateway


def get_candle_feed(request: Request) -> CandleFeed:
    gateway = getattr(request.app.state, "trading_gateway", None)
    if gateway is None:
        raise RuntimeError("Trading gateway is not configured on the application.")
    return gateway


def get_gemini_llm(request: Request) -> LlmMarketAnalysisPort | None:
    return getattr(request.app.state, "gemini_llm", None)


TradingGatewayDep = Annotated[TradingGateway, Depends(get_trading_gateway)]
CandleFeedDep = Annotated[CandleFeed, Depends(get_candle_feed)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
GeminiLlmDep = Annotated[LlmMarketAnalysisPort | None, Depends(get_gemini_llm)]
