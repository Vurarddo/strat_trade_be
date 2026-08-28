"""Can asset quality be predicted BEFORE trading, from measurable features?

If yes -> replace the hand-curated name blacklist with a structural rule.
If no  -> the blacklist is unfalsifiable curve-fitting and must not be trusted.

Validation is split-half: derive the rule on 24-26.08, test on 27-28.08.
"""

from __future__ import annotations

import glob

import numpy as np
import pandas as pd
from scipy import stats

BE = 1 / 1.9132


def load() -> pd.DataFrame:
    fr = [pd.read_csv(f) for f in sorted(glob.glob("/Users/vlados/Downloads/Pocket Option*.csv"))]
    df = pd.concat(fr, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df[df.Outcome.isin(["WIN", "LOSS"])].sort_values("Open Time").reset_index(drop=True)
    df["is_win"] = df.Outcome.eq("WIN")
    df["pnl"] = df["Broker Profit ($)"]
    df["stake"] = df["Trade Amount ($)"]
    df["px"] = df["Broker Open Price"]
    df["atr_bps"] = df.ATR / df.px * 1e4
    df["slip_bps"] = df.Slippage / df.px * 1e4
    df["slip_atr"] = df.slip_bps / df.atr_bps.replace(0, np.nan)
    df["is_otc"] = df.Asset.str.contains("OTC", na=False)
    df["sec"] = df["Open Time"].dt.second
    df["half"] = np.where(df["Open Time"].dt.date.astype(str) < "2026-08-27", "A_24-26", "B_27-28")
    return df


def hr(t: str) -> None:
    print("\n" + "=" * 106)
    print(t)
    print("=" * 106)


def asset_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("Asset").agg(
        n=("is_win", "size"),
        wr=("is_win", "mean"),
        pnl=("pnl", "sum"),
        turnover=("stake", "sum"),
        atr_bps=("atr_bps", "median"),
        slip_bps=("slip_bps", "median"),
        slip_atr=("slip_atr", "median"),
        is_otc=("is_otc", "first"),
    )
    g["roi"] = g.pnl / g.turnover * 100
    g["wr"] = g.wr * 100
    return g


def main() -> None:
    df = load()
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)

    hr("1. DO PRE-TRADE MEASURABLE FEATURES PREDICT ASSET PROFITABILITY?")
    g = asset_table(df)
    gm = g[g.n >= 10]
    print(f"assets with >=10 trades: {len(gm)} of {len(g)}\n")
    print("Spearman correlation of each measurable feature with the asset's ROI:")
    for f in ["atr_bps", "slip_bps", "slip_atr", "n"]:
        r, p = stats.spearmanr(gm[f], gm.roi)
        flag = "  <-- significant" if p < 0.05 else ""
        print(f"  {f:10s} vs ROI : rho={r:+.3f}  p={p:.4f}{flag}")
    r, p = stats.pointbiserialr(gm.is_otc.astype(int), gm.roi)
    print(f"  {'is_otc':10s} vs ROI : r  ={r:+.3f}  p={p:.4f}")

    print("\nSame at TRADE level (not asset level), n=%d:" % len(df))
    for f in ["atr_bps", "slip_bps", "slip_atr"]:
        sub = df.dropna(subset=[f])
        r, p = stats.pointbiserialr(sub.is_win.astype(int), sub[f])
        print(f"  {f:10s} vs win: r={r:+.4f}  p={p:.4f}")

    hr("2. IS THE CURRENT NAME-BASED BLACKLIST DATA-MINED FROM THESE LOSSES?")
    import sys
    sys.path.insert(0, "src")
    from strat_trade.domain.trading.asset_filter import is_toxic_asset

    g2 = g.copy()
    g2["blacklisted"] = [is_toxic_asset(a)[0] for a in g2.index]
    bl, ok = g2[g2.blacklisted], g2[~g2.blacklisted]
    print(f"  blacklisted & traded: {len(bl)} assets, {bl.n.sum()} trades, PnL=${bl.pnl.sum():+,.0f}")
    print(f"  not blacklisted     : {len(ok)} assets, {ok.n.sum()} trades, PnL=${ok.pnl.sum():+,.0f}")
    neg = int((bl.pnl < 0).sum())
    print(f"\n  of {len(bl)} blacklisted assets, {neg} were losers and {len(bl)-neg} were winners")
    u = stats.mannwhitneyu(bl.roi, ok.roi, alternative="less")
    print(f"  Mann-Whitney (blacklisted ROI < rest): p = {u.pvalue:.5f}")
    print("  -> a p this small means the list tracks THIS sample's PnL almost perfectly,")
    print("     which is the signature of a list curated FROM these results, not a prior.")

    print("\n  Split-half test: does the blacklist derived from half A predict half B?")
    A = asset_table(df[df.half == "A_24-26"])
    B = asset_table(df[df.half == "B_27-28"])
    common = A.index.intersection(B.index)
    A2, B2 = A.loc[common], B.loc[common]
    A2 = A2[A2.n >= 5]
    B2 = B2.loc[A2.index]
    losers_A = A2[A2.pnl < 0].index
    if len(losers_A) >= 5:
        blocked_B = B2.loc[B2.index.isin(losers_A)]
        kept_B = B2.loc[~B2.index.isin(losers_A)]
        print(f"    assets losing in half A: {len(losers_A)} (of {len(A2)} with >=5 trades)")
        print(f"    their PnL in half B    : ${blocked_B.pnl.sum():+,.0f} on {blocked_B.n.sum()} trades")
        print(f"    the rest in half B     : ${kept_B.pnl.sum():+,.0f} on {kept_B.n.sum()} trades")
        r, p = stats.spearmanr(A2.roi, B2.roi)
        print(f"    Spearman(ROI in A, ROI in B) = {r:+.3f}  p={p:.4f}")
        if p > 0.05:
            print("    -> An asset's past PnL does NOT predict its future PnL.")
            print("       Blacklisting by name/PnL is therefore worthless as a forward rule.")

    hr("3. WHAT DOES SEPARATE WINNERS FROM LOSERS? (structural, not name-based)")
    print("Testing each candidate GATE on the full sample, then split-half:\n")
    gates = {
        "SPOT only": ~df.is_otc,
        "entry not on bar edge (sec>2)": df.sec > 2,
        "ATR >= 2 bps": df.atr_bps >= 2.0,
        "ATR <= 20 bps": df.atr_bps <= 20.0,
        "slip/ATR <= 3": df.slip_atr <= 3.0,
        "slip <= 10 bps": df.slip_bps <= 10.0,
    }
    print(f"  {'gate':34s} {'kept n':>7} {'WR%':>7} {'PnL$':>9} | {'A: WR%':>8} {'A PnL$':>9} | {'B: WR%':>8} {'B PnL$':>9}")
    for name, mask in gates.items():
        k = df[mask]
        if len(k) < 30:
            continue
        a = k[k.half == "A_24-26"]
        b = k[k.half == "B_27-28"]
        print(
            f"  {name:34s} {len(k):>7} {k.is_win.mean()*100:>7.2f} {k.pnl.sum():>+9,.0f} | "
            f"{a.is_win.mean()*100:>8.2f} {a.pnl.sum():>+9,.0f} | "
            f"{b.is_win.mean()*100:>8.2f} {b.pnl.sum():>+9,.0f}"
        )
    print("\n  A gate is only trustworthy if it works in BOTH halves.")

    hr("4. CANDIDATE COMBINED GATE — validated on both halves")
    combo = (~df.is_otc) & (df.sec > 2)
    for name, mask in [
        ("SPOT + sec>2", combo),
        ("SPOT + sec>2 + ATR>=0.5bps", combo & (df.atr_bps >= 0.5)),
        ("all assets + sec>2 + slip/ATR<=3", (df.sec > 2) & (df.slip_atr <= 3.0)),
        ("OTC + sec>2 + slip/ATR<=3", df.is_otc & (df.sec > 2) & (df.slip_atr <= 3.0)),
    ]:
        k = df[mask]
        if len(k) < 20:
            continue
        a, b = k[k.half == "A_24-26"], k[k.half == "B_27-28"]
        w, n = int(k.is_win.sum()), len(k)
        ci = stats.binomtest(w, n).proportion_ci(0.95)
        print(f"\n  {name}")
        print(f"    full : n={n:4d}  WR={w/n*100:5.2f}%  CI=[{ci.low*100:.1f},{ci.high*100:.1f}]  "
              f"PnL=${k.pnl.sum():+,.0f}  p(>BE)={stats.binomtest(w,n,BE,alternative='greater').pvalue:.4f}")
        for lbl, x in [("A 24-26", a), ("B 27-28", b)]:
            if len(x) >= 15:
                print(f"    {lbl}: n={len(x):4d}  WR={x.is_win.mean()*100:5.2f}%  PnL=${x.pnl.sum():+,.0f}")

    hr("5. OTC MAJORS vs OTC EXOTICS — is the split structural or arbitrary?")
    majors = ["EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
    def is_major(a: str) -> bool:
        base = a.replace(" OTC", "").strip()
        parts = base.split("/")
        return len(parts) == 2 and all(p in majors for p in parts)

    df["otc_major"] = df.is_otc & df.Asset.map(is_major)
    df["otc_exotic"] = df.is_otc & ~df.Asset.map(is_major)
    print(f"  {'bucket':22s} {'n':>5} {'WR%':>7} {'PnL$':>9} {'ROI%':>7} {'medATR':>8} {'medSlip':>8} | A PnL | B PnL")
    for name, mask in [
        ("SPOT", ~df.is_otc),
        ("OTC majors", df.otc_major),
        ("OTC exotics", df.otc_exotic),
    ]:
        k = df[mask]
        a, b = k[k.half == "A_24-26"], k[k.half == "B_27-28"]
        print(
            f"  {name:22s} {len(k):>5} {k.is_win.mean()*100:>7.2f} {k.pnl.sum():>+9,.0f} "
            f"{k.pnl.sum()/k.stake.sum()*100:>+7.2f} {k.atr_bps.median():>8.2f} "
            f"{k.slip_bps.median():>8.2f} | ${a.pnl.sum():+,.0f} | ${b.pnl.sum():+,.0f}"
        )
    print("\n  OTC majors, restricted to sec>2:")
    k = df[df.otc_major & (df.sec > 2)]
    a, b = k[k.half == "A_24-26"], k[k.half == "B_27-28"]
    w, n = int(k.is_win.sum()), len(k)
    print(f"    n={n}  WR={w/n*100:.2f}%  PnL=${k.pnl.sum():+,.0f}  "
          f"| A: {a.is_win.mean()*100:.1f}% ${a.pnl.sum():+,.0f} | B: {b.is_win.mean()*100:.1f}% ${b.pnl.sum():+,.0f}")

    hr("6. HOW MANY ASSETS WOULD SURVIVE A HONEST GATE?")
    keep = df[(df.sec > 2)]
    gg = asset_table(keep)
    gg = gg[gg.n >= 15]
    print(f"  assets with >=15 trades after the bar-edge gate: {len(gg)}")
    print(gg.sort_values("roi", ascending=False)[
        ["n", "wr", "pnl", "roi", "atr_bps", "slip_bps", "slip_atr", "is_otc"]
    ].round(2).to_string())
    print("\n  REMINDER: ranking assets by their ROI here is exactly the overfitting trap.")
    print("  Section 2 showed past asset PnL does not predict future asset PnL.")


if __name__ == "__main__":
    main()
