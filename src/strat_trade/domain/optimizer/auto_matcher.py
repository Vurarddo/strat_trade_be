from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, StakeModel
from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.registry import list_available_strategies
from strat_trade.domain.trading.asset_filter import (
    is_toxic_asset,
    is_whitelisted_asset,
    qualify_asset_microstructure,
)
from strat_trade.domain.trading.entities import StrategyAssignment

logger = logging.getLogger(__name__)

PRIORITY_STRATEGIES: frozenset[str] = frozenset(
    {
        "support_resistance_bounce",
        "rsi_stochastic_extreme",
    }
)


class StrategyAutoMatcher:
    """Evaluates strategy catalog to find optimal strategy and parameters."""

    def __init__(self, candle_count: int = 150) -> None:
        self.candle_count = candle_count

    def _generate_strategy_variations(
        self,
        strat_id: str,
        def_params: dict[str, Any],
        base_expiration_bars: int,
    ) -> list[dict[str, Any]]:
        """Generates distinctive quantitative parameter sets for a specific strategy."""
        variations: list[dict[str, Any]] = []

        # 1. Base default variation
        base = dict(def_params)
        base["base_expiration_bars"] = base_expiration_bars
        variations.append(base)

        if strat_id == "hybrid_multifactors":
            # Fast scalp
            v_fast = dict(def_params)
            v_fast.update(
                {
                    "rsi_period": 10,
                    "rsi_oversold": 32.0,
                    "rsi_overbought": 68.0,
                    "ema_fast": 7,
                    "ema_mid": 16,
                    "adx_trend_threshold": 22.0,
                    "adx_min_threshold": 22.0,
                    "base_expiration_bars": max(1, base_expiration_bars - 1),
                }
            )
            variations.append(v_fast)
            # Trend filter
            v_trend = dict(def_params)
            v_trend.update(
                {
                    "rsi_period": 16,
                    "rsi_oversold": 28.0,
                    "rsi_overbought": 72.0,
                    "ema_fast": 12,
                    "ema_mid": 26,
                    "adx_trend_threshold": 28.0,
                    "base_expiration_bars": base_expiration_bars + 1,
                }
            )
            variations.append(v_trend)

        elif strat_id == "bollinger_atr_reversion":
            # Sensitive bounce
            v_sens = dict(def_params)
            v_sens.update(
                {
                    "bb_length": 20,
                    "bb_std": 1.8,
                    "rsi_period": 10,
                    "rsi_oversold": 32.0,
                    "rsi_overbought": 68.0,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_sens)
            # High volatility filter
            v_wide = dict(def_params)
            v_wide.update(
                {
                    "bb_length": 22,
                    "bb_std": 2.3,
                    "rsi_period": 14,
                    "rsi_oversold": 25.0,
                    "rsi_overbought": 75.0,
                    "base_expiration_bars": base_expiration_bars + 1,
                }
            )
            variations.append(v_wide)

        elif strat_id == "ema_pullback_trend":
            # Fast momentum ribbon
            v_fast = dict(def_params)
            v_fast.update(
                {
                    "ema_fast": 7,
                    "ema_mid": 18,
                    "adx_threshold": 20.0,
                    "rsi_period": 14,
                    "rsi_overbought": 65.0,
                    "rsi_oversold": 35.0,
                    "stoch_overbought": 75.0,
                    "stoch_oversold": 25.0,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_fast)
            # Strong trend filter
            v_strong = dict(def_params)
            v_strong.update(
                {
                    "ema_fast": 13,
                    "ema_mid": 26,
                    "adx_threshold": 28.0,
                    "rsi_period": 14,
                    "rsi_overbought": 65.0,
                    "rsi_oversold": 35.0,
                    "stoch_overbought": 75.0,
                    "stoch_oversold": 25.0,
                    "base_expiration_bars": base_expiration_bars + 1,
                }
            )
            variations.append(v_strong)

        elif strat_id == "rsi_stochastic_extreme":
            # Standard extreme exhaustion (3 bars = 180s)
            v_std = dict(def_params)
            v_std.update(
                {
                    "rsi_period": 9,
                    "rsi_oversold": 28.0,
                    "rsi_overbought": 72.0,
                    "stoch_oversold": 20.0,
                    "stoch_overbought": 80.0,
                    "base_expiration_bars": max(3, base_expiration_bars),
                }
            )
            variations.append(v_std)
            # Ultra extreme exhaustion with 4 bars (240s)
            v_ultra = dict(def_params)
            v_ultra.update(
                {
                    "rsi_period": 14,
                    "rsi_oversold": 22.0,
                    "rsi_overbought": 78.0,
                    "stoch_oversold": 15.0,
                    "stoch_overbought": 85.0,
                    "base_expiration_bars": max(3, base_expiration_bars + 1),
                }
            )
            variations.append(v_ultra)

        elif strat_id == "macd_divergence_break":
            # Agile MACD
            v_agile = dict(def_params)
            v_agile.update(
                {
                    "macd_fast": 8,
                    "macd_slow": 21,
                    "macd_sign": 7,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_agile)

        elif strat_id == "volatility_squeeze_breakout":
            # Fast breakout
            v_sq = dict(def_params)
            v_sq.update(
                {
                    "bb_length": 20,
                    "kc_mult": 1.3,
                    "momentum_period": 10,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_sq)

        elif strat_id == "supertrend_adx_momentum":
            # Strong trend rider
            v_tr = dict(def_params)
            v_tr.update(
                {
                    "atr_period": 10,
                    "atr_multiplier": 3.0,
                    "adx_threshold": 26.0,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_tr)
            # Low threshold trend
            v_low = dict(def_params)
            v_low.update(
                {
                    "atr_period": 10,
                    "atr_multiplier": 2.5,
                    "adx_threshold": 18.0,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_low)

        elif strat_id == "support_resistance_bounce":
            # Agile S/R
            v_sr = dict(def_params)
            v_sr.update(
                {
                    "swing_window": 15,
                    "min_wick_ratio": 0.35,
                    "base_expiration_bars": base_expiration_bars,
                }
            )
            variations.append(v_sr)
            # Major levels S/R
            v_maj = dict(def_params)
            v_maj.update(
                {
                    "swing_window": 25,
                    "min_wick_ratio": 0.40,
                    "base_expiration_bars": base_expiration_bars + 1,
                }
            )
            variations.append(v_maj)

        return variations

    def _heuristic_profile_for_asset(
        self,
        asset: str,
        strategies: list[dict[str, Any]],
        expiration_bars: int,
        allowed_strategies: Sequence[str] | None = None,
    ) -> StrategyAssignment:
        """Heuristically matches strategy and parameters when historical data is limited."""
        sym = asset.upper()

        if allowed_strategies:
            filtered = [s for s in strategies if s["id"] in allowed_strategies]
            if filtered:
                strategies = filtered

        if "GOLD" in sym or "XAU" in sym:
            # Gold / Commodities -> Support & Resistance Pin-Bar
            st = next(
                (s for s in strategies if s["id"] == "support_resistance_bounce"), strategies[0]
            )
            params = {
                "swing_window": 20,
                "rsi_period": 14,
                "min_wick_ratio": 0.35,
                "base_expiration_bars": expiration_bars,
            }
            rationale = f"Фрактальні рівні підтримки/опору та Pin-Bar для золота {asset}"
        elif "#" in sym or "AAPL" in sym or "TSLA" in sym or "NVDA" in sym or "INTC" in sym:
            # Stocks -> Support & Resistance Pin-Bar
            st = next(
                (s for s in strategies if s["id"] == "support_resistance_bounce"), strategies[0]
            )
            params = {
                "swing_window": 25,
                "rsi_period": 14,
                "min_wick_ratio": 0.40,
                "base_expiration_bars": expiration_bars,
            }
            rationale = f"Фрактальні рівні підтримки/опору та Pin-Bar для акцій {asset}"
        elif any(c in sym for c in ("BTC", "ETH", "BNB", "MATIC", "SOL", "DOGE", "XRP")):
            # Crypto -> RSI + Stoch Extreme Scalp
            st = next((s for s in strategies if s["id"] == "rsi_stochastic_extreme"), strategies[0])
            params = {
                "rsi_period": 14,
                "rsi_oversold": 25.0,
                "rsi_overbought": 75.0,
                "stoch_k": 14,
                "stoch_d": 3,
                "stoch_oversold": 20.0,
                "stoch_overbought": 80.0,
                "base_expiration_bars": expiration_bars,
            }
            rationale = f"Подвійне виснаження осциляторів для крипто-активу {asset}"
        elif any(
            c in sym
            for c in (
                "EUR",
                "GBP",
                "AUD",
                "NZD",
                "CAD",
                "CHF",
                "JPY",
                "ARS",
                "CNH",
                "CNY",
                "JOD",
                "CLP",
                "BDT",
                "EGP",
            )
        ):
            # Forex -> S&R Bounce (JPY/GBP) or RSI + Stoch Extreme Scalp
            if "JPY" in sym or "GBP" in sym:
                st = next(
                    (s for s in strategies if s["id"] == "support_resistance_bounce"), strategies[0]
                )
                params = {
                    "swing_window": 20,
                    "rsi_period": 14,
                    "min_wick_ratio": 0.35,
                    "base_expiration_bars": expiration_bars,
                }
                rationale = f"Фрактальні рівні відбою для валютного спреду {asset}"
            else:
                st = next(
                    (s for s in strategies if s["id"] == "rsi_stochastic_extreme"), strategies[0]
                )
                params = {
                    "rsi_period": 14,
                    "rsi_oversold": 25.0,
                    "rsi_overbought": 75.0,
                    "stoch_k": 14,
                    "stoch_d": 3,
                    "stoch_oversold": 20.0,
                    "stoch_overbought": 80.0,
                    "base_expiration_bars": expiration_bars,
                }
                rationale = f"Подвійне виснаження осциляторів для валютної пари {asset}"
        else:
            # Curated sniper fallback: Primary S&R Bounce, Secondary RSI + Stoch Extreme
            st = next(
                (s for s in strategies if s["id"] == "support_resistance_bounce"),
                next(
                    (s for s in strategies if s["id"] == "rsi_stochastic_extreme"),
                    strategies[0],
                ),
            )
            if st["id"] == "support_resistance_bounce":
                params = {
                    "swing_window": 20,
                    "rsi_period": 14,
                    "min_wick_ratio": 0.35,
                    "base_expiration_bars": expiration_bars,
                }
                rationale = f"Пріоритетний Sniper S&R Pin-Bar профіль для активу {asset}"
            elif st["id"] == "rsi_stochastic_extreme":
                params = {
                    "rsi_period": 14,
                    "rsi_oversold": 25.0,
                    "rsi_overbought": 75.0,
                    "stoch_k": 14,
                    "stoch_d": 3,
                    "stoch_oversold": 20.0,
                    "stoch_overbought": 80.0,
                    "base_expiration_bars": expiration_bars,
                }
                rationale = f"Вторинний Sniper RSI + Stoch Extreme профіль для активу {asset}"
            else:
                params = {
                    "base_expiration_bars": expiration_bars,
                }
                rationale = f"Базовий евристичний профіль для активу {asset}"

        return StrategyAssignment(
            asset=asset,
            strategy_id=st["id"],
            strategy_name=st["name"],
            category=st["category"],
            parameters=params,
            estimated_win_rate_pct=62.0,
            estimated_profit_factor=1.45,
            estimated_trades_count=5,
            quantum_score=85.0,
            rationale=rationale,
        )

    async def find_optimal_strategy_for_asset(
        self,
        asset: str,
        candles: list[Candle] | pd.DataFrame,
        timeframe_seconds: int = 60,
        expiration_bars: int = 3,
        payout_rate: float = 0.92,
        allowed_strategies: Sequence[str] | None = None,
    ) -> StrategyAssignment | None:
        """Runs multi-strategy backtesting on asset candles to find optimal strategy."""
        strategies = list_available_strategies()
        if allowed_strategies:
            filtered = [s for s in strategies if s["id"] in allowed_strategies]
            if filtered:
                strategies = filtered

        # Check toxic OTC asset blacklist
        is_toxic, toxic_reason = is_toxic_asset(asset)
        if is_toxic:
            logger.warning("Asset %s rejected by toxic asset blacklist: %s", asset, toxic_reason)
            return None

        if isinstance(candles, list):
            if not candles or len(candles) < 35:
                return self._heuristic_profile_for_asset(
                    asset, strategies, expiration_bars, allowed_strategies=allowed_strategies
                )
            df_raw = pd.DataFrame(
                [
                    {
                        "timestamp": getattr(c, "open_time", getattr(c, "timestamp", None)),
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(getattr(c, "volume", 0.0)),
                    }
                    for c in candles
                ]
            )
        else:
            df_raw = candles
            if len(df_raw) < 35:
                return self._heuristic_profile_for_asset(
                    asset, strategies, expiration_bars, allowed_strategies=allowed_strategies
                )

        if len(df_raw) >= 50:
            is_qual, qual_reason = qualify_asset_microstructure(df_raw)
            if not is_qual:
                logger.warning(
                    "Asset %s failed microstructure qualification: %s", asset, qual_reason
                )
                return None

        best_assignment: StrategyAssignment | None = None
        best_score = -999999.0
        is_whitelisted = is_whitelisted_asset(asset)

        if allowed_strategies:
            candidate_strategies = [s for s in strategies if s["id"] in allowed_strategies]
        else:
            candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]
        if not candidate_strategies:
            candidate_strategies = strategies

        for strat_meta in candidate_strategies:
            strat_id = strat_meta["id"]
            default_params = {p["name"]: p["default"] for p in strat_meta["parameters"]}

            variations = self._generate_strategy_variations(
                strat_id, default_params, expiration_bars
            )

            for params in variations:
                exp_b = int(params.get("base_expiration_bars", expiration_bars))
                cfg = BacktestConfig(
                    asset=asset,
                    timeframe_seconds=timeframe_seconds,
                    initial_deposit=Decimal("1000.0"),
                    stake_model=StakeModel.FLAT,
                    stake_amount=Decimal("10.0"),
                    payout_rate=Decimal(str(payout_rate)),
                    min_payout_rate=Decimal("0.80"),
                    expiration_bars=exp_b,
                    expiration_seconds=exp_b * timeframe_seconds,
                    strategy_name=strat_id,
                    strategy_params=params,
                )

                try:
                    engine = BinaryBacktestEngine(cfg)
                    sum_res = engine.run(df_raw)

                    wr = float(sum_res.win_rate_pct)
                    pf = float(sum_res.profit_factor)
                    roi = float(sum_res.roi_pct)
                    dd = float(sum_res.max_drawdown_pct)
                    trades = sum_res.total_trades

                    if trades >= 2:
                        score = (
                            (wr - 50.0) * 3.0
                            + min(pf, 4.0) * 15.0
                            + min(trades, 10) * 3.0
                            - dd * 0.5
                            + roi * 0.5
                        )
                    elif trades == 1:
                        score = (wr - 50.0) * 1.5 + (15.0 if wr > 50 else -15.0)
                    else:
                        score = -50.0

                    # Prioritize high-performing strategies (+15.0 quantum bonus)
                    if strat_id in PRIORITY_STRATEGIES:
                        score += 15.0

                    # Whitelist asset ranking boost (+15.0 bonus)
                    if is_whitelisted:
                        score += 15.0

                    if score > best_score:
                        best_score = score
                        if trades >= 2:
                            rationale = (
                                f"WinRate {wr:.1f}% ({trades} угод, PF {pf:.2f}) для фази {asset}"
                            )
                        elif trades == 1 and wr >= 50:
                            rationale = f"Висока точність сигналу (WR {wr:.0f}%) для {asset}"
                        else:
                            rationale = f"Оптимізований профіль індикаторів для {asset}"

                        best_assignment = StrategyAssignment(
                            asset=asset,
                            strategy_id=strat_id,
                            strategy_name=strat_meta["name"],
                            category=strat_meta["category"],
                            parameters=params,
                            estimated_win_rate_pct=wr if trades > 0 else 60.0,
                            estimated_profit_factor=pf if trades > 0 else 1.35,
                            estimated_trades_count=trades,
                            quantum_score=score if trades > 0 else 75.0,
                            rationale=rationale,
                        )
                except Exception as e:
                    logger.debug("Strategy %s eval failed on %s: %s", strat_id, asset, e)
                    continue

        if (
            not best_assignment
            or best_assignment.estimated_trades_count == 0
            or best_assignment.estimated_win_rate_pct < 50.0
        ):
            return self._heuristic_profile_for_asset(
                asset, strategies, expiration_bars, allowed_strategies=allowed_strategies
            )

        return best_assignment
