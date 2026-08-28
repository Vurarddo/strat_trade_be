"""Formal confirmation of the two decisive splits: bar-alignment and OTC."""

from __future__ import annotations

import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DOWNLOADS = Path("/Users/vlados/Downloads")


def load() -> pd.DataFrame:
    fr = []
    for f in sorted(glob.glob(str(DOWNLOADS / "Pocket Option*.csv"))):
        fr.append(pd.read_csv(f))
    df = pd.concat(fr, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df.sort_values("Open Time").reset_index(drop=True)
    df["is_win"] = df.Outcome.eq("WIN")
    df["is_loss"] = df.Outcome.eq("LOSS")
    df["pnl"] = df["Broker Profit ($)"]
    df["stake"] = df["Trade Amount ($)"]
    df["sec"] = df["Open Time"].dt.second
    df["is_otc"] = df.Asset.str.contains("OTC", na=False)
    df["aligned"] = df.sec <= 2
    df["px"] = df["Broker Open Price"]
    df["atr_bps"] = df.ATR / df.px * 1e4
    df["slip_bps"] = df.Slippage / df.px * 1e4
    df["move_bps"] = (df["Broker Close Price"] - df.px) / df.px * 1e4
    df["signed_move"] = np.where(df.Direction == "CALL", df.move_bps, -df.move_bps)
    return df[df.Outcome.isin(["WIN", "LOSS"])].reset_index(drop=True)


BE = 1 / 1.9132


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    return (
        (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d,
        (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d,
    )


def report(label: str, s: pd.DataFrame) -> dict:
    w = int(s.is_win.sum())
    n = len(s)
    lo, hi = wilson(w, n)
    p_lt = stats.binomtest(w, n, BE, alternative="less").pvalue
    p_gt = stats.binomtest(w, n, BE, alternative="greater").pvalue
    print(
        f"  {label:34s} n={n:4d}  WR={w/n*100:5.2f}%  CI=[{lo*100:5.2f},{hi*100:5.2f}]  "
        f"PnL=${s.pnl.sum():+8,.0f}  ROI={s.pnl.sum()/s.stake.sum()*100:+6.2f}%  "
        f"p(<BE)={p_lt:.4f}  p(>BE)={p_gt:.4f}"
    )
    return {"w": w, "n": n, "pnl": s.pnl.sum()}


def hr(t):
    print("\n" + "=" * 112)
    print(t)
    print("=" * 112)


def main() -> None:
    df = load()
    pd.set_option("display.width", 220)
    print(f"decisive trades: {len(df)}   breakeven WR at realized 91.32% payout = {BE*100:.2f}%")

    hr("A. SPLIT 1 — ENTRY ALIGNED TO THE BAR OPEN (sec <= 2) vs THE REST")
    a = df[df.aligned]
    b = df[~df.aligned]
    ra, rb = report("aligned  (sec 0-2)", a), report("not aligned (sec > 2)", b)
    ct = [[ra["w"], ra["n"] - ra["w"]], [rb["w"], rb["n"] - rb["w"]]]
    print(f"\n  chi2 p = {stats.chi2_contingency(ct).pvalue:.6f}   "
          f"Fisher p = {stats.fisher_exact(ct)[1]:.6f}")
    print(f"  loss concentrated in the aligned bucket: ${ra['pnl']:,.0f} of ${df.pnl.sum():,.0f} total "
          f"= {ra['pnl']/df.pnl.sum()*100:.0f}%")
    print(f"  aligned bucket is {ra['n']/len(df)*100:.0f}% of trades but "
          f"{ra['pnl']/df.pnl.sum()*100:.0f}% of the damage")
    print("\n  Finer breakdown by second:")
    for lo_, hi_ in [(0, 0), (1, 1), (2, 2), (3, 4), (5, 9), (10, 19), (20, 59)]:
        s = df[(df.sec >= lo_) & (df.sec <= hi_)]
        if len(s) >= 5:
            w = int(s.is_win.sum())
            print(f"    sec {lo_:2d}-{hi_:2d}: n={len(s):4d}  WR={w/len(s)*100:5.2f}%  PnL=${s.pnl.sum():+7,.0f}")
    print("\n  Signed directional edge (bps) by alignment:")
    for lbl, s in [("aligned", a), ("not aligned", b)]:
        t = stats.ttest_1samp(s.signed_move, 0)
        print(f"    {lbl:12s}: mean={s.signed_move.mean():+.3f} bps  t={t.statistic:+.2f} p={t.pvalue:.4f}")
    print("\n  -> Entries fired on the just-closed bar have NEGATIVE skill; the rest do not.")
    print("     This is the signature of acting on the closing bar of an impulse move.")

    hr("B. SPLIT 2 — OTC vs SPOT")
    o, s_ = df[df.is_otc], df[~df.is_otc]
    ro, rs = report("OTC", o), report("SPOT", s_)
    ct = [[ro["w"], ro["n"] - ro["w"]], [rs["w"], rs["n"] - rs["w"]]]
    print(f"\n  chi2 p = {stats.chi2_contingency(ct).pvalue:.6f}   "
          f"Fisher p = {stats.fisher_exact(ct)[1]:.6f}")
    print(f"  OTC median ATR={o.atr_bps.median():.2f} bps  slip={o.slip_bps.median():.2f} bps  "
          f"slip/ATR={(o.slip_bps/o.atr_bps).median():.2f}")
    print(f"  SPOT median ATR={s_.atr_bps.median():.2f} bps  slip={s_.slip_bps.median():.2f} bps  "
          f"slip/ATR={(s_.slip_bps/s_.atr_bps).median():.2f}")
    print(f"\n  OTC turnover share: {o.stake.sum()/df.stake.sum()*100:.0f}%")
    print("\n  Signed directional edge (bps):")
    for lbl, x in [("OTC", o), ("SPOT", s_)]:
        t = stats.ttest_1samp(x.signed_move, 0)
        print(f"    {lbl:5s}: mean={x.signed_move.mean():+.3f}  t={t.statistic:+.2f} p={t.pvalue:.4f}")

    hr("C. 2x2 INTERACTION — is the bar-alignment leak an OTC phenomenon?")
    print(f"  {'':22s} {'n':>5} {'WR%':>7} {'PnL$':>9} {'ROI%':>7}")
    for otc in [True, False]:
        for al in [True, False]:
            x = df[(df.is_otc == otc) & (df.aligned == al)]
            if len(x) < 5:
                continue
            w = int(x.is_win.sum())
            lbl = f"{'OTC' if otc else 'SPOT'} / {'aligned' if al else 'not aligned'}"
            print(f"  {lbl:22s} {len(x):5d} {w/len(x)*100:7.2f} {x.pnl.sum():+9,.0f} "
                  f"{x.pnl.sum()/x.stake.sum()*100:+7.2f}")
    print("\n  logistic regression: win ~ is_otc + aligned")
    X = pd.DataFrame({
        "const": 1.0,
        "is_otc": df.is_otc.astype(float),
        "aligned": df.aligned.astype(float),
    }).values
    y = df.is_win.astype(float).values
    beta = np.zeros(X.shape[1])
    for _ in range(60):
        p = 1 / (1 + np.exp(-X @ beta))
        W = np.diag(p * (1 - p) + 1e-9)
        try:
            beta += np.linalg.solve(X.T @ W @ X, X.T @ (y - p))
        except np.linalg.LinAlgError:
            break
    p = 1 / (1 + np.exp(-X @ beta))
    cov = np.linalg.inv(X.T @ np.diag(p * (1 - p) + 1e-9) @ X)
    se = np.sqrt(np.diag(cov))
    for nm, bt, s2 in zip(["intercept", "is_otc", "aligned"], beta, se):
        z = bt / s2
        print(f"    {nm:10s} beta={bt:+.4f}  se={s2:.4f}  z={z:+.2f}  "
              f"p={2*(1-stats.norm.cdf(abs(z))):.4f}  OR={math.exp(bt):.3f}")

    hr("D. THE CLEAN SUBSET — what survives if both leaks are removed")
    clean = df[(~df.aligned) & (~df.is_otc)]
    report("SPOT + not aligned", clean)
    clean2 = df[~df.aligned]
    report("all assets, not aligned", clean2)
    clean3 = df[~df.is_otc]
    report("SPOT, any alignment", clean3)
    print("\n  WARNING: these are POST-HOC subsets chosen after seeing the data.")
    print("  With 2 binary splits = 4 subsets, plus the 66 assets and 24 hours already")
    print("  scanned, the multiple-testing burden is large. None of these is a validated")
    print("  edge -- they are hypotheses that must be confirmed FORWARD on new data.")
    n = len(clean)
    w = int(clean.is_win.sum())
    print(f"\n  For the SPOT+unaligned subset (n={n}, WR={w/n*100:.2f}%):")
    print(f"    naive p(>BE) = {stats.binomtest(w, n, BE, alternative='greater').pvalue:.4f}")
    print(f"    Bonferroni over ~100 subsets examined: alpha = {0.05/100:.5f} -> "
          f"{'SURVIVES' if stats.binomtest(w,n,BE,alternative='greater').pvalue < 0.0005 else 'DOES NOT SURVIVE'}")

    hr("E. FORWARD-TEST SIZING — how many trades to validate the SPOT hypothesis")
    for tgt in [0.55, 0.56, 0.58, 0.60]:
        za, zb = 1.645, 0.842
        nn = ((za * math.sqrt(BE * (1 - BE)) + zb * math.sqrt(tgt * (1 - tgt))) / (tgt - BE)) ** 2
        print(f"  to prove true WR={tgt*100:.0f}% > BE {BE*100:.2f}%: n = {nn:,.0f} trades")
    print(f"\n  SPOT trades collected so far: {len(s_)} in 82.5 h "
          f"({len(s_)/82.5:.1f}/h) -> {2062/max(len(s_)/82.5,0.01):,.0f} h for the 55% test")

    hr("F. COST OF THE 66-ASSET SPRAY")
    per_asset = df.groupby("Asset").agg(n=("is_win", "size"), pnl=("pnl", "sum"))
    print(f"  assets traded: {len(per_asset)}")
    print(f"  assets with < 20 trades: {(per_asset.n < 20).sum()} "
          f"({(per_asset.n < 20).sum()/len(per_asset)*100:.0f}%), "
          f"their combined PnL = ${per_asset.loc[per_asset.n < 20, 'pnl'].sum():+,.0f}")
    print(f"  assets with >= 20 trades: {(per_asset.n >= 20).sum()}, "
          f"combined PnL = ${per_asset.loc[per_asset.n >= 20, 'pnl'].sum():+,.0f}")
    top5 = df[df.Asset.isin(df.Asset.value_counts().head(5).index)]
    w = int(top5.is_win.sum())
    print(f"\n  5 most-traded assets: n={len(top5)}  WR={w/len(top5)*100:.2f}%  "
          f"PnL=${top5.pnl.sum():+,.0f}")
    print("  ", list(df.Asset.value_counts().head(5).index))

    hr("G. DAILY EQUITY PATH ON THE REAL $50k DEPOSIT")
    df["day"] = df["Open Time"].dt.date
    eq = 50000 + df.pnl.cumsum()
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100
    print(f"  peak equity  : ${peak.max():,.0f}")
    print(f"  final equity : ${eq.iloc[-1]:,.0f}")
    print(f"  max drawdown : {dd.min():.2f}% of peak (${(eq-peak).min():,.0f})")
    print(f"  daily PnL    :")
    for d, s2 in df.groupby("day"):
        w = int(s2.is_win.sum())
        print(f"    {d}  n={len(s2):4d}  WR={w/len(s2)*100:5.2f}%  PnL=${s2.pnl.sum():+7,.0f}  "
              f"turnover=${s2.stake.sum():,.0f}")


if __name__ == "__main__":
    main()
