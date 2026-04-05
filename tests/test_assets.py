import asyncio
from strat_trade.settings import Settings
from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway

async def main():
    settings = Settings()
    gateway = PocketOptionTradingGateway(
        ssid=settings.pocket_option_ssid,
        is_demo=settings.pocket_option_is_demo,
        region=settings.pocket_option_region,
        use_raw_auth_frame=settings.pocket_option_use_raw_auth_frame,
        sdk_debug=settings.pocket_option_sdk_debug,
    )
    assets = await gateway.get_available_assets()
    for a in assets[:2]:
        print(a)
    await gateway.aclose()

asyncio.run(main())
