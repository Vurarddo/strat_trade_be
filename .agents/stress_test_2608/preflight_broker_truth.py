"""Pre-flight check: does the broker actually answer the queries the bot now trusts?

Read-only. Places no trades. Verifies that get_closed_deal / get_opened_deal
return the fields settlement now depends on, so a session is not started only to
discover every trade fell back to candles.
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, "src")

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway  # noqa: E402
from strat_trade.settings import Settings  # noqa: E402

REQUIRED_FOR_SETTLEMENT = ("result", "profit")
REQUIRED_FOR_PRICING = ("entry_price", "close_price")


def hr(t: str) -> None:
    print("\n" + "=" * 92)
    print(t)
    print("=" * 92)


async def main() -> int:
    settings = Settings()
    gw = PocketOptionTradingGateway(
        ssid=settings.pocket_option_ssid,
        is_demo=settings.pocket_option_is_demo,
        region=settings.pocket_option_region,
    )

    verdict_ok = False
    price_ok = False

    try:
        hr("1. CONNECTION AND ACCOUNT")
        balance = await gw.get_balance()
        print(f"  connected. balance = {balance.amount} {balance.currency}"
              f"   demo = {balance.is_demo}")
        print(f"\n  Your plan will declare initial_deposit = 50000.")
        if abs(float(balance.amount) - 50000.0) > 1.0:
            print(f"  MISMATCH: the account actually holds {balance.amount}.")
            print("  The stop-loss, take-profit and drawdown breakers are all measured")
            print("  against the declared deposit, so they will not line up with the")
            print("  real account until you reset the demo balance to 50000.")
        else:
            print("  Matches the account. The breakers will measure against reality.")

        hr("2. CLOSED DEAL HISTORY (read-only)")
        client = await gw._client_connected()
        # The deal cache fills asynchronously after the socket authenticates.
        ids: list[str] = []
        for attempt in range(6):
            raw = await client.closed_deals()
            ids = list(raw.keys()) if isinstance(raw, dict) else list(raw or [])
            if ids:
                break
            print(f"  attempt {attempt + 1}: history still empty, waiting...")
            await asyncio.sleep(2.0)
        print(f"  broker reports {len(ids)} closed deal(s) in this session")

        if not ids:
            print("\n  No closed deals to inspect. This is expected on a fresh session:")
            print("  the history is per-connection, not the full account archive.")
            print("  The settlement path cannot be proven until the first trade closes.")
            print("  Watch the log for 'Broker did not settle ... falling back to candles'")
            print("  during the first few minutes -- that message means the fix is inert.")
            return 2

        hr("3. PAYLOAD SHAPE OF A SETTLED DEAL")
        sample = ids[:3]
        for deal_id in sample:
            deal = await client.get_closed_deal(str(deal_id))
            print(f"\n  deal {deal_id}:")
            if not isinstance(deal, dict):
                print(f"    unusable payload: {type(deal).__name__}")
                continue
            print(f"    keys: {sorted(deal.keys())}")
            print("    " + json.dumps({k: str(v)[:24] for k, v in list(deal.items())[:12]},
                                      indent=6)[6:])
            missing_v = [k for k in REQUIRED_FOR_SETTLEMENT if deal.get(k) is None]
            missing_p = [k for k in REQUIRED_FOR_PRICING if deal.get(k) is None]
            print(f"    settlement fields missing: {missing_v or 'none'}")
            print(f"    price fields missing     : {missing_p or 'none'}")

        hr("4. THE GATEWAY WRAPPERS THE BOT ACTUALLY CALLS")
        for deal_id in sample:
            result = await gw.get_trade_result(str(deal_id))
            entry = await gw.get_deal_entry_price(str(deal_id))
            print(f"  {deal_id}:")
            print(f"    get_trade_result    -> {result}")
            print(f"    get_deal_entry_price-> {entry}")
            if result is not None:
                verdict_ok = True
            if entry is not None:
                price_ok = True

        hr("VERDICT")
        print(f"  broker settlement usable : {verdict_ok}")
        print(f"  broker fill price usable : {price_ok}")
        if verdict_ok and price_ok:
            print("\n  Both paths work. The bot will anchor entries to the real fill and")
            print("  settle on the broker's own verdict. Safe to start.")
            return 0
        print("\n  At least one path is not answering. The bot will still run, but it")
        print("  will fall back to candles and the session will have the same blind")
        print("  spot as 28-29.08. Do not treat its statistics as ground truth.")
        return 1
    finally:
        await gw.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
