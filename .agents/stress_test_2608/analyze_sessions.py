"""Statistical stress-test of real Pocket Option bot sessions."""

from __future__ import annotations

import ast
import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DOWNLOADS = Path("/Users/vlados/Downloads")


def load() -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(DOWNLOADS / "Pocket Option*.csv"))):
        df = pd.read_csv(f)
        df["source_file"] = Path(f).name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df["Close Time"] = pd.to_datetime(df["Close Time"], utc=True)
    df["conf"] = df["Confidence %"].astype(str).str.rstrip("%").replace("nan", None).astype(float)
    df = df.drop_duplicates(subset=["Broker Order UUID"])
    df = df.sort_values("Open Time").reset_index(drop=True)
    df["hold_s"] = (df["Close Time"] - df["Open Time"]).dt.total_seconds()
    df["move"] = df["Broker Close Price"] - df["Broker Open Price"]
    df["move_abs"] = df["move"].abs()
    # normalized move in ATR units
    df["move_atr"] = df["move_abs"] / df["ATR"]
    df["is_win"] = df["Outcome"].eq("WIN")
    df["is_loss"] = df["Outcome"].eq("LOSS")
    return df


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def summary_block(df: pd.DataFrame, key: str, min_n: int = 1) -> pd.DataFrame:
    g = df.groupby(key)
    rows = []
    for name, sub in g:
        n = len(sub)
        if n < min_n:
            continue
        w = int(sub["is_win"].sum())
        loss = int(sub["is_loss"].sum())
        dec = w + loss
        wr = w / dec * 100 if dec else 0.0
        pnl = sub["Broker Profit ($)"].sum()
        lo, hi = wilson(w, dec)
        # binomial p-value vs 52.08% breakeven at 92% payout
        pval = stats.binomtest(w, dec, 1 / 1.92, alternative="greater").pvalue if dec else 1.0
        rows.append(
            {
                key: name,
                "n": n,
                "win": w,
                "wr%": round(wr, 1),
                "wr_lo95%": round(lo * 100, 1),
                "wr_hi95%": round(hi * 100, 1),
                "pnl$": round(pnl, 0),
                "p>BE": round(pval, 3),
            }
        )
    return pd.DataFrame(rows).sort_values("pnl$")


def main() -> None:
    df = load()
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    pd.set_option("display.max_rows", 200)

    n = len(df)
    w = int(df["is_win"].sum())
    l_ = int(df["is_loss"].sum())
    draws = n - w - l_
    dec = w + l_
    wr = w / dec * 100
    pnl = df["Broker Profit ($)"].sum()
    stake = df["Trade Amount ($)"].sum()

    print("=" * 100)
    print("1. GLOBAL")
    print("=" * 100)
    print(f"files          : {df['source_file'].nunique()}  {sorted(df['source_file'].unique())}")
    print(f"period         : {df['Open Time'].min()} -> {df['Open Time'].max()}")
    print(f"trades         : {n}   (win={w} loss={l_} draw/other={draws})")
    print(f"win rate       : {wr:.2f}%   decisive={dec}")
    lo, hi = wilson(w, dec)
    print(f"WR 95% CI      : [{lo*100:.2f}% .. {hi*100:.2f}%]")
    print(f"total staked   : ${stake:,.0f}")
    print(f"net PnL        : ${pnl:,.0f}   ROI on turnover = {pnl/stake*100:.2f}%")
    print(f"avg payout(win): {df.loc[df.is_win,'Broker Profit ($)'].mean()/100*100:.1f}%")
    print(f"EV per $1      : {pnl/stake:.4f}")

    # breakeven table
    print()
    print("Breakeven WR by payout:")
    for p in [0.75, 0.80, 0.82, 0.85, 0.88, 0.90, 0.92]:
        be = 1 / (1 + p) * 100
        ev = (wr / 100) * p - (1 - wr / 100)
        print(
            f"  payout {p*100:4.0f}%  ->  BE_WR={be:5.2f}%   "
            f"EV@currentWR({wr:.1f}%) = {ev:+.4f} $/$1  "
            f"({'PROFIT' if ev > 0 else 'LOSS'})"
        )

    # binomial test vs breakeven
    for p in [0.92, 0.85, 0.80]:
        be = 1 / (1 + p)
        pv = stats.binomtest(w, dec, be, alternative="greater").pvalue
        print(f"  binomial test WR > BE({p*100:.0f}%): p = {pv:.4f}")

    print()
    print("=" * 100)
    print("2. PER SESSION FILE")
    print("=" * 100)
    print(summary_block(df, "source_file").to_string(index=False))

    print()
    print("=" * 100)
    print("3. PER STRATEGY")
    print("=" * 100)
    print(summary_block(df, "Strategy Name").to_string(index=False))

    print()
    print("=" * 100)
    print("4. PER ASSET")
    print("=" * 100)
    print(summary_block(df, "Asset").to_string(index=False))

    print()
    print("=" * 100)
    print("5. PER DIRECTION")
    print("=" * 100)
    print(summary_block(df, "Direction").to_string(index=False))

    print()
    print("=" * 100)
    print("6. CONFIDENCE CALIBRATION (does confidence predict anything?)")
    print("=" * 100)
    print(summary_block(df, "conf").to_string(index=False))
    sub = df.dropna(subset=["conf"])
    r, p = stats.pointbiserialr(sub["is_win"].astype(int), sub["conf"])
    print(f"\npoint-biserial corr(conf, win) = {r:+.4f}   p = {p:.4f}")
    print(f"mean conf | WIN  = {sub.loc[sub.is_win,'conf'].mean():.2f}%")
    print(f"mean conf | LOSS = {sub.loc[sub.is_loss,'conf'].mean():.2f}%")
    tt = stats.ttest_ind(
        sub.loc[sub.is_win, "conf"], sub.loc[sub.is_loss, "conf"], equal_var=False
    )
    print(f"Welch t-test: t={tt.statistic:+.3f} p={tt.pvalue:.4f}")

    print()
    print("=" * 100)
    print("7. NOISE SENSITIVITY: |move| vs ATR  (how much of the outcome is coin-flip noise)")
    print("=" * 100)
    q = df["move_atr"].dropna()
    print(f"move/ATR percentiles: {q.describe(percentiles=[.1,.25,.5,.75,.9]).round(3).to_dict()}")
    for thr in [0.1, 0.25, 0.5, 1.0]:
        sub2 = df[df["move_atr"] <= thr]
        if len(sub2) == 0:
            continue
        ww = int(sub2["is_win"].sum())
        dd = int(sub2["is_win"].sum() + sub2["is_loss"].sum())
        print(
            f"  |move| <= {thr:4.2f}*ATR : n={len(sub2):3d}  WR={ww/dd*100 if dd else 0:5.1f}%  "
            f"PnL=${sub2['Broker Profit ($)'].sum():+,.0f}   "
            f"({len(sub2)/len(df)*100:.0f}% of all trades)"
        )
    # bucket by move_atr
    df["atr_bucket"] = pd.cut(
        df["move_atr"], [0, 0.25, 0.5, 1.0, 2.0, 100], labels=["<0.25", "0.25-0.5", "0.5-1", "1-2", ">2"]
    )
    print()
    print(summary_block(df.dropna(subset=["atr_bucket"]), "atr_bucket").to_string(index=False))

    print()
    print("=" * 100)
    print("8. SLIPPAGE ANALYSIS (normalized by ATR)")
    print("=" * 100)
    df["slip_atr"] = df["Slippage"] / df["ATR"]
    print(df["slip_atr"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).round(3).to_string())
    df["slip_bucket"] = pd.qcut(df["slip_atr"], 4, labels=["Q1_low", "Q2", "Q3", "Q4_high"], duplicates="drop")
    print()
    print(summary_block(df.dropna(subset=["slip_bucket"]), "slip_bucket").to_string(index=False))
    big = df[df["slip_atr"] > 1.0]
    print(f"\ntrades where slippage > 1 ATR: {len(big)} ({len(big)/len(df)*100:.1f}%)")
    if len(big):
        bw = int(big["is_win"].sum())
        bd = bw + int(big["is_loss"].sum())
        print(f"  their WR = {bw/bd*100:.1f}%  PnL = ${big['Broker Profit ($)'].sum():+,.0f}")

    print()
    print("=" * 100)
    print("9. HOURLY / SESSION BREAKDOWN (UTC)")
    print("=" * 100)
    df["hour"] = df["Open Time"].dt.hour
    print(summary_block(df, "hour").sort_values("hour").to_string(index=False))

    print()
    print("=" * 100)
    print("10. SIGNAL REASON / REGIME")
    print("=" * 100)
    print(summary_block(df, "Signal Reason").to_string(index=False))

    print()
    print("=" * 100)
    print("11. PARAMETER-SET DRIFT (same strategy, different params on different assets)")
    print("=" * 100)
    tmp = df.groupby("Strategy Name")["Strategy Parameters"].nunique()
    print(tmp.to_string())
    print("\nAre params tied to STRATEGY or to ASSET?")
    for s in df["Strategy Name"].unique():
        sub3 = df[df["Strategy Name"] == s]
        print(f"\n  {s}: {sub3['Strategy Parameters'].nunique()} distinct param-sets over {len(sub3)} trades")
        for pset, cnt in sub3["Strategy Parameters"].value_counts().items():
            try:
                d = ast.literal_eval(pset)
                keys = sorted(d.keys())
            except Exception:
                keys = ["?"]
            assets = sub3[sub3["Strategy Parameters"] == pset]["Asset"].unique()
            print(f"    n={cnt:3d} keys={keys}")
            print(f"         assets={list(assets)}")

    print()
    print("=" * 100)
    print("12. PARAM/STRATEGY MISMATCH DETECTION")
    print("=" * 100)
    mismatch = 0
    for _, row in df.iterrows():
        try:
            d = ast.literal_eval(row["Strategy Parameters"])
        except Exception:
            continue
        s = row["Strategy Name"].lower()
        keys = set(d.keys())
        # a pin-bar strategy should not carry ema/adx params, etc.
        if "pin-bar" in s or "pin_bar" in s:
            expected = {"swing_window", "min_wick_ratio"}
            if not expected & keys:
                mismatch += 1
        if "ema" in s or "ribbon" in s:
            if not ({"ema_fast", "ema_mid"} & keys):
                mismatch += 1
        if "rsi" in s and "stoch" in s:
            if not ({"rsi_period", "rsi_oversold"} & keys):
                mismatch += 1
    print(f"trades whose logged params do NOT match their strategy's own parameter schema: {mismatch} / {len(df)}")

    print()
    print("=" * 100)
    print("13. STRATEGY NAME DUPLICATION (aliasing)")
    print("=" * 100)
    print(df["Strategy Name"].value_counts().to_string())

    print()
    print("=" * 100)
    print("14. SEQUENTIAL / CLUSTERING: consecutive losses, concurrency, correlated entries")
    print("=" * 100)
    seq = df["Outcome"].tolist()
    max_l = cur = 0
    for o in seq:
        if o == "LOSS":
            cur += 1
            max_l = max(max_l, cur)
        else:
            cur = 0
    print(f"max consecutive losses observed: {max_l}")
    # runs test for independence
    wins = df["is_win"].astype(int).values
    runs = 1 + int((np.diff(wins) != 0).sum())
    n1, n2 = wins.sum(), len(wins) - wins.sum()
    exp_runs = 2 * n1 * n2 / (n1 + n2) + 1
    var_runs = (2 * n1 * n2 * (2 * n1 * n2 - n1 - n2)) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
    z = (runs - exp_runs) / math.sqrt(var_runs)
    print(f"Wald-Wolfowitz runs test: runs={runs} expected={exp_runs:.1f} z={z:+.3f} p={2*(1-stats.norm.cdf(abs(z))):.4f}")

    # overlapping trades
    overlaps = 0
    for i, r in df.iterrows():
        conc = df[(df["Open Time"] < r["Close Time"]) & (df["Close Time"] > r["Open Time"])]
        if len(conc) > 1:
            overlaps += 1
    print(f"trades that overlapped in time with >=1 other trade: {overlaps} ({overlaps/len(df)*100:.0f}%)")

    # same-currency concurrent exposure
    def legs(a: str) -> tuple[str, str]:
        a = a.replace(" OTC", "").strip()
        p = a.split("/")
        return (p[0], p[1]) if len(p) == 2 else (a, "")

    conflicts = []
    for i, r in df.iterrows():
        conc = df[
            (df["Open Time"] < r["Close Time"])
            & (df["Close Time"] > r["Open Time"])
            & (df.index != i)
        ]
        b1, q1 = legs(r["Asset"])
        for _, c in conc.iterrows():
            b2, q2 = legs(c["Asset"])
            shared = {b1, q1} & {b2, q2}
            if shared:
                conflicts.append((r["Asset"], c["Asset"], sorted(shared)[0]))
    print(f"concurrent trades sharing a currency leg: {len(conflicts)//2} pairs")
    if conflicts:
        from collections import Counter

        print("  top shared legs:", Counter(c[2] for c in conflicts).most_common(6))

    print()
    print("=" * 100)
    print("15. TIME-BETWEEN-TRADES / cooldown compliance")
    print("=" * 100)
    d = df["Open Time"].diff().dt.total_seconds().dropna()
    print(d.describe(percentiles=[0.1, 0.25, 0.5, 0.75]).round(1).to_string())
    print(f"gaps < 30s (global cooldown): {(d < 30).sum()}")
    print(f"gaps < 5s: {(d < 5).sum()}")

    print()
    print("=" * 100)
    print("16. MONTE-CARLO: is the observed PnL distinguishable from a fair coin?")
    print("=" * 100)
    rng = np.random.default_rng(42)
    sims = 20000
    payout = 0.92
    # simulate with true p = breakeven
    p_be = 1 / 1.92
    res = rng.binomial(dec, p_be, sims)
    sim_pnl = res * 100 * payout - (dec - res) * 100
    print(f"observed decisive trades = {dec}, observed wins = {w}, observed PnL = ${pnl:,.0f}")
    print(f"under H0 (p = breakeven 52.08%): mean PnL = ${sim_pnl.mean():,.0f}, sd = ${sim_pnl.std():,.0f}")
    print(f"P(sim PnL <= observed) = {(sim_pnl <= pnl).mean():.4f}")
    # required WR
    print()
    print("Sample size needed to prove a real edge:")
    for true_wr in [0.55, 0.57, 0.60]:
        # n for 95% power one-sided vs p0=0.5208
        p0 = p_be
        za, zb = 1.645, 0.842
        nn = ((za * math.sqrt(p0 * (1 - p0)) + zb * math.sqrt(true_wr * (1 - true_wr))) / (true_wr - p0)) ** 2
        print(f"  to detect true WR={true_wr*100:.0f}% vs BE 52.08% at 95%/80% power: n = {nn:.0f} trades")

    print()
    print("=" * 100)
    print("17. DRAWDOWN of the actual equity curve")
    print("=" * 100)
    eq = df["Broker Profit ($)"].cumsum()
    peak = eq.cummax()
    dd = eq - peak
    print(f"final equity delta : ${eq.iloc[-1]:+,.0f}")
    print(f"max drawdown ($)   : ${dd.min():,.0f}")
    print(f"max DD as % of 10k : {dd.min()/10000*100:.1f}%")
    print(f"longest losing streak: {max_l} trades = ${-max_l*100:,.0f}")

    print()
    print("=" * 100)
    print("18. INDICATOR COLUMN COVERAGE (are filters actually running?)")
    print("=" * 100)
    for c in ["RSI", "ADX", "ATR", "Stoch %K", "Confidence %", "Slippage"]:
        nn = df[c].notna().sum()
        print(f"  {c:14s}: {nn:4d}/{len(df)} populated ({nn/len(df)*100:5.1f}%)")

    print()
    print("=" * 100)
    print("19. RSI / STOCH AT ENTRY vs OUTCOME (are the filters informative?)")
    print("=" * 100)
    for col in ["RSI", "Stoch %K"]:
        sub4 = df.dropna(subset=[col])
        r2, p2 = stats.pointbiserialr(sub4["is_win"].astype(int), sub4[col])
        print(f"  corr({col}, win) = {r2:+.4f} p={p2:.3f}   "
              f"mean|WIN={sub4.loc[sub4.is_win,col].mean():.1f} mean|LOSS={sub4.loc[sub4.is_loss,col].mean():.1f}")
    # contrarian check: did PUT signals fire at low RSI?
    print()
    print("  Direction vs RSI sanity (PUT should fire at HIGH rsi for mean-reversion):")
    print(df.groupby("Direction")["RSI"].describe()[["count", "mean", "min", "max"]].round(1).to_string())
    print()
    print("  Mean-reversion strategies firing AGAINST their own premise:")
    mr = df[df["Strategy Name"].str.contains("Rsi|RSI|Bounce|Pin", case=False, na=False)]
    bad_put = mr[(mr["Direction"] == "PUT") & (mr["RSI"] < 50)]
    bad_call = mr[(mr["Direction"] == "CALL") & (mr["RSI"] > 50)]
    print(f"    PUT with RSI<50 : {len(bad_put)}  WR={bad_put['is_win'].mean()*100:.0f}%  PnL=${bad_put['Broker Profit ($)'].sum():+,.0f}")
    print(f"    CALL with RSI>50: {len(bad_call)} WR={bad_call['is_win'].mean()*100:.0f}%  PnL=${bad_call['Broker Profit ($)'].sum():+,.0f}")

    print()
    print("=" * 100)
    print("20. EXPIRATION / HOLD TIME")
    print("=" * 100)
    print(df["hold_s"].value_counts().to_string())
    print()
    print(summary_block(df, "hold_s").to_string(index=False))


if __name__ == "__main__":
    main()
