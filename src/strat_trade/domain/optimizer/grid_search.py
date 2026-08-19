from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, StakeModel


@dataclass
class OptimizationResultItem:
    rank: int
    params: dict[str, Any]
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    profit_factor: float
    net_profit: float
    roi_pct: float
    max_drawdown_pct: float
    max_consecutive_losses: int
    rank_score: float


@dataclass
class OptimizationReport:
    strategy_name: str
    asset: str
    timeframe_seconds: int
    total_combinations_tested: int
    candle_count: int
    best_params: dict[str, Any]
    results: list[OptimizationResultItem]


class StrategyOptimizerEngine:
    """Hyperparameter Grid Search Optimizer for binary options trading strategies."""

    def __init__(
        self,
        *,
        strategy_name: str,
        asset: str = "EURUSD_otc",
        timeframe_seconds: int = 60,
        initial_deposit: float = 1000.0,
        payout_rate: float = 0.85,
        stake_model: StakeModel = StakeModel.FLAT,
        stake_amount: float = 10.0,
        stake_percent: float = 1.0,
        daily_stop_loss_pct: float = 0.05,
        max_combinations: int = 80,
    ) -> None:
        self.strategy_name = strategy_name
        self.asset = asset
        self.timeframe_seconds = timeframe_seconds
        self.initial_deposit = initial_deposit
        self.payout_rate = payout_rate
        self.stake_model = stake_model
        self.stake_amount = stake_amount
        self.stake_percent = stake_percent
        self.daily_stop_loss_pct = daily_stop_loss_pct
        self.max_combinations = max(1, min(max_combinations, 200))

    def run(self, df_raw: pd.DataFrame, parameter_grid: dict[str, list[Any]]) -> OptimizationReport:
        if df_raw.empty or len(df_raw) < 60:
            return OptimizationReport(
                strategy_name=self.strategy_name,
                asset=self.asset,
                timeframe_seconds=self.timeframe_seconds,
                total_combinations_tested=0,
                candle_count=len(df_raw),
                best_params={},
                results=[],
            )

        # Generate Cartesian product of parameters
        keys = list(parameter_grid.keys())
        values = list(parameter_grid.values())
        raw_combos = [dict(zip(keys, prod)) for prod in itertools.product(*values)]

        # Sample if combinations exceed limit
        if len(raw_combos) > self.max_combinations:
            step = len(raw_combos) / self.max_combinations
            combos = [raw_combos[int(i * step)] for i in range(self.max_combinations)]
        else:
            combos = raw_combos

        results: list[OptimizationResultItem] = []

        for combo in combos:
            exp_bars = combo.get("base_expiration_bars", combo.get("expiration_bars", 3))
            adaptive_exp = combo.get("adaptive_expiration_enabled", False)

            cfg = BacktestConfig(
                asset=self.asset,
                timeframe_seconds=self.timeframe_seconds,
                initial_deposit=Decimal(str(self.initial_deposit)),
                stake_model=self.stake_model,
                stake_amount=Decimal(str(self.stake_amount)),
                stake_percent=Decimal(str(self.stake_percent)),
                payout_rate=Decimal(str(self.payout_rate)),
                min_payout_rate=Decimal("0.70"),
                expiration_bars=int(exp_bars),
                adaptive_expiration=bool(adaptive_exp),
                daily_stop_loss_pct=Decimal(str(self.daily_stop_loss_pct)),
                strategy_name=self.strategy_name,
                strategy_params=combo,
            )

            engine = BinaryBacktestEngine(cfg)
            summary = engine.run(df_raw)

            wr = float(summary.win_rate_pct)
            pf = float(summary.profit_factor)
            dd = float(summary.max_drawdown_pct)
            net = float(summary.net_profit)
            trades = summary.total_trades

            # Scoring formula: favors high WR & PF with low drawdown and adequate trade volume
            if trades >= 3:
                dd_factor = max(0.05, 1.0 - (dd / 100.0))
                score = (wr * pf * dd_factor) + (net * 0.1)
            else:
                score = 0.0

            results.append(
                OptimizationResultItem(
                    rank=0,
                    params=combo,
                    total_trades=trades,
                    winning_trades=summary.winning_trades,
                    losing_trades=summary.losing_trades,
                    draw_trades=summary.draw_trades,
                    win_rate_pct=round(wr, 2),
                    profit_factor=round(pf, 2),
                    net_profit=round(net, 2),
                    roi_pct=round(float(summary.roi_pct), 2),
                    max_drawdown_pct=round(dd, 2),
                    max_consecutive_losses=summary.max_consecutive_losses,
                    rank_score=round(score, 2),
                )
            )

        # Sort descending by rank_score, then win_rate_pct, then net_profit
        results.sort(
            key=lambda x: (x.rank_score, x.win_rate_pct, x.net_profit, x.total_trades),
            reverse=True,
        )

        for i, item in enumerate(results, start=1):
            item.rank = i

        best_params = results[0].params if results else {}

        return OptimizationReport(
            strategy_name=self.strategy_name,
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            total_combinations_tested=len(results),
            candle_count=len(df_raw),
            best_params=best_params,
            results=results,
        )
