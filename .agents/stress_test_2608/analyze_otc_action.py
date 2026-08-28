"""What concrete action for OTC? Payout-aware break-even, weekend effect, sample size needed."""

from __future__ import annotations

import glob

import numpy as np
import pandas as pd
from scipy import stats


def load() -> pd.DataFrame:
    fr = [pd.read_csv(f) for f in sorted(glob.glob("/Users/vlados/Downloads/Pocket Option*.csv"))]
    df = pd.concat(fr, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df[df.Outcome.isin(["WIN", "LOSS"])].sort_values("Open Time").reset_index(drop=True)
    df["is_win"] = df.Outcome.eq("WIN")
    df["pnl"] = df["Broker Profit ($)"]
    df["stake"] = df["Trade Amount ($)"]
    df["is_otc"] = df.Asset.str.contains("OTC", na=False)
    df["sec"] = df["Open Time"].dt.second
    # realised payout on winners: profit/stake
    df["payout"] = np.where(df.is_win, df.pnl / df.stake, np.nan)
    df["dow"] = df["Open Time"].dt.day_name()
    df["date"] = df["Open Time"].dt.date
    return df


def hr(t: str) -> None:
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)


def main() -> None:
    df = load()

    hr("1. REALISED PAYOUT AND EXACT BREAK-EVEN WIN RATE PER BUCKET")
    print(f"  {'bucket':16s} {'n':>5} {'payout%':>9} {'BE WR%':>8} {'actual WR%':>11} {'edge pp':>9} {'ROI%':>8}")
    for name, mask in [("SPOT", ~df.is_otc), ("OTC", df.is_otc), ("ALL", df.index == df.index)]:
        k = df[mask]
        po = k.payout.median()
        be = 1 / (1 + po) * 100
        wr = k.is_win.mean() * 100
        print(f"  {name:16s} {len(k):>5} {po*100:>9.2f} {be:>8.2f} {wr:>11.2f} {wr-be:>+9.2f} "
              f"{k.pnl.sum()/k.stake.sum()*100:>+8.2f}")
    print("\n  Payout distribution on winners (OTC):")
    print("   ", df[df.is_otc].payout.describe(percentiles=[.05, .25, .5, .75, .95]).round(4).to_dict())
    print("  Payout distribution on winners (SPOT):")
    print("   ", df[~df.is_otc].payout.describe(percentiles=[.05, .25, .5, .75, .95]).round(4).to_dict())

    hr("2. WEEKEND vs WEEKDAY (OTC is the only market on Sat/Sun)")
    print(f"  {'day':12s} {'n':>5} {'otc%':>6} {'WR%':>7} {'PnL$':>9}")
    for d, k in df.groupby("dow", sort=False):
        print(f"  {d:12s} {len(k):>5} {k.is_otc.mean()*100:>6.0f} {k.is_win.mean()*100:>7.2f} {k.pnl.sum():>+9,.0f}")
    wknd = df[df.dow.isin(["Saturday", "Sunday"])]
    wkdy = df[~df.dow.isin(["Saturday", "Sunday"])]
    if len(wknd) > 20:
        otc_wknd = wknd[wknd.is_otc]
        otc_wkdy = wkdy[wkdy.is_otc]
        print(f"\n  OTC on weekend : n={len(otc_wknd)} WR={otc_wknd.is_win.mean()*100:.2f}% PnL=${otc_wknd.pnl.sum():+,.0f}")
        print(f"  OTC on weekday : n={len(otc_wkdy)} WR={otc_wkdy.is_win.mean()*100:.2f}% PnL=${otc_wkdy.pnl.sum():+,.0f}")
        t = stats.fisher_exact([[otc_wknd.is_win.sum(), (~otc_wknd.is_win).sum()],
                                [otc_wkdy.is_win.sum(), (~otc_wkdy.is_win).sum()]])
        print(f"  Fisher exact p = {t[1]:.4f}")
    else:
        print("\n  No weekend data in this sample -> OTC weekend behaviour is UNTESTED.")

    hr("3. HOW MANY TRADES TO PROVE OTC HAS AN EDGE (or does not)?")
    po = df[df.is_otc].payout.median()
    be = 1 / (1 + po)
    print(f"  OTC break-even WR = {be*100:.2f}% (payout {po*100:.2f}%)")
    print(f"  observed OTC WR   = {df[df.is_otc].is_win.mean()*100:.2f}% on {df.is_otc.sum()} trades\n")
    print(f"  {'true WR':>9} {'edge pp':>9} {'n for 80% power':>17} {'trading days @120/day':>22}")
    for true_wr in [0.525, 0.535, 0.545, 0.555, 0.57]:
        eff = (true_wr - be) / np.sqrt(be * (1 - be))
        if eff <= 0:
            continue
        n = int(np.ceil(((1.645 + 0.84) / eff) ** 2))
        print(f"  {true_wr*100:>8.1f}% {(true_wr-be)*100:>+9.2f} {n:>17,} {n/120:>22.0f}")
    print("\n  -> Even a strong +3pp edge needs ~1.5k trades to confirm.")
    print("     One week of data can never settle this. It can only detect a large leak.")

    hr("4. WHAT AN 'OTC PROBATION' MODE WOULD HAVE COST")
    otc = df[df.is_otc].copy()
    print(f"  actual OTC turnover  : ${otc.stake.sum():>10,.0f}   PnL ${otc.pnl.sum():+,.0f}")
    for frac in [0.25, 0.10]:
        print(f"  at {frac*100:>3.0f}% stake      : ${otc.stake.sum()*frac:>10,.0f}   PnL ${otc.pnl.sum()*frac:+,.0f}")
    spot = df[~df.is_otc]
    print(f"\n  SPOT PnL untouched   : ${spot.pnl.sum():+,.0f} on {len(spot)} trades")
    for frac in [0.25, 0.10]:
        total = spot.pnl.sum() + otc.pnl.sum() * frac
        print(f"  week PnL with OTC@{frac*100:>3.0f}% + bar-edge gate: "
              f"${spot[spot.sec>2].pnl.sum() + otc[otc.sec>2].pnl.sum()*frac:+,.0f}")

    hr("5. EV-GATE: WHAT PAYOUT FLOOR IS NEEDED?")
    print("  Required payout to break even at a given true WR:")
    print(f"  {'true WR':>9} {'min payout':>12}")
    for wr in [0.50, 0.52, 0.53, 0.54, 0.55, 0.56]:
        print(f"  {wr*100:>8.1f}% {(1/wr - 1)*100:>11.2f}%")
    print("\n  Observed payout percentiles across ALL trades (winners only):")
    q = df.payout.quantile([.05, .10, .25, .50]).round(4)
    for k, v in q.items():
        print(f"    p{int(k*100):02d} = {v*100:.2f}%  -> needs WR >= {1/(1+v)*100:.2f}%")


if __name__ == "__main__":
    main()
