"""Audits the concrete plan returned by /bot/auto-assign before it is started."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from scipy import stats

sys.path.insert(0, "src")

from strat_trade.api.schemas import StartBotRequest  # noqa: E402
from strat_trade.domain.trading.asset_filter import (  # noqa: E402
    is_asset_in_active_session,
    is_otc_asset,
    is_spot_market_closed,
)
from strat_trade.domain.trading.correlation import (  # noqa: E402
    is_correlated_conflict,
    normalize_symbol,
)
from strat_trade.domain.trading.entities import LiveTradeRecord, TradeOutcome  # noqa: E402
from strat_trade.domain.trading.entities import IndicatorSnapshot  # noqa: E402
from strat_trade.domain.strategies.registry import split_strategy_params  # noqa: E402

PLAN_PATH = Path(".agents/stress_test_2608/live_plan.json")


def hr(t: str) -> None:
    print("\n" + "=" * 96)
    print(t)
    print("=" * 96)


def main() -> None:
    payload = json.loads(PLAN_PATH.read_text())
    plan = payload["plan"]
    assignments = plan["assignments"]

    hr("1. SCHEMA VALIDATION OF /bot/start")
    try:
        StartBotRequest(**payload)
        print("  ACCEPTED by StartBotRequest.")
    except Exception as exc:
        print(f"  REJECTED: {exc}")
        return
    print(f"  declared total_assets = {plan['total_assets']}")
    print(f"  actual assignments    = {len(assignments)}")
    if plan["total_assets"] != len(assignments):
        print("  ^ mismatch is cosmetic: the engine iterates the list, not the counter.")

    hr("2. ASSETS THE OPTIMISER ITSELF REJECTED, YET LEFT IN THE PLAN")
    rejected = [a for a in assignments if "REJECTED" in a["rationale"]]
    print(f"  {len(rejected)} of {len(assignments)} assignments carry a rejection rationale:\n")
    for a in rejected:
        reason = a["rationale"].split("] ", 1)[-1]
        print(f"    {a['asset']:14s} score={a['quantum_score']:>6.1f}  {reason}")
    print("\n  These got heuristic defaults, not tuned parameters. The runtime")
    print("  microstructure gate re-checks every asset on each scan, so they should")
    print("  not trade -- but they will start trading, on untuned parameters, the")
    print("  moment their volatility rises above the threshold.")

    hr("3. SAMPLE SIZE BEHIND EACH 'ESTIMATED WIN RATE'")
    counts = Counter(a["estimated_trades_count"] for a in assignments)
    print("  backtest trades behind an assignment:")
    for n in sorted(counts):
        print(f"    n={n:<3} -> {counts[n]} assignments")
    print()
    perfect = [a for a in assignments if a["estimated_win_rate_pct"] >= 100.0]
    print(f"  {len(perfect)} assignments claim a 100% win rate. Their real confidence:\n")
    print(f"    {'asset':14s} {'n':>3} {'claimed':>9} {'95% CI lower bound':>20}")
    for a in perfect:
        n = a["estimated_trades_count"]
        ci = stats.binomtest(n, n).proportion_ci(0.95)
        print(f"    {a['asset']:14s} {n:>3} {a['estimated_win_rate_pct']:>8.0f}% {ci.low * 100:>19.1f}%")
    print("\n  A 100% win rate on 3 trades is compatible with a true rate of 29%.")
    print("  quantum_score is monotone in these numbers, so the ranking is noise.")

    losers = [a for a in assignments if a["estimated_profit_factor"] < 1.0]
    if losers:
        print(f"\n  Assignments the optimiser scored as LOSING (profit factor < 1.0):")
        for a in losers:
            print(
                f"    {a['asset']:14s} PF={a['estimated_profit_factor']:.2f} "
                f"WR={a['estimated_win_rate_pct']:.0f}% n={a['estimated_trades_count']}"
            )

    hr("4. PARAMETER COMPATIBILITY (would anything be silently dropped?)")
    problems = 0
    for a in assignments:
        _, dropped = split_strategy_params(a["strategy_id"], a["parameters"])
        if dropped:
            problems += 1
            print(f"    {a['asset']:14s} {a['strategy_id']:26s} ignores: {', '.join(dropped)}")
    if not problems:
        print("    none - every assignment's parameters are accepted by its strategy.")
    else:
        print(f"\n  {problems} assignment(s) carry parameters their strategy does not accept.")
        print("  These now log a warning at start-up instead of vanishing silently.")

    hr("5. SPOT vs OTC, AND WHAT TRADES WHEN")
    spot = [a["asset"] for a in assignments if not is_otc_asset(a["asset"])]
    otc = [a["asset"] for a in assignments if is_otc_asset(a["asset"])]
    print(f"  spot assignments: {len(spot)} -> {', '.join(sorted(spot))}")
    print(f"  OTC assignments : {len(otc)}")

    now = datetime(2026, 8, 28, 15, 10, tzinfo=UTC)  # Friday 19:10 UTC+4
    print(f"\n  Now ({now:%a %d.%m %H:%M} UTC):")
    print(f"    spot market closed? {is_spot_market_closed(now)[0]}")
    for label, moment in [
        ("Fri 20:00 UTC", datetime(2026, 8, 28, 20, 0, tzinfo=UTC)),
        ("Fri 21:30 UTC", datetime(2026, 8, 28, 21, 30, tzinfo=UTC)),
        ("Sat 12:00 UTC", datetime(2026, 8, 29, 12, 0, tzinfo=UTC)),
        ("Sun 22:00 UTC", datetime(2026, 8, 30, 22, 0, tzinfo=UTC)),
    ]:
        live = [a["asset"] for a in assignments if is_asset_in_active_session(a["asset"], moment)[0]]
        n_spot = sum(1 for x in live if not is_otc_asset(x))
        print(f"    {label}: {len(live):>2} tradable ({n_spot} spot, {len(live) - n_spot} OTC)")

    hr("6. OTC / SPOT TWINS AND THE CORRELATION FILTER")
    keys: dict[str, list[str]] = {}
    for a in assignments:
        keys.setdefault(normalize_symbol(a["asset"]), []).append(a["asset"])
    twins = {k: v for k, v in keys.items() if len(v) > 1}
    print(f"  pairs that normalise to the same symbol: {len(twins)}")
    for k, v in sorted(twins.items()):
        print(f"    {k:10s} <- {', '.join(v)}")

    def _rec(asset: str, action: str) -> LiveTradeRecord:
        return LiveTradeRecord(
            trade_id=asset,
            asset=asset,
            action=action,
            stake=1,
            open_time=now,
            expiration_seconds=180,
            open_price=1,
            strategy_id="x",
            strategy_name="x",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.6,
            reason="x",
            payout_rate=0.92,
            outcome=TradeOutcome.PENDING,
        )

    print("\n  Does the correlation filter see a twin as a conflict?")
    for k, v in sorted(twins.items()):
        active = [_rec(v[0], "CALL")]
        same, reason = is_correlated_conflict(v[1], "CALL", active)
        opposite, _ = is_correlated_conflict(v[1], "PUT", active)
        print(f"    {v[1]:14s} vs open CALL on {v[0]:14s}: same-dir blocked={same}, "
              f"opposite blocked={opposite}")
    print("\n  If a twin is NOT blocked, the bot can hold the spot and OTC version of")
    print("  the same pair at once, which is one position of double size, not two.")

    hr("7. RISK CONTROLS AT THIS STAKE")
    stake = plan["stake_amount"]
    otc_stake = stake * plan["otc_stake_multiplier"]
    print(f"  flat stake        : ${stake:.2f}  (spot)   ${otc_stake:.2f}  (OTC on probation)")
    print(f"  stop-loss         : ${plan['stop_loss_amount']:,.0f}"
          f"  = {plan['stop_loss_amount'] / otc_stake:,.0f} losing OTC trades in a row")
    print(f"  take-profit       : ${plan['take_profit_amount']:,.0f}"
          f"  = {plan['take_profit_amount'] / (otc_stake * 0.92):,.0f} net OTC wins")
    print(f"  max drawdown 8%   : ${plan['initial_deposit'] * plan['max_drawdown_pct_limit']:,.0f}")
    print("\n  At this stake every hard limit is far out of reach, which is correct")
    print("  for a measurement run: the sample will not be truncated by a breaker.")
    print(f"\n  per_asset_max_consecutive_losses = {plan['per_asset_max_consecutive_losses']}"
          " -> a 60-min mute after 2 losses in a row on one asset")
    print(f"  per_asset_min_winrate_pct = {plan['per_asset_min_winrate_pct']}"
          " -> 120-min mute once an asset has 3+ trades below that")
    print("  Both fire long before the statistical governor reaches n=20, so most")
    print("  muting this week will come from those two, not from the Wilson rule.")


if __name__ == "__main__":
    main()
