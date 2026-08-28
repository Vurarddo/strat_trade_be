from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.data_loader import parse_candles_csv_or_json
from strat_trade.domain.backtest.models import StakeModel
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    RollingVerificationReport,
)
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.ports.candles import CandleFeed


async def execute_rolling_15_verification(
    feed: CandleFeed | None,
    *,
    asset: str,
    timeframe_seconds: int = 60,
    strategy_name: str = "bollinger_atr_reversion",
    strategy_params: dict[str, Any] | None = None,
    payout_rate: float = 0.92,
    min_payout_rate: float = 0.80,
    initial_deposit: float = 1000.0,
    stake_amount: float = 10.0,
    stake_model: str = "flat",
    batch_size: int = 15,
    min_win_rate_pct: float = 53.4,
    candle_count: int = 500,
    auto_tune: bool = False,
    parameter_grid: dict[str, list[Any]] | None = None,
    max_combinations: int = 60,
    end_at: datetime | None = None,
    custom_dataset_content: str | bytes | None = None,
    filename: str = "",
) -> RollingVerificationReport:
    """
    Executes rolling 15-trade verification benchmark with optional auto-tuning feedback loop.
    """
    try:
        sm = StakeModel(stake_model.lower().strip())
    except ValueError:
        sm = StakeModel.FLAT

    if custom_dataset_content:
        df = parse_candles_csv_or_json(custom_dataset_content, filename=filename)
    else:
        if feed is None:
            raise InvalidMarketParametersError(
                "No CandleFeed available and no custom dataset provided."
            )
        candles = await feed.get_candles(
            asset=asset.strip(),
            timeframe=timeframe_seconds,
            count=min(max(candle_count, 50), 2000),
            end_time=end_at,
        )
        if not candles:
            raise InvalidMarketParametersError(f"No candles returned from broker for {asset}.")

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
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    runner = Rolling15TradeVerificationRunner(
        strategy_name=strategy_name,
        strategy_params=strategy_params or {},
        asset=asset.strip(),
        timeframe_seconds=timeframe_seconds,
        payout_rate=Decimal(str(payout_rate)),
        min_payout_rate=Decimal(str(min_payout_rate)),
        initial_deposit=Decimal(str(initial_deposit)),
        stake_model=sm,
        stake_amount=Decimal(str(stake_amount)),
        batch_size=batch_size,
        min_win_rate_pct=Decimal(str(min_win_rate_pct)),
        auto_tune_on_failure=auto_tune,
        max_tuning_combinations=max_combinations,
    )

    if auto_tune:
        return runner.verify_or_optimize(
            df,
            initial_params=strategy_params,
            parameter_grid=parameter_grid,
            max_combinations=max_combinations,
        )
    return runner.run(df, params=strategy_params)
