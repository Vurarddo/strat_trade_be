import asyncio
import logging
from decimal import Decimal

from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.trading.asset_filter import filter_allowed_assets
from strat_trade.domain.trading.entities import PreTradingPlan, StrategyAssignment
from strat_trade.ports.candles import CandleFeed

logger = logging.getLogger(__name__)


async def generate_pre_trading_plan(
    feed: CandleFeed,
    assets: list[str],
    initial_deposit: float = 1000.0,
    stake_model: str = "flat",
    stake_amount: float = 10.0,
    stake_percent: float = 1.0,
    expiration_seconds: int = 180,
    daily_stop_loss_pct: float = 0.05,
    daily_take_profit_pct: float = 0.025,
    trailing_profit_lock_enabled: bool = True,
    trailing_profit_lock_threshold_usd: float = 500.0,
    trailing_profit_retention_pct: float = 0.75,
    per_asset_degradation_guard_enabled: bool = True,
    per_asset_max_consecutive_losses: int = 2,
    per_asset_min_winrate_pct: float = 40.0,
    max_concurrent_trades: int = 3,
    min_payout_rate: float = 0.80,
    cooldown_bars: int = 3,
    global_cooldown_seconds: int = 30,
    max_consecutive_losses: int = 3,
    max_drawdown_pct_limit: float = 0.08,
    correlation_filter_enabled: bool = True,
    pause_duration_minutes: int = 15,
    asset_blacklist: list[str] | None = None,
    asset_whitelist: list[str] | None = None,
    toxic_filter_enabled: bool = True,
    session_filter_enabled: bool = True,
    allowed_strategies: list[str] | None = None,
    enforce_whitelist_only: bool = False,
    bar_edge_guard_seconds: float = 3.0,
    use_closed_bar_only: bool = True,
    dynamic_strategy_switching_enabled: bool = False,
    asset_governor_enabled: bool = True,
    otc_stake_multiplier: float = 0.25,
    otc_min_payout_rate: float = 0.90,
    governor_min_trades_for_mute: int = 20,
    governor_mute_duration_minutes: int = 240,
    governor_promotion_min_trades: int = 400,
) -> PreTradingPlan:
    """Evaluates selected assets concurrently and auto-assigns optimal strategy to each."""
    matcher = StrategyAutoMatcher(candle_count=150)
    sem = asyncio.Semaphore(8)

    if toxic_filter_enabled:
        target_assets = filter_allowed_assets(
            assets,
            blacklist=asset_blacklist,
            whitelist=asset_whitelist,
            enforce_whitelist_only=enforce_whitelist_only,
        )
    else:
        target_assets = list(assets)

    if not target_assets:
        target_assets = [
            "EURUSD_otc",
            "USDCLP_otc",
            "USDBDT_otc",
            "USDEGP_otc",
            "Gold_otc",
        ]

    async def _process_asset(asset: str) -> StrategyAssignment | None:
        async with sem:
            try:
                candles = await feed.get_candles(asset=asset, timeframe=60, count=150)
            except Exception as e:
                logger.debug("Failed to fetch candles for asset profiling %s: %s", asset, e)
                candles = []

            return await matcher.find_optimal_strategy_for_asset(
                asset=asset,
                candles=candles,
                timeframe_seconds=60,
                expiration_bars=max(1, expiration_seconds // 60),
                payout_rate=0.92 if "otc" in asset.lower() else 0.80,
                allowed_strategies=allowed_strategies,
            )

    tasks = [_process_asset(asset) for asset in target_assets]
    raw_assignments = await asyncio.gather(*tasks)
    assignments = [a for a in raw_assignments if a is not None]

    dep_dec = Decimal(str(initial_deposit))
    stop_loss_amount = (dep_dec * Decimal(str(daily_stop_loss_pct))).quantize(Decimal("0.01"))
    take_profit_amount = (dep_dec * Decimal(str(daily_take_profit_pct))).quantize(Decimal("0.01"))

    return PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=dep_dec,
        stake_model=stake_model,
        stake_amount=Decimal(str(stake_amount)),
        stake_percent=stake_percent,
        expiration_seconds=expiration_seconds,
        daily_stop_loss_pct=daily_stop_loss_pct,
        stop_loss_amount=stop_loss_amount,
        daily_take_profit_pct=daily_take_profit_pct,
        take_profit_amount=take_profit_amount,
        trailing_profit_lock_enabled=trailing_profit_lock_enabled,
        trailing_profit_lock_threshold_usd=Decimal(str(trailing_profit_lock_threshold_usd)),
        trailing_profit_retention_pct=trailing_profit_retention_pct,
        per_asset_degradation_guard_enabled=per_asset_degradation_guard_enabled,
        per_asset_max_consecutive_losses=per_asset_max_consecutive_losses,
        per_asset_min_winrate_pct=per_asset_min_winrate_pct,
        max_concurrent_trades=max_concurrent_trades,
        min_payout_rate=min_payout_rate,
        cooldown_bars=cooldown_bars,
        global_cooldown_seconds=global_cooldown_seconds,
        max_consecutive_losses=max_consecutive_losses,
        max_drawdown_pct_limit=max_drawdown_pct_limit,
        correlation_filter_enabled=correlation_filter_enabled,
        pause_duration_minutes=pause_duration_minutes,
        asset_blacklist=asset_blacklist or [],
        asset_whitelist=asset_whitelist or [],
        toxic_filter_enabled=toxic_filter_enabled,
        session_filter_enabled=session_filter_enabled,
        allowed_strategies=allowed_strategies or [],
        bar_edge_guard_seconds=bar_edge_guard_seconds,
        use_closed_bar_only=use_closed_bar_only,
        dynamic_strategy_switching_enabled=dynamic_strategy_switching_enabled,
        asset_governor_enabled=asset_governor_enabled,
        otc_stake_multiplier=otc_stake_multiplier,
        otc_min_payout_rate=otc_min_payout_rate,
        governor_min_trades_for_mute=governor_min_trades_for_mute,
        governor_mute_duration_minutes=governor_mute_duration_minutes,
        governor_promotion_min_trades=governor_promotion_min_trades,
    )
