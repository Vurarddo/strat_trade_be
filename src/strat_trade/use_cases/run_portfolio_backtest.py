from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.models import (
    PortfolioBacktestConfig,
    PortfolioBacktestSummary,
    StakeModel,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.ports.candles import CandleFeed


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    rows = [
        {
            "timestamp": c.open_time,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": float(c.volume) if c.volume is not None else 0.0,
        }
        for c in candles
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


async def execute_portfolio_backtest(
    feed: CandleFeed,
    *,
    assets: list[str],
    max_concurrent_trades: int = 3,
    timeframe_seconds: int = 60,
    initial_deposit: float = 1000.0,
    stake_model: str = "flat",
    stake_amount: float = 10.0,
    stake_percent: float = 1.0,
    martingale_multiplier: float = 2.0,
    martingale_max_steps: int = 2,
    payout_rates: dict[str, float] | None = None,
    min_payout_rate: float = 0.80,
    expiration_bars: int = 3,
    adaptive_expiration: bool = False,
    daily_stop_loss_pct: float = 0.05,
    strategy_name: str = "hybrid_multifactors",
    strategy_params: dict[str, Any] | None = None,
    candle_count: int = 300,
    end_at: datetime | None = None,
    expiration_seconds: int | None = None,
) -> PortfolioBacktestSummary:
    if not assets:
        raise InvalidMarketParametersError(
            "At least one asset must be selected for portfolio backtest."
        )

    clean_assets = [a.strip() for a in assets if a.strip()]
    if not clean_assets:
        raise InvalidMarketParametersError("No valid asset symbols provided.")

    if feed is None:
        raise InvalidMarketParametersError("No CandleFeed broker connection available.")

    # Fetch live assets payouts if needed
    live_payouts: dict[str, Decimal] = {}
    if hasattr(feed, "get_assets"):
        try:
            active_list = await feed.get_assets()
            for item in active_list:
                sym = item.get("symbol")
                p = item.get("payout")
                if sym and p is not None:
                    live_payouts[sym] = Decimal(str(p)) / Decimal("100.0")
        except Exception:
            pass

    resolved_payouts: dict[str, Decimal] = {}
    for a in clean_assets:
        if payout_rates and a in payout_rates:
            resolved_payouts[a] = Decimal(str(payout_rates[a]))
        elif a in live_payouts:
            resolved_payouts[a] = live_payouts[a]
        else:
            resolved_payouts[a] = Decimal("0.92") if "otc" in a.lower() else Decimal("0.80")

    # Concurrently fetch candle series for all assets
    async def fetch_one(asset: str) -> tuple[str, pd.DataFrame]:
        try:
            candles = await asyncio.wait_for(
                feed.get_candles(
                    asset=asset,
                    timeframe=timeframe_seconds,
                    count=candle_count,
                    end_time=end_at,
                ),
                timeout=12.0,
            )
            df = _candles_to_df(candles)
            return asset, df
        except Exception:
            return asset, pd.DataFrame()

    tasks = [fetch_one(a) for a in clean_assets]
    results = await asyncio.gather(*tasks)
    asset_dfs = {a: df for a, df in results if not df.empty}

    if not asset_dfs:
        raise InvalidMarketParametersError(
            "Could not load candle data for any of the selected assets. Check broker connection."
        )

    config = PortfolioBacktestConfig(
        assets=clean_assets,
        timeframe_seconds=timeframe_seconds,
        initial_deposit=Decimal(str(initial_deposit)),
        max_concurrent_trades=max(1, max_concurrent_trades),
        stake_model=StakeModel(stake_model.lower()),
        stake_amount=Decimal(str(stake_amount)),
        stake_percent=Decimal(str(stake_percent)),
        martingale_multiplier=Decimal(str(martingale_multiplier)),
        martingale_max_steps=martingale_max_steps,
        payout_rates=resolved_payouts,
        min_payout_rate=Decimal(str(min_payout_rate)),
        expiration_bars=expiration_bars,
        adaptive_expiration=adaptive_expiration,
        daily_stop_loss_pct=Decimal(str(daily_stop_loss_pct)),
        strategy_name=strategy_name,
        strategy_params=strategy_params or {},
        expiration_seconds=expiration_seconds,
    )

    engine = PortfolioBacktestEngine(config)
    return engine.run(asset_dfs)
