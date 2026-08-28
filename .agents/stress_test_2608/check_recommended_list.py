"""Checks a narrowed OTC-only list against every filter, and scores it on history."""

from __future__ import annotations

import glob
import sys

import pandas as pd
from scipy import stats

sys.path.insert(0, "src")

from strat_trade.domain.trading.asset_filter import (  # noqa: E402
    is_asset_in_active_session,
    is_otc_asset,
    is_toxic_asset,
)

RECOMMENDED = [
    "EURUSD_otc",
    "GBPUSD_otc",
    "AUDUSD_otc",
    "NZDUSD_otc",
    "USDJPY_otc",
    "CADJPY_otc",
    "AUDCAD_otc",
    "AUDNZD_otc",
    "EURNZD_otc",
    "USDCNH_otc",
]

NAME_MAP = {
    "EURUSD_otc": "EUR/USD OTC",
    "GBPUSD_otc": "GBP/USD OTC",
    "AUDUSD_otc": "AUD/USD OTC",
    "NZDUSD_otc": "NZD/USD OTC",
    "USDJPY_otc": "USD/JPY OTC",
    "CADJPY_otc": "CAD/JPY OTC",
    "AUDCAD_otc": "AUD/CAD OTC",
    "AUDNZD_otc": "AUD/NZD OTC",
    "EURNZD_otc": "EUR/NZD OTC",
    "USDCNH_otc": "USD/CNH OTC",
}


def hr(t: str) -> None:
    print("\n" + "=" * 88)
    print(t)
    print("=" * 88)


def main() -> None:
    hr("FILTER CHECK FOR THE NARROWED LIST")
    night = pd.Timestamp("2026-08-29 23:00", tz="UTC").to_pydatetime()
    noon = pd.Timestamp("2026-08-29 12:00", tz="UTC").to_pydatetime()
    print(f"  {'asset':14s} {'OTC':>5} {'blacklisted':>12} {'Sat 12:00':>11} {'Sat 23:00':>11}")
    for a in RECOMMENDED:
        toxic = is_toxic_asset(a)[0]
        print(
            f"  {a:14s} {str(is_otc_asset(a)):>5} {str(toxic):>12} "
            f"{str(is_asset_in_active_session(a, noon)[0]):>11} "
            f"{str(is_asset_in_active_session(a, night)[0]):>11}"
        )

    hr("HOW THESE ASSETS BEHAVED IN THE LOSING WEEK (with the bar-edge gate applied)")
    frames = [
        pd.read_csv(f) for f in sorted(glob.glob("/Users/vlados/Downloads/Pocket Option*.csv"))
    ]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df[df.Outcome.isin(["WIN", "LOSS"])]
    df["is_win"] = df.Outcome.eq("WIN")
    df["pnl"] = df["Broker Profit ($)"]
    df["sec"] = df["Open Time"].dt.second
    gated = df[df.sec >= 3]

    wanted = set(NAME_MAP.values())
    sub = gated[gated.Asset.isin(wanted)]
    print(f"  {'asset':16s} {'n':>5} {'WR%':>7} {'PnL$':>9}")
    for asset, g in sub.groupby("Asset"):
        print(f"  {asset:16s} {len(g):>5} {g.is_win.mean() * 100:>7.2f} {g.pnl.sum():>+9,.0f}")
    missing = sorted(wanted - set(sub.Asset.unique()))
    if missing:
        print(f"\n  no history in the sample: {', '.join(missing)}")

    w, n = int(sub.is_win.sum()), len(sub)
    be = 1 / 1.92
    p = stats.binomtest(w, n, be, alternative="greater").pvalue
    print(f"\n  combined: n={n}, WR={w / n * 100:.2f}%, PnL=${sub.pnl.sum():+,.0f}")
    print(f"  at 25% stake that PnL would have been ${sub.pnl.sum() * 0.25:+,.0f}")
    print(f"  p(WR > break-even) = {p:.4f}")
    print("\n  NOTE: this subset was chosen for structure (major pairs, continuous")
    print("  quotes), not for its PnL here. Picking assets by past PnL is exactly")
    print("  the overfitting the earlier split-half test ruled out.")

    hr("GOVERNOR LEARNING RATE AT THIS WIDTH")
    for rate in (120, 200, 300):
        per_asset = rate / len(RECOMMENDED)
        print(
            f"  at {rate:>3} trades/day -> {per_asset:.0f}/asset/day, "
            f"n=20 reached in {20 / per_asset:.1f} days"
        )


if __name__ == "__main__":
    main()
