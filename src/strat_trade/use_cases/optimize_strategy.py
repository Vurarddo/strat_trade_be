from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.models import StakeModel
from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import BrokerUnavailableError, InvalidMarketParametersError
from strat_trade.domain.optimizer.grid_search import OptimizationReport, StrategyOptimizerEngine
from strat_trade.domain.strategies.registry import _STRATEGIES
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


def _build_default_grid(strategy_name: str) -> dict[str, list[Any]]:
    meta = _STRATEGIES.get(strategy_name.strip().lower())
    if not meta:
        meta = _STRATEGIES["hybrid_multifactors"]

    grid: dict[str, list[Any]] = {}
    for p in meta.cls.get_parameter_definitions():
        if p.options:
            grid[p.name] = p.options
        elif p.min_value is not None and p.max_value is not None:
            if p.param_type == "int":
                min_v = int(p.min_value)
                max_v = int(p.max_value)
                step = int(p.step or 1)
                grid[p.name] = list(range(min_v, max_v + 1, max(1, step)))[:4]
            elif p.param_type == "float":
                min_v = float(p.min_value)
                max_v = float(p.max_value)
                step = float(p.step or (max_v - min_v) / 3.0)
                vals = []
                cur = min_v
                while cur <= max_v + 1e-6:
                    vals.append(round(cur, 2))
                    cur += step
                grid[p.name] = vals[:4]
        else:
            grid[p.name] = [p.default_value]
    return grid


async def execute_strategy_optimization(
    *,
    feed: CandleFeed,
    strategy_name: str,
    asset: str,
    timeframe_seconds: int = 60,
    candle_count: int = 300,
    initial_deposit: float = 1000.0,
    payout_rate: float | None = None,
    stake_model: str = "flat",
    stake_amount: float = 10.0,
    stake_percent: float = 1.0,
    daily_stop_loss_pct: float = 0.05,
    custom_parameter_grid: dict[str, list[Any]] | None = None,
    max_combinations: int = 60,
    end_time: datetime | None = None,
) -> OptimizationReport:
    clean_asset = asset.strip()
    if not clean_asset:
        raise InvalidMarketParametersError("Asset cannot be empty.")

    # 1. Fetch live payout if not specified
    eff_payout = payout_rate
    if eff_payout is None:
        eff_payout = 0.92 if "otc" in clean_asset.lower() else 0.80
        if hasattr(feed, "get_assets"):
            try:
                assets = await feed.get_assets()
                for item in assets:
                    if item.get("symbol") == clean_asset and item.get("payout") is not None:
                        eff_payout = float(item["payout"]) / 100.0
                        break
            except Exception:
                pass

    # 2. Fetch candles
    try:
        candles = await asyncio.wait_for(
            feed.get_candles(
                asset=clean_asset,
                timeframe=timeframe_seconds,
                count=candle_count,
                end_time=end_time,
            ),
            timeout=15.0,
        )
    except Exception as exc:
        raise BrokerUnavailableError(
            f"Failed to fetch market candles for {clean_asset}: {exc}"
        ) from exc

    df = _candles_to_df(candles)
    if df.empty or len(df) < 60:
        raise InvalidMarketParametersError(
            f"Insufficient historical candles for {clean_asset} ({len(df)} bars < 60)."
        )

    # 3. Parameter Grid
    grid = (
        custom_parameter_grid
        if (custom_parameter_grid and len(custom_parameter_grid) > 0)
        else _build_default_grid(strategy_name)
    )

    model_enum = (
        StakeModel(stake_model.lower())
        if stake_model.lower() in [s.value for s in StakeModel]
        else StakeModel.FLAT
    )

    optimizer = StrategyOptimizerEngine(
        strategy_name=strategy_name,
        asset=clean_asset,
        timeframe_seconds=timeframe_seconds,
        initial_deposit=initial_deposit,
        payout_rate=eff_payout,
        stake_model=model_enum,
        stake_amount=stake_amount,
        stake_percent=stake_percent,
        daily_stop_loss_pct=daily_stop_loss_pct,
        max_combinations=max_combinations,
    )

    return optimizer.run(df, grid)
