"""Deep-dive stress test: directional bias, slippage dominance, candle-sync, overfitting."""

from __future__ import annotations

import glob
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DOWNLOADS = Path("/Users/vlados/Downloads")


def load() -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(DOWNLOADS / "Pocket Option*.csv"))):
        d = pd.read_csv(f)
        d["source_file"] = Path(f).name
        frames.append(d)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df["Close Time"] = pd.to_datetime(df["Close Time"], utc=True)
    df["conf"] = df["Confidence %"].astype(str).str.rstrip("%").astype(float)
    df = df.sort_values("Open Time").reset_index(drop=True)
    df["move"] = df["Broker Close Price"] - df["Broker Open Price"]
    df["move_abs"] = df["move"].abs()
    df["is_win"] = df["Outcome"].eq("WIN")
    df["is_loss"] = df["Outcome"].eq("LOSS")
    df["stake"] = df["Trade Amount ($)"]
    df["payout"] = df["Broker Profit ($)"] / df["stake"]
    # relative move in basis points of price
    df["move_bps"] = df["move"] / df["Broker Open Price"] * 10000
    df["atr_bps"] = df["ATR"] / df["Broker Open Price"] * 10000
    df["slip_bps"] = df["Slippage"] / df["Broker Open Price"] * 10000
    return df


def hr(t: str) -> None:
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)


def main() -> None:
    df = load()
    pd.set_option("display.width", 210)
    pd.set_option("display.max_columns", 60)
    pd.set_option("display.max_rows", 300)

    hr("A. REAL PAYOUT DISTRIBUTION (what the broker actually paid)")
    winp = df.loc[df.is_win, "payout"]
    print(winp.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).round(4).to_string())
    print("\npayout value counts on WINS:")
    print((winp * 100).round(0).value_counts().sort_index().to_string())
    print("\nstake distribution:")
    print(df["stake"].value_counts().sort_index().to_string())
    print("\nBreakeven WR required by the payouts ACTUALLY received:")
    avg_p = winp.mean()
    print(f"  mean realized payout = {avg_p*100:.2f}%  ->  BE_WR = {1/(1+avg_p)*100:.2f}%")
    print(f"  worst realized payout = {winp.min()*100:.0f}%  ->  BE_WR = {1/(1+winp.min())*100:.2f}%")

    hr("B. DIRECTIONAL BIAS — the single biggest leak")
    call = df[df.Direction == "CALL"]
    put = df[df.Direction == "PUT"]
    cw, cn = int(call.is_win.sum()), int(call.is_win.sum() + call.is_loss.sum())
    pw, pn = int(put.is_win.sum()), int(put.is_win.sum() + put.is_loss.sum())
    print(f"CALL: n={cn}  WR={cw/cn*100:.2f}%  PnL=${call['Broker Profit ($)'].sum():+,.0f}")
    print(f"PUT : n={pn}  WR={pw/pn*100:.2f}%  PnL=${put['Broker Profit ($)'].sum():+,.0f}")
    chi = stats.chi2_contingency([[cw, cn - cw], [pw, pn - pw]])
    print(f"chi2 CALL vs PUT: chi2={chi.statistic:.3f} p={chi.pvalue:.4f}")
    print(f"Fisher exact p = {stats.fisher_exact([[cw, cn-cw],[pw, pn-pw]])[1]:.4f}")

    print("\nIs price systematically DRIFTING DOWN in the sample? (net move over all trades)")
    print(f"  mean signed move (bps of price) all trades : {df['move_bps'].mean():+.3f}")
    print(f"  median signed move (bps)                   : {df['move_bps'].median():+.3f}")
    print(f"  mean move on CALL entries (bps)            : {call['move_bps'].mean():+.3f}")
    print(f"  mean move on PUT entries (bps)             : {put['move_bps'].mean():+.3f}")
    tt = stats.ttest_1samp(df["move_bps"], 0)
    print(f"  t-test mean move != 0: t={tt.statistic:+.3f} p={tt.pvalue:.4f}")

    print("\nCALL/PUT WR per strategy:")
    rows = []
    for s, sub in df.groupby("Strategy Name"):
        for d, s2 in sub.groupby("Direction"):
            n = int(s2.is_win.sum() + s2.is_loss.sum())
            if n == 0:
                continue
            rows.append(
                {
                    "strategy": s,
                    "dir": d,
                    "n": n,
                    "wr%": round(int(s2.is_win.sum()) / n * 100, 1),
                    "pnl$": round(s2["Broker Profit ($)"].sum(), 0),
                }
            )
    print(pd.DataFrame(rows).to_string(index=False))

    hr("C. SLIPPAGE DOMINANCE — is execution error bigger than the edge?")
    df["slip_vs_move"] = df["Slippage"] / df["move_abs"].replace(0, np.nan)
    print(f"median |move| (bps of price) : {df['move_abs'].div(df['Broker Open Price']).mul(10000).median():.2f}")
    print(f"median slippage  (bps)       : {df['slip_bps'].median():.2f}")
    print(f"median ATR       (bps)       : {df['atr_bps'].median():.2f}")
    dom = (df["Slippage"] > df["move_abs"]).sum()
    print(f"\ntrades where SLIPPAGE > |price move to expiry| : {dom}/{len(df)} = {dom/len(df)*100:.1f}%")
    print("   -> in those trades the outcome is decided by execution error, not by the signal")
    sub = df[df["Slippage"] > df["move_abs"]]
    n = int(sub.is_win.sum() + sub.is_loss.sum())
    print(f"   their WR = {int(sub.is_win.sum())/n*100:.1f}%  PnL = ${sub['Broker Profit ($)'].sum():+,.0f}")
    sub2 = df[df["Slippage"] <= df["move_abs"]]
    n2 = int(sub2.is_win.sum() + sub2.is_loss.sum())
    print(f"   complement (slip <= move): n={n2} WR={int(sub2.is_win.sum())/n2*100:.1f}%  PnL=${sub2['Broker Profit ($)'].sum():+,.0f}")

    print("\nslippage in bps by asset (top offenders):")
    g = df.groupby("Asset").agg(
        n=("Slippage", "size"),
        slip_bps=("slip_bps", "median"),
        atr_bps=("atr_bps", "median"),
        pnl=("Broker Profit ($)", "sum"),
    )
    g["slip/atr"] = (g.slip_bps / g.atr_bps).round(2)
    print(g.sort_values("slip_bps", ascending=False).round(2).head(15).to_string())

    hr("D. CANDLE-BOUNDARY SYNC — does the bot enter mid-candle?")
    df["sec"] = df["Open Time"].dt.second
    print("entry second-of-minute distribution:")
    print(df["sec"].value_counts().sort_index().to_string())
    aligned = df[df["sec"] <= 2]
    mid = df[df["sec"] > 2]
    for name, s in [("aligned (sec<=2)", aligned), ("mid-candle (sec>2)", mid)]:
        n = int(s.is_win.sum() + s.is_loss.sum())
        if n:
            print(
                f"  {name:22s}: n={n:3d}  WR={int(s.is_win.sum())/n*100:5.1f}%  "
                f"PnL=${s['Broker Profit ($)'].sum():+,.0f}  ({n/len(df)*100:.0f}% of trades)"
            )
    print(f"\nuniformity chi2 of entry seconds (H0=random/unsynced): p={stats.chisquare(df['sec'].value_counts().reindex(range(60), fill_value=0))[1]:.2e}")
    print("mean seconds into the candle:", round(df["sec"].mean(), 1))

    hr("E. EXPIRY ALIGNMENT — 180s from a mid-candle entry never lands on a bar close")
    print("All trades held exactly 180s. If entry is at sec=37, the option settles at sec=37 of")
    print("the 3rd minute — i.e. INSIDE a forming candle, not at any M1 close the strategy modelled.")
    off = df[df["sec"] > 2]
    print(f"trades settling inside a forming bar: {len(off)}/{len(df)} = {len(off)/len(df)*100:.1f}%")

    hr("F. OVERFITTING FOOTPRINT — parameter/strategy explosion vs sample size")
    df["combo"] = df["Strategy Name"] + " | " + df["Strategy Parameters"]
    combos = df.groupby(["Asset", "combo"]).size()
    print(f"distinct (asset x strategy x params) cells : {len(combos)}")
    print(f"total trades                              : {len(df)}")
    print(f"mean trades per cell                      : {combos.mean():.2f}")
    print(f"cells with <5 trades                      : {(combos < 5).sum()} ({(combos<5).sum()/len(combos)*100:.0f}%)")
    print(f"cells with 1 trade                        : {(combos == 1).sum()}")
    print("\ndistinct assets traded:", df["Asset"].nunique())
    print("distinct strategies   :", df["Strategy Name"].nunique())
    print("distinct param-sets   :", df["Strategy Parameters"].nunique())
    print("\nMultiple-testing: with", len(combos), "cells tested at alpha=0.05,")
    print(f"  expected false 'winners' by chance = {len(combos)*0.05:.1f}")
    print(f"  Bonferroni-corrected alpha = {0.05/len(combos):.5f}")

    print("\nAssets that LOOK good but are pure small-sample noise (n<12, WR>60%):")
    rows = []
    for a, s in df.groupby("Asset"):
        n = int(s.is_win.sum() + s.is_loss.sum())
        if n == 0:
            continue
        wr = int(s.is_win.sum()) / n * 100
        if n < 12 and wr > 60:
            p = stats.binomtest(int(s.is_win.sum()), n, 1 / 1.92, alternative="greater").pvalue
            rows.append({"asset": a, "n": n, "wr%": round(wr, 1), "p_raw": round(p, 3),
                         "survives_bonferroni": p < 0.05 / len(combos)})
    print(pd.DataFrame(rows).to_string(index=False) if rows else "  none")

    hr("G. CONCURRENCY / QUEUE CONFLICTS in the live log")
    df["minute"] = df["Open Time"].dt.floor("min")
    per_min = df.groupby("minute").size()
    print("trades opened in the same minute:")
    print(per_min.value_counts().sort_index().to_string())
    multi = per_min[per_min > 1]
    print(f"\nminutes with >1 simultaneous entry: {len(multi)}")

    # opposite direction on correlated legs at the same time
    def legs(a: str) -> tuple[str, str]:
        a = a.replace(" OTC", "").strip().split("/")
        return (a[0], a[1]) if len(a) == 2 else (a[0], "")

    same_dir_same_leg = 0
    opposing = 0
    examples = []
    for i, r in df.iterrows():
        conc = df[(df["Open Time"] < r["Close Time"]) & (df["Close Time"] > r["Open Time"]) & (df.index > i)]
        b1, q1 = legs(r["Asset"])
        for _, c in conc.iterrows():
            b2, q2 = legs(c["Asset"])
            # net exposure direction of currency b
            def expo(base, quote, d):
                return {base: 1 if d == "CALL" else -1, quote: -1 if d == "CALL" else 1}

            e1, e2 = expo(b1, q1, r.Direction), expo(b2, q2, c.Direction)
            for cur in set(e1) & set(e2):
                if e1[cur] == e2[cur]:
                    same_dir_same_leg += 1
                    if len(examples) < 8:
                        examples.append(f"    DOUBLED {cur}: {r.Asset} {r.Direction} + {c.Asset} {c.Direction} @ {r['Open Time']:%H:%M}")
                else:
                    opposing += 1
    print(f"\nconcurrent trades DOUBLING exposure on the same currency : {same_dir_same_leg}")
    print(f"concurrent trades OPPOSING (self-hedge, guaranteed -stake): {opposing}")
    print("examples:")
    for e in examples:
        print(e)

    hr("H. REPEATED ENTRIES ON THE SAME ASSET (cooldown / revenge trading)")
    df["gap_asset"] = df.groupby("Asset")["Open Time"].diff().dt.total_seconds()
    ga = df["gap_asset"].dropna()
    print(ga.describe(percentiles=[0.1, 0.25, 0.5]).round(0).to_string())
    print(f"\nre-entries on same asset within 180s (while prev trade still LIVE): {(ga < 180).sum()}")
    print(f"re-entries within 360s: {(ga < 360).sum()}")
    quick = df[df["gap_asset"] < 360]
    n = int(quick.is_win.sum() + quick.is_loss.sum())
    if n:
        print(f"  their WR={int(quick.is_win.sum())/n*100:.1f}%  PnL=${quick['Broker Profit ($)'].sum():+,.0f}")

    # loss -> immediate re-entry
    df["prev_out"] = df["Outcome"].shift(1)
    after_loss = df[df["prev_out"] == "LOSS"]
    n = int(after_loss.is_win.sum() + after_loss.is_loss.sum())
    print(f"\ntrades taken right after a LOSS: n={n} WR={int(after_loss.is_win.sum())/n*100:.1f}% PnL=${after_loss['Broker Profit ($)'].sum():+,.0f}")
    after_win = df[df["prev_out"] == "WIN"]
    n = int(after_win.is_win.sum() + after_win.is_loss.sum())
    print(f"trades taken right after a WIN : n={n} WR={int(after_win.is_win.sum())/n*100:.1f}% PnL=${after_win['Broker Profit ($)'].sum():+,.0f}")

    hr("I. OTC vs SPOT")
    df["is_otc"] = df["Asset"].str.contains("OTC")
    for flag, s in df.groupby("is_otc"):
        n = int(s.is_win.sum() + s.is_loss.sum())
        lbl = "OTC" if flag else "SPOT"
        print(
            f"{lbl:5s}: n={n:3d}  WR={int(s.is_win.sum())/n*100:5.2f}%  "
            f"PnL=${s['Broker Profit ($)'].sum():+,.0f}  "
            f"median ATR(bps)={s['atr_bps'].median():.2f}  median slip(bps)={s['slip_bps'].median():.2f}"
        )
    otc, spot = df[df.is_otc], df[~df.is_otc]
    print(f"\nshare of turnover on OTC: {otc['stake'].sum()/df['stake'].sum()*100:.0f}%")
    # exotic OTC
    exotic = df[df["Asset"].str.contains("MAD|KES|TND|YER|ARS|SGD|IDR|BHD|OMR|QAR", na=False)]
    n = int(exotic.is_win.sum() + exotic.is_loss.sum())
    print(f"\nEXOTIC/synthetic OTC pairs (MAD,KES,TND,YER,ARS,SGD): n={n} "
          f"WR={int(exotic.is_win.sum())/n*100:.1f}% PnL=${exotic['Broker Profit ($)'].sum():+,.0f}")
    print("   assets:", sorted(exotic['Asset'].unique()))

    hr("J. NOISE FLOOR — how many trades were sub-noise coin flips")
    # a 180s binary needs |move| > 0. Compare move to a tick-level noise proxy
    df["move_over_atr"] = df["move_abs"] / df["ATR"]
    tiny = df[df["move_over_atr"] < 0.15]
    n = int(tiny.is_win.sum() + tiny.is_loss.sum())
    print(f"trades resolved by < 0.15 ATR of movement: {len(tiny)} ({len(tiny)/len(df)*100:.0f}%)")
    if n:
        print(f"  WR={int(tiny.is_win.sum())/n*100:.1f}% PnL=${tiny['Broker Profit ($)'].sum():+,.0f}")
    print("\nATR(bps) distribution — is the bot trading dead, illiquid quotes?")
    print(df["atr_bps"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_string())
    lowvol = df[df["atr_bps"] < df["atr_bps"].quantile(0.25)]
    n = int(lowvol.is_win.sum() + lowvol.is_loss.sum())
    print(f"lowest-volatility quartile: n={n} WR={int(lowvol.is_win.sum())/n*100:.1f}% PnL=${lowvol['Broker Profit ($)'].sum():+,.0f}")

    hr("K. WHAT-IF: EV of the SAME trades at lower payouts")
    w = int(df.is_win.sum())
    l_ = int(df.is_loss.sum())
    for p in [0.92, 0.88, 0.85, 0.82, 0.80, 0.75]:
        pnl = w * 100 * p - l_ * 100
        print(f"  payout {p*100:3.0f}% : PnL = ${pnl:+,.0f}  on ${(w+l_)*100:,.0f} staked  "
              f"-> ROI {pnl/((w+l_)*100)*100:+.2f}%")
    print("\nRequired WR to break even, and how far the bot is from it:")
    wr = w / (w + l_) * 100
    for p in [0.92, 0.85, 0.80, 0.75]:
        be = 1 / (1 + p) * 100
        print(f"  payout {p*100:3.0f}% : need {be:.2f}%, have {wr:.2f}%, gap = {wr-be:+.2f} pp")

    hr("L. CONFIDENCE IS ANTI-CORRELATED WITH RESULT AT THE TOP END")
    for c in sorted(df["conf"].unique()):
        s = df[df.conf == c]
        n = int(s.is_win.sum() + s.is_loss.sum())
        lo = stats.binomtest(int(s.is_win.sum()), n).proportion_ci(0.95).low * 100 if n else 0
        print(f"  conf={c:.0f}%  n={n:3d}  WR={int(s.is_win.sum())/n*100:5.1f}%  "
              f"PnL=${s['Broker Profit ($)'].sum():+,.0f}   95%CI_low={lo:.1f}%")
    hi = df[df.conf >= 85]
    lo_ = df[df.conf < 85]
    a, b = int(hi.is_win.sum()), int(hi.is_win.sum() + hi.is_loss.sum())
    c_, d_ = int(lo_.is_win.sum()), int(lo_.is_win.sum() + lo_.is_loss.sum())
    print(f"\nconf>=85%: n={b} WR={a/b*100:.1f}%   conf<85%: n={d_} WR={c_/d_*100:.1f}%")
    print(f"Fisher p = {stats.fisher_exact([[a, b-a],[c_, d_-c_]])[1]:.4f}  "
          "(if the score worked, high-conf WR would be HIGHER)")


if __name__ == "__main__":
    main()
