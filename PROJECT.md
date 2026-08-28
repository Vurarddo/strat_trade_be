# Project: strat_trade_be (Sniper Confluence & Safety Guardrails)

## Architecture
Autonomous binary options algorithmic trading platform and backtest engine featuring:
- **Domain Strategy Engine**: Modular strategies with indicator preparation, bar-by-bar signal evaluation, and entry guardrails.
- **Risk Governance & Execution**: `LiveDemoBotEngine` and `PortfolioBacktestEngine` with dynamic asset qualification, anti-whipsaw cooldowns, and global consecutive-loss circuit breakers.
- **Optimizer & Auto-Matcher**: `StrategyAutoMatcher` assigning optimal sniper strategies to asset classes based on microstructure metrics.
- **Verification Infrastructure**: `Rolling15TradeVerificationRunner` for discrete non-overlapping batch validation and streak stress-testing.
- **Web UI & Telemetry**: FastAPI backend with Jinja2 templates, REST status polling, and live telemetry.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Strategy Portfolio Restructuring | Deactivate MACD divergence and hybrid strategies from live bot assignment | M1 | Initial Request §R1 |
| 2 | Primary Sniper Alpha Models | Focus allocation on S&R Pin-Bar, RSI+Stoch Extreme, EMA Ribbon | M1 | Initial Request §R1 |
| 3 | Runaway Momentum & Candle Filter | Suppress counter-trend reversal entries on 3-4 consecutive aggressive trend candles | M1 | Follow-up §R2 |
| 4 | UI Expiration Simplification | Automatic 180s (3 bars) strategy expiration, remove manual UI expiration dropdown | M2 | Initial Request §R2 |
| 5 | Dynamic Asset Qualification & Noise Filter | 4-metric microstructure statistical filter for continuous price action | M2 | Initial Request §R3 |
| 6 | Anti-Whipsaw Cooldown | Minimum 180s (3 min) post-settlement per-asset cooldown | M2 | Initial Request §R3 |
| 7 | Global Consecutive-Loss Circuit Breaker | 3 consecutive losses trigger 15-min (900s) portfolio lockout with UI telemetry & auto-resume | M2 | Follow-up §R1 |
| 8 | Multi-Session 600+ Trade & Streak Verification | Rolling 15-trade validation with WR >= 58% and positive PnL | M3 | Initial Request §R4 |
| 9 | August 24 7-Loss Cascade Elimination Stress-Test | Eliminate multi-loss streaks (>=4) during volatility sweeps while preserving winning streaks | M3 | Follow-up §R3 |
| 10 | Quality Gate Assurance | 100% pytest pass across all tests and 0 ruff lint errors | M3 | Follow-up §R3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Strategy Confluence & Runaway Momentum Guards | Implement runaway momentum candle filter in S&R Pin-Bar & RSI+Stoch Extreme strategies; verify sniper strategy prioritization | none | DONE |
| 2 | M2: Risk Governance & Telemetry UI | Global consecutive-loss circuit breaker (15-min pause), streak tracking, UI status banner with live countdown | M1 | DONE |
| 3 | M3: E2E Verification & Streak Stress-Testing | August 24 cascade elimination test suite, rolling 15-trade verification, full pytest suite 100% pass, 0 ruff errors | M1, M2 | DONE |

## Interface Contracts
### Strategy ↔ Runaway Momentum Guard
- Function: `check_runaway_momentum(df: pd.DataFrame, idx: int, lookback_bars: int = 3, min_body_ratio: float = 0.50, max_opposing_wick_ratio: float = 0.25) -> tuple[bool, bool]`
- Returns: `(is_bearish_runaway, is_bullish_runaway)`
- Behavior:
  - If `is_bearish_runaway` is True: suppress CALL signals (`action = None`, `regime = "runaway_momentum_suppressed"`).
  - If `is_bullish_runaway` is True: suppress PUT signals (`action = None`, `regime = "runaway_momentum_suppressed"`).

### Bot Engine ↔ Risk Governance & Telemetry
- Attributes on `LiveDemoBotEngine`:
  - `consecutive_losses: int`
  - `paused_until: datetime | None`
  - `status: BotStatus` (`BotStatus.PAUSED`)
- Reset conditions: `consecutive_losses = 0` on `TradeOutcome.WIN`, on auto-resume when `now >= paused_until`, or on manual `resume()`.
- Telemetry: `BotStatusResponse` returns `consecutive_losses`, `paused_until`, `is_paused`, `circuit_breaker_triggered`.

## Code Layout
- `src/strat_trade/domain/strategies/`: Strategy implementations (`support_resistance_bounce.py`, `rsi_stochastic_extreme.py`, `ema_pullback_trend.py`, `registry.py`, `base.py`).
- `src/strat_trade/domain/trading/`: Bot engine and risk models (`bot_engine.py`, `asset_filter.py`, `entities.py`, `trade_store.py`).
- `src/strat_trade/domain/optimizer/`: Auto-matcher (`auto_matcher.py`).
- `src/strat_trade/domain/backtest/`: Verification and backtesting (`verification_runner.py`, `portfolio_engine.py`).
- `src/strat_trade/web/templates/`: Web console UI (`index.html`).
- `tests/`: Automated test suites (`test_phase4_sniper_rolling_15_verification.py`, `test_execution_guardrails.py`, `test_august_24_streak_elimination.py`).
