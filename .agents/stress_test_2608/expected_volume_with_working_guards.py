"""Replays 28-29.08 with the guards actually enforced, to set volume expectations.

Illustrative only: the outcomes come from trades whose entry price was wrong, so
this cannot predict the next session's PnL. It answers a narrower question --
how much of the traffic the guards would have removed had they worked.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV = Path("/Users/vlados/Downloads/28.08_29.08 - 27.08_28.08.csv")

PER_ASSET_MUTE_MIN = 60
GLOBAL_PAUSE_MIN = 15
MAX_CONSECUTIVE_LOSSES = 3
PER_ASSET_MAX_LOSSES = 2


def main() -> None:
    df = pd.read_csv(CSV)
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df = df.sort_values("Open Time").reset_index(drop=True)

    taken: list[int] = []
    skipped_muted = skipped_paused = 0
    asset_streak: dict[str, int] = {}
    asset_muted_until: dict[str, pd.Timestamp] = {}
    global_streak = 0
    paused_until: pd.Timestamp | None = None

    for i, r in df.iterrows():
        t, asset = r["Open Time"], r["Asset"]

        if paused_until is not None and t < paused_until:
            skipped_paused += 1
            continue
        if asset in asset_muted_until and t < asset_muted_until[asset]:
            skipped_muted += 1
            continue

        taken.append(i)
        settle = t + pd.Timedelta(seconds=180)

        if r["Outcome"] == "LOSS":
            global_streak += 1
            asset_streak[asset] = asset_streak.get(asset, 0) + 1
            if asset_streak[asset] >= PER_ASSET_MAX_LOSSES:
                asset_muted_until[asset] = settle + pd.Timedelta(minutes=PER_ASSET_MUTE_MIN)
            if global_streak >= MAX_CONSECUTIVE_LOSSES:
                paused_until = settle + pd.Timedelta(minutes=GLOBAL_PAUSE_MIN)
                global_streak = 0
        elif r["Outcome"] == "WIN":
            global_streak = 0
            asset_streak[asset] = 0

    kept = df.loc[taken]
    w = int((kept["Outcome"] == "WIN").sum())
    loss = int((kept["Outcome"] == "LOSS").sum())

    print("=" * 88)
    print("SAME TAPE, GUARDS ENFORCED")
    print("=" * 88)
    print(f"  trades actually taken on 28-29.08 : {len(df)}")
    print(f"  trades that survive the guards    : {len(kept)}"
          f"  ({len(kept) / len(df) * 100:.0f}%)")
    print(f"    blocked by a per-asset mute     : {skipped_muted}")
    print(f"    blocked by the global pause     : {skipped_paused}")
    print()
    print(f"  record of the surviving trades    : {w}W / {loss}L"
          f"  ({w / (w + loss) * 100:.1f}%)" if w + loss else "")
    print(f"  their modelled PnL                : ${kept['Broker Profit ($)'].sum():+,.2f}")
    print(f"  (the full tape produced           : ${df['Broker Profit ($)'].sum():+,.2f})")
    print()
    print("  Caveat: these outcomes were produced with a mispriced entry, so the")
    print("  win rate above is not a forecast. The volume reduction is the point:")
    print(f"  expect roughly {len(kept) / len(df) * 100:.0f}% of last session's trade count.")

    span_h = (df["Open Time"].max() - df["Open Time"].min()).total_seconds() / 3600
    print(f"\n  last session: {len(df)} trades over {span_h:.0f}h"
          f" = {len(df) / span_h:.1f}/h")
    print(f"  with guards : {len(kept)} trades over {span_h:.0f}h"
          f" = {len(kept) / span_h:.1f}/h")

    print("\n  Sample-size consequence for the asset governor (needs n=20 per asset):")
    per_asset = kept.groupby("Asset").size().sort_values(ascending=False)
    print(f"    assets traded: {len(per_asset)}")
    print(f"    median trades per asset in {span_h:.0f}h: {per_asset.median():.0f}")
    if per_asset.median() > 0:
        days = 20 / (per_asset.median() / (span_h / 24))
        print(f"    -> about {days:.1f} days before a typical asset reaches n=20")


if __name__ == "__main__":
    main()
