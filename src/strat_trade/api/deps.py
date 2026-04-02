from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from strat_trade.adapters.db.sqlite_signal_repository import SqliteSignalRepository
from strat_trade.adapters.gemini_adapter import GeminiAdapter
from strat_trade.ports.candles import CandleFeed
from strat_trade.ports.llm_gateway import LlmGateway
from strat_trade.ports.signal_repository import SignalRepository
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


def get_llm_gateway(request: Request) -> LlmGateway:
    settings = get_settings(request)
    return GeminiAdapter(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )


def get_signal_repository(_request: Request) -> SignalRepository:
    return SqliteSignalRepository()


TradingGatewayDep = Annotated[TradingGateway, Depends(get_trading_gateway)]
CandleFeedDep = Annotated[CandleFeed, Depends(get_candle_feed)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
LlmGatewayDep = Annotated[LlmGateway, Depends(get_llm_gateway)]
SignalRepositoryDep = Annotated[SignalRepository, Depends(get_signal_repository)]
