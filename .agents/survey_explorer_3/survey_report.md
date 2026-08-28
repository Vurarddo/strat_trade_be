# 📊 Comprehensive Survey Report: Backtesting, Verification, Optimization & Test Infrastructure

**Project**: Pocket Option AutoTrader Pro (`strat_trade_be`)  
**Date**: 2026-08-20  
**Investigator**: survey_explorer_3  
**Status**: COMPLETE (Read-Only Investigation)  

---

## 1. Executive Summary

This report provides an exhaustive, authoritative architectural survey of the backtesting engine, simulation mechanics, payout modeling, strategy optimization framework, test infrastructure, datasets, and verification benchmark design for `strat_trade_be`.

### Key Findings Summary
1. **Backtesting Framework**: The system features two high-performance backtest engines:
   - `BinaryBacktestEngine` (`src/strat_trade/domain/backtest/engine.py`): Single-asset event-driven simulator supporting 3 money management models (Flat, Percent, Martingale), discrete forward bar expirations, payout filtering, and session stop-loss circuit breakers.
   - `PortfolioBacktestEngine` (`src/strat_trade/domain/backtest/portfolio_engine.py`): Multi-asset chronological simulator with shared deposit, max concurrent trade limits, per-asset payout rates, and asset performance leaderboards.
2. **Payout & PnL Formulation**: Payoff logic is strictly calibrated for fixed binary options structures:
   - **Win**: $\text{PnL} = \text{Stake} \times \text{Payout Rate}$ (e.g., $92\% \rightarrow +0.92 \times \text{Stake}$)
   - **Loss**: $\text{PnL} = -\text{Stake} \times 1.00$ ($-100\%$ loss)
   - **Draw**: $\text{PnL} = 0.00$
   - **Break-Even Win Rate ($WR_{BE}$)** at $92\%$ payout is $\frac{1}{1 + 0.92} = 52.083\%$.
3. **Core Strategy Defects Identified (R1 Context)**:
   - `VolatilitySqueezeBreakoutStrategy` (`src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:84`): Contains a false breakout defect where `(not sq_now and abs(mom) > 0)` triggers trades on every consecutive non-squeeze bar instead of strictly on squeeze exit transitions (`sq_prev and not sq_now`).
   - `BollingerAtrReversionStrategy` (`src/strat_trade/domain/strategies/bollinger_atr_reversion.py:101-122`): Lacks candle close confirmation inside bands and ADX trend suppression, leading to counter-trend knife catching during strong OTC trends ($ADX > 25$).
4. **Bot Guardrails & Anti-Whipsaw (R2 Context)**:
   - `LiveDemoBotEngine` (`src/strat_trade/domain/trading/bot_engine.py`): Currently relies on a hardcoded 30-second cooldown per asset and lacks per-asset/global bar cooldowns, correlated currency pair filtering, and consecutive-loss circuit breakers.
5. **Automated Rolling 15-Trade Window Verification Benchmark (R3 Context)**:
   - At $92\%$ payout, in any 15-trade sample, achieving $\ge 8$ wins out of 15 trades ($53.33\% \approx 53.4\%$ Win Rate) guarantees a positive net PnL ($+\$3.60$ per $\$10$ flat stake).
   - An automated rolling/sequential 15-trade benchmark suite can be constructed using `BinaryBacktestEngine` and `StrategyOptimizerEngine` to partition trades into $W=15$ non-overlapping batches, enforce $WR \ge 53.4\%$ and Net Growth $> 0$, and trigger automated parameter tuning if any batch fails.
6. **Test Infrastructure & Execution**:
   - Active virtual environment: `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/mypy`.
   - Test suite: **66 passing unit and integration tests** across 22 test files in `tests/` executing in $3.23$ seconds.
   - Code formatting & linting: Ruff checks pass with 0 errors across `src` and `tests`.

---

## 2. Backtesting Framework & Simulation Mechanics

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Backtesting Pipeline                                      │
├───────────────────────────────┬─────────────────────────────┬───────────────────────────────┤
│        1. Data Ingestion      │     2. Signal Generation    │    3. Execution & Settlement  │
│  - SQLite DB / Broker WS      │  - Indicator Pre-calc (ta)  │  - Non-overlapping Lock       │
│  - CSV / JSON Custom Loader   │  - Strategy.evaluate_bar()  │  - Money Management (Stake)   │
│  - Synthetic Generator (OHLC) │  - Confidence & Metadata    │  - Payout / PnL Settlement    │
│                               │                             │  - Drawdown & Equity Tracking │
└───────────────────────────────┴─────────────────────────────┴───────────────────────────────┘
```

### 2.1 Engine Overview

| Engine Class | File Path | Scope | Key Capabilities |
| :--- | :--- | :--- | :--- |
| `BinaryBacktestEngine` | `src/strat_trade/domain/backtest/engine.py:21-321` | Single Asset | Event-driven bar-by-bar simulation; Flat/Percent/Martingale stakes; Payout filtering; Session stop-loss; Detailed trade & equity tracking. |
| `PortfolioBacktestEngine` | `src/strat_trade/domain/backtest/portfolio_engine.py:39-338` | Multi-Asset Portfolio | Chronological multi-asset simulation; Shared balance; Max concurrent trade cap; Per-asset payout rates; Leaderboard breakdown. |

### 2.2 Simulation Loop Mechanics (`BinaryBacktestEngine`)

1. **Warm-up Window**:
   - Line 119: `for i in range(50, n - 1):`
   - The first 50 bars are reserved for rolling indicator warm-up (EMA, Bollinger Bands, ATR, RSI, MACD).
2. **Non-Overlapping Trade Constraint**:
   - Lines 120–121 & Line 268:
     ```python
     if i < next_available_idx:
         continue
     ...
     next_available_idx = exit_idx
     ```
   - In binary options, once an asset position is opened, no new trades are placed on that asset until the forward expiration time has elapsed (`exit_idx = i + exp_bars`).
3. **Session Stop-Loss Circuit Breaker**:
   - Lines 124–128:
     ```python
     drawdown_from_session = (session_start_balance - current_balance) / session_start_balance
     if drawdown_from_session >= stop_loss_pct:
         break
     ```
   - Instantly halts further trade execution if session drawdown breaches `daily_stop_loss_pct` (e.g., 5%).
4. **Execution & Settlement Timing**:
   - Signal evaluated at candle close $t$ (`entry_row = df.iloc[i]`).
   - Settlement occurs at forward bar $t + \text{expiration\_bars}$ (`exit_row = df.iloc[exit_idx]`).
   - Outcome determination:
     - **CALL**: $\text{exit\_price} > \text{entry\_price} \rightarrow \text{WIN}$; $\text{exit\_price} < \text{entry\_price} \rightarrow \text{LOSS}$; $\text{exit\_price} == \text{entry\_price} \rightarrow \text{DRAW}$.
     - **PUT**: $\text{exit\_price} < \text{entry\_price} \rightarrow \text{WIN}$; $\text{exit\_price} > \text{entry\_price} \rightarrow \text{LOSS}$; $\text{exit\_price} == \text{entry\_price} \rightarrow \text{DRAW}$.

### 2.3 Payoff Calculation & Break-Even Mathematics

The binary options payoff in `BinaryBacktestEngine` (lines 174–194) and `PortfolioBacktestEngine` (lines 150–170) is:

$$\text{Win PnL} = \text{Stake} \times \text{Payout Rate}$$
$$\text{Loss PnL} = -\text{Stake}$$
$$\text{Draw PnL} = 0.0$$

#### Break-Even Win Rate Formula
$$WR_{BE} = \frac{1}{1 + \text{Payout Rate}}$$

| Payout Rate | Mathematical $WR_{BE}$ | Outcome on 15 Trades ($8\text{W} / 7\text{L}$) | Outcome on 15 Trades ($7\text{W} / 8\text{L}$) |
| :--- | :--- | :--- | :--- |
| **92% (OTC)** | **52.08%** | **+$3.60 (WR: 53.33% > 52.08%) [PROFITABLE]** | -$15.60 (WR: 46.67%) [LOSS] |
| **85% (Standard)** | **54.05%** | -$2.00 (WR: 53.33% < 54.05%) [LOSS] | -$20.50 (WR: 46.67%) [LOSS] |
| **80% (Off-Peak)** | **55.56%** | -$6.00 (WR: 53.33% < 55.56%) [LOSS] | -$24.00 (WR: 46.67%) [LOSS] |

> **Crucial Insight**: At 92% broker payout, an 8-win / 7-loss batch (53.33% Win Rate $\approx 53.4\%$) satisfies the profitability condition ($\text{PnL} > 0$). This aligns directly with Requirement R3.

### 2.4 Money Management Models

`StakeModel` (`src/strat_trade/domain/backtest/models.py:10-14`):
1. **FLAT**: Fixed monetary stake (e.g., $\$10.00$ or $\$20.00$).
2. **PERCENT**: Proportional compounding sizing (e.g., $1.0\%$ or $2.0\%$ of current balance, bounded by $\ge \$1.00$).
3. **MARTINGALE**: Geometric step multiplier after consecutive losses up to `martingale_max_steps` (e.g., $10 \rightarrow 20 \rightarrow 40 \rightarrow 10$).

### 2.5 Vectorized Signal Metrics Engine

`compute_binary_options_signal_metrics` (`src/strat_trade/domain/binary_options_metrics.py`):
- Vectorized NumPy settlement comparison between `df['signal']` and `df['close'].shift(-expiration_bars)`.
- Calculates `total_trades`, `wins`, `losses`, `ties`, `winrate_pct`, and `expected_value_per_1_usd = (p_win * payout) - (p_loss * 1.0)`.
- Ultra-high throughput: $< 1\text{ ms}$ for $10,000$ bars.

### 2.6 Historical Data Loaders

`parse_candles_csv_or_json` (`src/strat_trade/domain/backtest/data_loader.py`):
- Accepts CSV string, JSON string, or raw bytes.
- Handles standard JSON shapes: `candles`, `data`, `history`, `items`, `result`.
- Automatically normalizes header aliases:
  - Timestamp: `time`, `datetime`, `date`, `timestamp`, `t`, `ts`
  - Open: `open`, `o`
  - High: `high`, `h`, `max`
  - Low: `low`, `l`, `min`
  - Close: `close`, `c`, `price`
  - Volume: `volume`, `vol`, `v`
- Epoch detection (seconds vs milliseconds via $10^{11}$ threshold).
- Enforces strict sorting and missing value cleanup (`dropna`, `fillna(0.0)`).

---

## 3. Strategy Catalog & Critical Defect Analysis

The system contains **8 registered strategies** in `src/strat_trade/domain/strategies/registry.py`:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Strategy Registry                                    │
├──────────────────────────────┬───────────────────────────┬─────────────────────────────┤
│ Strategy ID                  │ Category                  │ Key Indicators              │
├──────────────────────────────┼───────────────────────────┼─────────────────────────────┤
│ hybrid_multifactors          │ Hybrid Multi-Factor       │ EMA(9,21,50), RSI, BB, ADX │
│ bollinger_atr_reversion      │ Mean Reversion            │ BB(20,2), RSI(14), ATR(14)  │
│ ema_pullback_trend           │ Trend Following           │ EMA Ribbon(9,21,50), ADX    │
│ rsi_stochastic_extreme       │ Scalping Reversal         │ RSI(14), Stoch(14,3)        │
│ macd_divergence_break        │ Reversal Divergence       │ MACD(12,26,9)               │
│ volatility_squeeze_breakout  │ Volatility Breakout       │ BB(20,2), KC(20,1.5), Mom   │
│ supertrend_adx_momentum      │ Momentum Trend            │ SuperTrend(10,3), ADX(14)   │
│ support_resistance_bounce    │ Price Action / S&R        │ Fractal Highs/Lows, Pin-Bar │
└──────────────────────────────┴───────────────────────────┴─────────────────────────────┘
```

### 3.1 Defect 1: False Breakout in `VolatilitySqueezeBreakoutStrategy`

- **Location**: `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:84`
- **Observed Code**:
  ```python
  # Breakout Trigger: Squeeze was ON and fired OFF with directional momentum
  squeeze_fired = (sq_prev and not sq_now) or (not sq_now and abs(mom) > 0)
  ```
- **Analysis**:
  The clause `or (not sq_now and abs(mom) > 0)` creates severe signal noise. Whenever the market is outside of a squeeze and momentum is non-zero (which is almost every bar in volatile/trending regimes), `squeeze_fired` evaluates to `True` continuously bar-by-bar.
- **Required Fix**:
  Enforce strict squeeze transition logic:
  ```python
  squeeze_fired = sq_prev and not sq_now  # Fires strictly on squeeze release
  ```

### 3.2 Defect 2: Missing Trend Suppression & Candle Confirmation in `BollingerAtrReversionStrategy`

- **Location**: `src/strat_trade/domain/strategies/bollinger_atr_reversion.py:101-122`
- **Observed Code**:
  ```python
  lower_wick = min(open_, close) - low
  if (low <= bb_l or close <= bb_l * 1.0002 or bb_pband <= 0.05) and (
      rsi <= self.rsi_oversold or prev["rsi"] <= self.rsi_oversold
  ):
      action = TradeAction.CALL
      confidence = 0.65
      if lower_wick > body * 0.8:
          confidence += 0.15
      if close > open_:  # bullish candle
          confidence += 0.10
  ```
- **Analysis**:
  1. The strategy triggers even if the candle closes deep outside the lower/upper Bollinger Band (`low <= bb_l or close <= bb_l * 1.0002`), catching runaway knives.
  2. The strategy lacks an $ADX$ trend filter. When $ADX > 25$ (strong trend), price routinely hugs and rides the outer Bollinger Bands for 5–15 consecutive bars, causing consecutive losses.
- **Required Enhancement**:
  - Add $ADX(14)$ indicator computation in `prepare_dataframe`.
  - Suppress signals when $ADX > \text{adx\_trend\_threshold}$ (default $25.0$).
  - Require candle confirmation: rejection wick PLUS candle close inside the band (`close > bb_l` for CALL, `close < bb_h` for PUT).

---

## 4. Bot Execution Guardrails & Anti-Whipsaw Analysis

- **Location**: `src/strat_trade/domain/trading/bot_engine.py`

### 4.1 Current Execution Mechanism
- Evaluates assets every $4.0$ seconds in `_run_loop()`.
- Uses `asyncio.Semaphore(6)` for concurrency bounding.
- Currently checks a hardcoded 30-second cooldown per asset:
  ```python
  last_sig = self._last_signal_time.get(asset)
  if last_sig and (now - last_sig).total_seconds() < 30:
      return
  ```

### 4.2 Gaps Identified (R2 Blueprint)
1. **Configurable Cooldown Timers**:
   - Per-asset cooldown ($N$ bars or seconds).
   - Global cooldown across all assets after trade triggers.
2. **Correlated Currency Pair Filtering**:
   - Missing currency correlation matrix (e.g. `AUDUSD_otc` and `AUDNZD_otc` or `EURUSD_otc` and `GBPUSD_otc`).
   - If a CALL trade is currently open on `AUDUSD`, prevent opening a redundant CALL trade on `AUDNZD` in the same cycle.
3. **Consecutive-Loss Circuit Breaker**:
   - Missing dynamic pause mechanism after $K$ consecutive losses (e.g., pause trading for $M$ minutes if $K \ge 3$ consecutive losses occur).

---

## 5. Automated Rolling 15-Trade Window Verification Benchmark

### 5.1 Mathematical Foundation & Verification Criteria

In binary options with fixed payout $R = 0.92$ and fixed stake $S$:
- Win return: $+0.92 S$
- Loss return: $-1.00 S$
- Break-even win rate: $52.083\%$

For a fixed sample size $W = 15$ trades with $k$ wins and $(15 - k)$ losses:
$$\text{Net PnL}(k) = k \times (0.92 S) - (15 - k) \times S = S \times [1.92 k - 15]$$

- For $k = 8$ wins:
  $$\text{Net PnL}(8) = S \times [1.92(8) - 15] = S \times [15.36 - 15] = +0.36 S$$
  $$\text{Win Rate} = \frac{8}{15} = 53.333\% \approx 53.4\%$$
- For $k = 7$ wins:
  $$\text{Net PnL}(7) = S \times [1.92(7) - 15] = S \times [13.44 - 15] = -1.56 S$$
  $$\text{Win Rate} = \frac{7}{15} = 46.667\%$$

**Benchmark Acceptance Rule**:
Every sequential non-overlapping batch $B_j = [t_{15j}, \dots, t_{15(j+1)-1}]$ must strictly satisfy:
$$\text{Win Rate}(B_j) \ge 53.4\% \quad \text{AND} \quad \text{Net Profit}(B_j) > 0$$

```
Historical Trades Stream (N = 60 trades)
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Batch 1 (1-15)  │  │ Batch 2 (16-30)  │  │ Batch 3 (31-45)  │  │ Batch 4 (46-60)  │
│  9W / 6L (60.0%) │  │  8W / 7L (53.3%) │  │ 10W / 5L (66.7%) │  │  9W / 6L (60.0%) │
│  PnL: +$2.28     │  │  PnL: +$0.36     │  │  PnL: +$4.20     │  │  PnL: +$2.28     │
│  [PASSED ✅]     │  │  [PASSED ✅]     │  │  [PASSED ✅]     │  │  [PASSED ✅]     │
└──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘
```

### 5.2 Algorithmic Verification & Tuning Architecture

```python
class Rolling15TradeVerificationRunner:
    """Automated benchmark validating rolling 15-trade window profitability."""

    def __init__(
        self,
        strategy_name: str,
        asset: str = "EURUSD_otc",
        payout_rate: float = 0.92,
        batch_size: int = 15,
        min_win_rate_pct: float = 53.4,
    ) -> None:
        self.strategy_name = strategy_name
        self.asset = asset
        self.payout_rate = Decimal(str(payout_rate))
        self.batch_size = batch_size
        self.min_win_rate_pct = Decimal(str(min_win_rate_pct))

    def evaluate_batches(self, summary: BacktestSummary) -> dict[str, Any]:
        trades = summary.trades
        total_trades = len(trades)
        num_batches = total_trades // self.batch_size
        if num_batches == 0:
            return {"status": "INSUFFICIENT_TRADES", "num_batches": 0, "passed": False}

        batch_results = []
        all_passed = True

        for b in range(num_batches):
            batch_trades = trades[b * self.batch_size : (b + 1) * self.batch_size]
            wins = sum(1 for t in batch_trades if t.outcome == TradeOutcome.WIN)
            losses = sum(1 for t in batch_trades if t.outcome == TradeOutcome.LOSS)
            draws = sum(1 for t in batch_trades if t.outcome == TradeOutcome.DRAW)
            decisive = wins + losses
            wr = (Decimal(wins) / Decimal(decisive) * Decimal("100.0")) if decisive > 0 else Decimal("0.0")
            pnl = sum((t.pnl for t in batch_trades), Decimal("0.0"))

            passed = (wr >= self.min_win_rate_pct) and (pnl > Decimal("0.0"))
            if not passed:
                all_passed = False

            batch_results.append({
                "batch_index": b + 1,
                "trades_range": (b * self.batch_size + 1, (b + 1) * self.batch_size),
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "win_rate_pct": float(round(wr, 2)),
                "net_pnl": float(round(pnl, 2)),
                "passed": passed,
            })

        return {
            "status": "PASSED" if all_passed else "FAILED",
            "all_batches_passed": all_passed,
            "total_batches": num_batches,
            "batches": batch_results,
        }
```

### 5.3 Automated Tuning Feedback Loop
When a candidate configuration fails any 15-trade window:
1. Trigger `StrategyOptimizerEngine` (`src/strat_trade/domain/optimizer/grid_search.py`).
2. Search parameter space (e.g., ADX thresholds $18..30$, BB standard deviations $1.8..2.4$, RSI periods $10..16$, expiration bars $2..4$).
3. Filter candidates through the `Rolling15TradeVerificationRunner`.
4. Select the parameter plateau with the highest minimum batch win rate and stability score.

---

## 6. Test Suite & Infrastructure Inventory

### 6.1 Execution Environment & Tooling

- **Python Interpreter**: `/Users/vlados/work/projects/startup/strat_trade_be/.venv/bin/python` (Python 3.12.13)
- **Test Runner**: `/Users/vlados/work/projects/startup/strat_trade_be/.venv/bin/pytest` (pytest 9.1.1, pytest-asyncio 1.4.0)
- **Linter & Formatter**: `/Users/vlados/work/projects/startup/strat_trade_be/.venv/bin/ruff` (Ruff 0.8.0)
- **Type Checker**: `/Users/vlados/work/projects/startup/strat_trade_be/.venv/bin/mypy` (mypy 1.11.0)
- **Git Hook Gate**: `scripts/pre_commit_quality_security_gate.py`

### 6.2 Complete Test Suite Catalog (22 Test Files, 66 Passing Tests)

| Test File Path | Covered Domain & Components | Test Count | Status |
| :--- | :--- | :--- | :--- |
| `tests/test_backtest_models_and_engine.py` | `BinaryBacktestEngine`, Flat/Percent/Martingale stakes, payout filter rejection, daily stop loss circuit breaker | 5 | ✅ Passed |
| `tests/test_portfolio_backtest_models_and_engine.py` | `PortfolioBacktestEngine`, multi-asset simulation, per-asset leaderboard, shared balance concurrency | 2 | ✅ Passed |
| `tests/test_binary_options_metrics.py` | `compute_binary_options_signal_metrics`, CALL/PUT settlement, tie handling, 10k vector perf | 3 | ✅ Passed |
| `tests/test_new_strategies.py` | All 8 strategies in `registry.py`, parameter definition validation, end-to-end bar evaluation & backtests | 9 | ✅ Passed |
| `tests/test_hybrid_strategy.py` | `HybridMultiFactorsStrategy` multi-indicator synergy, signal generation, parameter definitions | 2 | ✅ Passed |
| `tests/test_strategy_optimizer.py` | `StrategyOptimizerEngine` Cartesian grid search, ranking formula, best parameter discovery | 1 | ✅ Passed |
| `tests/test_strategy_auto_matcher.py` | `StrategyAutoMatcher` parameter variation generation, asset heuristic profiling | 1 | ✅ Passed |
| `tests/test_backtest_data_loader.py` | `parse_candles_csv_or_json`, CSV/JSON ingestion, header normalization, epoch conversion | 4 | ✅ Passed |
| `tests/test_backtest_api.py` | `POST /api/v1/backtest/run`, `POST /api/v1/backtest/upload`, `GET /api/v1/backtest/strategies` | 3 | ✅ Passed |
| `tests/test_portfolio_backtest_api.py` | `POST /api/v1/backtest/portfolio/run` API endpoint | 1 | ✅ Passed |
| `tests/test_optimizer_api.py` | `POST /api/v1/backtest/optimize` API endpoint | 2 | ✅ Passed |
| `tests/test_bot_and_audit_api.py` | `POST /api/v1/bot/auto-assign`, `/start`, `/stop`, `GET /status`, `/trades`, broker merge | 2 | ✅ Passed |
| `tests/test_live_trade_store.py` | SQLite `TradeStore` persistence, trade saving, outcome update, listing, pagination | 1 | ✅ Passed |
| `tests/test_broker_xls_merger.py` | Broker exported XLS/CSV report parsing and telemetry alignment | 1 | ✅ Passed |
| `tests/test_candles_api.py` | `GET /api/v1/candles/` broker gateway mock, period validation, broker errors | 8 | ✅ Passed |
| `tests/test_balance_api.py` | `GET /api/v1/balance` endpoint and PocketOption error/demo mapping | 2 | ✅ Passed |
| `tests/test_indicators_api.py` | `POST /api/v1/indicators/...` calculation endpoints | 4 | ✅ Passed |
| `tests/test_indicator_payload.py` | Indicator request payload schemas and validator models | 3 | ✅ Passed |
| `tests/test_rsi_indicator.py` | RSI domain calculator and value boundaries | 4 | ✅ Passed |
| `tests/test_trading_view_gateway.py` | `TradingViewGateway` interval translation, DataFrame normalization | 3 | ✅ Passed |
| `tests/test_tradingview_api.py` | `GET /api/v1/tradingview/candles` REST endpoint | 4 | ✅ Passed |
| `tests/test_backtest_sanity_mock_df.py` | Sanity test: OHLCV DataFrame (~100 bars) $\rightarrow$ Candles $\rightarrow$ ta RSI | 1 | ✅ Passed |
| **Total** | **All Modules in Workspace** | **66** | **100% Passed (3.23s)** |

---

## 7. Datasets & Available Data Sources

1. **SQLite Persistent Trade Database**:
   - File: `data/trades.db`
   - Table: `trades` (80 persisted live/demo trades with full indicator snapshots, broker order IDs, PnL, outcomes).
2. **Pocket Option WebSocket Feed (`PocketOptionTradingGateway`)**:
   - Real-time candle history fetching for native periods ($1\text{s}, 5\text{s}, 15\text{s}, 30\text{s}, 60\text{s}, 300\text{s}$).
   - Dynamic asset payout querying (`get_asset_payout`).
3. **TradingView Feed (`TradingViewGateway`)**:
   - `tvDatafeed` scraper for multi-timeframe spot market OHLCV data ($1\text{m}, 3\text{m}, 5\text{m}, 15\text{m}, 1\text{h}, 1\text{d}$).
4. **Synthetic Historical Generator**:
   - Synthetic OHLCV generators in test fixtures (`numpy` geometric random walk + sinusoidal trend waves + Gaussian noise).
5. **CSV/JSON Custom Loader**:
   - Ingestion through `parse_candles_csv_or_json` supporting any historical broker dumps.

---

## 8. Actionable Recommendations for Implementation Phase

| Area | Target File | Actionable Implementation Details |
| :--- | :--- | :--- |
| **R1: Volatility Squeeze Bug Fix** | `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:84` | Change `squeeze_fired = (sq_prev and not sq_now) or (not sq_now and abs(mom) > 0)` to `squeeze_fired = sq_prev and not sq_now`. |
| **R1: Bollinger ATR Enhancement** | `src/strat_trade/domain/strategies/bollinger_atr_reversion.py` | 1. Calculate $ADX(14)$ in `prepare_dataframe`.<br>2. Add `adx_trend_threshold` (default $25.0$) to suppress signals during runaway trends.<br>3. Enforce candle close confirmation: `close > bb_l` and bullish candle for CALL; `close < bb_h` and bearish candle for PUT. |
| **R2: Bot Engine Guardrails** | `src/strat_trade/domain/trading/bot_engine.py` | 1. Add configurable per-asset and global cooldown timers ($N$ bars/seconds).<br>2. Add correlated currency exposure filter (prevent duplicate entries in correlated pairs).<br>3. Add consecutive loss circuit breaker (pause bot after $K$ consecutive losses). |
| **R3: Rolling 15-Trade Window Benchmark** | `src/strat_trade/domain/backtest/` & `tests/` | 1. Implement `Rolling15TradeVerificationRunner` in domain.<br>2. Add automated tuning loop using `StrategyOptimizerEngine`.<br>3. Add unit and regression benchmark tests verifying all sequential 15-trade batches pass $WR \ge 53.4\%$ and Net Growth $> 0$. |

---

*Report prepared by `survey_explorer_3`. All source files verified directly.*
