from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.data_loader import parse_candles_csv_or_json
from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, BacktestSummary, StakeModel
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.ports.candles import CandleFeed


async def execute_backtest(
    feed: CandleFeed | None,
    *,
    asset: str,
    timeframe_seconds: int,
    initial_deposit: float = 1000.0,
    stake_model: str = "flat",
    stake_amount: float = 10.0,
    stake_percent: float = 1.0,
    martingale_multiplier: float = 2.0,
    martingale_max_steps: int = 2,
    payout_rate: float = 0.85,
    min_payout_rate: float = 0.80,
    expiration_bars: int = 3,
    adaptive_expiration: bool = False,
    daily_stop_loss_pct: float = 0.05,
    strategy_name: str = "hybrid_multifactors",
    strategy_params: dict[str, Any] | None = None,
    candle_count: int = 500,
    end_at: datetime | None = None,
    custom_dataset_content: str | bytes | None = None,
    filename: str = "",
    expiration_seconds: int | None = None,
) -> BacktestSummary:
    """
    Execute a full binary options backtest either from live/history broker feed
    or from an uploaded CSV/JSON dataset.
    """
    try:
        sm = StakeModel(stake_model.lower().strip())
    except ValueError:
        sm = StakeModel.FLAT

    config = BacktestConfig(
        asset=asset.strip(),
        timeframe_seconds=timeframe_seconds,
        initial_deposit=Decimal(str(initial_deposit)),
        stake_model=sm,
        stake_amount=Decimal(str(stake_amount)),
        stake_percent=Decimal(str(stake_percent)),
        martingale_multiplier=Decimal(str(martingale_multiplier)),
        martingale_max_steps=martingale_max_steps,
        payout_rate=Decimal(str(payout_rate)),
        min_payout_rate=Decimal(str(min_payout_rate)),
        expiration_bars=max(1, expiration_bars),
        adaptive_expiration=adaptive_expiration,
        daily_stop_loss_pct=Decimal(str(daily_stop_loss_pct)),
        strategy_name=strategy_name,
        strategy_params=strategy_params or {},
        expiration_seconds=expiration_seconds,
    )

    if custom_dataset_content:
        df = parse_candles_csv_or_json(custom_dataset_content, filename=filename)
    else:
        if feed is None:
            raise InvalidMarketParametersError(
                "No CandleFeed available and no custom dataset provided."
            )
        # Fetch from broker
        candles = await feed.get_candles(
            asset=asset,
            timeframe=timeframe_seconds,
            count=min(max(candle_count, 50), 2000),
            end_time=end_at,
        )
        if not candles:
            raise InvalidMarketParametersError(f"No candles returned from broker for {asset}.")

        rows = []
        for c in candles:
            rows.append(
                {
                    "timestamp": c.open_time,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume) if c.volume is not None else 0.0,
                }
            )
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    engine = BinaryBacktestEngine(config)
    return engine.run(df)
