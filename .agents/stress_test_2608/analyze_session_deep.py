"""Second pass: slippage economics, circuit-breaker behaviour, restart detection."""

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
    df["move"] = (df["Broker Close Price"] - df["Broker Open Price"]).abs()
    df["move_atr"] = df["move"] / df["ATR"]
    df["slip_atr"] = df["Slippage"] / df["ATR"]

    hr("A. SLIPPAGE vs THE MOVE YOU ARE BETTING ON")
    print("  A binary option pays if price ends on the right side of the ENTRY price.")
    print("  So what matters is slippage measured against the size of the move that")
    print("  decides the trade.\n")
    print(f"  median |close - open| over 3 min : {df['move'].median():.5f}"
          f"  ({df['move_atr'].median():.2f} ATR)")
    print(f"  median entry slippage            : {df['Slippage'].median():.5f}"
          f"  ({df['slip_atr'].median():.2f} ATR)")
    ratio = df["Slippage"].median() / df["move"].median()
    print(f"\n  slippage / decisive move = {ratio:.2f}x")
    worse = (df["Slippage"] > df["move"]).sum()
    print(f"  trades where slippage EXCEEDED the whole 3-minute move: {worse} of {len(df)}"
          f"  ({worse / len(df) * 100:.0f}%)")
    print("\n  When the entry error is bigger than the move being predicted, the")
    print("  outcome is decided by the fill, not by the signal.")

    print("\n  Per-asset, to rule out a single bad feed:")
    print(f"  {'asset':16s} {'n':>3} {'med slip':>10} {'med move':>10} {'slip/move':>10}")
    for a, g in df.groupby("Asset"):
        if len(g) < 3:
            continue
        ms, mm = g["Slippage"].median(), g["move"].median()
        print(f"  {a:16s} {len(g):>3} {ms:>10.5f} {mm:>10.5f} {ms / mm:>10.2f}")

    hr("B. IS SLIPPAGE PRICE-SCALE ARTEFACT OR REAL?")
    df["slip_bps"] = df["Slippage"] / df["Broker Open Price"] * 10000
    print("  slippage in basis points of price:")
    print(f"    median {df['slip_bps'].median():.2f} bps   mean {df['slip_bps'].mean():.2f} bps"
          f"   max {df['slip_bps'].max():.2f} bps")
    print("\n  For a 3-minute FX bet, a few bps is normal; tens of bps is not.")
    print(f"  {'asset':16s} {'n':>3} {'med bps':>9} {'max bps':>9}")
    for a, g in df.groupby("Asset"):
        if len(g) < 3:
            continue
        print(f"  {a:16s} {len(g):>3} {g['slip_bps'].median():>9.2f} {g['slip_bps'].max():>9.2f}")

    hr("C. CIRCUIT BREAKER -- 11 LOSSES IN A ROW WITH A CAP OF 3")
    print("  Rule: 3 consecutive losses -> PAUSE for 15 min.")
    print("  But the code also auto-unpauses on the first WIN that settles:\n")
    print("      elif outcome == TradeOutcome.WIN:")
    print("          self.consecutive_losses = 0")
    print("          if self.status == BotStatus.PAUSED and self.paused_until:")
    print("              self.status = BotStatus.RUNNING   # pause cancelled\n")
    print("  With max_concurrent_trades = 3 there are up to 2 other trades in flight")
    print("  when the breaker fires. Any one of them settling as a WIN cancels the")
    print("  pause immediately.\n")

    streak, start = 0, None
    runs = []
    for _, r in df.iterrows():
        if r["Outcome"] == "LOSS":
            if streak == 0:
                start = r["Open Time"]
            streak += 1
        else:
            if streak >= 3:
                runs.append((start, streak))
            streak = 0
    if streak >= 3:
        runs.append((start, streak))
    print(f"  losing runs of 3 or more: {len(runs)}")
    for st, ln in runs:
        print(f"    {st:%Y-%m-%d %H:%M:%S} UTC   length {ln}")

    longest = df.copy()
    s, best, bi = 0, 0, 0
    for i, o in enumerate(longest["Outcome"]):
        if o == "LOSS":
            s += 1
            if s > best:
                best, bi = s, i
        elif o == "WIN":
            s = 0
    seg = longest.iloc[bi - best + 1 : bi + 1]
    print(f"\n  The worst run ({best} losses) in detail:")
    print(f"  {'open time':22s} {'asset':14s} {'dir':5s} {'amt':>6} {'gap':>7}")
    prev = None
    for _, r in seg.iterrows():
        gap = "" if prev is None else f"{(r['Open Time'] - prev).total_seconds() / 60:.1f}m"
        print(f"  {r['Open Time']:%Y-%m-%d %H:%M:%S}   {r['Asset']:14s} "
              f"{r['Direction']:5s} {r['Trade Amount ($)']:>6} {gap:>7}")
        prev = r["Open Time"]
    dur = (seg["Open Time"].max() - seg["Open Time"].min()).total_seconds() / 60
    print(f"\n  {best} consecutive losses spread over {dur:.0f} minutes.")
    print("  A 15-minute pause after the 3rd would have removed the rest of the run.")

    hr("D. DID THE PER-ASSET MUTE (2 LOSSES -> 60 MIN) EVER BITE?")
    print("  If it worked, an asset should have no trade within 60 min of its 2nd")
    print("  consecutive loss.\n")
    total_viol = 0
    for a, g in df.groupby("Asset"):
        g = g.sort_values("Open Time").reset_index(drop=True)
        s = 0
        muted_until = None
        viol = []
        for _, r in g.iterrows():
            if muted_until is not None and r["Open Time"] < muted_until:
                viol.append((r["Open Time"], muted_until))
            if r["Outcome"] == "LOSS":
                s += 1
                if s >= 2:
                    muted_until = r["Open Time"] + pd.Timedelta(minutes=60)
            elif r["Outcome"] == "WIN":
                s = 0
        if viol:
            total_viol += len(viol)
            print(f"  {a:16s} {len(viol)} trade(s) opened while it should have been muted")
            for t, mu in viol[:3]:
                print(f"      {t:%m-%d %H:%M:%S}  mute ran to {mu:%m-%d %H:%M:%S}")
    print(f"\n  total violations: {total_viol}")
    print("  Note: the mute is set when a trade SETTLES, and settlement is 3 min after")
    print("  entry, so a little leakage is expected. Large leakage is not.")

    hr("E. RESTART DETECTION -- WHY ASSETS CHANGED STRATEGY MID-RUN")
    print("  An asset has exactly one strategy per plan. If its strategy changes,")
    print("  a new plan was loaded, i.e. the bot was restarted with a fresh")
    print("  auto-assign. Locating those switch points:\n")
    switches = []
    for a, g in df.groupby("Asset"):
        g = g.sort_values("Open Time")
        prev_s, prev_t = None, None
        for _, r in g.iterrows():
            if prev_s is not None and r["Strategy Name"] != prev_s:
                switches.append((r["Open Time"], a, prev_s, r["Strategy Name"], prev_t))
            prev_s, prev_t = r["Strategy Name"], r["Open Time"]
    switches.sort()
    print(f"  {len(switches)} strategy switches across {df['Asset'].nunique()} assets:")
    print(f"  {'switch seen at':22s} {'asset':14s} from -> to")
    for t, a, f, to, _ in switches:
        print(f"  {t:%Y-%m-%d %H:%M:%S}   {a:14s} {f}  ->  {to}")

    if switches:
        times = pd.Series([s[0] for s in switches])
        print("\n  Clustered by hour (a restart shows up as a cluster):")
        for h, c in times.dt.floor("h").value_counts().sort_index().items():
            print(f"    {h:%Y-%m-%d %H:00}  {c} switch(es)")

    hr("F. WHAT THE SESSION ACTUALLY COST, BY STAKE SIZE")
    for amt, g in df.groupby("Trade Amount ($)"):
        w = (g["Outcome"] == "WIN").sum()
        loss = (g["Outcome"] == "LOSS").sum()
        print(f"  ${amt:>6.2f} stake: n={len(g):>4}  {w}W/{loss}L  "
              f"PnL ${g['Broker Profit ($)'].sum():>+9.2f}")
    print("\n  Had the whole session run at the planned $10 base stake")
    print(f"  (so $2.50 on OTC), the loss would have been about "
          f"${df['Broker Profit ($)'].sum() / 10:,.2f}.")


if __name__ == "__main__":
    main()
