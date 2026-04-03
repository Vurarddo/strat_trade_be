import time
from datetime import UTC, datetime, timedelta
from typing import Any

from strat_trade.domain.services.market_evaluator import MarketStateEvaluator
from strat_trade.domain.trade_record import TradeSignalRecord
from strat_trade.ports.candles import CandleFeed
from strat_trade.ports.llm_gateway import LlmGateway
from strat_trade.ports.signal_repository import SignalRepository
from strat_trade.ports.trading_gateway import TradingGateway
from strat_trade.use_cases.fetch_candles import fetch_recent_candles


class GenerateTradingSignalUseCase:
    """End-to-end LLM signal generation usecase from raw market data."""

    def __init__(
        self,
        candle_feed: CandleFeed,
        llm_gateway: LlmGateway,
        signal_repository: SignalRepository,
        trading_gateway: TradingGateway,
        max_count: int = 5000,
    ) -> None:
        self._candle_feed = candle_feed
        self._llm_gateway = llm_gateway
        self._signal_repository = signal_repository
        self._trading_gateway = trading_gateway
        self._max_count = max_count
        self._evaluator = MarketStateEvaluator()

    async def execute(
        self,
        asset: str,
        timeframe_seconds: int,
        count: int,
        auto_trade: bool = False,
        amount: float = 1.0,
    ) -> dict[str, Any]:
        t0 = time.time()

        # 1. Fetch candles via CandleFeed
        page = await fetch_recent_candles(
            feed=self._candle_feed,
            asset=asset,
            timeframe_seconds=timeframe_seconds,
            count=count,
            max_count=self._max_count,
        )
        t1 = time.time()
        print(f"🚀 [PROFILER] Candle Fetch: {t1 - t0:.3f}s", flush=True)

        # 2. Pass them to MarketStateEvaluator to get MarketStateVector
        market_state = self._evaluator.evaluate(page.candles)
        t2 = time.time()
        print(f"🚀 [PROFILER] Math & Pandas: {t2 - t1:.3f}s", flush=True)

        # 3. Pre-LLM Hard Filter (Short-Circuit)
        if market_state.regime.is_choppy:
            print("⚡ [PROFILER] Market is choppy. Short-circuiting LLM.", flush=True)
            adx_val = market_state.regime.adx_14
            adx_str = f"{adx_val:.2f}" if adx_val is not None else "N/A"
            llm_verdict = {
                "chain_of_thought": {
                    "step_1_regime": f"ADX is {adx_str} (Choppy)",
                    "step_2_smc": "Bypassed",
                    "step_3_confluence": "Bypassed",
                    "step_4_verdict": "Hard filter triggered",
                },
                "direction": "NEUTRAL",
                "expiration_in_seconds": timeframe_seconds,
                "win_probability_percentage": 0,
                "strategy_name": "Hard Filter - Low Volatility",
            }
        else:
            # 4. Convert MarketStateVector + Context to a JSON string
            payload_dict = {
                "timeframe_seconds": timeframe_seconds,
                "market_state": market_state.model_dump(),
            }
            import json

            state_json = json.dumps(payload_dict)

            # 5. LLM Inference (Only executed if market is trending)
            llm_verdict = await self._llm_gateway.analyze_market_state(state_json)
            t3 = time.time()
            print(f"🚀 [PROFILER] LLM Inference: {t3 - t2:.3f}s", flush=True)
            print(f"🚀 [PROFILER] TOTAL PIPELINE: {t3 - t0:.3f}s", flush=True)

        # Strict LLM Expiration Rejection (Risk Management)
        min_expiration = timeframe_seconds * 3
        if llm_verdict.get("direction", "NEUTRAL") != "NEUTRAL" and llm_verdict.get("expiration_in_seconds", timeframe_seconds) < min_expiration:
            exp_sec = llm_verdict.get("expiration_in_seconds", timeframe_seconds)
            print(f"🛑 [RISK MANAGEMENT] LLM suggested {exp_sec}s (Below minimum {min_expiration}s). Rejecting trade.", flush=True)
            
            # Mutate the signal into a rejected state
            llm_verdict["direction"] = "NEUTRAL"
            llm_verdict["strategy_name"] = "REJECTED: Invalid LLM Expiration"
            llm_verdict["win_probability_percentage"] = 0
            if "chain_of_thought" not in llm_verdict:
                llm_verdict["chain_of_thought"] = {}
            llm_verdict["chain_of_thought"]["step_4_verdict"] = f"Trade rejected due to invalid expiration ({exp_sec}s)"

        # 6. Auto Trade Execution
        direction = llm_verdict.get("direction", "NEUTRAL")
        exp_seconds = llm_verdict.get("expiration_in_seconds", timeframe_seconds)
        auto_executed = False

        if direction != "NEUTRAL":
            if auto_trade:
                # Place the trade via trading gateway
                success = await self._trading_gateway.place_trade(
                    asset=asset, direction=direction, amount=amount, expiration_in_seconds=exp_seconds
                )
                auto_executed = success
                if success:
                    print(f"🟢 [TRADE OPENED] Asset: {asset} | Dir: {direction} | Amount: ${amount} | Exp: {exp_seconds}s | Entry: {market_state.current_price}", flush=True)
                else:
                    print(f"🔴 [TRADE FAILED] Asset: {asset} | Dir: {direction} | Amount: ${amount} | Exp: {exp_seconds}s | Entry: {market_state.current_price}", flush=True)
            else:
                print(f"🔵 [PAPER TRADE OPENED] Asset: {asset} | Dir: {direction} | Exp: {exp_seconds}s | Entry: {market_state.current_price} (Auto-trade OFF)", flush=True)

        # 7. Save State-Action Signal to Persistence
        current_utc_time = datetime.now(UTC)
        record = TradeSignalRecord(
            asset=asset,
            timestamp=current_utc_time,
            direction=direction,
            entry_price=market_state.current_price,
            expiration_in_seconds=exp_seconds,
            expected_close_time=current_utc_time + timedelta(seconds=exp_seconds),
            strategy_name=llm_verdict.get("strategy_name", "Unknown"),
            win_probability_percentage=llm_verdict.get("win_probability_percentage", 0),
            auto_executed=auto_executed,
        )
        saved_record = await self._signal_repository.save_signal(record)

        # 8. Return the LLM's parsed dictionary alongside the original MarketStateVector
        return {
            "market_state": market_state.model_dump(),
            "llm_signal": llm_verdict,
            "signal_id": saved_record.id,
            "auto_executed": auto_executed,
            "amount": amount,
        }
