"""Verifies the single-restart hypothesis and checks how PnL in the export is derived."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV = Path("/Users/vlados/Downloads/28.08_29.08 - 27.08_28.08.csv")


def hr(t: str) -> None:
    print("\n" + "=" * 98)
    print(t)
    print("=" * 98)


def main() -> None:
    df = pd.read_csv(CSV)
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df.sort_values("Open Time").reset_index(drop=True)

    hr("ONE RESTART, OR CONTINUOUS STRATEGY DRIFT?")
    print("  If a single restart at time T explains everything, then for every asset")
    print("  that changed strategy, ALL trades on the old strategy are before T and")
    print("  ALL trades on the new one are after T. Testing T = 2026-08-29 14:30 UTC.\n")
    T = pd.Timestamp("2026-08-29 14:30", tz="UTC")
    clean = True
    for a, g in df.groupby("Asset"):
        g = g.sort_values("Open Time")
        before = set(g[g["Open Time"] < T]["Strategy Name"])
        after = set(g[g["Open Time"] >= T]["Strategy Name"])
        if len(before) > 1 or len(after) > 1:
            clean = False
            print(f"  {a:16s} MIXED  before={before or '-'}  after={after or '-'}")
    if clean:
        print("  Every asset used exactly one strategy before T and one after T.")
        print("  -> consistent with a single restart with a fresh auto-assign.")
        print("  -> dynamic_strategy_switching_enabled=false was respected.")

    print("\n  Assignment map on each side of the restart:")
    print(f"  {'asset':16s} {'before 14:30':32s} {'after 14:30':32s}")
    for a, g in df.groupby("Asset"):
        b = sorted(set(g[g["Open Time"] < T]["Strategy Name"]))
        af = sorted(set(g[g["Open Time"] >= T]["Strategy Name"]))
        mark = "  <-- changed" if b and af and b != af else ""
        print(f"  {a:16s} {(b[0] if b else '-'):32s} {(af[0] if af else '-'):32s}{mark}")

    hr("IS 'Broker Profit ($)' REAL, OR RECONSTRUCTED?")
    print("  xls_merger recomputes the outcome from broker open/close prices and")
    print("  assigns profit = amount * 0.92 for every win, rather than reading the")
    print("  payout the broker actually applied. Checking the export:\n")
    won = df[df["Outcome"] == "WIN"]
    ratios = (won["Broker Profit ($)"] / won["Trade Amount ($)"]).round(4)
    print(f"  distinct win payout ratios in the file: {sorted(ratios.unique())}")
    if len(ratios.unique()) == 1:
        print(f"  Every single win pays exactly {ratios.iloc[0] * 100:.0f}%.")
        print("  A real broker feed would show a spread of payouts across assets and")
        print("  times. This column is a model, not ground truth.")
    losses = df[df["Outcome"] == "LOSS"]
    lr = (losses["Broker Profit ($)"] / losses["Trade Amount ($)"]).round(4)
    print(f"  distinct loss ratios: {sorted(lr.unique())}  (a full stake loss, as expected)")

    print("\n  Consequence: the reported PnL is only correct if OTC really paid 92%.")
    print("  The plan set otc_min_payout_rate = 0.90, so anything the bot took should")
    print("  have been at or above 90% -- but that has to be confirmed against the")
    print("  actual demo balance, not this file.")
    pnl = df["Broker Profit ($)"].sum()
    print(f"\n  modelled PnL in this file: ${pnl:,.2f}")
    for p in (0.92, 0.85, 0.80):
        w = (df["Outcome"] == "WIN")
        alt = (df.loc[w, "Trade Amount ($)"] * p).sum() - df.loc[df["Outcome"] == "LOSS",
                                                                 "Trade Amount ($)"].sum()
        print(f"    if the true average payout were {p * 100:.0f}%: ${alt:,.2f}")

    hr("WHERE THE LOSS ACTUALLY CAME FROM")
    df["is_otc"] = df["Asset"].str.contains("OTC")
    for otc, g in df.groupby("is_otc"):
        w = int((g["Outcome"] == "WIN").sum())
        loss = int((g["Outcome"] == "LOSS").sum())
        d = w + loss
        turn = g["Trade Amount ($)"].sum()
        p = g["Broker Profit ($)"].sum()
        label = "OTC (stake $25)" if otc else "SPOT (stake $100)"
        print(f"  {label:20s} n={len(g):>4}  {w}W/{loss}L  WR={w / d * 100 if d else 0:.1f}%")
        print(f"  {'':20s} turnover ${turn:>8,.0f}   PnL ${p:>+9.2f}"
              f"   ROI {p / turn * 100:>+6.2f}%")
    spot = df[~df["is_otc"]]
    print(f"\n  {len(spot)} spot trades = {len(spot) / len(df) * 100:.0f}% of the count but "
          f"{abs(spot['Broker Profit ($)'].sum()) / abs(df['Broker Profit ($)'].sum()) * 100:.0f}%"
          " of the loss.")
    print("  The OTC probation multiplier capped OTC risk at $25, but spot kept the")
    print("  full $100 stake. Spot is the only place the restart to $100 really bit.")
    print("\n  Spot trades in detail:")
    print(f"  {'open time':22s} {'asset':10s} {'dir':5s} {'outcome':8s} {'pnl':>8}  strategy")
    for _, r in spot.iterrows():
        print(f"  {r['Open Time']:%Y-%m-%d %H:%M:%S}   {r['Asset']:10s} {r['Direction']:5s} "
              f"{r['Outcome']:8s} {r['Broker Profit ($)']:>+8.0f}  {r['Strategy Name']}")


if __name__ == "__main__":
    main()
