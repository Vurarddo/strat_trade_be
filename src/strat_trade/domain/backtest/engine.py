from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd

from strat_trade.domain.backtest.models import (
    BacktestConfig,
    BacktestSummary,
    BacktestTrade,
    EquityPoint,
    StakeModel,
    TradeAction,
    TradeOutcome,
)

if TYPE_CHECKING:
    from strat_trade.domain.strategies.base import BaseStrategy


class BinaryBacktestEngine:
    """
    Vectorized and event-driven binary options backtesting engine with support for:
    - Multiple Money Management Models (Flat, Compounding %, Capped Martingale)
    - Session Stop-Loss Circuit Breakers
    - Payout Filtering
    - Expiration verification (fixed or ATR-adaptive)
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.strategy = self._create_strategy()

    def _create_strategy(self) -> BaseStrategy:
        from strat_trade.domain.strategies.registry import get_strategy_instance

        params = dict(self.config.strategy_params or {})
        params["base_expiration_bars"] = self.config.expiration_bars
        params["adaptive_expiration_enabled"] = self.config.adaptive_expiration
        return get_strategy_instance(self.config.strategy_name, **params)

    def run(self, df_raw: pd.DataFrame | list[Any]) -> BacktestSummary:
        """
        Run backtest over a DataFrame or list of Candle objects with OHLCV data.
        Columns required: timestamp / open_time, open, high, low, close, volume (optional).
        """
        if isinstance(df_raw, list):
            df_norm = pd.DataFrame(
                [
                    {
                        "timestamp": getattr(c, "open_time", getattr(c, "timestamp", None)),
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(getattr(c, "volume", 0.0)),
                    }
                    for c in df_raw
                ]
            )
        else:
            df_norm = df_raw.copy()

        if "timestamp" not in df_norm.columns and "open_time" in df_norm.columns:
            df_norm["timestamp"] = df_norm["open_time"]
        elif "timestamp" not in df_norm.columns:
            df_norm["timestamp"] = pd.date_range(
                end=pd.Timestamp.now(tz="UTC"), periods=len(df_norm), freq="1min"
            )

        df_raw = df_norm

        eff_payout = Decimal(str(self.config.payout_rate))
        min_payout = Decimal(str(self.config.min_payout_rate))

        # Payout Filter check
        if eff_payout < min_payout:
            p_pct = eff_payout * 100
            min_pct = min_payout * 100
            return self._empty_summary(
                df_raw,
                f"Payout rate {p_pct}% is below minimum required {min_pct}%.",
            )

        df = self.strategy.prepare_dataframe(df_raw)
        n = len(df)
        if n < 40:
            return self._empty_summary(
                df_raw, "Insufficient historical candles for backtesting (< 40 bars)."
            )

        current_balance = Decimal(str(self.config.initial_deposit))
        peak_balance = current_balance
        max_drawdown_amount = Decimal("0.0")
        max_drawdown_pct = Decimal("0.0")

        trades: list[BacktestTrade] = []
        equity_curve: list[EquityPoint] = [
            EquityPoint(
                timestamp=df.iloc[0]["timestamp"].to_pydatetime()
                if hasattr(df.iloc[0]["timestamp"], "to_pydatetime")
                else pd.to_datetime(df.iloc[0]["timestamp"]).to_pydatetime(),
                balance=current_balance,
                drawdown_pct=Decimal("0.0"),
            )
        ]

        # State tracking for Money Management
        consecutive_losses = 0
        consecutive_wins = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0

        # Session Stop-Loss
        session_start_balance = current_balance
        stop_loss_pct = Decimal(str(self.config.daily_stop_loss_pct))

        # In binary options, don't open overlapping trades on the same asset if still active
        next_available_idx = 0

        for i in range(50, n - 1):
            if i < next_available_idx:
                continue

            # Check session stop-loss
            drawdown_from_session = (
                session_start_balance - current_balance
            ) / session_start_balance
            if drawdown_from_session >= stop_loss_pct:
                break

            sig = self.strategy.evaluate_bar(df, i)
            if sig.action is None:
                continue

            exp_bars = sig.expiration_bars
            exit_idx = i + exp_bars
            if exit_idx >= n:
                # Candle timeline ended before trade expired
                break

            # Calculate Stake according to model
            if self.config.stake_model == StakeModel.FLAT:
                stake = Decimal(str(self.config.stake_amount))
            elif self.config.stake_model == StakeModel.PERCENT:
                pct = Decimal(str(self.config.stake_percent)) / Decimal("100.0")
                stake = current_balance * pct
            elif self.config.stake_model == StakeModel.MARTINGALE:
                base_stake = Decimal(str(self.config.stake_amount))
                if (
                    consecutive_losses > 0
                    and consecutive_losses <= self.config.martingale_max_steps
                ):
                    multiplier = (
                        Decimal(str(self.config.martingale_multiplier)) ** consecutive_losses
                    )
                    stake = base_stake * multiplier
                else:
                    stake = base_stake
            else:
                stake = Decimal(str(self.config.stake_amount))

            # Bound stake by remaining balance
            stake = min(stake, current_balance)
            if stake <= Decimal("0.0"):
                break

            # Execution prices
            entry_row = df.iloc[i]
            exit_row = df.iloc[exit_idx]

            entry_price = Decimal(str(entry_row["close"]))
            exit_price = Decimal(str(exit_row["close"]))

            # Evaluate Outcome
            if sig.action == TradeAction.CALL:
                if exit_price > entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = stake * eff_payout
                elif exit_price < entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -stake
                else:
                    outcome = TradeOutcome.DRAW
                    pnl = Decimal("0.0")
            else:  # PUT
                if exit_price < entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = stake * eff_payout
                elif exit_price > entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -stake
                else:
                    outcome = TradeOutcome.DRAW
                    pnl = Decimal("0.0")

            current_balance += pnl

            if outcome == TradeOutcome.WIN:
                consecutive_wins += 1
                consecutive_losses = 0
                if consecutive_wins > max_consecutive_wins:
                    max_consecutive_wins = consecutive_wins
            elif outcome == TradeOutcome.LOSS:
                consecutive_losses += 1
                consecutive_wins = 0
                if consecutive_losses > max_consecutive_losses:
                    max_consecutive_losses = consecutive_losses
            else:
                # DRAW
                consecutive_losses = 0
                consecutive_wins = 0

            # Update Peak & Drawdown
            if current_balance > peak_balance:
                peak_balance = current_balance
            current_dd_amount = peak_balance - current_balance
            current_dd_pct = (
                (current_dd_amount / peak_balance * Decimal("100.0"))
                if peak_balance > 0
                else Decimal("0.0")
            )

            if current_dd_amount > max_drawdown_amount:
                max_drawdown_amount = current_dd_amount
            if current_dd_pct > max_drawdown_pct:
                max_drawdown_pct = current_dd_pct

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

            trade = BacktestTrade(
                entry_index=i,
                exit_index=exit_idx,
                entry_time=entry_dt,
                exit_time=exit_dt,
                action=sig.action,
                entry_price=entry_price,
                exit_price=exit_price,
                stake=round(stake, 2),
                payout_rate=self.config.payout_rate,
                pnl=round(pnl, 2),
                outcome=outcome,
                balance_after=round(current_balance, 2),
                confidence=sig.confidence,
                expiration_seconds=exp_bars * self.config.timeframe_seconds,
                metadata=sig.metadata,
            )
            trades.append(trade)

            equity_curve.append(
                EquityPoint(
                    timestamp=exit_dt,
                    balance=round(current_balance, 2),
                    drawdown_pct=round(current_dd_pct, 2),
                )
            )

            # Prevent opening another trade until this one has expired
            next_available_idx = exit_idx

        # Calculate Overall Summary Metrics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
        losing_trades = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
        draw_trades = sum(1 for t in trades if t.outcome == TradeOutcome.DRAW)

        decisive_trades = winning_trades + losing_trades
        win_rate_pct = (
            (Decimal(str(winning_trades)) / Decimal(str(decisive_trades)) * Decimal("100.0"))
            if decisive_trades > 0
            else Decimal("0.0")
        )

        total_gain = sum((t.pnl for t in trades if t.pnl > 0), Decimal("0.0"))
        total_loss = abs(sum((t.pnl for t in trades if t.pnl < 0), Decimal("0.0")))
        if total_loss > Decimal("0.0"):
            profit_factor = round(total_gain / total_loss, 2)
        elif total_gain > Decimal("0.0"):
            profit_factor = Decimal("99.99")
        else:
            profit_factor = Decimal("0.0")

        initial_dep = Decimal(str(self.config.initial_deposit))
        net_profit = round(current_balance - initial_dep, 2)
        roi_pct = (
            round((net_profit / initial_dep * Decimal("100.0")), 2)
            if initial_dep > 0
            else Decimal("0.0")
        )

        return BacktestSummary(
            asset=self.config.asset,
            timeframe_seconds=self.config.timeframe_seconds,
            initial_deposit=initial_dep,
            final_balance=round(current_balance, 2),
            net_profit=net_profit,
            roi_pct=roi_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            draw_trades=draw_trades,
            win_rate_pct=round(win_rate_pct, 2),
            profit_factor=profit_factor,
            max_drawdown_amount=round(max_drawdown_amount, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            trades=trades,
            equity_curve=equity_curve,
            strategy_name=self.config.strategy_name,
        )

    def _empty_summary(self, df_raw: pd.DataFrame, message: str) -> BacktestSummary:
        dep = Decimal(str(self.config.initial_deposit))
        return BacktestSummary(
            asset=self.config.asset,
            timeframe_seconds=self.config.timeframe_seconds,
            initial_deposit=dep,
            final_balance=dep,
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
            trades=[],
            equity_curve=[],
            strategy_name=self.config.strategy_name,
        )
