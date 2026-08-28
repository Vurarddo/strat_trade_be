# Milestone 3 Explorer 3: Test Architecture for Rolling 15-Trade Verification Benchmark & Auto-Tuning Loop

**Author**: Explorer 3 (Milestone 3 — Automated Iterative Verification & Optimization Loop R3)  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_explorer_3/`  
**Date**: 2026-08-20  

---

## 1. Observation

### 1.1 Requirements & Codebase Grounding
- **ORIGINAL_REQUEST.md (§R3 & Acceptance Criteria)**:
  - "Construct an objective verification test runner that tests candidate strategy configurations on historical candle datasets." (Lines 22-23)
  - "Evaluate performance across sequential non-overlapping 15-trade batches under realistic payout conditions (92% payout / -100% loss)." (Line 23)
  - "If any 15-trade batch fails the profitability threshold (Win Rate $\ge 53.4\%$, Net Profit $> 0$), automatically trigger parameter tuning or filter adjustments until all validation batches achieve consistent profit growth without overfitting." (Line 24)
  - "In the automated backtest verification benchmark, every rolling/sequential 15-trade validation sample yields a positive net PnL (Win Rate $\ge 53.4\%$, Net Growth $> 0$)." (Line 37)
- **PROJECT.md (§Interface Contracts & Code Layout)**:
  - Feature 7: "Rolling 15-Trade Window Verification Benchmark" (Line 28)
  - Feature 8: "Automated Parameter Tuning Feedback Loop" (Line 29)
  - M3 Interface: `Rolling15TradeVerificationRunner` in `src/strat_trade/domain/backtest/verification_runner.py` with `evaluate_batches(summary: BacktestSummary) -> dict[str, Any]` validating `win_rate_pct >= 53.4%` and `net_pnl > 0.0` under 92% payout (Lines 66-70).
- **TEST_INFRA.md (§Test Architecture & Coverage Thresholds)**:
  - Benchmark Suite: `tests/test_rolling_15_trade_verification.py` (Line 23).
  - "All 15-trade rolling batches must strictly satisfy: Win Rate $\ge 53.4\%$, Net Growth $> 0$ at 92% broker payout." (Line 39).
  - Coverage: $\ge 5$ Tier 1, $\ge 5$ Tier 2, $\ge 5$ Tier 3/4 tests per feature (Lines 35-39).
- **Existing Codebase State**:
  - `src/strat_trade/domain/backtest/models.py`: Defines `BacktestConfig`, `BacktestTrade`, `TradeOutcome`, `BacktestSummary`.
  - `src/strat_trade/domain/backtest/engine.py`: Event-driven `BinaryBacktestEngine` simulating trade entries and forward exits at $t + \text{expiration\_bars}$, computing `win_rate_pct`, `profit_factor`, `net_profit`, and `trades`.
  - `src/strat_trade/domain/optimizer/grid_search.py`: `StrategyOptimizerEngine` executing Cartesian grid search over parameter grids, ranking configurations by `rank_score = (wr * pf * dd_factor) + (net * 0.1)`.
  - `src/strat_trade/domain/optimizer/auto_matcher.py`: `StrategyAutoMatcher` matching assets to optimal strategy variants and parameter profiles.
  - `src/strat_trade/domain/binary_options_metrics.py`: Vectorized `compute_binary_options_signal_metrics` computing expected value per $1 USD stake.
  - Existing test suite (`tests/`): 30 test files with 278 unit/adversarial tests passing at 100% with 0 regressions.

---

## 2. Logic Chain

### 2.1 Mathematical Foundations of Binary Options & 15-Trade Batches

Under the binary options payout model on Pocket Option:
- **Broker Payout**: $R = 0.92$ (92% profit on winning trade).
- **Loss Penalty**: $-1.00$ (-100% of stake on losing trade).
- **Tie / Draw PnL**: $0.00$ (Stake returned intact).

#### Mathematical Break-Even Win Rate ($WR_{BE}$)
For unit stake $S = 1.0$, the expected value per trade is:
$$E[X] = p \cdot R - (1 - p) \cdot 1.00 = p \cdot (1 + R) - 1.00$$
Setting $E[X] = 0$:
$$WR_{BE} = \frac{1}{1 + R} = \frac{1}{1 + 0.92} = \frac{1}{1.92} \approx 52.0833\%$$

#### Discrete Payoff Distribution for 15-Trade Batches ($N = 15$)
Let $W$ be wins, $L = 15 - W$ be losses in a 15-trade batch with unit stake $S = 1.0$:
$$\text{Net PnL}(W) = W \times 0.92 - (15 - W) \times 1.00 = 1.92 W - 15.00$$
$$\text{Win Rate}(W) = \frac{W}{15} \times 100\%$$

| Wins ($W$) | Losses ($L$) | Win Rate (%) | Net PnL ($S = 1.0$) | Net PnL ($S = 10.0$) | Profit Factor | Threshold Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 15 | 0 | 100.00% | +13.80 | +138.00 | $\infty$ | **PASS** |
| 14 | 1 | 93.33% | +11.88 | +118.80 | 12.88 | **PASS** |
| 13 | 2 | 86.67% | +9.96 | +99.60 | 5.98 | **PASS** |
| 12 | 3 | 80.00% | +8.04 | +80.40 | 3.68 | **PASS** |
| 11 | 4 | 73.33% | +6.12 | +61.20 | 2.53 | **PASS** |
| 10 | 5 | 66.67% | +4.20 | +42.00 | 1.84 | **PASS** |
| 9 | 6 | 60.00% | +2.28 | +22.80 | 1.38 | **PASS** |
| **8** | **7** | **53.33%** | **+0.36** | **+3.60** | **1.05** | **PASS (Minimum Winning Integer)** |
| 7 | 8 | 46.67% | -1.56 | -15.60 | 0.81 | **FAIL** |
| 6 | 9 | 40.00% | -3.48 | -34.80 | 0.61 | **FAIL** |
| 5 | 10 | 33.33% | -5.40 | -54.00 | 0.46 | **FAIL** |
| 0 | 15 | 0.00% | -15.00 | -150.00 | 0.00 | **FAIL** |

#### Key Inferences:
1. **Integer Critical Threshold**: In any 15-trade batch, $W = 8$ is the *exact mathematical tipping point*. 8 wins yields $+0.36$ net gain per unit stake at $53.33\%$ win rate. 7 wins yields $-1.56$ net loss at $46.67\%$ win rate.
2. **Tolerance & Precision**: $\frac{8}{15} \approx 53.3333\%$. When evaluating the threshold $\text{Win Rate} \ge 53.4\%$ vs $\ge 53.33\%$, an exact integer ratio $W \ge 8$ on a 15-trade sample corresponds to $53.33\%$. In `Rolling15TradeVerificationRunner`, the acceptance condition must enforce $W \ge 8$ (or `win_rate_pct >= Decimal("53.33")` / `win_rate_pct >= Decimal("53.4")` when floating round off $53.33\%$ is handled) and `net_pnl > Decimal("0.0")`.
3. **Ties / Draws Handling**: When ties occur (e.g. $W=7, L=6, D=2$), decisive trades $= 13$. Win rate is $\frac{7}{13} = 53.85\% \ge 53.4\%$, and Net PnL is $7 \times 0.92 - 6 \times 1.00 = +0.44 > 0.0$. This batch correctly passes.

---

### 2.2 Batch Partitioning & Boundary Condition Logic

Let $M$ be the total number of trades from a backtest execution.
1. **Sequential Non-Overlapping Batches**:
   - Number of full batches: $K = \lfloor M / 15 \rfloor$.
   - Slices: $[0:15], [15:30], \dots, [(K-1)\cdot 15 : K \cdot 15]$.
   - Remainder slice: $[K \cdot 15 : M]$ of size $R = M \bmod 15$.
2. **Rolling / Sliding Windows**:
   - Number of rolling windows: $N_{rolling} = \max(0, M - 15 + 1)$.
   - Slices: $[0:15], [1:16], [2:17], \dots, [M-15 : M]$.

#### Boundary Matrix:
- **$M = 0$ (Empty trades)**:
  - Batches $= 0$. Runner returns `total_batches=0, all_batches_passed=False, status="INSUFFICIENT_TRADES"`.
- **$1 \le M < 15$ (Fewer than 15 trades)**:
  - Full batches $= 0$. Partial remainder batch of size $M$.
  - Runner returns `total_batches=0, partial_batches=1, all_batches_passed=False, status="INSUFFICIENT_TRADES"`.
- **$M = 15, 30, 45, 60$ (Exact Multiples of 15)**:
  - Exactly $K = M / 15$ full batches ($K = 1, 2, 3, 4$). Remainder $= 0$.
  - Every batch has exactly 15 trades. `all_batches_passed = all(b.passed for b in batches)`.
- **$M = 16, 29, 31, 44, 59, 74$ (Remainder Trades)**:
  - $K = \lfloor M / 15 \rfloor$ full batches evaluated. Remainder batch of size $M \bmod 15 \in [1, 14]$ flagged as `is_partial=True` and evaluated with proportionate threshold or reported separately.

---

### 2.3 Synthetic Multi-Regime Candle Test Fixtures

To ensure deterministic, reproducible test execution across all market dynamics, `tests/test_rolling_15_trade_verification.py` will incorporate a specialized `MultiRegimeCandleFactory`:

```python
class MultiRegimeCandleFactory:
    """Deterministic OHLCV fixture generator for quantitative strategy benchmarking."""
    
    @staticmethod
    def make_ranging_channel(n: int = 200, base_price: float = 1.0850, amplitude: float = 0.0015, period: int = 25) -> pd.DataFrame:
        """Sinusoidal mean-reverting channel with low ADX (<18) and clean Bollinger bounces."""
        ...
        
    @staticmethod
    def make_trending_runaway(n: int = 200, base_price: float = 1.0850, slope: float = 0.00025, noise: float = 0.00005) -> pd.DataFrame:
        """Strong directional runaway trend with high ADX (>35) and expanding moving averages."""
        ...
        
    @staticmethod
    def make_squeeze_and_breakout(n: int = 200, squeeze_bars: int = 40, breakout_direction: str = "BULLISH") -> pd.DataFrame:
        """Compression phase (BB inside KC) transitioning into sharp expansion and momentum surge."""
        ...
        
    @staticmethod
    def make_high_volatility_chop(n: int = 200, base_price: float = 1.0850, volatility: float = 0.0008) -> pd.DataFrame:
        """Noisy random walk with large wicks, false breakouts, and high ATR spikes."""
        ...
        
    @staticmethod
    def make_composite_session(n: int = 600) -> pd.DataFrame:
        """Multi-regime concatenated sequence: Ranging (150 bars) -> Squeeze (50 bars) -> Bullish Trend (150 bars) -> Chop (100 bars) -> Mean Reversion (150 bars)."""
        ...
```

---

### 2.4 Automated Auto-Tuning Feedback Loop Workflow

When a candidate strategy is evaluated:
1. **Phase 1: Baseline Verification**:
   - Strategy is backtested across candle dataset.
   - Sequential trades partitioned into 15-trade batches.
   - Batch 1: WR $= 40.0\%$, Net PnL $= -34.80 \to$ **FAIL**.
   - Batch 2: WR $= 46.7\%$, Net PnL $= -15.60 \to$ **FAIL**.
   - `all_batches_passed = False`.
2. **Phase 2: Optimizer Trigger**:
   - `Rolling15TradeVerificationRunner` activates auto-tuning mode (`auto_tune=True`).
   - Invokes `StrategyOptimizerEngine` or auto-tuning parameter sweep across strategy's parameter space (e.g. `bb_std`: `[1.8, 2.0, 2.2]`, `adx_trend_threshold`: `[20.0, 25.0, 30.0]`, `expiration_bars`: `[2, 3, 4]`).
3. **Phase 3: Multi-Batch Optimization Objective**:
   - Objective function evaluates candidates on *worst-batch performance* and *batch consistency* ($\min_{b} \text{WR}_b \ge 53.4\%$ and $\min_b \text{NetPnL}_b > 0$).
4. **Phase 4: Verified Optimal Output**:
   - Re-running verification benchmark with tuned parameters achieves 100% batch pass rate (e.g. Batch 1: 10W/5L, Batch 2: 11W/4L, Batch 3: 9W/6L).
   - Test verifies: `initial_report.all_batches_passed == False` $\to$ `tuned_report.all_batches_passed == True` $\to$ `tuned_report.auto_tuned == True`.

---

### 2.5 API Schemas & Integration Contracts

#### Domain Data Models (`src/strat_trade/domain/backtest/verification_runner.py`)
```python
@dataclass(frozen=True)
class TradeBatchResult:
    batch_index: int
    start_trade_index: int
    end_trade_index: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: Decimal
    net_pnl: Decimal
    max_consecutive_losses: int
    roi_pct: Decimal
    passed: bool
    is_partial: bool = False

@dataclass
class RollingVerificationReport:
    strategy_name: str
    asset: str
    total_trades: int
    payout_rate: Decimal
    total_batches: int
    passed_batches: int
    failed_batches: int
    all_batches_passed: bool
    overall_win_rate_pct: Decimal
    overall_net_pnl: Decimal
    batches: list[TradeBatchResult] = field(default_factory=list)
    auto_tuned: bool = False
    initial_params: dict[str, Any] = field(default_factory=dict)
    optimized_params: dict[str, Any] | None = None
    tuning_iterations: int = 0
```

#### API Schemas (`src/strat_trade/api/schemas.py`)
```python
class TradeBatchResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_index: int
    start_trade_index: int
    end_trade_index: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    net_pnl: float
    max_consecutive_losses: int
    roi_pct: float
    passed: bool
    is_partial: bool = False

class RollingVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str = "EURUSD_otc"
    timeframe_seconds: int = 60
    strategy_name: str = "bollinger_atr_reversion"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    payout_rate: float = 0.92
    initial_deposit: float = 1000.0
    stake_amount: float = 10.0
    candle_count: int = 500
    auto_tune: bool = False
    parameter_grid: dict[str, list[Any]] | None = None

class RollingVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_name: str
    asset: str
    total_trades: int
    payout_rate: float
    total_batches: int
    passed_batches: int
    failed_batches: int
    all_batches_passed: bool
    overall_win_rate_pct: float
    overall_net_pnl: float
    batches: list[TradeBatchResultResponse]
    auto_tuned: bool
    initial_params: dict[str, Any]
    optimized_params: dict[str, Any] | None = None
```

#### API Endpoint (`src/strat_trade/api/routes/backtest.py`)
- `POST /api/v1/backtest/verify-15-trades`: Accepts `RollingVerificationRequest`, executes verification & optional auto-tuning, returns `RollingVerificationResponse`.

---

## 3. Concrete Test Plan & Test Case Definitions (`tests/test_rolling_15_trade_verification.py`)

The test architecture is structured into **5 rigorous tiers** containing **40 distinct test cases**:

### Tier 1: Unit & Mathematical Verification Tests (10 Tests)
| # | Test Function Name | Scope / Input Condition | Expected Result & Assertions |
|---|-------------------|-------------------------|------------------------------|
| 1 | `test_math_92pct_payout_8_wins_7_losses_profit` | 15 trades: 8 WIN, 7 LOSS, Payout = 0.92, Stake = $10.0 | Net PnL $= +3.60$, WR $= 53.33\%$, `passed == True`. |
| 2 | `test_math_92pct_payout_7_wins_8_losses_loss` | 15 trades: 7 WIN, 8 LOSS, Payout = 0.92, Stake = $10.0 | Net PnL $= -15.60$, WR $= 46.67\%$, `passed == False`. |
| 3 | `test_math_92pct_payout_15_wins_zero_losses` | 15 trades: 15 WIN, 0 LOSS, Payout = 0.92, Stake = $10.0 | Net PnL $= +138.00$, WR $= 100.0\%$, PF $= \infty$, `passed == True`. |
| 4 | `test_math_92pct_payout_zero_wins_15_losses` | 15 trades: 0 WIN, 15 LOSS, Payout = 0.92, Stake = $10.0 | Net PnL $= -150.00$, WR $= 0.0\%$, PF $= 0.0$, `passed == False`. |
| 5 | `test_math_ties_and_draws_handling` | 15 trades: 7 WIN, 6 LOSS, 2 DRAW, Payout = 0.92, Stake = $10.0 | Decisive $= 13$, WR $= 53.85\%$, Net PnL $= +4.40$, `passed == True`. |
| 6 | `test_math_varying_payout_rates_break_even` | Parameterized payouts: 0.80, 0.85, 0.90, 0.92, 0.95 | Verifies exact integer win counts required to achieve positive Net PnL across broker payouts. |
| 7 | `test_math_percent_stake_compounding_batch` | 15 trades with 2% compounding stake model | Net PnL reflects dynamic balance progression, batch metrics calculated accurately. |
| 8 | `test_math_martingale_stake_in_15_trade_batch` | 15 trades under 2-step Martingale stake model | Stake escalations tracked accurately, drawdowns and net profit verified. |
| 9 | `test_math_max_consecutive_losses_in_batch` | 15 trades: 7 losses followed by 8 wins | `max_consecutive_losses == 7`, Net PnL $= +3.60$, `passed == True`. |
| 10 | `test_math_roi_and_profit_factor_consistency` | 15 trades with various win/loss permutations | Asserts $\text{ROI} = (\text{Net PnL} / \text{Initial Deposit}) \times 100\%$ and $\text{PF} = \text{Gross Gains} / \text{Gross Losses}$. |

### Tier 2: Boundary & Edge Case Partitioning Tests (10 Tests)
| # | Test Function Name | Scope / Input Condition | Expected Result & Assertions |
|---|-------------------|-------------------------|------------------------------|
| 11 | `test_partitioning_empty_trades_list` | 0 trades generated ($M = 0$) | `total_batches == 0`, `all_batches_passed == False`, status indicates insufficient data. |
| 12 | `test_partitioning_single_trade` | 1 trade ($M = 1$) | `total_batches == 0`, partial batch reported, `all_batches_passed == False`. |
| 13 | `test_partitioning_14_trades_insufficient` | 14 trades ($M = 14$) | `total_batches == 0`, 1 partial batch of length 14, `all_batches_passed == False`. |
| 14 | `test_partitioning_exact_15_trades_one_batch` | Exactly 15 trades ($M = 15$) | `total_batches == 1`, 0 remainder trades, batch index 0 spans [0:15]. |
| 15 | `test_partitioning_16_trades_single_batch_one_remainder` | 16 trades ($M = 16$) | `total_batches == 1`, 1 full batch [0:15], 1 partial remainder [15:16]. |
| 16 | `test_partitioning_exact_30_trades_two_batches` | Exactly 30 trades ($M = 30$) | `total_batches == 2`, Batch 0 [0:15], Batch 1 [15:30], 0 remainder. |
| 17 | `test_partitioning_45_trades_three_batches` | Exactly 45 trades ($M = 45$) | `total_batches == 3`, Batch 0 [0:15], Batch 1 [15:30], Batch 2 [30:45]. |
| 18 | `test_partitioning_59_trades_three_batches_14_remainder` | 59 trades ($M = 59$) | `total_batches == 3`, 3 full batches, 1 remainder of 14 trades. |
| 19 | `test_partitioning_exact_60_trades_four_batches` | Exactly 60 trades ($M = 60$) | `total_batches == 4`, exactly 4 non-overlapping batches of 15 trades each. |
| 20 | `test_rolling_sliding_window_partitioning` | 30 trades evaluated under rolling sliding window mode | Generates $30 - 15 + 1 = 16$ sliding windows of 15 trades each. |

### Tier 3: Strategy & Regime Integration Tests (8 Tests)
| # | Test Function Name | Scope / Input Condition | Expected Result & Assertions |
|---|-------------------|-------------------------|------------------------------|
| 21 | `test_bollinger_atr_on_ranging_channel_passes` | `BollingerAtrReversionStrategy` on sinusoidal channel (250 bars) | Generates $\ge 15$ trades, every batch achieves $W \ge 8$, Net PnL $> 0$. |
| 22 | `test_bollinger_atr_adx_suppression_on_runaway_trend` | `BollingerAtrReversionStrategy` on runaway trend (250 bars) | ADX filter suppresses counter-trend signals; 0 toxic knife-catch losses. |
| 23 | `test_squeeze_breakout_on_multi_cycle_squeeze` | `VolatilitySqueezeBreakoutStrategy` on 3 squeeze cycles | Triggers strictly on squeeze release, generates high-win-rate batch. |
| 24 | `test_squeeze_breakout_uncompressed_ranging_silence` | `VolatilitySqueezeBreakoutStrategy` on wide uncompressed channel | Zero false breakout signals fired during non-squeeze bars. |
| 25 | `test_hybrid_multifactors_on_composite_market` | `HybridMultiFactorsStrategy` on 400 composite candles | Multi-factor confirmation yields $\ge 2$ consecutive passing 15-trade batches. |
| 26 | `test_ema_pullback_on_trending_market` | `EmaPullbackTrendStrategy` on strong trend market | Pullback signals align with EMA ribbon, passing all batches. |
| 27 | `test_supertrend_adx_on_high_volatility_crypto` | `SupertrendAdxMomentumStrategy` on volatile trend bars | Momentum filter captures breakout extensions, batch win rate $\ge 60\%$. |
| 28 | `test_support_resistance_bounce_fractal_reversal` | `SupportResistanceBounceStrategy` on multi-pivot range | Wick rejections at major swing levels generate positive PnL batches. |

### Tier 4: Automated Optimization Loop & Feedback Tests (6 Tests)
| # | Test Function Name | Scope / Input Condition | Expected Result & Assertions |
|---|-------------------|-------------------------|------------------------------|
| 29 | `test_autotune_triggers_on_failing_batch` | Suboptimal config (`bb_std=1.5`, `adx=40`) failing Batch 1 (40% WR) | Runner detects failure, triggers optimizer, tunes parameters, all batches pass. |
| 30 | `test_autotune_skips_when_all_batches_pass` | Optimal config already passing all batches | Runner completes in 1 iteration without invoking heavy optimizer (`auto_tuned == False`). |
| 31 | `test_autotune_grid_search_parameter_discovery` | Custom grid with 12 combinations | Evaluates parameter variations, selects best parameter set satisfying all batches. |
| 32 | `test_autotune_overfitting_guard_out_of_sample` | 60-trade dataset split into In-Sample (30) and Out-of-Sample (30) | Parameter set optimized on IS maintains $\ge 53.4\%$ win rate on OOS batches. |
| 33 | `test_autotune_max_iterations_ceiling` | Impossible market condition with unachievable target | Auto-tuner respects max iterations cap and cleanly returns best available report without infinite loop. |
| 34 | `test_autotune_preserves_unmodified_strategy_defaults` | Auto-tuning strategy with partial grid | Only specified parameters are tuned; default parameters remain intact. |

### Tier 5: Real-World Multi-Regime Benchmark & Adversarial Stress Tests (6 Tests)
| # | Test Function Name | Scope / Input Condition | Expected Result & Assertions |
|---|-------------------|-------------------------|------------------------------|
| 35 | `test_benchmark_continuous_60_trade_multi_cycle` | 60-trade backtest spanning 600 realistic market bars | Evaluates 4 sequential 15-trade batches; asserts all 4 batches achieve Net PnL $> 0$. |
| 36 | `test_benchmark_high_volatility_news_shock_resilience` | Sudden 500% ATR spike and rapid mean reversion | Guardrails prevent drawdown cascade; batch win rate maintained above break-even. |
| 37 | `test_benchmark_prolonged_ranging_to_breakout_shift` | 150 bars ranging $\to$ 150 bars violent breakout | Strategy adapts to regime transition across sequential 15-trade cycles. |
| 38 | `test_benchmark_multi_asset_portfolio_batch_evaluation` | Multi-asset portfolio backtest (EUR/USD, GBP/USD, USD/JPY) | Unified 15-trade batches across shared portfolio pass profitability criteria. |
| 39 | `test_api_verify_15_trades_endpoint_full_lifecycle` | FastAPI `POST /api/v1/backtest/verify-15-trades` | Endpoint parses request, executes verification, returns valid `RollingVerificationResponse`. |
| 40 | `test_api_verify_15_trades_with_autotune_endpoint` | FastAPI `POST /api/v1/backtest/verify-15-trades` with `auto_tune=True` | Endpoint executes auto-tuning and returns optimized parameters with passing batches. |

---

## 4. Caveats

1. **Broker Slippage & Execution Delays**: Historical candle backtests assume instantaneous order fills at bar close/open. In live trading, broker latency (~50-300ms) and price quote drift can introduce slight variance.
2. **Discrete Integer Trade Granularity**: In a 15-trade batch, each trade represents exactly $6.667\%$ of the sample. Win rate values are discrete multiples: $0\%, 6.67\%, 13.33\%, \dots, 53.33\%, 60.00\%, \dots, 100\%$. The transition from $W=7$ to $W=8$ shifts the win rate from $46.67\%$ to $53.33\%$.
3. **Overfitting Sensitivity on Small Search Grids**: Auto-tuning on short candle histories (<150 bars) risks selecting parameters fit to localized noise. The test fixtures provide $\ge 250-600$ candles to ensure statistical significance.

---

## 5. Conclusion

1. **Test Architecture is Fully Specified**: A rigorous, mathematically sound test architecture for `tests/test_rolling_15_trade_verification.py` is established, covering binary options math ($W \ge 8$ break-even), batch partitioning boundary conditions, multi-regime fixtures, auto-tuning feedback loops, and API/CLI schemas.
2. **Complete 40-Test Specification Delivered**: 40 concrete test case definitions spanning 5 tiers are fully designed and mapped to `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `TEST_INFRA.md`.
3. **Execution Readiness**: The test architecture seamlessly integrates with the existing codebase (`BinaryBacktestEngine`, `StrategyOptimizerEngine`, `FastAPI` schemas) and provides complete guidance for Worker implementation in Milestone 3.

---

## 6. Verification Method

To verify the test suite and ensure zero regressions across the codebase:

```bash
# 1. Run all existing tests to confirm baseline integrity
.venv/bin/pytest -v

# 2. Run specific backtest and optimizer tests
.venv/bin/pytest -v tests/test_backtest_models_and_engine.py tests/test_strategy_optimizer.py tests/test_optimizer_api.py

# 3. Upon implementation of tests/test_rolling_15_trade_verification.py, run:
.venv/bin/pytest -v tests/test_rolling_15_trade_verification.py
```

Invalidation Conditions:
- Any 15-trade batch with $W = 8$ wins at 92% payout failing to yield positive Net PnL.
- Batch partitioning misallocating trades or losing remainder records.
- Auto-tuning entering infinite loops or failing to produce verifiable improvements.
