# Handoff Report: Dynamic Microstructure Noise Filter & Anti-Whipsaw Cooldown (Requirement R3)

**Agent**: M3 Worker 1 (Implementer, QA, Specialist)  
**Date**: 2026-08-23  
**Status**: Task Completed (100% Tests Pass, 0 Lint Errors)

---

## 1. Observation

1. **Microstructure Noise in Step-Tick Feeds**:
   - In `src/strat_trade/domain/trading/asset_filter.py`, static blacklists alone cannot dynamically distinguish newly listed synthetic feeds or exotic pairs that exhibit discrete step-ticks, repetitive tick quantization, zero-volatility flatlines, or high-frequency micro-whipsaw noise.
   - Genuine continuous liquid assets (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCLP`, `USDBDT`, `USDEGP`, `Gold`) possess continuous price distributions with flat-bar ratios $< 5\%$, unique close ratios $> 50\%$, balanced return sign alternation ($\approx 50\%$), and normalized $ATR(14) / Close \ge 0.00003$.

2. **Settlement Cooldown Configuration**:
   - In `src/strat_trade/domain/trading/bot_engine.py` (lines 343–347), post-trade settlement cooldown was computed as `cooldown_sec = cooldown_bars * 60`. If a plan configured `cooldown_bars = 1`, cooldown was only 60 seconds, which permitted premature re-entries during prolonged breakout spikes or whipsaws.
   - In `_execute_order()`, per-asset `cooldown_until` was not checked atomically inside `async with self._order_lock:`, creating a potential concurrency race condition if multiple worker coroutines scheduled orders around the settlement boundary.

3. **Existing Test Baseline**:
   - Baseline test suite had 828 tests passing (`pytest` output: `828 passed`).
   - Project uses `ruff` for linting with strict 100-character line length limits.

---

## 2. Logic Chain

1. **Statistical Price Action Metric Qualification**:
   - Implemented `qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]` in `asset_filter.py`:
     - Requires $\ge 50$ valid OHLC candles (`len(candles) >= 50`).
     - `flat_bar_ratio`: $\frac{1}{N}\sum \mathbf{1}_{\{High == Low \lor |Close - Open| \le 10^{-9}\}}$; rejects if $> 0.15$ (15%).
     - `unique_price_ratio`: $\frac{|\{Close\}|}{N}$; rejects if $< 0.30$ (30%) to filter out step-tick quantization.
     - `whipsaw_sign_flip_ratio`: proportion of consecutive 1-bar returns flipping sign ($r_t \cdot r_{t-1} < 0$); rejects if $> 0.80$ (80%) to filter out non-directional alternating noise.
     - `relative_atr`: $\frac{ATR(14)}{Close}$; rejects if $< 0.00003$ to filter out dead/zero volatility.
   - Enhanced `filter_allowed_assets()` to optionally accept `candle_data` and filter out unqualifying assets.
   - Integrated `qualify_asset_microstructure()` into `StrategyAutoMatcher.find_optimal_strategy_for_asset()` to prevent allocating live trading strategies to poorly behaving feeds.

2. **Anti-Whipsaw Post-Settlement Cooldown & Atomic Guard**:
   - Updated `bot_engine.py` trade settlement logic:
     `cooldown_sec = max(180, cooldown_bars * 60)`
     This guarantees a hard floor of 180 seconds (3 minutes) between trade resolution and next signal scan on that asset.
   - Added atomic check inside `async with self._order_lock:` in `_execute_order()`:
     ```python
     cooldown_until = self._asset_cooldown_until.get(assignment.asset)
     if cooldown_until and now < cooldown_until:
         logger.debug(
             "Asset %s is in post-settlement cooldown inside order lock (until %s)",
             assignment.asset,
             cooldown_until.isoformat(),
         )
         return
     ```

3. **Behavioral Test Coverage**:
   - Added 8 dedicated unit and integration test functions to `tests/test_strategy_curation_and_asset_filter.py` covering every metric boundary, edge cases (empty, `< 50`, NaNs, non-positive prices), continuous liquid pair qualification, dynamic asset filtering with candle data, and engine cooldown enforcement with atomic rejection.

---

## 3. Caveats

1. **Sufficient History Requirement**: `qualify_asset_microstructure` requires at least 50 bars. When fewer than 50 bars are provided, it returns `False` with an insufficient history explanation. Callers (`find_optimal_strategy_for_asset`) fall back to curated heuristic profiles when candle counts are $< 50$.
2. **Backwards Compatibility**: `filter_allowed_assets()` signature has `candle_data` defaulting to `None`, preserving full backward compatibility for callers passing only symbol lists.

---

## 4. Conclusion

- Requirement R3 is fully implemented with genuine statistical domain logic and robust anti-whipsaw mechanics.
- All liquid continuous OTC and Forex pairs (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCLP`, `USDBDT`, `USDEGP`, `Gold`, etc.) pass microstructure qualification.
- Discrete step-tick assets, flatline feeds, and micro-whipsaw noise are deterministically rejected.
- Hard minimum 3-minute settlement cooldown is enforced across the bot engine with atomic synchronization.
- Test suite expanded from 828 to 840 passing tests with 0 lint errors.

---

## 5. Verification Method

To independently verify the implementation:

```bash
# 1. Run the full test suite
.venv/bin/pytest -v

# 2. Run the specific asset filter and cooldown tests
.venv/bin/pytest tests/test_strategy_curation_and_asset_filter.py -v

# 3. Verify zero lint errors
.venv/bin/ruff check src tests
```

### Verification Artifacts
- Source file: `/Users/vlados/work/projects/startup/strat_trade_be/src/strat_trade/domain/trading/asset_filter.py`
- Source file: `/Users/vlados/work/projects/startup/strat_trade_be/src/strat_trade/domain/trading/bot_engine.py`
- Source file: `/Users/vlados/work/projects/startup/strat_trade_be/src/strat_trade/domain/optimizer/auto_matcher.py`
- Test file: `/Users/vlados/work/projects/startup/strat_trade_be/tests/test_strategy_curation_and_asset_filter.py`
- Changes log: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_worker_1/changes.md`
- Briefing: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_worker_1/BRIEFING.md`
