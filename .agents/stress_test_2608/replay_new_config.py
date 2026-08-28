"""Replays the 24-28.08 week through the gates that are now in the code.

This is a counterfactual, not a backtest: it re-scores the trades that were
actually taken. It cannot show trades the new config would have taken instead,
so treat the result as an upper bound on the damage avoided, not as a forecast.
"""

from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")

from strat_trade.domain.trading.asset_governor import (  # noqa: E402
    AssetGovernor,
    AssetGovernorConfig,
)

BAR_EDGE_GUARD_SECONDS = 3
OTC_STAKE_MULTIPLIER = 0.25
OTC_MIN_PAYOUT = 0.90
SPOT_MIN_PAYOUT = 0.80


def load() -> pd.DataFrame:
    frames = [pd.read_csv(f) for f in sorted(glob.glob("/Users/vlados/Downloads/Pocket Option*.csv"))]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df[df.Outcome.isin(["WIN", "LOSS"])].sort_values("Open Time").reset_index(drop=True)
    df["is_win"] = df.Outcome.eq("WIN")
    df["pnl"] = df["Broker Profit ($)"]
    df["stake"] = df["Trade Amount ($)"]
    df["is_otc"] = df.Asset.str.contains("OTC", na=False)
    df["sec"] = df["Open Time"].dt.second
    # Realised payout: known on winners, assumed at the 92% book rate on losers.
    df["payout"] = np.where(df.is_win, df.pnl / df.stake, 0.92)
    return df


def hr(title: str) -> None:
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)


def summarise(label: str, kept: pd.DataFrame, scale: pd.Series | None = None) -> dict:
    if kept.empty:
        return {"label": label, "n": 0, "wr": 0.0, "pnl": 0.0, "turnover": 0.0}
    mult = scale if scale is not None else pd.Series(1.0, index=kept.index)
    return {
        "label": label,
        "n": len(kept),
        "wr": kept.is_win.mean() * 100.0,
        "pnl": float((kept.pnl * mult).sum()),
        "turnover": float((kept.stake * mult).sum()),
    }


def main() -> None:
    df = load()

    hr("BASELINE — WHAT ACTUALLY HAPPENED")
    base = summarise("as traded", df)
    print(
        f"  {base['n']} trades, WR {base['wr']:.2f}%, turnover ${base['turnover']:,.0f}, "
        f"PnL ${base['pnl']:+,.0f}"
    )

    hr("GATES APPLIED ONE AT A TIME (cumulative)")
    rows = [base]

    step1 = df[df.sec >= BAR_EDGE_GUARD_SECONDS]
    rows.append(summarise(f"+ bar-edge guard ({BAR_EDGE_GUARD_SECONDS}s)", step1))

    # The payout floor is deliberately NOT replayed. The broker report only
    # reveals the payout on winning trades (profit/stake); on losers it is
    # unobservable. Applying the floor here could therefore only ever delete
    # winners, which would understate the gate by construction.
    step2 = step1
    mult = np.where(step2.is_otc, OTC_STAKE_MULTIPLIER, 1.0)
    rows.append(
        summarise(
            f"+ OTC probation ({OTC_STAKE_MULTIPLIER:.0%} stake)",
            step2,
            pd.Series(mult, index=step2.index),
        )
    )

    print(f"  {'configuration':38s} {'trades':>7} {'WR%':>7} {'turnover$':>11} {'PnL$':>9}")
    for r in rows:
        print(
            f"  {r['label']:38s} {r['n']:>7} {r['wr']:>7.2f} "
            f"{r['turnover']:>11,.0f} {r['pnl']:>+9,.0f}"
        )
    print(f"\n  Net swing vs baseline: ${rows[-1]['pnl'] - base['pnl']:+,.0f}")
    print(
        "\n  Not replayed: the per-bucket payout floor. Payout is only observable\n"
        "  on winners, so replaying it would delete winners and nothing else."
    )

    hr("WOULD THE GOVERNOR HAVE MUTED ANYTHING, AND WHEN?")
    gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20, mute_duration_minutes=240))
    kept_pnl = 0.0
    skipped_pnl = 0.0
    skipped_n = 0
    mute_log: list[tuple[str, str, int]] = []

    for _, t in step2.iterrows():
        verdict = gov.evaluate(t.Asset, t["Open Time"])
        scale = OTC_STAKE_MULTIPLIER if t.is_otc else 1.0
        if not verdict.is_tradable:
            skipped_pnl += t.pnl * scale
            skipped_n += 1
            continue
        kept_pnl += t.pnl * scale
        was_muted = gov.stats_for(t.Asset).muted_until
        gov.record_outcome(t.Asset, bool(t.is_win), float(t.payout), t["Open Time"])
        now_muted = gov.stats_for(t.Asset).muted_until
        if now_muted != was_muted and now_muted is not None:
            st = gov.stats_for(t.Asset)
            mute_log.append((t.Asset, t["Open Time"].strftime("%d.%m %H:%M"), st.wins + st.losses))

    print(f"  trades suppressed by the governor : {skipped_n}")
    print(f"  PnL avoided on those trades       : ${-skipped_pnl:+,.0f}")
    print(f"  PnL on the trades still taken     : ${kept_pnl:+,.0f}")
    print(f"\n  mute events ({len(mute_log)}):")
    for asset, when, n in mute_log:
        print(f"    {when}  {asset:16s} after {n} decided trades")
    if not mute_log:
        print("    none — no asset accumulated enough evidence within one week")

    hr("FULL CONFIG vs BASELINE")
    total = kept_pnl
    print(f"  as traded            : ${base['pnl']:+,.0f}")
    print(f"  with every gate on   : ${total:+,.0f}")
    print(f"  difference           : ${total - base['pnl']:+,.0f}")
    print(
        f"\n  Capital at risk drops from ${base['turnover']:,.0f} to "
        f"${rows[-1]['turnover']:,.0f} ({rows[-1]['turnover'] / base['turnover'] - 1:+.0%})."
    )
    print("\n  The gates remove a measured leak. They do not manufacture an edge:")
    print("  the surviving sample is close to break-even, which is the honest")
    print("  starting point for a forward test, not a profit forecast.")


if __name__ == "__main__":
    main()
