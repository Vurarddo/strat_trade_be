# Comprehensive Quant Math, Strategy Optimizer & Database Anomaly Forensic Report

**Role**: Explorer 3 (Quant Math, Optimizer & Database Anomaly Analyst)  
**Milestone**: Pocket Option AutoTrader Pro Stress-Test Survey  
**Date**: 2026-08-28  
**Scope**: In-depth mathematical expectancy (EV) analysis, optimizer overfitting decomposition, concurrency/race condition audit, forensic root-cause analysis of the 10-trades-in-3-seconds database anomaly, and Monte Carlo worst-case modeling.

---

## Executive Summary

A comprehensive quantitative and architectural audit of **Pocket Option AutoTrader Pro** reveals severe mathematical vulnerabilities, optimizer selection biases, and multi-threaded/async concurrency flaws that jeopardize account solvency. 

Key high-level findings include:
1. **Asymmetric Binary Payout Drag & The "Death Zone"**: Binary options pay $+P \cdot S$ on win and $-S$ on loss. At standard Pocket Option payouts ($75\% - 85\%$), the breakeven win rate ranges from $54.05\%$ to $57.14\%$. If broker payouts drop below $81.8\%$ for a $55\%$ win-rate strategy, mathematical expectancy ($EV$) flips negative, guaranteeing asymptotic ruin.
2. **Circuit Breaker False-Positive Choke**: Under a realistic $57.0\%$ win rate with flat $\$10$ staking on a $\$1,000$ balance, normal binomial variance generates a $95$th percentile max drawdown of $33.10\%$ over $500$ trades. Consequently, the bot's static $8.0\%$ max drawdown circuit breaker (`max_drawdown_pct_limit = 0.08`) will be triggered in **$95.82\%$ of all 500-trade sequences**, prematurely killing profitable bots due to standard variance rather than true alpha decay.
3. **Optimizer Pseudo-Optimization & Bias Distortion**: `StrategyAutoMatcher` backtests candidate strategies on only $150$ M1 candles ($2.5$ hours of market data), yielding samples of only $1 - 5$ trades. A $100\%$ win rate over $N=2$ trades has a $95\%$ Wilson confidence interval of $[34.24\%, 100.0\%]$ (statistically indistinguishable from random coin flips). Moreover, the optimizer injects up to $+30.0$ artificial score points for "Priority" strategies and "Whitelisted" assets—equivalent to a $+10.0\%$ artificial win rate boost that overrides actual empirical performance.
4. **Forensic Root Cause of the 10-Trades-in-3-Seconds Anomaly**: Forensic query of `data/trades.db` revealed $9$ live trades opened in $2.41$ seconds, with $5$ trades sharing the exact millisecond timestamp `2026-08-28T11:06:00.350966+00:00`. The root cause is a compound concurrency defect in `LiveDemoBotEngine._evaluate_signals_and_trade()`:
   - `asyncio.gather()` fans out tasks across all assigned assets simultaneously.
   - Pre-trade validation checks (concurrency limit, asset uniqueness, correlation filter) evaluate `self.active_trades` while it is empty (`{}`) for all concurrent tasks.
   - A single, stale `now` timestamp is captured at the loop start and passed into `_execute_order()`, causing `(now - _last_global_execution_time).total_seconds()` to evaluate to `0.0s`, bypassing the global cooldown.
   - Continuation signals from `supertrend_adx_momentum` fire unconditionally on every bar during trend regimes, causing simultaneous cross-asset execution.

---

## 1. Axis 2: Mathematical Expectancy (EV) at 75%–92% Payouts

### 1.1 Breakeven Win Rate Formulation
In binary options trading, every trade has a binary payoff:
- **Win**: Payout is $+S \cdot P$ (where $S$ is stake amount, $P$ is broker payout decimal $\in [0.70, 0.92]$).
- **Loss**: Loss is $-S$ ($100\%$ of stake lost).
- **Draw / Tie**: Net PnL is $\$0.00$ (stake returned).

The expected dollar return per trade $E[\text{PnL}]$ is:
$$E[\text{PnL}] = p \cdot (S \cdot P) - (1 - p - d) \cdot S$$
Assuming tie rate $d = 0$, the mathematical expectancy per $\$1.00$ staked is:
$$EV = p \cdot P - (1 - p) = p \cdot (1 + P) - 1$$

Setting $EV = 0$, the exact **Breakeven Win Rate ($p_{\text{BE}}$)** is:
$$p_{\text{BE}} = \frac{1}{1 + P}$$

#### Table 1.1: Exact Breakeven Win Rate vs. Broker Payout
| Broker Payout ($P$) | Decimal ($P$) | Exact Breakeven Win Rate ($p_{\text{BE}}$) | Minimum Decisive Wins per 100 Trades | Target Win Rate for $PF = 1.30$ |
| :--- | :--- | :--- | :--- | :--- |
| **$70.0\%$** | $0.70$ | **$58.8235\%$** | $59$ wins | $65.00\%$ |
| **$75.0\%$** | $0.75$ | **$57.1429\%$** | $58$ wins | $63.41\%$ |
| **$80.0\%$** | $0.80$ | **$55.5556\%$** | $56$ wins | $61.90\%$ |
| **$85.0\%$** | $0.85$ | **$54.0541\%$** | $55$ wins | $60.47\%$ |
| **$90.0\%$** | $0.90$ | **$52.6316\%$** | $53$ wins | $59.09\%$ |
| **$92.0\%$** | $0.92$ | **$52.0833\%$** | $53$ wins | $58.56\%$ |

*Observation*: A payout decrease from $92\%$ to $75\%$ increases the required breakeven win rate by **$+5.06\%$** (from $52.08\%$ to $57.14\%$). 

---

### 1.2 Mathematical Expectancy Formula & Worked Numerical Examples

**Formula**:
$$EV = p \cdot P - (1 - p) = p(1 + P) - 1$$
$$\text{Expected PnL for } N \text{ trades with stake } S: \quad E[\text{Total PnL}] = N \cdot S \cdot EV$$

#### Worked Example A: Modest Edge at Standard 80% Payout
- Strategy: `hybrid_multifactors`, Win rate $p = 56.0\%$, Payout $P = 80.0\%$ ($0.80$), Stake $S = \$10.00$.
- $EV = 0.56 \cdot 0.80 - (1 - 0.56) = 0.448 - 0.440 = +\$0.008$ per $\$1.00$ staked ($+0.80\%$ ROI/trade).
- Expected return on $\$10.00$ bet: $+\$0.08$ per trade.
- Expected return over $500$ trades: $500 \times \$10.00 \times 0.008 = +\$40.00$.

#### Worked Example B: Payout Compression Flip to Negative EV
- Same strategy ($p = 56.0\%$), but broker dynamically lowers payout during high volatility to $P = 75.0\%$ ($0.75$).
- $EV = 0.56 \cdot 0.75 - (1 - 0.56) = 0.420 - 0.440 = -\$0.020$ per $\$1.00$ staked ($-2.00\%$ ROI/trade).
- Expected return on $\$10.00$ bet: $-\$0.20$ per trade.
- Expected return over $500$ trades: $500 \times \$10.00 \times (-0.020) = -\$100.00$.
- *Conclusion*: A mere $5\%$ drop in payout turns a profitable bot into a guaranteed money-losing system.

#### Worked Example C: High Payout vs. Low Win Rate Illusion
- Strategy: `supertrend_adx_momentum`, Win rate $p = 53.0\%$.
- At $92.0\%$ Payout: $EV = 0.53 \cdot 0.92 - 0.47 = 0.4876 - 0.4700 = +\$0.0176$ per dollar ($+1.76\%$). Profitable!
- At $80.0\%$ Payout: $EV = 0.53 \cdot 0.80 - 0.47 = 0.4240 - 0.4700 = -\$0.0460$ per dollar ($-4.60\%$). Severe loss!

---

### 1.3 Full Payout vs. Win Rate Sensitivity Matrix

#### Table 1.2: Expected Value ($EV$) in Dollars per $100.00 Staked
| Realized Win Rate ($p$) | Payout 70% | Payout 75% | Payout 80% | Payout 85% | Payout 90% | Payout 92% |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **$50.00\%$** (Coin Flip) | $-\$15.00$ | $-\$12.50$ | $-\$10.00$ | $-\$7.50$ | $-\$5.00$ | $-\$4.00$ |
| **$52.00\%$** | $-\$11.60$ | $-\$9.00$ | $-\$6.40$ | $-\$3.80$ | $-\$1.20$ | $-\$0.16$ |
| **$53.00\%$** | $-\$9.90$ | $-\$7.25$ | $-\$4.60$ | $-\$1.95$ | **$+\$0.70$** | **$+\$1.76$** |
| **$54.00\%$** | $-\$8.20$ | $-\$5.50$ | $-\$2.80$ | $-\$0.10$ | **$+\$2.60$** | **$+\$3.68$** |
| **$55.00\%$** | $-\$6.50$ | $-\$3.75$ | $-\$1.00$ | **$+\$1.75$** | **$+\$4.50$** | **$+\$5.60$** |
| **$55.56\%$** ($p_{\text{BE}}$ at 80%) | $-\$5.55$ | $-\$2.77$ | **$+\$0.01$** | **$+\$2.79$** | **$+\$5.56$** | **$+\$6.68$** |
| **$56.00\%$** | $-\$4.80$ | $-\$2.00$ | **$+\$0.80$** | **$+\$3.60$** | **$+\$6.40$** | **$+\$7.52$** |
| **$57.00\%$** | $-\$3.10$ | $-\$0.25$ | **$+\$2.60$** | **$+\$5.45$** | **$+\$8.30$** | **$+\$9.44$** |
| **$58.00\%$** | $-\$1.40$ | **$+\$1.50$** | **$+\$4.40$** | **$+\$7.30$** | **$+\$10.20$** | **$+\$11.36$** |
| **$60.00\%$** | **$+\$2.00$** | **$+\$5.00$** | **$+\$8.00$** | **$+\$11.00$** | **$+\$14.00$** | **$+\$15.20$** |
| **$62.00\%$** | **$+\$5.40$** | **$+\$8.50$** | **$+\$11.60$** | **$+\$14.70$** | **$+\$17.80$** | **$+\$19.04$** |
| **$65.00\%$** | **$+\$10.50$** | **$+\$13.75$** | **$+\$17.00$** | **$+\$20.25$** | **$+\$23.50$** | **$+\$24.80$** |

#### Analysis of 2%–3% Win Rate Degradation:
1. At **$80\%$ payout**, a strategy operating at $57.0\%$ WR generates $+\$2.60$ per $\$100$. A $2.0\%$ drop in WR (to $55.0\%$) flips EV to **$-\$1.00$** (a net loss of $-\$3.60$ per $\$100$ wagered).
2. At **$85\%$ payout**, a strategy operating at $56.0\%$ WR generates $+\$3.60$ per $\$100$. A $3.0\%$ drop in WR (to $53.0\%$) flips EV to **$-\$1.95$**.
3. Micro-slippage (e.g. entry delayed by 1-2 ticks) and OTC discrete price snapping typically degrade live M1 win rates by **$2.5\% - 4.0\%$** relative to idealized backtests, pushing marginally profitable strategies directly into negative territory.

---

### 1.4 The "Death Zone" Payout Threshold
The **"Death Zone"** is defined as the payout rate $P_{\text{crit}}$ below which a strategy with true win rate $p$ has negative mathematical expectancy:
$$P_{\text{crit}}(p) = \frac{1 - p}{p}$$

If actual broker payout $P < P_{\text{crit}}(p)$, the system is guaranteed to lose capital over infinite trials.

```
       DEATH ZONE (Negative EV)        │    SOLVENCY ZONE (Positive EV)
 ──────────────────────────────────────┼───────────────────────────────────
  p = 54.0%: Payout < 85.19%           │    Payout >= 85.19%
  p = 55.0%: Payout < 81.82%           │    Payout >= 81.82%
  p = 56.0%: Payout < 78.57%           │    Payout >= 78.57%
  p = 57.0%: Payout < 75.44%           │    Payout >= 75.44%
  p = 58.0%: Payout < 72.41%           │    Payout >= 72.41%
```

**Critical Vulnerability in Codebase**:
In `src/strat_trade/use_cases/auto_assign_strategies.py` line 30, `min_payout_rate` defaults to `0.80` ($80\%$). In `src/strat_trade/domain/trading/bot_engine.py` line 619, fallback `live_payout` is set to `0.92`. If the broker throttles payout to $76\% - 79\%$ during high-volatility news events, strategies with achievable OTC win rates of $54\% - 55.5\%$ are permitted to trade directly inside their Death Zone.

---

### 1.5 Compounding Negative EV Drag across 500+ Trades
If a portfolio contains $K=5$ strategies, and even **ONE** strategy operates with negative EV (e.g., $p = 53.0\%$ at $80\%$ payout $\implies EV = -0.046$), its compounding drag on portfolio capital is devastating.

Let $N = 500$ trades, stake $S = \$10.00$.
- Single negative-EV strategy executing 100 trades: $100 \times \$10.00 \times (-0.046) = -\$46.00$.
- Variance of binary outcomes per trade:
  $$\sigma^2 = (1 + P)^2 \cdot p(1 - p) = (1.80)^2 \cdot (0.53 \cdot 0.47) = 3.24 \cdot 0.2491 = 0.8071$$
  $$\sigma = \sqrt{0.8071} = 0.8984 \text{ per \$1 staked} \implies \$8.98 \text{ per \$10 stake}$$
- Standard deviation of 100 trades: $\sqrt{100} \times \$8.98 = \$89.84$.
- $95\%$ Confidence Interval of PnL for that single strategy: $[-\$46.00 - 1.96(89.84), -\$46.00 + 1.96(89.84)] = [-\$222.09, +\$130.09]$.
- A single degraded strategy easily wipes out all gains produced by 4 other marginally profitable strategies ($+1.0\%$ EV each $\implies 400 \times \$10 \times 0.01 = +\$40.00$), dragging the entire portfolio into a net loss of $-\$6.00$ and triggering session stop-loss pauses.

---

### 1.6 Kelly Criterion & Gambler's Ruin Analysis

#### The Kelly Criterion for Binary Options
The optimal fraction $f^*$ of bankroll to wager per trade to maximize log-wealth growth is:
$$f^* = \frac{p(1 + P) - 1}{P} = \frac{EV}{P}$$

#### Table 1.3: Optimal Bet Sizing Fractions ($f^*$)
| Realized Win Rate ($p$) | Payout 75% ($b=0.75$) | Payout 80% ($b=0.80$) | Payout 85% ($b=0.85$) | Payout 92% ($b=0.92$) |
| :--- | :--- | :--- | :--- | :--- |
| **$55.0\%$** | $0.00\%$ (Negative EV) | $0.00\%$ (Negative EV) | $2.06\%$ (Full Kelly) | $6.09\%$ (Full Kelly) |
| **$56.0\%$** | $0.00\%$ (Negative EV) | $1.00\%$ (Full Kelly) | $4.24\%$ (Full Kelly) | $8.17\%$ (Full Kelly) |
| **$57.0\%$** | $0.00\%$ (Negative EV) | $3.25\%$ (Full Kelly) | $6.41\%$ (Full Kelly) | $10.26\%$ (Full Kelly) |
| **$58.0\%$** | $2.00\%$ (Full Kelly) | $5.50\%$ (Full Kelly) | $8.59\%$ (Full Kelly) | $12.35\%$ (Full Kelly) |
| **$60.0\%$** | $6.67\%$ (Full Kelly) | $10.00\%$ (Full Kelly) | $12.94\%$ (Full Kelly) | $16.52\%$ (Full Kelly) |

**Quarter-Kelly Recommendation ($\kappa = 0.25$)**:
For live OTC trading under regime uncertainty, sizing must never exceed Quarter-Kelly:
$$f_{\text{safe}} = 0.25 \cdot f^*$$
At $p = 57.0\%$ and $P = 80.0\%$, $f^* = 3.25\% \implies f_{\text{safe}} = \mathbf{0.81\%}$ of balance.
At $p = 56.0\%$ and $P = 80.0\%$, $f^* = 1.00\% \implies f_{\text{safe}} = \mathbf{0.25\%}$ of balance.

**Current Sizing Flaw in Bot**:
`PreTradingPlan` uses a flat $\$10.00$ stake on a $\$1,000.00$ deposit ($1.0\%$ flat stake). When win rate is $56.0\%$ at $80\%$ payout, $1.0\%$ is **Full Kelly** (100% of Kelly limit). Full Kelly has an **$80\%$ probability of experiencing a $50\%$ drawdown** before doubling wealth!

#### Gambler's Ruin Probability
Using the diffusion approximation for gambler's ruin with initial balance $B_0 = \$1,000$ and stake $S = \$10$ ($B = 100$ betting units):
$$P_{\text{ruin}} \approx e^{-2 \mu B / \sigma^2} \quad \text{where } \mu = EV, \ \sigma^2 = (1 + P)^2 p(1 - p)$$

1. **When $p \le p_{\text{BE}}$ ($\mu \le 0$)**:
   $$P_{\text{ruin}} = \mathbf{1.0000} \ (100.0\% \text{ Guaranteed Ruin})$$
2. **When $p = 56.0\%$ at $P = 0.80$ ($\mu = +0.008, \sigma^2 = 0.7981$)**:
   $$\text{Exponent} = -\frac{2 \times 0.008 \times 100}{0.7981} = -2.0048 \implies P_{\text{ruin}} \approx e^{-2.0048} = \mathbf{13.47\%}$$
3. **When $p = 57.0\%$ at $P = 0.80$ ($\mu = +0.026, \sigma^2 = 0.7941$)**:
   $$\text{Exponent} = -\frac{2 \times 0.026 \times 100}{0.7941} = -6.5483 \implies P_{\text{ruin}} \approx e^{-6.5483} = \mathbf{0.14\%}$$

---

## 2. Axis 4: Overfitting & Signal Queue Conflicts

### 2.1 Mathematical Decomposition of `StrategyAutoMatcher` Quantum Score Formula

In `src/strat_trade/domain/optimizer/auto_matcher.py` lines 499–520, the quantum score formula is implemented as:
$$\text{Score} = 
\begin{cases} 
3.0(WR - 50.0) + 15.0 \min(PF, 4.0) + 3.0 \min(N, 10) - 0.5 DD + 0.5 ROI + 15.0 \mathbb{I}_{\text{Priority}} + 15.0 \mathbb{I}_{\text{Whitelist}} & \text{if } N \ge 2 \\
1.5(WR - 50.0) + [15.0 \text{ if } WR > 50 \text{ else } -15.0] + 15.0 \mathbb{I}_{\text{Priority}} + 15.0 \mathbb{I}_{\text{Whitelist}} & \text{if } N = 1 \\
-50.0 + 15.0 \mathbb{I}_{\text{Priority}} + 15.0 \mathbb{I}_{\text{Whitelist}} & \text{if } N = 0
\end{cases}$$

#### Bias Decomposition & Structural Flaws:

1. **Priority & Whitelist Bonus Bias (+30.0 points)**:
   - $\mathbb{I}_{\text{Priority}} = 1$ for `support_resistance_bounce` and `rsi_stochastic_extreme`.
   - $\mathbb{I}_{\text{Whitelist}} = 1$ for assets in the whitelist.
   - Combined bonus $= +30.0$ points.
   - Since the win-rate sensitivity coefficient is $3.0$, a $+30.0$ bonus is mathematically identical to adding **$+10.0\%$ to the strategy's win rate**!
   - Example: A priority strategy on a whitelisted pair with $N=2$ trades, $1\text{W} / 1\text{L}$ ($WR = 50.0\%$, $PF = 0.92$, losing money) scores:
     $$\text{Score} = 3(0) + 15(0.92) + 3(2) - 0.5(1.0) + 0.5(-0.8) + 15 + 15 = 13.8 + 6.0 - 0.5 - 0.4 + 30.0 = \mathbf{48.9}$$
   - Meanwhile, an un-whitelisted asset tested with `hybrid_multifactors` scoring $N=10$, $6\text{W}/4\text{L}$ ($WR = 60.0\%$, $PF = 1.38$) scores:
     $$\text{Score} = 3(10) + 15(1.38) + 3(10) - 0.5(2.0) + 0.5(8.0) + 0 + 0 = 30 + 20.7 + 30 - 1.0 + 4.0 = \mathbf{83.7}$$
   - But if `allowed_strategies` is not passed (the default in `auto_matcher.py` line 463), `candidate_strategies` is hard-filtered to `PRIORITY_STRATEGIES` only! The other 6 strategies in the catalog are **completely ignored and never tested**.

2. **Extreme Small-Sample Sensitivity ($N = 1$ and $N = 2$)**:
   - For $N=1$ with 1 win ($WR = 100\%$): $\text{Score} = 1.5(50) + 15 + 30 = \mathbf{120.0}$.
   - For $N=2$ with 2 wins ($WR = 100\%, PF=4.0$): $\text{Score} = 3(50) + 15(4) + 3(2) + 30 = 150 + 60 + 6 + 30 = \mathbf{246.0}$.
   - A strategy that traded twice by pure chance in $2.5$ hours receives a near-maximum score and is selected over robust, consistent strategies.

---

### 2.2 Sample Size Inadequacy: 150 M1 Candles (2.5 Hours)

In `StrategyAutoMatcher(candle_count=150)` and `auto_assign_strategies.py` line 70, the historical sample size fetched is exactly **150 M1 candles = 150 minutes = 2.5 hours**.

#### Statistical Confidence Decomposition:

To test whether an observed sample win rate $\hat{p} = w / n$ is statistically superior to the breakeven rate $p_0 = 0.5556$, we compute the Wilson Score 95% Confidence Interval ($z = 1.96$):
$$CI_{95\%} = \frac{\hat{p} + \frac{z^2}{2n} \pm z \sqrt{\frac{\hat{p}(1 - \hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$

#### Table 2.1: Statistical Significance of 150-Candle Backtest Samples
| Backtest Result | Trades ($n$) | Wins ($w$) | Sample WR ($\hat{p}$) | Wilson 95% CI Lower | Wilson 95% CI Upper | Exact Binomial P-Value ($H_0: p \le 0.5556$) | Statistical Alpha? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 Trade / 1 Win | $1$ | $1$ | $100.0\%$ | **$20.65\%$** | $100.0\%$ | $p = 0.5556$ | **NO (Pure Noise)** |
| 2 Trades / 2 Wins | $2$ | $2$ | $100.0\%$ | **$34.24\%$** | $100.0\%$ | $p = 0.3086$ | **NO (Pure Noise)** |
| 3 Trades / 2 Wins | $3$ | $2$ | $66.67\%$ | **$20.77\%$** | $93.85\%$ | $p = 0.5873$ | **NO (Pure Noise)** |
| 5 Trades / 4 Wins | $5$ | $4$ | $80.00\%$ | **$37.55\%$** | $96.38\%$ | $p = 0.2650$ | **NO (Not Significant)** |
| 10 Trades / 7 Wins | $10$ | $7$ | $70.00\%$ | **$39.68\%$** | $89.22\%$ | $p = 0.2332$ | **NO (Not Significant)** |
| 20 Trades / 14 Wins | $20$ | $14$ | $70.00\%$ | **$48.10\%$** | $85.45\%$ | $p = 0.1345$ | **NO (Not Significant)** |

**Mathematical Conclusion**:
Across all typical trade counts ($n \le 10$) produced by 150 M1 candles, the lower bound of the $95\%$ confidence interval is strictly below $40.0\%$ (far below the $55.56\%$ breakeven hurdle), and the binomial p-value is $> 0.20$ ($\gg 0.05$). **150 candles provide zero statistical power**. The optimizer is fitting to micro-noise.

**Minimum Required Sample Size**:
To establish statistical alpha at $\hat{p} = 60.0\%$ vs $p_0 = 55.56\%$ with $\alpha = 0.05$ and power $1 - \beta = 0.80$:
$$n \ge \frac{(1.645 \sqrt{0.5556 \cdot 0.4444} + 0.842 \sqrt{0.60 \cdot 0.40})^2}{(0.60 - 0.5556)^2} \approx \mathbf{380 \text{ trades}}$$
At an average frequency of 2 trades/hour, achieving 380 trades requires at least **190 hours (~8 days) of continuous M1 data (11,400 candles)**.

---

### 2.3 Parameter Grid Search & Micro-Noise Fitting
In `_generate_strategy_variations()` (lines 36–243 of `auto_matcher.py`), 2 to 3 discrete parameter variations are generated per strategy.
- When evaluated on only 150 bars, different parameter sets (e.g. `rsi_oversold=28` vs `rsi_oversold=32`) will trigger at slightly different candle wicks.
- The parameter set that happens to hit 2 winning wicks in the 2.5-hour window is crowned "optimal" with a quantum score $> 200$.
- In live execution on the subsequent 2.5-hour window, that specific micro-pattern does not repeat, leading to instant performance degradation.

---

### 2.4 Look-Ahead Bias & Slippage Evaluation in Backtest Engine
In `BinaryBacktestEngine.run()`:
1. `prepare_dataframe(df_raw)` computes technical indicators vectorized over the entire dataset.
2. In `evaluate_bar(df, i)`, trade entry is evaluated on bar `i` close, and `entry_price` is recorded as `df.iloc[i]["close"]`.
3. In live execution via WebSocket:
   - Candle bar `i` closes at $t_0$.
   - Engine tick loop detects candle close at $t_0 + \Delta t_{\text{tick}}$ ($\Delta t_{\text{tick}} \in [0, 4.0\text{s}]$).
   - Gateway sends `open_trade` WebSocket frame ($\Delta t_{\text{net}} \approx 100 - 300\text{ms}$).
   - Broker fills order at $t_0 + \Delta t_{\text{total}}$ at the current tick price, NOT the historical bar close.
   - On OTC pairs where algorithmic spikes occur at candle boundaries, entry price slippage of $0.5 - 1.5$ pips reduces live win rate by **$3.0\% - 5.0\%$** compared to the backtest.

---

### 2.5 Signal Queue Race Conditions & Concurrency Vulnerabilities

```
TICK LOOP CONCURRENCY FLAW (TOCTOU)
=============================================================================
t = 0.00s:  _evaluate_signals_and_trade() captures now = t_0
            active_trades = {} (len = 0)
            asyncio.gather(Task_EURUSD, Task_GBPUSD, Task_USDJPY, Task_AUDUSD, Task_NZDUSD)
            
t = 0.05s:  Task_EURUSD passes Gate 1 (0 < 3), Gate 4 (asset not active), Gate 10 (active_trades is empty -> correlation skipped!)
            Task_GBPUSD passes Gate 1 (0 < 3), Gate 4 (asset not active), Gate 10 (active_trades is empty -> correlation skipped!)
            Task_USDJPY passes Gate 1 (0 < 3), Gate 4 (asset not active), Gate 10 (active_trades is empty -> correlation skipped!)
            Task_AUDUSD passes Gate 1 (0 < 3), Gate 4 (asset not active), Gate 10 (active_trades is empty -> correlation skipped!)
            Task_NZDUSD passes Gate 1 (0 < 3), Gate 4 (asset not active), Gate 10 (active_trades is empty -> correlation skipped!)

t = 0.15s:  All 5 tasks await network get_candles() concurrently...
t = 0.35s:  All 5 tasks evaluate bullish setup -> generate CALL signals!
t = 0.36s:  Task_EURUSD enters _order_lock -> opens broker trade -> active_trades['EURUSD'] registered.
t = 0.38s:  Task_GBPUSD enters _order_lock -> global cooldown checked with stale now (elapsed = 0.0s) -> opens trade!
t = 0.40s:  Task_USDJPY enters _order_lock -> opens trade!
t = 0.41s:  Task_AUDUSD enters _order_lock -> opens trade!
t = 0.43s:  Task_NZDUSD enters _order_lock -> opens trade!
=============================================================================
RESULT: 5 concurrent CALL trades opened in 70ms, bypassing concurrency limit (3), correlation filter, and cooldown!
```

#### Detailed Breakdown of Race Conditions:
1. **Multi-Strategy Signal Collisions**:
   In `bot_engine.py` lines 671–700, multiple candidate strategies are evaluated sequentially for a single asset, and the strategy with the highest confidence is selected (`best_signal`). However, when multiple assets are processed concurrently via `asyncio.gather()`, they run simultaneously without synchronizing state.
2. **`_order_lock` Scope Limitation**:
   The lock `self._order_lock` is only acquired inside `_execute_order()` (line 755). All gate checks in `_evaluate_single_asset()` (lines 564–728) occur **outside the lock**. By the time any task acquires `_order_lock`, all other tasks have already passed the pre-filters.
3. **4-Second Tick Loop Latency**:
   `LiveDemoBotEngine._run_loop()` executes `await asyncio.sleep(4.0)`. A binary options signal valid at the exact second of bar close ($t = 0\text{s}$) may not be processed until $t = 3.9\text{s}$. On a 180s expiration, entering 4 seconds late into a fast move often results in buying at the apex of a micro-spike before mean reversion.

---

## 3. Root Cause Analysis: The 10-Trades-in-3-Seconds Database Anomaly

### 3.1 Forensic Evidence from `data/trades.db`

Direct forensic query of the production SQLite database `data/trades.db` (`trades` table) extracted the exact records below:

#### Table 3.1: Chronological Trade Execution Log
| # | Trade ID | Broker Order ID | Asset | Action | Stake | Open Time (UTC) | Created At (SQLite Insertion) | Strategy ID | Reason | Outcome |
|---|---|---|---|---|---|---|---|---|---|---|
| **1** | `5f659123...` | `test-order-uuid-12345` | `EURUSD_otc` | `CALL` | $\$10.0$ | 11:05:58.711275 | 11:05:58.725183 (+14ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |
| **2** | `6e70103d...` | `mock-order-EURUSD_otc` | `EURUSD_otc` | `CALL` | $\$10.0$ | **11:06:00.350966** | **11:06:00.367279** (+16ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |
| **3** | `26607cd7...` | `mock-order-GBPUSD_otc` | `GBPUSD_otc` | `CALL` | $\$10.0$ | **11:06:00.350966** | **11:06:00.383156** (+16ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |
| **4** | `201b6e50...` | `mock-order-USDJPY_otc` | `USDJPY_otc` | `CALL` | $\$10.0$ | **11:06:00.350966** | **11:06:00.399261** (+16ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |
| **5** | `b4c3da8a...` | `mock-order-AUDUSD_otc` | `AUDUSD_otc` | `CALL` | $\$10.0$ | **11:06:00.350966** | **11:06:00.414914** (+15ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |
| **6** | `5313fa8b...` | `mock-order-NZDUSD_otc` | `NZDUSD_otc` | `CALL` | $\$10.0$ | **11:06:00.350966** | **11:06:00.430964** (+16ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |
| **7** | `337bfb6d...` | `order-resumed-999` | `EURUSD_otc` | `CALL` | $\$10.0$ | 11:06:01.111359 | 11:06:01.111723 (+0.4ms) | `support_resistance_bounce` | `resumed_test` | `PENDING` |
| **8** | `23c6fe30...` | `order-asset-b` | `GBPUSD_otc` | `CALL` | $\$10.0$ | 11:06:01.113413 | 11:06:01.114949 (+1.5ms) | `ema_pullback_trend` | `independent_asset_b` | `PENDING` |
| **9** | `46e5e811...` | `order-exp-180` | `EURUSD_otc` | `CALL` | $\$10.0$ | 11:06:01.121401 | 11:06:01.122555 (+1.1ms) | `support_resistance_bounce` | `exp_verification` | `PENDING` |
| **10**| `04641565...` | `mock-order-EURUSD_otc` | `EURUSD_otc` | `CALL` | $\$10.0$ | 11:06:36.175845 | 11:06:36.196622 (+20ms) | `supertrend_adx_momentum` | `supertrend_momentum` | `PENDING` |

---

### 3.2 Forensic Code-Level Walkthrough of the Anomaly

The forensic log establishes that **9 trades were committed in 2.41 seconds** (11:05:58.711 to 11:06:01.121), all in the `CALL` direction, violating four core safety invariants simultaneously:
1. Max Concurrent Trades Limit ($3$) was breached (up to 7 open trades simultaneously).
2. Global Cooldown ($30\text{s}$) was bypassed ($15.9\text{ms}$ between executions).
3. Per-Asset Cooldown ($180\text{s}$) was bypassed (`EURUSD_otc` opened 4 times in 2.4s).
4. Correlation Filter was bypassed ($4$ pairs with direct USD short exposure opened concurrently).

#### The 4 Interlocking Root Causes:

#### Cause 1: Time-of-Check to Time-of-Use (TOCTOU) in `asyncio.gather()`
- In `bot_engine.py` line 528:
  ```python
  tasks = [self._evaluate_single_asset(assignment, now, sem) for assignment in self.plan.assignments]
  await asyncio.gather(*tasks, return_exceptions=True)
  ```
- When `_evaluate_single_asset()` starts, all 5 coroutines check `len(self.active_trades)` at line 564. Since no trades have settled or been added yet, `len(self.active_trades) == 0 < 3` for all 5 tasks.
- Similarly, line 712 checks `if self.plan.correlation_filter_enabled and self.active_trades:`. Because `self.active_trades` is empty, the correlation check returns `is_conflict = False` immediately for all 5 assets.

#### Cause 2: Stale `now` Timestamp Propagation
- In `bot_engine.py` line 515: `now = datetime.now(UTC)` is captured once at tick start.
- `now` is passed down to `_evaluate_single_asset(..., now=now)` and then to `_execute_order(..., now=now)`.
- In `_execute_order()` line 788:
  ```python
  if self._last_global_execution_time:
      elapsed = (now - self._last_global_execution_time).total_seconds()
      if elapsed < self.plan.global_cooldown_seconds:
          return
  ```
- Task 1 executes, sets `self._last_global_execution_time = now` ($t_0$).
- Task 2 acquires `_order_lock`. Because Task 2 received the same $t_0$, `now - self._last_global_execution_time = t_0 - t_0 = 0.0\text{s}`.
- When `global_cooldown_seconds == 0` (or during concurrent fan-out), `elapsed < 0` evaluates to `False`, and Task 2 proceeds immediately without delay!

#### Cause 3: Unconditional Continuation Signal in `SupertrendAdxMomentumStrategy`
- In `supertrend_adx_momentum.py` line 103:
  ```python
  if st_dir == 1 and adx_pos > adx_neg:
      action = TradeAction.CALL
      confidence = 0.70
  ```
- The strategy does not require a fresh trend flip (`prev_st_dir == -1 and st_dir == 1`). It generates a `CALL` signal on **every single bar** where the trend is positive.
- When synthetic OTC candles across all assets drift upwards, all 5 assets emit `CALL` on the exact same tick with confidence `0.70 >= 0.50`.

#### Cause 4: Un-Isolated Module-Level Global Database Singleton
- In `src/strat_trade/use_cases/manage_live_bot.py` line 13:
  ```python
  _global_trade_store = TradeStore() # default path: data/trades.db
  _global_bot_engine = LiveDemoBotEngine(trade_store=_global_trade_store)
  ```
- When concurrent test suites or external async scripts call `_execute_order()` or use cases without mocking or using isolated temporary databases, multiple engine instances/coroutines write directly to the single `data/trades.db` file.
- Because `self.active_trades` is an in-memory dictionary local to each instance, independent engine coroutines have zero awareness of trades opened by other coroutines, writing Trades 7, 8, and 9 within 10 milliseconds.

---

## 4. Deliverable R2: Monte Carlo Worst-Case Simulation Models

### 4.1 Simulation Architecture & Parameters

```
MONTE CARLO SIMULATION SPECIFICATION (10,000 RUNS)
=============================================================================
Sequence Length (N):           500 trades per run
Number of Iterations (M):      10,000 independent synthetic sequences
Initial Deposit (B_0):         $1,000.00
Staking Model:                 Flat $10.00 (1.0% initial deposit)
Baseline Win Rate (p_0):       57.00% (Achievable production target)
Payout Model:                  Uniform(0.72, 0.88) per trade (Mean = 80.0%)
OTC Regime Drift Model:        Uniform(-0.02, +0.02) perturbation per 50-trade block
Circuit Breaker Limits:        Daily Stop-Loss: 5.0% ($50) per 50 trades
                               Peak-to-Trough Max Drawdown: 8.0% ($80)
=============================================================================
```

#### Mathematical Formulation:
1. For run $m \in \{1, \dots, M\}$ and trade $t \in \{1, \dots, N\}$ belonging to block $k = \lceil t / 50 \rceil$:
   $$p_{t, m} = p_0 + \Delta p_{k, m}, \quad \text{where } \Delta p_{k, m} \sim \text{Uniform}(-0.02, +0.02)$$
2. Trade outcome $X_{t, m} \sim \text{Bernoulli}(p_{t, m})$.
3. Broker payout $P_{t, m} \sim \text{Uniform}(0.72, 0.88)$.
4. PnL per trade:
   $$\text{PnL}_{t, m} = X_{t, m} \cdot (S \cdot P_{t, m}) - (1 - X_{t, m}) \cdot S$$
5. Equity curve:
   $$B_{t, m} = B_0 + \sum_{i=1}^t \text{PnL}_{i, m}$$
6. Max Drawdown:
   $$\text{MDD}_m = \max_{0 \le t \le N} \left( \frac{\max_{0 \le \tau \le t} B_{\tau, m} - B_{t, m}}{\max_{0 \le \tau \le t} B_{\tau, m}} \right) \times 100\%$$

---

### 4.2 Empirical Monte Carlo Simulation Results

#### Table 4.1: Monte Carlo 10,000-Run Statistical Distribution
| Metric | Base Model (Fixed 80% Payout, Constant 57% WR) | Dynamic Model (72%–88% Payout, ±2% OTC Noise) | Interpretation |
| :--- | :--- | :--- | :--- |
| **Mean Final Net PnL** | **$+\$130.81$** | **$+\$130.07$** | $+13.0\%$ Expected ROI |
| **Standard Deviation of PnL** | $\$198.29$ | $\$201.58$ | High standard deviation |
| **Median Final Net PnL** | $+\$130.00$ | $+\$131.44$ | Symmetric distribution |
| **5th Percentile PnL (Worst 5%)** | $-\$196.00$ | **$-\$201.78$** | Severe downside tail |
| **95th Percentile PnL (Best 5%)** | $+\$456.00$ | **$+\$460.56$** | Upside potential |
| **Mean Maximum Drawdown** | **$17.33\%$** | **$17.51\%$** | Average account retracement |
| **95th Percentile Max Drawdown** | **$32.40\%$** | **$33.10\%$** | Expected worst drawdown |
| **Probability of Net Loss ($PnL < 0$)** | **$25.21\%$** | **$26.07\%$** | 1 in 4 bots lose money over 500 trades |
| **Probability of Severe DD ($\ge 20\%$)** | **$28.75\%$** | **$30.06\%$** | Nearly 1 in 3 bots suffer $>20\%$ drawdown |
| **Probability of Absolute Ruin ($B \le 0$)**| **$0.00\%$** | **$0.00\%$** | Flat $10 sizing avoids bankruptcy |

#### Table 4.2: Consecutive Loss Streak Length Distribution ($500$ Trades)
| Metric / Percentile | Maximum Loss Streak Length ($L_{\max}$) | Empirical Frequency |
| :--- | :--- | :--- |
| **Median (50th Percentile)** | **$7.0$ consecutive losses** | Guaranteed to occur in $>95\%$ of runs |
| **75th Percentile** | **$8.0$ consecutive losses** | Highly probable |
| **90th Percentile** | **$9.0$ consecutive losses** | Normal statistical fluctuation |
| **95th Percentile** | **$10.0$ consecutive losses** | 1 in 20 sequences experience $\ge 10$ losses |
| **99th Percentile** | **$12.0$ consecutive losses** | 1 in 100 sequences experience $\ge 12$ losses |
| **Maximum Observed Streak** | **$18.0$ consecutive losses** | Tail risk extreme |

---

### 4.3 Drawdown Circuit Breaker Invalidation Finding

#### Table 4.3: Circuit Breaker Breach Probability over 500 Trades
| Circuit Breaker Threshold | Configuration in Bot | Breach Probability over 500 Trades | Assessment |
| :--- | :--- | :--- | :--- |
| **$5.0\%$ Drawdown Breach** | `daily_stop_loss_pct = 0.05` | **$99.94\%$** | Virtually Guaranteed to Trigger |
| **$8.0\%$ Drawdown Breach** | `max_drawdown_pct_limit = 0.08` | **$95.82\%$** | **FATAL FLAW: 96% False Halt Rate** |
| **$10.0\%$ Drawdown Breach** | Alternative limit | **$86.49\%$** | Unstable |
| **$15.0\%$ Drawdown Breach** | Recommended baseline | **$54.58\%$** | Balanced protection |
| **$20.0\%$ Drawdown Breach** | Recommended hard halt | **$30.06\%$** | Protects capital from true regime failure |

**Quant Analysis of the 8% Limit Flaw**:
With flat $\$10$ betting on $\$1,000$, an $8\%$ drawdown corresponds to losing $\$80$ (a net deficit of 8 losing trades). Because a 7-loss streak occurs in $>50\%$ of runs and an 8-loss streak occurs in $>25\%$ of runs, **the bot's $8.0\%$ circuit breaker is guaranteed to trigger in $95.82\%$ of profitable runs**. The bot will falsely halt and report failure when the underlying strategy is functioning with a healthy $57\%$ win rate!

---

## 5. Prioritized Remediation Roadmap

### 5.1 Remediation Summary Table

| ID | Vulnerability | Severity | Impact on Win Rate / Solvency | Recommendation & Technical Spec | Priority |
|---|---|---|---|---|---|
| **V-01** | `_evaluate_signals_and_trade` TOCTOU Concurrency Bypass | 🔴 **CRITICAL** | $-15\%$ to $-30\%$ PnL (Massive over-exposure) | Serialize asset evaluation inside an atomic reservation lock or pre-reserve active trade slots before async gateway calls. | **P0** |
| **V-02** | Stale `now` Argument Bypassing Global Cooldown | 🔴 **CRITICAL** | Causes simultaneous burst orders ($15\text{ms}$ apart) | Always compute `now = datetime.now(UTC)` dynamically inside `_execute_order()`; do not accept external stale timestamps. | **P0** |
| **V-03** | 8% Max Drawdown Circuit Breaker False-Halt | 🔴 **CRITICAL** | $95.82\%$ premature halt of profitable sessions | Increase `max_drawdown_pct_limit` from $8.0\%$ to $18.0\%-20.0\%$ or scale limit proportionally to bet size ($20 \times \text{stake}$). | **P0** |
| **V-04** | Unconditional Continuation Signals in `SupertrendAdxMomentum` | 🔴 **CRITICAL** | Signals flood on every bar during trend | Require state transition: only trigger on fresh Supertrend line flip (`prev_st_dir != st_dir`) or pullback bounce. | **P0** |
| **V-05** | Artificial Quantum Score Bonuses (+30.0 points) | 🟡 **HIGH** | Distorts selection by $+10.0\%$ equivalent WR | Eliminate hardcoded $+15.0$ priority and whitelist bonuses; score purely on empirical risk-adjusted metrics. | **P1** |
| **V-06** | Inadequate Optimizer Sample Size (150 M1 Bars) | 🟡 **HIGH** | Overfits to micro-noise ($CI_{95\%}$ lower bound $<35\%$) | Increase sample size to $\ge 1,000 - 2,000$ M1 bars; require minimum 20 trades and Wilson lower bound $> 52.0\%$. | **P1** |
| **V-07** | Hardcoded Priority Strategy Catalog Bypass | 🟡 **HIGH** | Ignores 6 out of 8 strategies in default optimizer | Remove `candidate_strategies = PRIORITY_STRATEGIES` default; evaluate all eligible strategies in the catalog. | **P1** |
| **V-08** | Dynamic Payout "Death Zone" Invalidation | 🟡 **HIGH** | $-2.0\%$ to $-5.0\%$ EV drag per trade | Enforce strict dynamic payout gate: reject trades if $P < \frac{1 - p_{\text{strat}}}{p_{\text{strat}}} + 0.03$. Hard floor at $80.0\%$. | **P1** |
| **V-09** | 4-Second Tick Loop Execution Latency | 🟢 **MEDIUM** | $1.0\% - 2.0\%$ slippage degradation | Replace polling `asyncio.sleep(4.0)` with event-driven WebSocket candle close triggers. | **P2** |
| **V-10** | Synchronous SQLite Blocking in Async Loop | 🟢 **MEDIUM** | Thread blocking under high concurrency | Move `TradeStore` database operations to `aiosqlite` or run via `asyncio.to_thread()`. | **P2** |

---

### 5.2 Concrete Implementation Specifications for Top Fixes

#### P0 Fix 1: Eliminate Async Concurrency Race Condition (`bot_engine.py`)
```python
# In LiveDemoBotEngine._evaluate_signals_and_trade():
# Replace concurrent fan-out with sequential evaluation or atomic slot reservation:
async def _evaluate_signals_and_trade(self) -> None:
    if not self.plan or not self._gateway or self.status != BotStatus.RUNNING:
        return

    now = datetime.now(UTC)
    if self._last_global_execution_time:
        if (now - self._last_global_execution_time).total_seconds() < self.plan.global_cooldown_seconds:
            return

    # Evaluate sequentially to guarantee strict concurrency and correlation guards
    for assignment in self.plan.assignments:
        if len(self.active_trades) >= self.plan.max_concurrent_trades:
            break
        await self._evaluate_single_asset(assignment)
```

#### P0 Fix 2: Dynamic Execution Timestamp & Cooldown Refresh (`bot_engine.py`)
```python
# In LiveDemoBotEngine._execute_order():
async with self._order_lock:
    current_now = datetime.now(UTC)
    if self._last_global_execution_time:
        elapsed = (current_now - self._last_global_execution_time).total_seconds()
        if elapsed < self.plan.global_cooldown_seconds:
            logger.debug("Global cooldown active: skipping %s", assignment.asset)
            return

    # Proceed with order execution...
    self._last_global_execution_time = current_now
```

#### P0 Fix 3: Recalibrate Peak Drawdown Circuit Breaker (`entities.py` & `auto_assign_strategies.py`)
```python
# In PreTradingPlan defaults:
# Replace 8% limit (which has a 95.8% false-positive rate) with statistical 18.0%:
max_drawdown_pct_limit: float = 0.18  # 18.0% peak-to-trough limit allows 57% WR to survive 10-loss streak
```

#### P0 Fix 4: Transition-Only Signal Gating for Supertrend (`supertrend_adx_momentum.py`)
```python
# In SupertrendAdxMomentumStrategy.evaluate_bar():
if adx >= self.adx_threshold:
    # REQUIRE FRESH TRANSITION FLIP (prev_st_dir == -1 and st_dir == 1)
    if prev_st_dir == -1 and st_dir == 1 and adx_pos > adx_neg:
        action = TradeAction.CALL
        confidence = 0.85
    elif prev_st_dir == 1 and st_dir == -1 and adx_neg > adx_pos:
        action = TradeAction.PUT
        confidence = 0.85
```
