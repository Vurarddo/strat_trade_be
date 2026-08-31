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
        exp_bars = self.config.expiration_bars
        if self.config.expiration_seconds is not None and self.config.timeframe_seconds > 0:
            exp_bars = max(1, self.config.expiration_seconds // self.config.timeframe_seconds)
        params["base_expiration_bars"] = params.get("base_expiration_bars", exp_bars)
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

        if pd.api.types.is_numeric_dtype(df_norm["timestamp"]):
            first_val = float(df_norm["timestamp"].dropna().iloc[0]) if len(df_norm) > 0 else 0
            if first_val > 1e16:  # nanoseconds
                df_norm["timestamp"] = pd.to_datetime(df_norm["timestamp"], unit="ns", utc=True)
            elif first_val > 1e13:  # microseconds
                df_norm["timestamp"] = pd.to_datetime(df_norm["timestamp"], unit="us", utc=True)
            elif first_val > 1e11:  # milliseconds
                df_norm["timestamp"] = pd.to_datetime(df_norm["timestamp"], unit="ms", utc=True)
            elif first_val > 1e8:  # seconds
                df_norm["timestamp"] = pd.to_datetime(df_norm["timestamp"], unit="s", utc=True)
            else:
                df_norm["timestamp"] = pd.to_datetime(
                    df_norm["timestamp"], utc=True, format="mixed"
                )
        else:
            df_norm["timestamp"] = pd.to_datetime(df_norm["timestamp"], utc=True, format="mixed")

        df_norm = df_norm.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
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
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
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
                else pd.to_datetime(df.iloc[0]["timestamp"], utc=True).to_pydatetime(),
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

            # Determine trade expiration in seconds
            if self.config.expiration_seconds is not None:
                if (
                    self.config.adaptive_expiration
                    and self.config.expiration_bars > 0
                    and sig.expiration_bars != self.config.expiration_bars
                ):
                    exp_seconds = max(
                        1,
                        int(
                            self.config.expiration_seconds
                            * (sig.expiration_bars / self.config.expiration_bars)
                        ),
                    )
                else:
                    exp_seconds = max(1, int(self.config.expiration_seconds))
            else:
                exp_seconds = max(1, int(sig.expiration_bars * self.config.timeframe_seconds))

            entry_row = df.iloc[i]
            entry_t = entry_row["timestamp"]
            entry_time = (
                entry_t if isinstance(entry_t, pd.Timestamp) else pd.to_datetime(entry_t, utc=True)
            )
            target_exit_time = entry_time + pd.Timedelta(seconds=exp_seconds)

            # Search forward in the dataframe for the first row where timestamp >= target_exit_time
            exit_idx = int(df["timestamp"].searchsorted(target_exit_time, side="left"))
            if exit_idx <= i or exit_idx >= n or df.iloc[exit_idx]["timestamp"] < target_exit_time:
                exit_idx = None
                for j in range(i + 1, n):
                    if df.iloc[j]["timestamp"] >= target_exit_time:
                        exit_idx = j
                        break

            if exit_idx is None or exit_idx >= n:
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
                expiration_seconds=exp_seconds,
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
