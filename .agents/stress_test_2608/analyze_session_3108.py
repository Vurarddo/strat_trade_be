"""Deep analysis of 31.08 OTC session after broker-truth fix."""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

CSV = Path("/Users/vlados/Downloads/31.08 - pocket_option_audit_merged.csv")

# From bot_status at start (30.08) — assets that should NOT trade
REJECTED_AT_START = {
    "USDCNH OTC",
    "USDEGP OTC",
    "SARCNY OTC",
    "EURTRY OTC",
    "USDPHP OTC",
    "OMRCNY OTC",
    "USDBDT OTC",
    "USDCLP OTC",
    "JODCNY OTC",
    "EURRUB OTC",
    "IRRUSD OTC",
    "NGNUSD OTC",
}

# Alternative naming styles in CSV
REJECTED_ALIASES = {
    "USD/CNH OTC",
    "USD/EGP OTC",
    "SAR/CNY OTC",
    "EUR/TRY OTC",
    "USD/PHP OTC",
    "OMR/CNY OTC",
    "USD/BDT OTC",
    "USD/CLP OTC",
    "JOD/CNY OTC",
    "EUR/RUB OTC",
    "IRR/USD OTC",
    "NGN/USD OTC",
}


def hr(t: str) -> None:
    print("\n" + "=" * 94)
    print(t)
    print("=" * 94)


def money(x: float | Decimal) -> str:
    return f"${float(x):+,.2f}"


def main() -> None:
    df = pd.read_csv(CSV)
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df["Close Time"] = pd.to_datetime(df["Close Time"], utc=True)
    df = df.sort_values("Open Time").reset_index(drop=True)
    df["conf"] = df["Confidence %"].astype(str).str.replace("%", "").astype(float)
    df["exp_sec"] = (df["Close Time"] - df["Open Time"]).dt.total_seconds()

    hr("1. SESSION SNAPSHOT")
    pnl = float(df["Broker Profit ($)"].sum())
    wins = int((df["Outcome"] == "WIN").sum())
    losses = int((df["Outcome"] == "LOSS").sum())
    draws = int((df["Outcome"] == "DRAW").sum())
    n = len(df)
    wr = wins / n * 100 if n else 0
    stake = float(df["Trade Amount ($)"].iloc[0])
    avg_win = float(df.loc[df["Outcome"] == "WIN", "Broker Profit ($)"].mean()) if wins else 0
    avg_loss = float(df.loc[df["Outcome"] == "LOSS", "Broker Profit ($)"].mean()) if losses else 0
    payout = avg_win / stake if stake and wins else 0
    be = 1 / (1 + payout) * 100 if payout else float("nan")
    print(f"  trades            : {n}  (W {wins} / L {losses} / D {draws})")
    print(f"  win rate          : {wr:.1f}%")
    print(f"  net PnL           : {money(pnl)}")
    print(f"  stake             : ${stake:.0f} flat")
    print(f"  avg win / loss    : {money(avg_win)} / {money(avg_loss)}")
    print(f"  implied payout    : {payout:.0%}  (break-even WR ≈ {be:.1f}%)")
    print(f"  session window    : {df['Open Time'].iloc[0]} → {df['Open Time'].iloc[-1]}")
    print(f"  duration          : {(df['Open Time'].iloc[-1] - df['Open Time'].iloc[0])}")
    print(f"  all bot trades    : {(df['Is Bot Trade'] == 'YES').all()}")
    print(f"  all OTC           : {df['Asset'].str.contains('OTC', case=False).all()}")

    hr("2. BROKER-TRUTH FIX VERIFICATION (primary goal of this restart)")
    ops = df["Open Price Source"].value_counts().to_dict()
    ss = df["Settlement Source"].value_counts().to_dict()
    slip0 = int((df["Slippage"] == 0).sum())
    price_match = int((df["Broker Open Price"] == df["Internal Open Price"]).sum())
    print(f"  Open Price Source : {ops}")
    print(f"  Settlement Source : {ss}")
    print(f"  Slippage == 0     : {slip0}/{n}")
    print(f"  broker open == internal open : {price_match}/{n}")
    if ops.get("broker", 0) == n and ss.get("broker", 0) == n and slip0 == n:
        print("  VERDICT: broker-truth is LIVE and working on every trade.")
    else:
        print("  VERDICT: FIX INCOMPLETE — some trades still use candle settlement.")

    hr("3. MICROSTRUCTURE / REJECTED ASSETS")
    traded = sorted(df["Asset"].unique())
    print(f"  unique assets traded ({len(traded)}):")
    for a in traded:
        sub = df[df["Asset"] == a]
        print(
            f"    {a:35s}  n={len(sub):2d}  "
            f"PnL={money(sub['Broker Profit ($)'].sum()):>10s}  "
            f"WR={ (sub['Outcome']=='WIN').mean()*100:5.1f}%"
        )
    leaked = [a for a in traded if a in REJECTED_AT_START or a in REJECTED_ALIASES]
    # also soft-match exotic names
    soft = []
    for a in traded:
        key = a.replace("/", "").replace(" ", "").upper()
        for r in REJECTED_AT_START | REJECTED_ALIASES:
            rk = r.replace("/", "").replace(" ", "").upper()
            if key == rk or key.startswith(rk[:6]):
                soft.append(a)
    soft = sorted(set(soft + leaked))
    if soft:
        print(f"  LEAK: previously-rejected assets appeared: {soft}")
    else:
        print("  OK: none of the 12 MICROSTRUCTURE-REJECTED assets from start status traded.")

    # unexpected asset classes (stocks etc not in forex status)
    forex_like = df["Asset"].str.contains("/", regex=False)
    non_fx = sorted(df.loc[~forex_like, "Asset"].unique())
    if non_fx:
        print(f"  NOTE: non-FX OTC assets also traded: {non_fx}")
        print("        These were NOT in the 30.08 bot_status snapshot — plan likely re-assigned.")

    hr("4. STRATEGY BREAKDOWN")
    for strat, g in df.groupby("Strategy Name"):
        w = int((g["Outcome"] == "WIN").sum())
        l = int((g["Outcome"] == "LOSS").sum())
        p = float(g["Broker Profit ($)"].sum())
        print(
            f"  {strat:35s}  n={len(g):2d}  W/L={w}/{l}  "
            f"WR={w/len(g)*100:5.1f}%  PnL={money(p):>10s}"
        )
        reasons = g["Signal Reason"].value_counts().to_dict()
        print(f"    reasons: {reasons}")

    hr("5. PER-ASSET × STRATEGY (where money went)")
    rows = []
    for (asset, strat), g in df.groupby(["Asset", "Strategy Name"]):
        w = int((g["Outcome"] == "WIN").sum())
        p = float(g["Broker Profit ($)"].sum())
        rows.append((p, asset, strat, len(g), w, len(g) - w))
    rows.sort()
    print(f"  {'PnL':>10s}  {'n':>3s}  {'W/L':>5s}  Asset / Strategy")
    for p, asset, strat, n_, w, l in rows:
        print(f"  {money(p):>10s}  {n_:3d}  {w}/{l:<3d}  {asset} / {strat}")

    hr("6. STREAKS & CIRCUIT BREAKER")
    outcomes = df["Outcome"].tolist()
    times = df["Open Time"].tolist()
    max_loss_streak = 0
    cur = 0
    streaks = []
    for o, t in zip(outcomes, times):
        if o == "LOSS":
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            if cur >= 2:
                streaks.append((cur, t))
            cur = 0
    if cur >= 2:
        streaks.append((cur, times[-1]))
    print(f"  max consecutive losses : {max_loss_streak}")
    print(f"  loss streaks ≥2        : {streaks if streaks else 'none'}")
    # gap between trades after losses — did pause fire?
    df["gap_sec"] = df["Open Time"].diff().dt.total_seconds()
    after_loss = []
    for i in range(1, len(df)):
        if df.loc[i - 1, "Outcome"] == "LOSS":
            after_loss.append(df.loc[i, "gap_sec"])
    if after_loss:
        s = pd.Series(after_loss)
        print(
            f"  gap after a LOSS (sec) : min={s.min():.0f}  "
            f"median={s.median():.0f}  max={s.max():.0f}"
        )
    # look for pause-like gaps (> 10 min) after loss streaks
    big_gaps = df[df["gap_sec"] >= 600][["Open Time", "gap_sec", "Asset", "Outcome"]]
    if len(big_gaps):
        print("  gaps ≥10 min (possible pause / quiet market):")
        for _, r in big_gaps.iterrows():
            prev_out = df.loc[r.name - 1, "Outcome"] if r.name > 0 else "?"
            print(
                f"    after {prev_out} → gap {r['gap_sec']/60:.1f}m  "
                f"next {r['Asset']} @ {r['Open Time']}"
            )

    hr("7. ENTRY TIMING / BAR-EDGE")
    print(f"  entry_second distribution: {df['Entry Second'].value_counts().sort_index().to_dict()}")
    print(f"  expiration seconds       : {sorted(df['exp_sec'].unique().tolist())}")
    late = df[df["Entry Second"] >= 10]
    print(f"  entries at sec ≥10       : {len(late)}/{n}")

    hr("8. DIRECTION & RSI / SIGNAL SANITY")
    print(f"  direction mix: {df['Direction'].value_counts().to_dict()}")
    # RSI vs direction for RSI strategy
    rsi_strat = df[df["Strategy Name"].str.contains("RSI", case=False)]
    if len(rsi_strat):
        print(f"\n  RSI-strategy trades ({len(rsi_strat)}):")
        print(
            f"  {'time':20s} {'dir':4s} {'RSI':>6s} {'Stoch':>6s} {'ADX':>5s} "
            f"{'out':5s} {'pnl':>6s} asset"
        )
        for _, r in rsi_strat.iterrows():
            print(
                f"  {str(r['Open Time'])[11:19]:20s} {r['Direction']:4s} "
                f"{r['RSI']:6.2f} {r['Stoch %K']:6.2f} {r['ADX']:5.2f} "
                f"{r['Outcome']:5s} {r['Broker Profit ($)']:6.0f} {r['Asset']}"
            )
        # check contradiction: PUT should be overbought, CALL oversold
        bad = []
        for _, r in rsi_strat.iterrows():
            params = ast.literal_eval(r["Strategy Parameters"]) if isinstance(r["Strategy Parameters"], str) else {}
            ob = float(params.get("rsi_overbought", 70))
            os_ = float(params.get("rsi_oversold", 30))
            if r["Direction"] == "PUT" and r["RSI"] < ob - 5:
                bad.append((r["Asset"], "PUT", r["RSI"], f"expected RSI≥~{ob}"))
            if r["Direction"] == "CALL" and r["RSI"] > os_ + 5:
                bad.append((r["Asset"], "CALL", r["RSI"], f"expected RSI≤~{os_}"))
        if bad:
            print(f"  RSI/direction soft mismatches: {bad}")
        else:
            print("  RSI direction alignment looks consistent with overbought/oversold intent.")

    hr("9. EQUITY PATH & DRAWDOWN (from $50,000)")
    start = 50_000.0
    eq = start
    peak = start
    max_dd = 0.0
    path = []
    for _, r in df.iterrows():
        eq += float(r["Broker Profit ($)"])
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd = max(max_dd, dd)
        path.append(eq)
    print(f"  start → end       : ${start:,.0f} → ${eq:,.2f}")
    print(f"  net               : {money(eq - start)}")
    print(f"  max drawdown      : {max_dd:.3f}%  (peak ${peak:,.2f})")
    print(f"  equity path       : {[round(x, 2) for x in path]}")

    # running WR
    running_w = 0
    print("\n  chronological tape:")
    print(
        f"  {'#':>3s} {'time':8s} {'dir':4s} {'out':5s} {'pnl':>6s} "
        f"{'eq':>10s} {'WR%':>5s} asset / strategy"
    )
    for i, r in df.iterrows():
        if r["Outcome"] == "WIN":
            running_w += 1
        wr_i = running_w / (i + 1) * 100
        print(
            f"  {i+1:3d} {str(r['Open Time'])[11:19]:8s} {r['Direction']:4s} "
            f"{r['Outcome']:5s} {r['Broker Profit ($)']:6.0f} "
            f"{path[i]:10.2f} {wr_i:5.1f} {r['Asset']} / {r['Strategy Name'][:22]}"
        )

    hr("10. EXPECTANCY")
    # EV per trade at observed payout
    ev = pnl / n if n else 0
    print(f"  EV per trade      : {money(ev)}")
    print(f"  EV / stake        : {ev/stake*100:.2f}%")
    # required WR at this payout
    print(f"  observed WR       : {wr:.1f}%  vs break-even {be:.1f}%")
    edge = wr - be
    print(f"  edge vs BE        : {edge:+.1f} pp")
    if n < 30:
        print(f"  NOTE: n={n} is too small for statistical significance. Treat as smoke test.")

    hr("11. VERDICT")
    checks = []
    checks.append(("broker-truth open+settle", ops.get("broker", 0) == n and ss.get("broker", 0) == n))
    checks.append(("slippage eliminated", slip0 == n))
    checks.append(("no rejected exotic FX leak", not soft))
    checks.append(("session profitable", pnl > 0))
    checks.append(("WR above break-even", wr > be))
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print()
    if pnl > 0 and wr > be:
        print("  Session is green, but sample is tiny. Do NOT scale stake yet.")
    elif pnl < 0:
        print("  Session is red. Inspect strategy/asset clusters above before continuing overnight.")
    print("  Keep OTC stake at $25 (probation). Next dump: same merged CSV + bot status if reassigned.")


if __name__ == "__main__":
    main()
