from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.models import (
    AssetPerformance,
    BacktestTrade,
    EquityPoint,
    PortfolioBacktestConfig,
    PortfolioBacktestSummary,
    StakeModel,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.strategies.base import BaseStrategy
from strat_trade.domain.strategies.registry import get_strategy_instance


@dataclass
class _CandidateSignal:
    asset: str
    entry_index: int
    entry_time: datetime
    exit_index: int
    exit_time: datetime
    action: TradeAction
    confidence: float
    expiration_seconds: int
    entry_price: Decimal
    payout_rate: Decimal
    metadata: dict[str, Any]


class PortfolioBacktestEngine:
    """Multi-asset chronological binary options portfolio backtest engine.

    Simulates trading multiple assets concurrently against a shared deposit with
    concurrent trade limits, per-asset payout rates, and unified risk governance.
    """

    def __init__(self, config: PortfolioBacktestConfig) -> None:
        self.config = config
        params = dict(config.strategy_params or {})
        params["base_expiration_bars"] = config.expiration_bars
        params["adaptive_expiration_enabled"] = config.adaptive_expiration
        self.strategy: BaseStrategy = get_strategy_instance(config.strategy_name, **params)

    def run(self, asset_dfs: dict[str, pd.DataFrame]) -> PortfolioBacktestSummary:
        initial_dep = Decimal(str(self.config.initial_deposit))
        if not asset_dfs:
            return self._empty_summary(initial_dep)

        # 1. Prepare indicators and signals for each asset
        prepared_dfs: dict[str, pd.DataFrame] = {}
        all_signals: list[_CandidateSignal] = []

        for asset, df_raw in asset_dfs.items():
            if df_raw is None or len(df_raw) < 60:
                continue

            payout = self.config.payout_rates.get(asset, Decimal("0.85"))
            if payout < self.config.min_payout_rate:
                continue

            prep = self.strategy.prepare_dataframe(df_raw)
            prepared_dfs[asset] = prep
            n = len(prep)

            for i in range(50, n - 1):
                sig = self.strategy.evaluate_bar(prep, i)
                if sig.action is None:
                    continue

                exp_bars = sig.expiration_bars
                exit_idx = i + exp_bars
                if exit_idx >= n:
                    exit_idx = n - 1

                entry_row = prep.iloc[i]
                exit_row = prep.iloc[exit_idx]

                entry_t = entry_row["timestamp"]
                exit_t = exit_row["timestamp"]
                entry_dt = (
                    entry_t.to_pydatetime()
                    if hasattr(entry_t, "to_pydatetime")
                    else pd.to_datetime(entry_t).to_pydatetime()
                )
                exit_dt = (
                    exit_t.to_pydatetime()
                    if hasattr(exit_t, "to_pydatetime")
                    else pd.to_datetime(exit_t).to_pydatetime()
                )

                all_signals.append(
                    _CandidateSignal(
                        asset=asset,
                        entry_index=i,
                        entry_time=entry_dt,
                        exit_index=exit_idx,
                        exit_time=exit_dt,
                        action=sig.action,
                        confidence=sig.confidence,
                        expiration_seconds=exp_bars * self.config.timeframe_seconds,
                        entry_price=Decimal(str(round(entry_row["close"], 5))),
                        payout_rate=payout,
                        metadata=sig.metadata,
                    )
                )

        if not all_signals:
            return self._empty_summary(initial_dep)

        # 2. Sort all signals chronologically
        all_signals.sort(key=lambda s: s.entry_time)

        # 3. Simulate chronological execution with shared balance & concurrency control
        current_balance = initial_dep
        peak_balance = current_balance
        max_drawdown_amount = Decimal("0.0")
        max_drawdown_pct = Decimal("0.0")
        session_start_balance = current_balance

        active_trades: list[BacktestTrade] = []
        completed_trades: list[BacktestTrade] = []
        equity_curve: list[EquityPoint] = [
            EquityPoint(
                timestamp=all_signals[0].entry_time,
                balance=current_balance,
                drawdown_pct=Decimal("0.0"),
            )
        ]

        consecutive_losses = 0
        consecutive_wins = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0

        def resolve_trade(t: BacktestTrade, exit_close: Decimal) -> None:
            nonlocal current_balance, peak_balance, max_drawdown_amount, max_drawdown_pct
            nonlocal consecutive_losses, consecutive_wins, max_consecutive_wins
            nonlocal max_consecutive_losses

            # Evaluate binary outcome
            if t.action == TradeAction.CALL:
                if exit_close > t.entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = t.stake * t.payout_rate
                elif exit_close < t.entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -t.stake
                else:
                    outcome = TradeOutcome.DRAW
                    pnl = Decimal("0.0")
            else:  # PUT
                if exit_close < t.entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = t.stake * t.payout_rate
                elif exit_close > t.entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -t.stake
                else:
                    outcome = TradeOutcome.DRAW
                    pnl = Decimal("0.0")

            t.exit_price = exit_close
            t.outcome = outcome
            t.pnl = round(pnl, 2)
            current_balance = round(current_balance + t.pnl, 2)
            t.balance_after = current_balance

            # Update streaks
            if outcome == TradeOutcome.WIN:
                consecutive_wins += 1
                consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
            elif outcome == TradeOutcome.LOSS:
                consecutive_losses += 1
                consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

            # Drawdown metrics
            if current_balance > peak_balance:
                peak_balance = current_balance
            dd_amount = peak_balance - current_balance
            dd_pct = (
                (dd_amount / peak_balance * Decimal("100.0"))
                if peak_balance > 0
                else Decimal("0.0")
            )
            if dd_amount > max_drawdown_amount:
                max_drawdown_amount = dd_amount
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

            equity_curve.append(
                EquityPoint(
                    timestamp=t.exit_time,
                    balance=current_balance,
                    drawdown_pct=round(dd_pct, 2),
                )
            )

        # Iterate over all candidate signals
        for sig in all_signals:
            # First, resolve active trades that closed before or at current signal timestamp
            still_active: list[BacktestTrade] = []
            for t in active_trades:
                if t.exit_time <= sig.entry_time:
                    # Resolve using asset's exit candle
                    prep = prepared_dfs[t.asset]
                    exit_close = Decimal(str(round(prep.iloc[t.exit_index]["close"], 5)))
                    resolve_trade(t, exit_close)
                    completed_trades.append(t)
                else:
                    still_active.append(t)
            active_trades = still_active

            # Session Stop-Loss Check
            dd_from_start = (session_start_balance - current_balance) / session_start_balance
            if dd_from_start >= self.config.daily_stop_loss_pct:
                break

            # Concurrency limit check
            if len(active_trades) >= self.config.max_concurrent_trades:
                continue

            # Don't open multiple trades on the exact same asset simultaneously
            if any(t.asset == sig.asset for t in active_trades):
                continue

            # Calculate Stake
            if self.config.stake_model == StakeModel.FLAT:
                stake = Decimal(str(self.config.stake_amount))
            elif self.config.stake_model == StakeModel.PERCENT:
                pct = Decimal(str(self.config.stake_percent)) / Decimal("100.0")
                stake = max(Decimal("1.0"), round(current_balance * pct, 2))
            elif self.config.stake_model == StakeModel.MARTINGALE:
                base_stake = Decimal(str(self.config.stake_amount))
                if 0 < consecutive_losses <= self.config.martingale_max_steps:
                    multiplier = (
                        Decimal(str(self.config.martingale_multiplier)) ** consecutive_losses
                    )
                    stake = base_stake * multiplier
                else:
                    stake = base_stake
            else:
                stake = Decimal("10.0")

            stake = min(stake, current_balance)
            if stake <= Decimal("0.0"):
                break

            trade = BacktestTrade(
                entry_index=sig.entry_index,
                exit_index=sig.exit_index,
                entry_time=sig.entry_time,
                exit_time=sig.exit_time,
                action=sig.action,
                entry_price=sig.entry_price,
                exit_price=Decimal("0.0"),
                stake=stake,
                payout_rate=sig.payout_rate,
                pnl=Decimal("0.0"),
                outcome=TradeOutcome.DRAW,
                balance_after=current_balance,
                confidence=sig.confidence,
                expiration_seconds=sig.expiration_seconds,
                asset=sig.asset,
                metadata=sig.metadata,
            )
            active_trades.append(trade)

        # Resolve any remaining active trades
        for t in active_trades:
            prep = prepared_dfs[t.asset]
            exit_close = Decimal(str(round(prep.iloc[t.exit_index]["close"], 5)))
            resolve_trade(t, exit_close)
            completed_trades.append(t)

        # 4. Calculate Per-Asset Performance Stats
        per_asset_stats = self._calc_per_asset_stats(completed_trades, self.config.assets)

        # 5. Compile Overall Portfolio Stats
        total_trades = len(completed_trades)
        winning_trades = sum(1 for t in completed_trades if t.outcome == TradeOutcome.WIN)
        losing_trades = sum(1 for t in completed_trades if t.outcome == TradeOutcome.LOSS)
        draw_trades = sum(1 for t in completed_trades if t.outcome == TradeOutcome.DRAW)

        win_rate_pct = (
            round((Decimal(winning_trades) / Decimal(total_trades) * Decimal("100.0")), 2)
            if total_trades > 0
            else Decimal("0.0")
        )

        gross_profit = sum((t.pnl for t in completed_trades if t.pnl > 0), Decimal("0.0"))
        gross_loss = abs(sum((t.pnl for t in completed_trades if t.pnl < 0), Decimal("0.0")))
        profit_factor = (
            round(gross_profit / gross_loss, 2)
            if gross_loss > 0
            else (Decimal("999.0") if gross_profit > 0 else Decimal("0.0"))
        )

        net_profit = round(current_balance - initial_dep, 2)
        roi_pct = (
            round((net_profit / initial_dep * Decimal("100.0")), 2)
            if initial_dep > 0
            else Decimal("0.0")
        )

        return PortfolioBacktestSummary(
            assets=list(asset_dfs.keys()),
            timeframe_seconds=self.config.timeframe_seconds,
            initial_deposit=initial_dep,
            final_balance=current_balance,
            net_profit=net_profit,
            roi_pct=roi_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            draw_trades=draw_trades,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            max_drawdown_amount=round(max_drawdown_amount, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            per_asset_stats=per_asset_stats,
            trades=completed_trades,
            equity_curve=equity_curve,
            strategy_name=self.config.strategy_name,
        )

    def _calc_per_asset_stats(
        self, trades: list[BacktestTrade], configured_assets: list[str]
    ) -> list[AssetPerformance]:
        total_p_trades = len(trades)
        trades_by_asset: dict[str, list[BacktestTrade]] = {a: [] for a in configured_assets}
        for t in trades:
            if t.asset not in trades_by_asset:
                trades_by_asset[t.asset] = []
            trades_by_asset[t.asset].append(t)

        stats: list[AssetPerformance] = []
        for asset, a_trades in trades_by_asset.items():
            cnt = len(a_trades)
            wins = sum(1 for t in a_trades if t.outcome == TradeOutcome.WIN)
            losses = sum(1 for t in a_trades if t.outcome == TradeOutcome.LOSS)
            draws = sum(1 for t in a_trades if t.outcome == TradeOutcome.DRAW)
            wr = (
                round(Decimal(wins) / Decimal(cnt) * Decimal("100.0"), 2)
                if cnt > 0
                else Decimal("0.0")
            )
            net_p = round(sum((t.pnl for t in a_trades), Decimal("0.0")), 2)
            tot_staked = sum((t.stake for t in a_trades), Decimal("0.0"))
            roi = (
                round(net_p / tot_staked * Decimal("100.0"), 2)
                if tot_staked > 0
                else Decimal("0.0")
            )

            gp = sum((t.pnl for t in a_trades if t.pnl > 0), Decimal("0.0"))
            gl = abs(sum((t.pnl for t in a_trades if t.pnl < 0), Decimal("0.0")))
            pf = round(gp / gl, 2) if gl > 0 else (Decimal("999.0") if gp > 0 else Decimal("0.0"))

            # Prettify name
            payout = self.config.payout_rates.get(asset, Decimal("0.85"))
            name = asset.replace("_otc", " OTC").replace("_", "/").upper()

            count_pct = (
                round(Decimal(cnt) / Decimal(total_p_trades) * Decimal("100.0"), 2)
                if total_p_trades > 0
                else Decimal("0.0")
            )

            stats.append(
                AssetPerformance(
                    asset=asset,
                    name=name,
                    payout_rate=payout,
                    total_trades=cnt,
                    winning_trades=wins,
                    losing_trades=losses,
                    draw_trades=draws,
                    win_rate_pct=wr,
                    net_profit=net_p,
                    roi_pct=roi,
                    profit_factor=pf,
                    max_drawdown_amount=Decimal("0.0"),
                    max_drawdown_pct=Decimal("0.0"),
                    trades_count_pct=count_pct,
                )
            )

        # Sort leaderboard by net_profit descending, then win_rate
        stats.sort(key=lambda s: (s.net_profit, s.win_rate_pct), reverse=True)
        return stats

    def _empty_summary(self, initial_dep: Decimal) -> PortfolioBacktestSummary:
        return PortfolioBacktestSummary(
            assets=self.config.assets,
            timeframe_seconds=self.config.timeframe_seconds,
            initial_deposit=initial_dep,
            final_balance=initial_dep,
            net_profit=Decimal("0.0"),
            roi_pct=Decimal("0.0"),
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            draw_trades=0,
            win_rate_pct=Decimal("0.0"),
            profit_factor=Decimal("0.0"),
            max_drawdown_amount=Decimal("0.0"),
            max_drawdown_pct=Decimal("0.0"),
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            per_asset_stats=[],
            trades=[],
            equity_curve=[],
            strategy_name=self.config.strategy_name,
        )
