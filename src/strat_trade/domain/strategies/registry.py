from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strat_trade.domain.strategies.base import BaseStrategy
from strat_trade.domain.strategies.bollinger_atr_reversion import BollingerAtrReversionStrategy
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy
from strat_trade.domain.strategies.macd_divergence_break import MacdDivergenceBreakStrategy
from strat_trade.domain.strategies.rsi_stochastic_extreme import RsiStochasticExtremeStrategy
from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
from strat_trade.domain.strategies.volatility_squeeze_breakout import (
    VolatilitySqueezeBreakoutStrategy,
)


@dataclass
class StrategyMetadata:
    id: str
    name: str
    category: (
        str  # "Hybrid", "Mean Reversion", "Trend Following", "Scalping", "Breakout", "Momentum"
    )
    description: str
    cls: type[BaseStrategy]
    recommended_timeframes: list[int]
    recommended_assets: list[str]


_STRATEGIES: dict[str, StrategyMetadata] = {
    "hybrid_multifactors": StrategyMetadata(
        id="hybrid_multifactors",
        name="Гібридна Мульти-Факторна",
        category="Hybrid Multi-Factor",
        description=(
            "Комплексна синергія EMA(9,21,50), RSI(14), Stochastic(14,3), "
            "Bollinger Bands(20,2) та ADX(14) з адаптивною експірацією."
        ),
        cls=HybridMultiFactorsStrategy,
        recommended_timeframes=[60, 180, 300],
        recommended_assets=["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
    ),
    "bollinger_atr_reversion": StrategyMetadata(
        id="bollinger_atr_reversion",
        name="Bollinger + ATR Mean Reversion",
        category="Mean Reversion",
        description=(
            "Торгівля відбою від меж смуг Боллінджера зі свічковими тінями "
            "та захистом від сплесків ATR (ідеально для флету OTC)."
        ),
        cls=BollingerAtrReversionStrategy,
        recommended_timeframes=[60, 180],
        recommended_assets=["EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc"],
    ),
    "ema_pullback_trend": StrategyMetadata(
        id="ema_pullback_trend",
        name="EMA Ribbon Trend Pullback",
        category="Trend Following",
        description=(
            "Трендова система відкату до динамічних рівнів EMA 9/21/50 "
            "при активному спрямованому русі за ADX > 25."
        ),
        cls=EmaPullbackTrendStrategy,
        recommended_timeframes=[60, 300],
        recommended_assets=["EURUSD", "GBPUSD", "USDJPY_otc"],
    ),
    "rsi_stochastic_extreme": StrategyMetadata(
        id="rsi_stochastic_extreme",
        name="RSI + Stoch Extreme Scalp",
        category="Scalping Reversal",
        description=(
            "Подвійне екстремальне виснаження осциляторів RSI (<25/>75) та "
            "Stochastic (<20/>80) для швидких 1-2 хв розворотів."
        ),
        cls=RsiStochasticExtremeStrategy,
        recommended_timeframes=[60],
        recommended_assets=["EURUSD_otc", "USDJPY_otc", "BTCUSD_otc"],
    ),
    "macd_divergence_break": StrategyMetadata(
        id="macd_divergence_break",
        name="MACD Divergence & Cross",
        category="Reversal Divergence",
        description=(
            "Детекція дивергенцій між ціновими екстремумами та гістограмою MACD "
            "з імпульсним перетином сигнальної лінії."
        ),
        cls=MacdDivergenceBreakStrategy,
        recommended_timeframes=[60, 180, 300],
        recommended_assets=["EURUSD_otc", "GBPUSD_otc"],
    ),
    "volatility_squeeze_breakout": StrategyMetadata(
        id="volatility_squeeze_breakout",
        name="TTM Volatility Squeeze Breakout",
        category="Volatility Breakout",
        description=(
            "Пробій консолідації при розширенні смуг Боллінджера за межі "
            "Keltner Channels під час відкриття сесій чи новин."
        ),
        cls=VolatilitySqueezeBreakoutStrategy,
        recommended_timeframes=[60, 180],
        recommended_assets=["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
    ),
    "supertrend_adx_momentum": StrategyMetadata(
        id="supertrend_adx_momentum",
        name="SuperTrend + ADX Momentum",
        category="Momentum Trend",
        description=(
            "Трендовий імпульс за динамічним індикатором SuperTrend "
            "з підтвердженням сили тренду за ADX."
        ),
        cls=SupertrendAdxMomentumStrategy,
        recommended_timeframes=[60, 300],
        recommended_assets=["EURUSD", "GBPUSD", "EURUSD_otc"],
    ),
    "support_resistance_bounce": StrategyMetadata(
        id="support_resistance_bounce",
        name="Support & Resistance Pin-Bar",
        category="Price Action / S&R",
        description=(
            "Відбій від динамічних фрактальних рівнів підтримки та опору "
            "зі свічковими патернами відхилення (Pin-Bars / Hammers)."
        ),
        cls=SupportResistanceBounceStrategy,
        recommended_timeframes=[60, 180],
        recommended_assets=["EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc"],
    ),
}


def list_available_strategies() -> list[dict[str, Any]]:
    out = []
    for meta in _STRATEGIES.values():
        params = [
            {
                "name": p.name,
                "display_name": p.display_name,
                "type": p.param_type,
                "default": p.default_value,
                "min": p.min_value,
                "max": p.max_value,
                "step": p.step,
                "options": p.options,
                "description": p.description,
            }
            for p in meta.cls.get_parameter_definitions()
        ]
        out.append(
            {
                "id": meta.id,
                "name": meta.name,
                "category": meta.category,
                "description": meta.description,
                "recommended_timeframes": meta.recommended_timeframes,
                "recommended_assets": meta.recommended_assets,
                "parameters": params,
            }
        )
    return out


def _resolve_metadata(strategy_name: str) -> StrategyMetadata:
    meta = (
        _STRATEGIES.get(strategy_name.strip().lower()) if isinstance(strategy_name, str) else None
    )
    if meta:
        return meta
    # Fallback to default top sniper performers
    return _STRATEGIES.get(
        "support_resistance_bounce",
        _STRATEGIES.get("rsi_stochastic_extreme", next(iter(_STRATEGIES.values()))),
    )


def split_strategy_params(
    strategy_name: str, params: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Splits params into those the strategy accepts and those it does not.

    Callers need the rejected keys: passing one strategy's tuned parameters to a
    different strategy used to drop them silently, leaving the second strategy
    running on library defaults while the trade log still recorded the tuned
    values. That made live results untraceable to any backtest.
    """
    import inspect

    meta = _resolve_metadata(strategy_name)
    combined = dict(params or {})

    sig = inspect.signature(meta.cls.__init__)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return combined, []

    valid_names = set(sig.parameters.keys()) - {"self"}
    accepted = {k: v for k, v in combined.items() if k in valid_names}
    rejected = sorted(k for k in combined if k not in valid_names)
    return accepted, rejected


def get_strategy_instance(
    strategy_name: str, params: dict[str, Any] | None = None, **kwargs: Any
) -> BaseStrategy:
    meta = _resolve_metadata(strategy_name)

    combined_params = dict(params or {})
    combined_params.update(kwargs)
    filtered, _rejected = split_strategy_params(strategy_name, combined_params)

    return meta.cls(**filtered)
