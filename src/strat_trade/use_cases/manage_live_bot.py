from __future__ import annotations

import logging
from typing import Any

from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import BotSessionSummary, LiveTradeRecord, PreTradingPlan
from strat_trade.domain.trading.trade_store import TradeStore

logger = logging.getLogger(__name__)

# Global singleton bot instance
_global_trade_store = TradeStore()
_global_bot_engine = LiveDemoBotEngine(trade_store=_global_trade_store)


def get_bot_engine() -> LiveDemoBotEngine:
    return _global_bot_engine


def get_trade_store() -> TradeStore:
    return _global_trade_store


async def start_live_bot(plan: PreTradingPlan, gateway: Any) -> BotSessionSummary:
    engine = get_bot_engine()
    await engine.start(plan, gateway)
    return engine.get_summary()


async def stop_live_bot() -> BotSessionSummary:
    engine = get_bot_engine()
    await engine.stop()
    return engine.get_summary()


async def pause_live_bot(
    duration_seconds: int | None = None, reason: str = ""
) -> BotSessionSummary:
    engine = get_bot_engine()
    await engine.pause(duration_seconds=duration_seconds, reason=reason)
    return engine.get_summary()


async def resume_live_bot() -> BotSessionSummary:
    engine = get_bot_engine()
    await engine.resume()
    return engine.get_summary()


def get_live_bot_status() -> BotSessionSummary:
    engine = get_bot_engine()
    return engine.get_summary()


def get_live_bot_trades(limit: int = 100, offset: int = 0) -> list[LiveTradeRecord]:
    store = get_trade_store()
    return store.list_trades(limit=limit, offset=offset)


def clear_live_bot_trades() -> int:
    engine = get_bot_engine()
    return engine.clear_history()
