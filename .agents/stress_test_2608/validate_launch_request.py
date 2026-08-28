"""Validates the exact /bot/auto-assign payload the user intends to send."""

from __future__ import annotations

import glob
import json
import sys

import pandas as pd
from scipy import stats

sys.path.insert(0, "src")

from strat_trade.api.schemas import AutoAssignRequest  # noqa: E402
from strat_trade.domain.strategies.registry import list_available_strategies  # noqa: E402
from strat_trade.domain.trading.asset_filter import (  # noqa: E402
    is_asset_in_active_session,
    is_otc_asset,
    is_toxic_asset,
)

PAYLOAD = json.loads(r"""
{"assets":["AUDCAD_otc","AUDCHF_otc","AUDNZD_otc","AUDUSD_otc","BHDCNY_otc","CADJPY_otc","EURTRY_otc","EURUSD_otc","GBPAUD_otc","GBPJPY_otc","KESUSD_otc","LBPUSD_otc","QARCNY_otc","SARCNY_otc","TNDUSD_otc","UAHUSD_otc","USDBDT_otc","USDCLP_otc","USDCOP_otc","USDINR_otc","USDTHB_otc","CHFJPY_otc","USDMYR_otc","YERUSD_otc","AUDCAD","AUDCHF","EURGBP","GBPAUD","USDARS_otc","MADUSD_otc","AUDJPY_otc","EURRUB_otc","NZDJPY_otc","CADCHF","EURNZD_otc","GBPUSD_otc","USDSGD_otc","CADCHF_otc","CADJPY","EURCAD","EURCHF_otc","GBPCHF","AUDUSD","EURHUF_otc","JODCNY_otc","SYPUSD_otc","USDJPY","EURGBP_otc","AEDCNY_otc","USDMXN_otc","USDJPY_otc","EURJPY_otc","CHFNOK_otc","USDPHP_otc","ZARUSD_otc","IRRUSD_otc","USDRUB_otc","AUDJPY","EURUSD","GBPJPY","USDEGP_otc","USDCHF","USDPKR_otc","GBPCAD","GBPUSD","USDCAD","USDCHF_otc","USDCNH_otc","USDDZD_otc","EURJPY","CHFJPY","USDVND_otc","NZDUSD_otc","NGNUSD_otc","EURCHF","USDBRL_otc","EURAUD","USDIDR_otc"],
"allowed_strategies":["rsi_stochastic_extreme","support_resistance_bounce","ema_pullback_trend"],
"initial_deposit":50000,"stake_model":"flat","stake_amount":100,"stake_percent":1,
"daily_stop_loss_pct":0.05,"daily_take_profit_pct":0.025,"trailing_profit_lock_enabled":true,
"per_asset_degradation_guard_enabled":true,"max_concurrent_trades":3,"min_payout_rate":0.8,
"session_filter_enabled":true,"bar_edge_guard_seconds":3,"use_closed_bar_only":true,
"dynamic_strategy_switching_enabled":false,"otc_stake_multiplier":0.25,"otc_min_payout_rate":0.9}
""")


def hr(t: str) -> None:
    print("\n" + "=" * 94)
    print(t)
    print("=" * 94)


def main() -> None:
    hr("1. SCHEMA VALIDATION (extra='forbid' rejects any unknown key)")
    try:
        req = AutoAssignRequest(**PAYLOAD)
        print("  ACCEPTED. Resolved values for anything you did not send:")
        sent = set(PAYLOAD)
        for name in AutoAssignRequest.model_fields:
            if name not in sent:
                print(f"    {name:38s} = {getattr(req, name)!r}   (default)")
    except Exception as exc:
        print(f"  REJECTED: {exc}")
        return

    hr("2. STRATEGY REGISTRY")
    all_strats = list_available_strategies()
    allowed = set(PAYLOAD["allowed_strategies"])
    print(f"  registered strategies: {len(all_strats)}")
    for s in all_strats:
        mark = "USED" if s["id"] in allowed else "  - "
        print(f"    [{mark}] {s['id']:30s} {s['name']}")
    print(f"\n  allowed_strategies limits the auto-matcher to {len(allowed)} of {len(all_strats)}.")
    print("  The other five stay registered but are never instantiated for this run.")

    hr("3. ASSET LIST BREAKDOWN")
    assets = PAYLOAD["assets"]
    otc = [a for a in assets if is_otc_asset(a)]
    spot = [a for a in assets if not is_otc_asset(a)]
    blocked = [a for a in assets if is_toxic_asset(a)[0]]
    survivors = [a for a in assets if not is_toxic_asset(a)[0]]
    otc_surv = [a for a in survivors if is_otc_asset(a)]
    spot_surv = [a for a in survivors if not is_otc_asset(a)]

    print(f"  requested            : {len(assets)}")
    print(f"    OTC                : {len(otc)}")
    print(f"    spot               : {len(spot)}")
    print(f"  blocked by blacklist : {len(blocked)}  (toxic_filter_enabled defaults to True)")
    print(f"  survivors            : {len(survivors)}  -> OTC {len(otc_surv)}, spot {len(spot_surv)}")
    print(f"\n  blocked: {', '.join(sorted(blocked))}")
    print(f"\n  OTC survivors ({len(otc_surv)}): {', '.join(sorted(otc_surv))}")
    print(f"\n  spot survivors ({len(spot_surv)}): {', '.join(sorted(spot_surv))}")

    hr("4. WHAT ACTUALLY TRADES THIS WEEKEND")
    saturday_noon = pd.Timestamp("2026-08-29 12:00", tz="UTC").to_pydatetime()
    saturday_night = pd.Timestamp("2026-08-29 23:00", tz="UTC").to_pydatetime()
    active_noon = [a for a in survivors if is_asset_in_active_session(a, saturday_noon)[0]]
    active_night = [a for a in survivors if is_asset_in_active_session(a, saturday_night)[0]]
    print(f"  Saturday 12:00 UTC : {len(active_noon)} tradable")
    print(f"  Saturday 23:00 UTC : {len(active_night)} tradable")
    blocked_night = sorted(set(active_noon) - set(active_night))
    print(f"  dropped overnight  : {len(blocked_night)} exotics -> {', '.join(blocked_night)}")
    print(f"\n  spot assets tradable on Saturday: "
          f"{[a for a in active_noon if not is_otc_asset(a)]}")

    hr("5. GOVERNOR LEARNING RATE WITH THIS MANY ASSETS")
    n_assets = len(otc_surv)
    trades_per_day = 120  # observed rate in the 24-28.08 sample
    per_asset_per_day = trades_per_day / max(1, n_assets)
    days_to_20 = 20 / per_asset_per_day
    print(f"  tradable OTC assets              : {n_assets}")
    print(f"  observed portfolio rate          : ~{trades_per_day} trades/day")
    print(f"  per asset                        : ~{per_asset_per_day:.1f} trades/day")
    print(f"  days for ONE asset to reach n=20 : {days_to_20:.1f}")
    print("\n  The governor cannot mute anything before n=20, so at this width it")
    print("  effectively never fires. Spreading the same flow over fewer assets is")
    print("  what turns the safety net on.")
    for k in (10, 15, 20, 30):
        print(f"    {k:2d} assets -> n=20 reached in {20 / (trades_per_day / k):.1f} days")

    hr("6. EXPIRATION ACTUALLY USED IN THE LOSING WEEK")
    frames = [pd.read_csv(f) for f in sorted(glob.glob("/Users/vlados/Downloads/Pocket Option*.csv"))]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df = df[df.Outcome.isin(["WIN", "LOSS"])]
    df["is_win"] = df.Outcome.eq("WIN")
    df["dur"] = (
        pd.to_datetime(df["Close Time"], utc=True) - pd.to_datetime(df["Open Time"], utc=True)
    ).dt.total_seconds().round().astype(int)

    print(f"  {'expiration':>12} {'trades':>8} {'WR%':>8} {'PnL$':>10} {'p(WR>BE)':>10}")
    be = 1 / 1.92
    for dur, g in df.groupby("dur"):
        if len(g) < 20:
            continue
        w, n = int(g.is_win.sum()), len(g)
        p = stats.binomtest(w, n, be, alternative="greater").pvalue
        print(
            f"  {dur:>10}s {n:>8} {w / n * 100:>8.2f} "
            f"{g['Broker Profit ($)'].sum():>+10,.0f} {p:>10.4f}"
        )
    others = df[~df.dur.isin([d for d, g in df.groupby('dur') if len(g) >= 20])]
    if len(others):
        print(f"  (+{len(others)} trades on expirations with too few samples to score)")
    print(f"\n  Default in the schema now: expiration_seconds = {req.expiration_seconds}s")
    print(f"  Auto-matcher optimises for: {max(1, req.expiration_seconds // 60)} bar(s) on M1")


if __name__ == "__main__":
    main()
