from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from strat_trade.api.deps import CandleFeedDep
from strat_trade.api.schemas import (
    AssetPerformanceResponse,
    BacktestRequest,
    BacktestResponse,
    BacktestTradeResponse,
    EquityPointResponse,
    OptimizationRequest,
    OptimizationResponse,
    OptimizationResultItemResponse,
    PortfolioBacktestRequest,
    PortfolioBacktestResponse,
    StrategyMetadataResponse,
    StrategyParameterDefResponse,
)
from strat_trade.domain.backtest.models import BacktestSummary, PortfolioBacktestSummary
from strat_trade.domain.strategies.registry import list_available_strategies
from strat_trade.use_cases.optimize_strategy import execute_strategy_optimization
from strat_trade.use_cases.run_backtest import execute_backtest
from strat_trade.use_cases.run_portfolio_backtest import execute_portfolio_backtest

router = APIRouter(prefix="/backtest", tags=["Backtest"])


def _summary_to_response(summary: BacktestSummary) -> BacktestResponse:
    return BacktestResponse(
        asset=summary.asset,
        timeframe_seconds=summary.timeframe_seconds,
        initial_deposit=float(summary.initial_deposit),
        final_balance=float(summary.final_balance),
        net_profit=float(summary.net_profit),
        roi_pct=float(summary.roi_pct),
        total_trades=summary.total_trades,
        winning_trades=summary.winning_trades,
        losing_trades=summary.losing_trades,
        draw_trades=summary.draw_trades,
        win_rate_pct=float(summary.win_rate_pct),
        profit_factor=float(summary.profit_factor),
        max_drawdown_amount=float(summary.max_drawdown_amount),
        max_drawdown_pct=float(summary.max_drawdown_pct),
        max_consecutive_wins=summary.max_consecutive_wins,
        max_consecutive_losses=summary.max_consecutive_losses,
        trades=[
            BacktestTradeResponse(
                entry_index=t.entry_index,
                exit_index=t.exit_index,
                entry_time=t.entry_time,
                exit_time=t.exit_time,
                action=t.action.value,
                entry_price=float(t.entry_price),
                exit_price=float(t.exit_price),
                stake=float(t.stake),
                payout_rate=float(t.payout_rate),
                pnl=float(t.pnl),
                outcome=t.outcome.value,
                balance_after=float(t.balance_after),
                confidence=t.confidence,
                expiration_seconds=t.expiration_seconds,
                asset=t.asset or summary.asset,
                metadata=t.metadata,
            )
            for t in summary.trades
        ],
        equity_curve=[
            EquityPointResponse(
                timestamp=p.timestamp,
                balance=float(p.balance),
                drawdown_pct=float(p.drawdown_pct),
            )
            for p in summary.equity_curve
        ],
        strategy_name=summary.strategy_name,
    )


def _portfolio_summary_to_response(
    summary: PortfolioBacktestSummary,
) -> PortfolioBacktestResponse:
    return PortfolioBacktestResponse(
        assets=summary.assets,
        timeframe_seconds=summary.timeframe_seconds,
        initial_deposit=float(summary.initial_deposit),
        final_balance=float(summary.final_balance),
        net_profit=float(summary.net_profit),
        roi_pct=float(summary.roi_pct),
        total_trades=summary.total_trades,
        winning_trades=summary.winning_trades,
        losing_trades=summary.losing_trades,
        draw_trades=summary.draw_trades,
        win_rate_pct=float(summary.win_rate_pct),
        profit_factor=float(summary.profit_factor),
        max_drawdown_amount=float(summary.max_drawdown_amount),
        max_drawdown_pct=float(summary.max_drawdown_pct),
        max_consecutive_wins=summary.max_consecutive_wins,
        max_consecutive_losses=summary.max_consecutive_losses,
        per_asset_stats=[
            AssetPerformanceResponse(
                asset=s.asset,
                name=s.name,
                payout_rate=float(s.payout_rate),
                total_trades=s.total_trades,
                winning_trades=s.winning_trades,
                losing_trades=s.losing_trades,
                draw_trades=s.draw_trades,
                win_rate_pct=float(s.win_rate_pct),
                net_profit=float(s.net_profit),
                roi_pct=float(s.roi_pct),
                profit_factor=float(s.profit_factor),
                max_drawdown_amount=float(s.max_drawdown_amount),
                max_drawdown_pct=float(s.max_drawdown_pct),
                trades_count_pct=float(s.trades_count_pct),
            )
            for s in summary.per_asset_stats
        ],
        trades=[
            BacktestTradeResponse(
                entry_index=t.entry_index,
                exit_index=t.exit_index,
                entry_time=t.entry_time,
                exit_time=t.exit_time,
                action=t.action.value,
                entry_price=float(t.entry_price),
                exit_price=float(t.exit_price),
                stake=float(t.stake),
                payout_rate=float(t.payout_rate),
                pnl=float(t.pnl),
                outcome=t.outcome.value,
                balance_after=float(t.balance_after),
                confidence=t.confidence,
                expiration_seconds=t.expiration_seconds,
                asset=t.asset,
                metadata=t.metadata,
            )
            for t in summary.trades
        ],
        equity_curve=[
            EquityPointResponse(
                timestamp=p.timestamp,
                balance=float(p.balance),
                drawdown_pct=float(p.drawdown_pct),
            )
            for p in summary.equity_curve
        ],
        strategy_name=summary.strategy_name,
    )


@router.post(
    "/run",
    response_model=BacktestResponse,
    summary="Execute binary options strategy backtest",
    description=(
        "Runs the hybrid quantitative strategy backtester on historical candles "
        "(fetched from broker). Calculates Win Rate, Profit Factor, Max Drawdown, "
        "equity curve, and detailed trade log."
    ),
    operation_id="runBacktest",
)
async def run_backtest_endpoint(
    feed: CandleFeedDep,
    req: BacktestRequest,
) -> BacktestResponse:
    summary = await execute_backtest(
        feed=feed,
        asset=req.asset,
        timeframe_seconds=req.timeframe_seconds,
        initial_deposit=req.initial_deposit,
        stake_model=req.stake_model,
        stake_amount=req.stake_amount,
        stake_percent=req.stake_percent,
        martingale_multiplier=req.martingale_multiplier,
        martingale_max_steps=req.martingale_max_steps,
        payout_rate=req.payout_rate,
        min_payout_rate=req.min_payout_rate,
        expiration_bars=req.expiration_bars,
        adaptive_expiration=req.adaptive_expiration,
        daily_stop_loss_pct=req.daily_stop_loss_pct,
        strategy_name=req.strategy_name,
        candle_count=req.candle_count,
        end_at=req.end_at,
    )
    return _summary_to_response(summary)


@router.post(
    "/portfolio/run",
    response_model=PortfolioBacktestResponse,
    summary="Execute multi-asset portfolio backtest",
    description=(
        "Runs chronological multi-asset portfolio backtesting against a shared deposit "
        "with concurrent trade limits, per-asset payout rates, and unified equity curve."
    ),
    operation_id="runPortfolioBacktest",
)
async def run_portfolio_backtest_endpoint(
    feed: CandleFeedDep,
    req: PortfolioBacktestRequest,
) -> PortfolioBacktestResponse:
    summary = await execute_portfolio_backtest(
        feed=feed,
        assets=req.assets,
        max_concurrent_trades=req.max_concurrent_trades,
        timeframe_seconds=req.timeframe_seconds,
        initial_deposit=req.initial_deposit,
        stake_model=req.stake_model,
        stake_amount=req.stake_amount,
        stake_percent=req.stake_percent,
        martingale_multiplier=req.martingale_multiplier,
        martingale_max_steps=req.martingale_max_steps,
        payout_rates=req.payout_rates,
        min_payout_rate=req.min_payout_rate,
        expiration_bars=req.expiration_bars,
        adaptive_expiration=req.adaptive_expiration,
        daily_stop_loss_pct=req.daily_stop_loss_pct,
        strategy_name=req.strategy_name,
        candle_count=req.candle_count,
        end_at=req.end_at,
    )
    return _portfolio_summary_to_response(summary)


@router.post(
    "/upload",
    response_model=BacktestResponse,
    summary="Execute backtest on uploaded CSV or JSON file",
    description=(
        "Upload an external dataset file (CSV/JSON) with OHLCV data to run backtesting offline."
    ),
    operation_id="uploadAndBacktest",
)
async def upload_and_backtest_endpoint(
    file: Annotated[UploadFile, File(description="CSV or JSON dataset file")],
    asset: Annotated[str, Form()] = "CUSTOM_ASSET",
    timeframe_seconds: Annotated[int, Form()] = 60,
    initial_deposit: Annotated[float, Form()] = 1000.0,
    stake_model: Annotated[str, Form()] = "flat",
    stake_amount: Annotated[float, Form()] = 10.0,
    stake_percent: Annotated[float, Form()] = 1.0,
    martingale_multiplier: Annotated[float, Form()] = 2.0,
    martingale_max_steps: Annotated[int, Form()] = 2,
    payout_rate: Annotated[float, Form()] = 0.85,
    min_payout_rate: Annotated[float, Form()] = 0.80,
    expiration_bars: Annotated[int, Form()] = 3,
    adaptive_expiration: Annotated[bool, Form()] = False,
    daily_stop_loss_pct: Annotated[float, Form()] = 0.05,
    strategy_name: Annotated[str, Form()] = "hybrid_multifactors",
) -> BacktestResponse:
    content = await file.read()
    summary = await execute_backtest(
        feed=None,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        initial_deposit=initial_deposit,
        stake_model=stake_model,
        stake_amount=stake_amount,
        stake_percent=stake_percent,
        martingale_multiplier=martingale_multiplier,
        martingale_max_steps=martingale_max_steps,
        payout_rate=payout_rate,
        min_payout_rate=min_payout_rate,
        expiration_bars=expiration_bars,
        adaptive_expiration=adaptive_expiration,
        daily_stop_loss_pct=daily_stop_loss_pct,
        strategy_name=strategy_name,
        custom_dataset_content=content,
        filename=file.filename or "",
    )
    return _summary_to_response(summary)


@router.get(
    "/strategies",
    response_model=list[StrategyMetadataResponse],
    summary="List all available strategies with metadata and parameter definitions",
    operation_id="listStrategies",
)
async def list_strategies_endpoint() -> list[StrategyMetadataResponse]:
    raw_list = list_available_strategies()
    return [
        StrategyMetadataResponse(
            id=s["id"],
            name=s["name"],
            category=s["category"],
            description=s["description"],
            recommended_timeframes=s["recommended_timeframes"],
            recommended_assets=s["recommended_assets"],
            parameters=[
                StrategyParameterDefResponse(
                    name=p["name"],
                    display_name=p["display_name"],
                    type=p["type"],
                    default=p["default"],
                    min=p["min"],
                    max=p["max"],
                    step=p["step"],
                    options=p["options"],
                    description=p["description"],
                )
                for p in s["parameters"]
            ],
        )
        for s in raw_list
    ]


@router.post(
    "/optimize",
    response_model=OptimizationResponse,
    summary="Run hyperparameter grid search optimization for a strategy",
    operation_id="optimizeStrategy",
)
async def optimize_strategy_endpoint(
    req: OptimizationRequest,
    feed: CandleFeedDep,
) -> OptimizationResponse:
    report = await execute_strategy_optimization(
        feed=feed,
        strategy_name=req.strategy_name,
        asset=req.asset,
        timeframe_seconds=req.timeframe_seconds,
        candle_count=req.candle_count,
        initial_deposit=req.initial_deposit,
        payout_rate=req.payout_rate,
        stake_model=req.stake_model,
        stake_amount=req.stake_amount,
        stake_percent=req.stake_percent,
        daily_stop_loss_pct=req.daily_stop_loss_pct,
        custom_parameter_grid=req.parameter_grid,
        max_combinations=req.max_combinations,
    )

    return OptimizationResponse(
        strategy_name=report.strategy_name,
        asset=report.asset,
        timeframe_seconds=report.timeframe_seconds,
        total_combinations_tested=report.total_combinations_tested,
        candle_count=report.candle_count,
        best_params=report.best_params,
        results=[
            OptimizationResultItemResponse(
                rank=r.rank,
                params=r.params,
                total_trades=r.total_trades,
                winning_trades=r.winning_trades,
                losing_trades=r.losing_trades,
                draw_trades=r.draw_trades,
                win_rate_pct=r.win_rate_pct,
                profit_factor=r.profit_factor,
                net_profit=r.net_profit,
                roi_pct=r.roi_pct,
                max_drawdown_pct=r.max_drawdown_pct,
                max_consecutive_losses=r.max_consecutive_losses,
                rank_score=r.rank_score,
            )
            for r in report.results
        ],
    )
