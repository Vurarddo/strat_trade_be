"""Analyses the 28-29.08 live session that ran with the new execution gates."""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from scipy import stats

CSV = Path("/Users/vlados/Downloads/28.08_29.08 - 27.08_28.08.csv")
PLAN = Path(".agents/stress_test_2608/live_plan.json")


def hr(t: str) -> None:
    print("\n" + "=" * 98)
    print(t)
    print("=" * 98)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - m) / d, (c + m) / d


def main() -> None:
    df = pd.read_csv(CSV)
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df["Close Time"] = pd.to_datetime(df["Close Time"], utc=True)
    df = df.sort_values("Open Time").reset_index(drop=True)

    hr("0. SCOPE")
    print(f"  rows            : {len(df)}")
    print(f"  bot trades      : {(df['Is Bot Trade'] == 'YES').sum()}")
    print(f"  window          : {df['Open Time'].min()}  ..  {df['Open Time'].max()}")
    span = (df["Open Time"].max() - df["Open Time"].min()).total_seconds() / 3600
    print(f"  span            : {span:.1f} h")
    bot = df[df["Is Bot Trade"] == "YES"].copy()
    if len(bot) < len(df):
        print(f"  NOTE: {len(df) - len(bot)} manual trades excluded from the stats below")

    hr("1. HEADLINE RESULT")
    n = len(bot)
    wins = (bot["Outcome"] == "WIN").sum()
    losses = (bot["Outcome"] == "LOSS").sum()
    draws = (bot["Outcome"] == "DRAW").sum()
    pnl = bot["Broker Profit ($)"].sum()
    turnover = bot["Trade Amount ($)"].sum()
    decided = wins + losses
    wr = wins / decided if decided else 0.0

    print(f"  trades          : {n}   (WIN {wins} / LOSS {losses} / DRAW {draws})")
    print(f"  net PnL         : ${pnl:,.2f}")
    print(f"  turnover        : ${turnover:,.2f}")
    print(f"  ROI on turnover : {pnl / turnover * 100:+.2f}%")
    print(f"  win rate        : {wr * 100:.2f}%  (on {decided} decided trades)")

    won = bot[bot["Outcome"] == "WIN"]
    payout = (won["Broker Profit ($)"] / won["Trade Amount ($)"]).mean() if len(won) else 0.0
    be = 1 / (1 + payout)
    print(f"  avg payout      : {payout * 100:.2f}%")
    print(f"  break-even WR   : {be * 100:.2f}%")
    print(f"  edge            : {(wr - be) * 100:+.2f} pp")

    lo, hi = wilson(int(wins), int(decided))
    print(f"  95% CI on WR    : [{lo * 100:.1f}%, {hi * 100:.1f}%]")
    if decided:
        p_low = stats.binomtest(int(wins), int(decided), be, alternative="less").pvalue
        p_high = stats.binomtest(int(wins), int(decided), be, alternative="greater").pvalue
        print(f"  p(WR < break-even) = {p_low:.4f}    p(WR > break-even) = {p_high:.4f}")
        if p_low < 0.05:
            print("  -> statistically significant LOSING edge")
        elif p_high < 0.05:
            print("  -> statistically significant WINNING edge")
        else:
            print("  -> indistinguishable from a coin flip at this sample size;")
            print(f"     the CI still spans {(hi - lo) * 100:.0f} pp, so nothing is proven either way")

    hr("2. STAKE -- DID THE OTC MULTIPLIER APPLY?")
    bot["is_otc"] = bot["Asset"].str.contains("OTC")
    print("  stake sizes seen:")
    for (otc, amt), cnt in sorted(
        Counter(zip(bot["is_otc"], bot["Trade Amount ($)"], strict=False)).items()
    ):
        tag = "OTC " if otc else "spot"
        print(f"    {tag} ${amt:>7.2f} x {cnt}")
    otc_amts = sorted(bot[bot["is_otc"]]["Trade Amount ($)"].unique())
    print(f"\n  Base stake was $100, otc_stake_multiplier 0.25 -> expected $25.00 on OTC.")
    print(f"  Observed OTC stakes: {otc_amts}")
    if otc_amts == [25.0]:
        print("  CONFIRMED: every OTC trade was sized down by the probation multiplier.")

    hr("3. BAR-EDGE GUARD -- DID IT HOLD?")
    bot["entry_second"] = bot["Open Time"].dt.second
    guard = 3
    viol = bot[(bot["entry_second"] < guard) | (bot["entry_second"] > 60 - guard)]
    print(f"  bar_edge_guard_seconds = {guard} -> entries must land in seconds [{guard}, {60 - guard}]")
    print(f"  violations: {len(viol)} of {n}")
    print(f"  entry-second range: {bot['entry_second'].min()} .. {bot['entry_second'].max()}")
    hist = Counter(bot["entry_second"] // 10 * 10)
    print("\n  distribution by 10-second bucket:")
    for b in sorted(hist):
        print(f"    :{b:02d}-:{b + 9:02d}  {'#' * hist[b]} ({hist[b]})")
    if len(viol) == 0:
        print("\n  CONFIRMED: no entry landed on a bar boundary.")

    hr("4. PER-ASSET BREAKDOWN")
    rows = []
    for asset, g in bot.groupby("Asset"):
        w = (g["Outcome"] == "WIN").sum()
        loss = (g["Outcome"] == "LOSS").sum()
        d = w + loss
        rows.append(
            {
                "asset": asset,
                "n": len(g),
                "win": w,
                "loss": loss,
                "wr": w / d * 100 if d else 0.0,
                "pnl": g["Broker Profit ($)"].sum(),
                "strategies": ", ".join(sorted(g["Strategy Name"].unique())),
            }
        )
    tbl = pd.DataFrame(rows).sort_values("pnl")
    print(f"  {'asset':16s} {'n':>3} {'W':>3} {'L':>3} {'WR%':>6} {'PnL$':>9}  strategy")
    for _, r in tbl.iterrows():
        print(
            f"  {r['asset']:16s} {r['n']:>3} {r['win']:>3} {r['loss']:>3} "
            f"{r['wr']:>6.1f} {r['pnl']:>+9.2f}  {r['strategies']}"
        )
    print(f"\n  assets traded: {len(tbl)}")
    print(f"  losing assets: {(tbl['pnl'] < 0).sum()}   winning: {(tbl['pnl'] > 0).sum()}")
    conc = tbl.nsmallest(3, "pnl")["pnl"].sum()
    print(f"  worst 3 assets contribute ${conc:,.2f} of the ${pnl:,.2f} total")

    hr("5. PER-STRATEGY BREAKDOWN")
    print(f"  {'strategy':32s} {'n':>4} {'W':>4} {'L':>4} {'WR%':>7} {'PnL$':>10} {'p(losing)':>10}")
    for name, g in bot.groupby("Strategy Name"):
        w = int((g["Outcome"] == "WIN").sum())
        loss = int((g["Outcome"] == "LOSS").sum())
        d = w + loss
        wr_s = w / d * 100 if d else 0.0
        p = stats.binomtest(w, d, be, alternative="less").pvalue if d else 1.0
        print(
            f"  {name:32s} {len(g):>4} {w:>4} {loss:>4} {wr_s:>7.1f} "
            f"{g['Broker Profit ($)'].sum():>+10.2f} {p:>10.4f}"
        )

    hr("6. SIGNAL REASON / REGIME")
    for reason, g in bot.groupby("Signal Reason"):
        w = int((g["Outcome"] == "WIN").sum())
        loss = int((g["Outcome"] == "LOSS").sum())
        d = w + loss
        print(
            f"  {reason:28s} n={len(g):>4}  WR={w / d * 100 if d else 0:>5.1f}%  "
            f"PnL=${g['Broker Profit ($)'].sum():>+9.2f}"
        )

    hr("7. DOES THE CSV'S RSI COLUMN MATCH THE STRATEGY'S ENTRY RULE?")
    print("  The bot writes the RSI column from _extract_snapshot(), which hardcodes")
    print("  a 14-period SIMPLE average. RsiStochasticExtremeStrategy computes RSI with")
    print("  the `ta` library (Wilder smoothing) at the period in its parameters.")
    print("  So the two numbers are different indicators. Checking the damage:\n")

    rsi_trades = bot[bot["Strategy Name"] == "RSI + Stoch Extreme Scalp"].copy()
    bad = 0
    periods = Counter()
    for _, r in rsi_trades.iterrows():
        try:
            p = ast.literal_eval(r["Strategy Parameters"])
        except Exception:
            continue
        periods[p.get("rsi_period")] += 1
        ob, os_ = p.get("rsi_overbought", 75), p.get("rsi_oversold", 25)
        rsi_v = r["RSI"]
        if r["Direction"] == "PUT" and rsi_v < ob:
            bad += 1
        elif r["Direction"] == "CALL" and rsi_v > os_:
            bad += 1
    print(f"  rsi_period actually used: {dict(periods)}")
    print(f"  RSI+Stoch trades: {len(rsi_trades)}")
    print(f"  trades whose logged RSI CONTRADICTS the entry threshold: {bad}")
    print("\n  Those are not bad entries -- they are bad logs. The RSI column cannot be")
    print("  used to audit this strategy until the snapshot uses the strategy's own")
    print("  period and smoothing.")

    print("\n  The Stoch %K column IS comparable (both use a raw 14-period window).")
    stoch_bad = 0
    for _, r in rsi_trades.iterrows():
        try:
            p = ast.literal_eval(r["Strategy Parameters"])
        except Exception:
            continue
        sob, sos = p.get("stoch_overbought", 80), p.get("stoch_oversold", 20)
        sk = r["Stoch %K"]
        if r["Direction"] == "PUT" and sk < sob:
            stoch_bad += 1
        elif r["Direction"] == "CALL" and sk > sos:
            stoch_bad += 1
    print(f"  trades whose logged Stoch %K contradicts the threshold: {stoch_bad}")
    if stoch_bad == 0:
        print("  -> the stochastic half of the entry rule fired correctly every time.")

    hr("8. ADX TREND GUARD (max_adx_trend)")
    viol_adx = []
    for _, r in rsi_trades.iterrows():
        try:
            p = ast.literal_eval(r["Strategy Parameters"])
        except Exception:
            continue
        cap = p.get("max_adx_trend")
        if cap is not None and pd.notna(r["ADX"]) and r["ADX"] >= cap:
            viol_adx.append((r["Asset"], r["ADX"], cap, r["Outcome"]))
    print(f"  RSI+Stoch trades opened with ADX at or above their own cap: {len(viol_adx)}")
    for a, adx_v, cap, out in viol_adx[:15]:
        print(f"    {a:16s} ADX={adx_v:>6.2f} >= cap {cap}   -> {out}")
    if viol_adx:
        w = sum(1 for x in viol_adx if x[3] == "WIN")
        print(f"\n  outcome of those: {w} WIN / {len(viol_adx) - w} LOSS")
        print("  The strategy suppresses the signal when ADX >= cap, so these should not")
        print("  exist. The logged ADX is a 14-period `ta` ADX -- the same one the strategy")
        print("  uses -- so unlike RSI this is a genuine discrepancy worth chasing.")

    hr("9. PLAN vs REALITY -- WHICH STRATEGY ACTUALLY RAN")
    plan = json.loads(PLAN.read_text())["plan"]
    assigned = {a["asset"]: a["strategy_name"] for a in plan["assignments"]}

    def to_plan_key(broker_asset: str) -> str:
        s = broker_asset.replace("/", "").replace(" OTC", "_otc")
        return s

    mismatch = []
    for asset, g in bot.groupby("Asset"):
        key = to_plan_key(asset)
        want = assigned.get(key)
        got = sorted(g["Strategy Name"].unique())
        if want is None:
            mismatch.append((asset, key, "NOT IN PLAN", got))
        elif want not in got or len(got) > 1:
            mismatch.append((asset, key, want, got))
    if not mismatch:
        print("  every traded asset ran the strategy the plan assigned to it.")
    else:
        print(f"  {len(mismatch)} asset(s) did not run their planned strategy:\n")
        for asset, key, want, got in mismatch:
            print(f"    {asset:16s} (plan key {key:14s})")
            print(f"        plan : {want}")
            print(f"        ran  : {', '.join(got)}")

    hr("10. SLIPPAGE")
    sl = bot["Slippage"].dropna()
    print(f"  mean {sl.mean():.5f}   median {sl.median():.5f}   max {sl.max():.5f}")
    bot["slip_vs_atr"] = bot["Slippage"] / bot["ATR"]
    sv = bot["slip_vs_atr"].dropna()
    print(f"  slippage / ATR: mean {sv.mean():.2f}   median {sv.median():.2f}   max {sv.max():.2f}")
    print("\n  slippage as a fraction of ATR, by outcome:")
    for out, g in bot.groupby("Outcome"):
        print(f"    {out:6s} n={len(g):>4}  median slip/ATR = {g['slip_vs_atr'].median():.2f}")
    hi_slip = bot[bot["slip_vs_atr"] > 1.0]
    print(f"\n  trades entered with slippage larger than one ATR: {len(hi_slip)} of {n}")
    if len(hi_slip):
        hw = (hi_slip["Outcome"] == "WIN").sum()
        hl = (hi_slip["Outcome"] == "LOSS").sum()
        print(f"    their record: {hw}W/{hl}L  PnL ${hi_slip['Broker Profit ($)'].sum():+,.2f}")

    hr("11. TIMELINE -- WHERE THE MONEY WENT")
    bot["hour"] = bot["Open Time"].dt.floor("h")
    cum = 0.0
    print(f"  {'hour (UTC)':18s} {'n':>3} {'W':>3} {'L':>3} {'PnL$':>9} {'cum$':>10}")
    for h, g in bot.groupby("hour"):
        w = int((g["Outcome"] == "WIN").sum())
        loss = int((g["Outcome"] == "LOSS").sum())
        p = g["Broker Profit ($)"].sum()
        cum += p
        print(f"  {h:%Y-%m-%d %H:00}   {len(g):>3} {w:>3} {loss:>3} {p:>+9.2f} {cum:>+10.2f}")

    hr("12. CONSECUTIVE LOSSES / DEGRADATION GUARD")
    streak = mx = 0
    for o in bot["Outcome"]:
        if o == "LOSS":
            streak += 1
            mx = max(mx, streak)
        elif o == "WIN":
            streak = 0
    print(f"  longest global losing streak: {mx}  (plan cap max_consecutive_losses = 3)")
    per = defaultdict(lambda: [0, 0])
    for asset, g in bot.groupby("Asset"):
        s = m = 0
        for o in g.sort_values("Open Time")["Outcome"]:
            if o == "LOSS":
                s += 1
                m = max(m, s)
            elif o == "WIN":
                s = 0
        per[asset] = m
    worst = sorted(per.items(), key=lambda x: -x[1])[:8]
    print("  longest per-asset losing streak (plan cap per_asset_max_consecutive_losses = 2):")
    for a, m in worst:
        flag = "  <- should have muted for 60 min" if m >= 2 else ""
        print(f"    {a:16s} {m}{flag}")


if __name__ == "__main__":
    main()
