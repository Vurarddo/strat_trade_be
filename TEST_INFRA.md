# E2E Test Infra: Sniper Confluence Trading System

## Test Philosophy
- Opaque-box, requirement-driven. Derives from ORIGINAL_REQUEST.md and trading system quantitative requirements.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Combinatorial + Real-World Workload Testing.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|---------------------|:------:|:------:|:------:|:------:|
| 1 | Strategy Deactivation (MACD & Hybrid) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 2 | Primary Sniper Alpha Selection | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 3 | Calibrated Expirations (180s / 3 bars) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 4 | UI Expiration Simplification | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 5 | Dynamic Microstructure Noise Filter | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 6 | Anti-Whipsaw Cooldown (min 180s) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 7 | Rolling 15-Trade Verification (WR >= 58%) | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 8 | 100% Pytest & Ruff Zero Errors | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **Test Runner**: `.venv/bin/pytest tests/test_phase4_sniper_rolling_15_verification.py -v` and full suite `.venv/bin/pytest`
- **Lint Runner**: `.venv/bin/ruff check src tests`
- **Verification Runner**: `Rolling15TradeVerificationRunner` in `src/strat_trade/domain/backtest/verification_runner.py`
- **Directory Layout**:
  - `tests/test_phase4_sniper_rolling_15_verification.py`: Phase 4 verification suite
  - `tests/test_strategy_curation_and_asset_filter.py`: Asset qualification and strategy curation
  - `tests/test_strategy_auto_matcher.py`: Priority strategy allocation & fallbacks
  - `tests/test_bot_and_audit_api.py`: Bot engine and API lifecycle
  - `tests/test_rolling_15_trade_verification.py` & `tests/test_phase3_rolling_15_trade_verification.py`: Historical rolling batch benchmarks

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | High-volatility market open across 8 pairs | F2, F3, F5, F6, F7 | High |
| 2 | Toxic crypto OTC feed injection | F5, F6 | Medium |
| 3 | Continuous 600-trade multi-session broker execution | F1, F2, F3, F6, F7, F8 | High |
| 4 | UI Plan Generation and Launch with Auto-Expiration | F3, F4 | Medium |
| 5 | Rolling 15-Trade Batch Verification on Real Trade Logs | F7, F8 | High |

## Coverage Thresholds
- Tier 1: >= 5 tests per feature (Happy-path unit & functional tests)
- Tier 2: >= 5 tests per feature (Boundary, zero-candle, malformed, threshold tests)
- Tier 3: Pairwise combination tests (e.g. microstructure filter + cooldown + sniper strategy execution)
- Tier 4: >= 5 realistic multi-session application scenarios (600+ real broker trade evaluation with WR >= 58% and positive net batch PnL)
