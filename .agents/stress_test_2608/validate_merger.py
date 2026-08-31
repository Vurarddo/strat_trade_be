"""Validates the merged CSV against the broker's own records, pulled from the API.

The merged export is the only thing the analysis ever sees, so if the merge is
wrong every conclusion is wrong. This compares it field by field against what
Pocket Option itself reports for the same order ids.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway  # noqa: E402
from strat_trade.settings import Settings  # noqa: E402

CSV = Path("/Users/vlados/Downloads/28.08_29.08 - 27.08_28.08.csv")


def hr(t: str) -> None:
    print("\n" + "=" * 94)
    print(t)
    print("=" * 94)


async def main() -> None:
    df = pd.read_csv(CSV)
    by_order = {str(r["Broker Order UUID"]): r for _, r in df.iterrows()}

    settings = Settings()
    gw = PocketOptionTradingGateway(
        ssid=settings.pocket_option_ssid,
        is_demo=settings.pocket_option_is_demo,
        region=settings.pocket_option_region,
    )

    try:
        client = await gw._client_connected()
        ids: list[str] = []
        for _ in range(6):
            raw = await client.closed_deals()
            ids = list(raw.keys()) if isinstance(raw, dict) else list(raw or [])
            if ids:
                break
            await asyncio.sleep(2.0)

        hr("OVERLAP BETWEEN THE BROKER API AND YOUR MERGED CSV")
        overlap = [i for i in ids if str(i) in by_order]
        print(f"  deals visible via the API : {len(ids)}")
        print(f"  rows in the merged CSV    : {len(df)}")
        print(f"  order ids present in both : {len(overlap)}")
        if not overlap:
            print("  Nothing to compare.")
            return

        hr("FIELD-BY-FIELD COMPARISON")
        print(f"  {'order':10s} {'field':14s} {'broker':>14s} {'merged CSV':>14s}  ok")
        problems: list[str] = []
        for deal_id in overlap:
            deal = await client.get_closed_deal(str(deal_id))
            if not isinstance(deal, dict):
                continue
            row = by_order[str(deal_id)]
            short = str(deal_id)[:8]

            checks = [
                ("open price", Decimal(str(deal["openPrice"])),
                 Decimal(str(row["Broker Open Price"]))),
                ("close price", Decimal(str(deal["closePrice"])),
                 Decimal(str(row["Broker Close Price"]))),
                ("amount", Decimal(str(deal["amount"])),
                 Decimal(str(row["Trade Amount ($)"]))),
                ("profit", Decimal(str(deal["profit"])),
                 Decimal(str(row["Broker Profit ($)"]))),
            ]
            for name, broker_v, csv_v in checks:
                ok = broker_v == csv_v
                if not ok:
                    problems.append(f"{short} {name}: broker {broker_v} vs csv {csv_v}")
                print(f"  {short:10s} {name:14s} {broker_v:>14} {csv_v:>14}  "
                      f"{'ok' if ok else 'MISMATCH'}")

            broker_outcome = (
                "WIN" if Decimal(str(deal["profit"])) > 0
                else "LOSS" if Decimal(str(deal["profit"])) < 0
                else "DRAW"
            )
            ok = broker_outcome == row["Outcome"]
            if not ok:
                problems.append(f"{short} outcome: broker {broker_outcome} vs csv {row['Outcome']}")
            print(f"  {short:10s} {'outcome':14s} {broker_outcome:>14s} {row['Outcome']:>14s}  "
                  f"{'ok' if ok else 'MISMATCH'}")

            # direction: PO encodes command 0 = CALL, 1 = PUT
            broker_dir = "CALL" if int(deal.get("command", 0)) == 0 else "PUT"
            ok = broker_dir == row["Direction"]
            if not ok:
                problems.append(f"{short} direction: broker {broker_dir} vs csv {row['Direction']}")
            print(f"  {short:10s} {'direction':14s} {broker_dir:>14s} {row['Direction']:>14s}  "
                  f"{'ok' if ok else 'MISMATCH'}")
            print()

        hr("VERDICT ON THE MERGE")
        if problems:
            print(f"  {len(problems)} mismatch(es):")
            for p in problems:
                print(f"    {p}")
        else:
            print(f"  Every field of all {len(overlap)} comparable deals matches the broker.")
            print("  The merge transfers broker ground truth faithfully.")

        hr("WHAT THE MERGE STILL CANNOT DO")
        print("  The merged CSV corrects the record AFTER the fact. During the session")
        print("  the bot still judged WIN/LOSS against its own stale price, and the")
        print("  circuit breaker, the degradation guard and the asset governor all")
        print("  learned from that judgement. Merging fixed the report, not the")
        print("  behaviour that produced it.\n")
        sub = df[df["Broker Order UUID"].astype(str).isin([str(i) for i in overlap])]
        print(f"  On these {len(sub)} deals the merged file records a median entry error of")
        print(f"  {sub['Slippage'].median():.5f} between the broker's fill and the bot's own")
        print("  price -- which is exactly the number that made the guards unreliable.")

    finally:
        await gw.aclose()


if __name__ == "__main__":
    asyncio.run(main())
