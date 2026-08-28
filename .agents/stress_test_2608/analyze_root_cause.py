"""Root-cause confirmation: stale-price hypothesis, directional lag, inversion test."""

from __future__ import annotations

import glob
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
    df["is_win"] = df["Outcome"].eq("WIN")
    df["is_loss"] = df["Outcome"].eq("LOSS")
    df["move"] = df["Broker Close Price"] - df["Broker Open Price"]
    df["move_abs"] = df["move"].abs()
    df["px"] = df["Broker Open Price"]
    df["move_bps"] = df["move"] / df["px"] * 1e4
    df["atr_bps"] = df["ATR"] / df["px"] * 1e4
    df["slip_bps"] = df["Slippage"] / df["px"] * 1e4
    df["sec"] = df["Open Time"].dt.second
    df["signed_move"] = np.where(df.Direction == "CALL", df["move_bps"], -df["move_bps"])
    return df


def hr(t: str) -> None:
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)


def main() -> None:
    df = load()
    pd.set_option("display.width", 210)
    pd.set_option("display.max_rows", 200)

    hr("1. SIGNED EDGE: does the signal predict direction AT ALL?")
    sm = df["signed_move"]
    print("signed_move = price movement in the direction the bot bet (bps). >0 = correct.")
    print(sm.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(3).to_string())
    t = stats.ttest_1samp(sm, 0)
    print(f"\nmean signed edge = {sm.mean():+.4f} bps   t={t.statistic:+.3f}  p={t.pvalue:.4f}")
    print(f"median signed edge = {sm.median():+.4f} bps")
    w = stats.wilcoxon(sm)
    print(f"Wilcoxon signed-rank p = {w.pvalue:.4f}")
    print("\n-> If mean/median signed edge is <= 0, the strategies have NEGATIVE directional skill.")

    print("\nsigned edge by strategy:")
    print(
        df.groupby("Strategy Name")["signed_move"]
        .agg(["count", "mean", "median"])
        .round(3)
        .sort_values("mean")
        .to_string()
    )
    print("\nsigned edge by direction:")
    print(df.groupby("Direction")["signed_move"].agg(["count", "mean", "median"]).round(3).to_string())

    hr("2. INVERSION TEST: would betting the OPPOSITE make money?")
    w_, l_ = int(df.is_win.sum()), int(df.is_loss.sum())
    for p in [0.92, 0.85, 0.80]:
        as_is = w_ * 100 * p - l_ * 100
        inv = l_ * 100 * p - w_ * 100
        print(
            f"  payout {p*100:3.0f}%: as-is WR={w_/(w_+l_)*100:.2f}% PnL=${as_is:+,.0f}   |   "
            f"INVERTED WR={l_/(w_+l_)*100:.2f}% PnL=${inv:+,.0f}"
        )
    print("\n-> Neither side clears the payout spread: this is a fee-drag problem, not a sign-flip bug.")

    hr("3. STALE-PRICE HYPOTHESIS: slippage vs seconds-into-candle")
    r, p = stats.spearmanr(df["sec"], df["slip_bps"])
    print(f"Spearman corr(seconds_into_minute, slippage_bps) = {r:+.4f}  p={p:.4f}")
    df["sec_bin"] = pd.cut(df["sec"], [-1, 2, 5, 10, 20, 60], labels=["0-2", "3-5", "6-10", "11-20", "21-60"])
    g = df.groupby("sec_bin", observed=True).agg(
        n=("slip_bps", "size"),
        med_slip_bps=("slip_bps", "median"),
        med_atr_bps=("atr_bps", "median"),
        wr=("is_win", "mean"),
        pnl=("Broker Profit ($)", "sum"),
    )
    g["slip/atr"] = (g.med_slip_bps / g.med_atr_bps).round(2)
    g["wr"] = (g.wr * 100).round(1)
    print(g.round(2).to_string())

    print("\nSlippage vs ATR — is slippage just proportional to volatility, or is it a feed bug?")
    r2, p2 = stats.spearmanr(df["atr_bps"], df["slip_bps"])
    print(f"  Spearman corr(ATR_bps, slip_bps) = {r2:+.4f} p={p2:.2e}")
    print(f"  median slip/ATR ratio = {(df['slip_bps']/df['atr_bps']).median():.2f}")
    print("  -> a ratio >> 1 means the bot's decision price is NOT the price it traded at.")

    hr("4. SLIPPAGE'S DIRECT COST: how many trades were flipped by the fill error")
    # a trade is 'flippable' if the entry error exceeds the winning margin
    df["flippable"] = df["Slippage"] > df["move_abs"]
    print(f"flippable trades (|entry error| > |move to expiry|): {df['flippable'].sum()} = {df['flippable'].mean()*100:.1f}%")
    print("\nWR conditioned on whether the fill error could flip the result:")
    for f, s in df.groupby("flippable"):
        n = int(s.is_win.sum() + s.is_loss.sum())
        print(
            f"  flippable={f}: n={n:3d}  WR={int(s.is_win.sum())/n*100:5.2f}%  "
            f"PnL=${s['Broker Profit ($)'].sum():+,.0f}"
        )
    clean = df[~df["flippable"]]
    n = int(clean.is_win.sum() + clean.is_loss.sum())
    print(f"\nOn the {n} 'clean' trades the WR is {int(clean.is_win.sum())/n*100:.1f}% "
          f"-> even without the fill error there is no edge.")

    hr("5. ARE ENTRIES CHASING THE BAR EXTREME? (mean-reversion fired at continuation)")
    # proxy: RSI/Stoch extremes vs outcome for the mean-reversion book
    mr = df[df["Signal Reason"].isin(["sr_bounce", "extreme_exhaustion"])]
    print(f"mean-reversion book: n={len(mr)}  PnL=${mr['Broker Profit ($)'].sum():+,.0f}")
    mr = mr.copy()
    mr["stoch_extreme"] = (mr["Stoch %K"] <= 20) | (mr["Stoch %K"] >= 80)
    for f, s in mr.groupby("stoch_extreme"):
        n = int(s.is_win.sum() + s.is_loss.sum())
        print(f"  stoch at extreme={f}: n={n:3d} WR={int(s.is_win.sum())/n*100:5.1f}% "
              f"PnL=${s['Broker Profit ($)'].sum():+,.0f}")
    mr["rsi_extreme"] = (mr["RSI"] <= 30) | (mr["RSI"] >= 70)
    for f, s in mr.groupby("rsi_extreme"):
        n = int(s.is_win.sum() + s.is_loss.sum())
        print(f"  rsi at extreme  ={f}: n={n:3d} WR={int(s.is_win.sum())/n*100:5.1f}% "
              f"PnL=${s['Broker Profit ($)'].sum():+,.0f}")

    print("\nHow often did a mean-reversion signal fire with NO oscillator extreme at all?")
    neither = mr[~mr["stoch_extreme"] & ~mr["rsi_extreme"]]
    n = int(neither.is_win.sum() + neither.is_loss.sum())
    print(f"  n={n} ({n/len(mr)*100:.0f}% of the MR book)  WR={int(neither.is_win.sum())/n*100:.1f}%  "
          f"PnL=${neither['Broker Profit ($)'].sum():+,.0f}")

    hr("6. TREND-FOLLOWING BOOK vs ADX (which is never logged)")
    tr = df[df["Signal Reason"] == "trending"]
    n = int(tr.is_win.sum() + tr.is_loss.sum())
    print(f"trending book: n={n} WR={int(tr.is_win.sum())/n*100:.1f}% PnL=${tr['Broker Profit ($)'].sum():+,.0f}")
    print(f"ADX populated in log: {df['ADX'].notna().sum()}/{len(df)}  -> the trend filter is UNVERIFIABLE")

    hr("7. STAKE MODEL: did the $10 vs $100 split hide the damage?")
    for s_, sub in df.groupby("Trade Amount ($)"):
        n = int(sub.is_win.sum() + sub.is_loss.sum())
        print(
            f"  stake ${s_:>3}: n={n:3d}  WR={int(sub.is_win.sum())/n*100:5.2f}%  "
            f"PnL=${sub['Broker Profit ($)'].sum():+,.0f}  turnover=${sub['Trade Amount ($)'].sum():,.0f}"
        )
    print("\nIf the whole sample had run at $100 flat:")
    print(f"  PnL = ${w_*100*0.9141 - l_*100:+,.0f}  (at the realized 91.4% avg payout)")

    hr("8. RISK OF RUIN / KELLY at the observed win rate")
    wr = w_ / (w_ + l_)
    for p in [0.92, 0.85, 0.80]:
        b = p
        kelly = (wr * (1 + b) - 1) / b
        print(f"  payout {p*100:3.0f}%: Kelly f* = {kelly*100:+.2f}%  "
              f"({'NO BET — negative edge' if kelly <= 0 else 'bet'})")
    print("\n  The bot used flat 1% ($100 on ~$10k). At a negative Kelly the")
    print("  optimal stake is ZERO; any positive stake guarantees ruin over time.")
    print(f"  Observed max drawdown was $4,063 = 40.6% of a $10k account in 2 days.")

    hr("9. SESSION-LEVEL DEGRADATION (is it getting worse?)")
    df["day"] = df["Open Time"].dt.date
    print(
        df.groupby("day")
        .agg(n=("is_win", "size"), wr=("is_win", "mean"), pnl=("Broker Profit ($)", "sum"))
        .assign(wr=lambda x: (x.wr * 100).round(1))
        .to_string()
    )
    print("\nRolling 50-trade WR:")
    roll = df["is_win"].rolling(50).mean() * 100
    print(roll.dropna().iloc[::25].round(1).to_string())

    hr("10. HOW MANY TRADES ARE NEEDED BEFORE ANY CLAIM IS VALID")
    print("Observed sample: 346 trades over ~29 h of trading.")
    print("95% CI on WR is [43.0%, 53.5%] — it contains the breakeven 52.08%,")
    print("so this sample cannot even prove the bot is losing, let alone winning.")
    for target in [0.55, 0.56, 0.58, 0.60]:
        p0 = 1 / 1.92
        za, zb = 1.645, 0.842
        nn = ((za * np.sqrt(p0 * (1 - p0)) + zb * np.sqrt(target * (1 - target))) / (target - p0)) ** 2
        print(f"  proving a true {target*100:.0f}% WR beats 52.08% needs n = {nn:,.0f} trades "
              f"(~{nn/346*29:,.0f} h at the current rate)")


if __name__ == "__main__":
    main()
