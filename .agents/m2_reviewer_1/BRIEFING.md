# BRIEFING — 2026-08-20T17:42:35+04:00

## Mission
Review and adversarial testing of Milestone 2: Bot Engine Execution Guardrails & Anti-Whipsaw (R2).

## 🔒 My Identity
- Archetype: reviewer_critic
- Roles: reviewer, critic
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_reviewer_1
- Original parent: b5bec36a-db84-436e-98e2-3b5605cf7864
- Milestone: Milestone 2 (R2)
- Instance: 1 of 1

## 🔒 Key Constraints
- Review-only — do NOT modify implementation code
- Check for integrity violations (hardcoding, facade implementations, bypassed tasks, fabricated artifacts)
- Provide rigorous verification, counter-examples, edge cases, and failure modes

## Current Parent
- Conversation ID: b5bec36a-db84-436e-98e2-3b5605cf7864
- Updated: 2026-08-20T17:42:35+04:00

## Review Scope
- **Files to review**:
  - `src/strat_trade/domain/trading/correlation.py`
  - `src/strat_trade/domain/trading/entities.py`
  - `src/strat_trade/domain/trading/bot_engine.py`
  - `src/strat_trade/domain/backtest/models.py`
  - `src/strat_trade/domain/backtest/portfolio_engine.py`
  - `src/strat_trade/use_cases/auto_assign_strategies.py`
  - `src/strat_trade/use_cases/manage_live_bot.py`
  - `src/strat_trade/api/schemas.py`
  - `src/strat_trade/api/routes/bot.py`
  - `tests/test_currency_correlation.py`
  - `tests/test_execution_guardrails.py`
- **Interface contracts**: PROJECT.md, ORIGINAL_REQUEST.md
- **Review criteria**: Correctness, completeness, state machine integrity, backtest-live parity, adversarial robustness

## Review Checklist
- **Items reviewed**:
  - `correlation.py` (currency normalization, pair extraction, directional exposure, conflict detection)
  - `entities.py` (BotStatus enums, PreTradingPlan, BotSessionSummary)
  - `bot_engine.py` (lifecycle, cooldowns, circuit breakers, pause/resume state machine)
  - `models.py` & `portfolio_engine.py` (backtest config, simulation loop parity)
  - `auto_assign_strategies.py` & `manage_live_bot.py` (use case integration)
  - `schemas.py` & `routes/bot.py` (Pydantic schemas and FastAPI endpoints)
  - `tests/test_currency_correlation.py` & `tests/test_execution_guardrails.py`
- **Verdict**: REQUEST_CHANGES (due to peak_balance / current_drawdown_pct lockout bug on resume from HALTED_BY_CIRCUIT_BREAKER)
- **Unverified claims**: none

## Attack Surface
- **Hypotheses tested**:
  - Resume after HALTED_BY_CIRCUIT_BREAKER: verified that old peak_balance causes instant re-halt on next loop iteration. [FAILED / VULNERABILITY FOUND]
  - Concurrency order lock vs global cooldown: verified order serialization. [PASS]
  - Multi-asset correlation conflict: verified in live bot and backtest engine. [PASS]
  - Post-settlement per-asset cooldown: verified in live bot and backtest engine. [PASS]
  - Consecutive losses pause and win streak reset: verified in live bot and backtest engine. [PASS]
- **Vulnerabilities found**:
  - Major: `LiveDemoBotEngine.resume()` leaves `peak_balance` unchanged from previous high-watermark, causing `_check_circuit_breakers()` in `_run_loop()` to immediately re-halt the bot on the first loop tick.
- **Untested angles**: none

## Key Decisions Made
- Issued REQUEST_CHANGES highlighting the specific state machine fix required for `resume()` from `HALTED_BY_CIRCUIT_BREAKER`.

## Artifact Index
- `.agents/m2_reviewer_1/handoff.md` — Review report & verdict
