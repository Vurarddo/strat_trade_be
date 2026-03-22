from __future__ import annotations

import asyncio
import json
import logging
import random
from decimal import Decimal

from pocketoptionapi_async import AsyncPocketOptionClient
from pocketoptionapi_async.constants import REGIONS
from pocketoptionapi_async.exceptions import PocketOptionError

from strat_trade.adapters.pocket_option_ws_handshake import attach_resilient_handshake
from strat_trade.domain.entities import AccountBalance
from strat_trade.domain.errors import BrokerUnavailableError

logger = logging.getLogger(__name__)


def _coerce_is_demo(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "")
    return bool(value)


def _sync_client_from_auth_frame(client: AsyncPocketOptionClient) -> None:
    """
    pocketoptionapi-async picks demo vs live *regions* from constructor is_demo, not from the
    JSON isDemo field. A live frame (isDemo:0) + POCKET_OPTION_IS_DEMO=true connects to demo
    hosts and fails — mirror the frame before connect().
    """
    raw = (client.raw_ssid or "").strip()
    if not raw.startswith('42["auth",'):
        return
    try:
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start == -1 or json_end <= json_start:
            return
        data = json.loads(raw[json_start:json_end])
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse 42 auth frame for isDemo/uid sync: %s", exc)
        return
    if "isDemo" in data:
        client.is_demo = _coerce_is_demo(data["isDemo"])
        logger.info("Pocket Option client is_demo synced from auth frame: %s", client.is_demo)
    uid = data.get("uid")
    if uid is not None:
        try:
            client.uid = int(uid)
        except (TypeError, ValueError):
            pass


def _use_raw_socket_auth_frame(client: AsyncPocketOptionClient) -> None:
    """Send the captured browser auth line verbatim; SDK rebuild drops optional keys."""
    raw = (client.raw_ssid or "").strip()
    if not raw.startswith('42["auth",'):
        return

    def _format_session_message() -> str:
        return raw

    client._format_session_message = _format_session_message  # type: ignore[method-assign]


def _shuffled_broker_region_names(*, is_demo: bool) -> list[str]:
    """Same grouping as pocketoptionapi_async; random order avoids always failing on first host."""
    all_regions = REGIONS.get_all_regions()
    if is_demo:
        demo_urls = set(REGIONS.get_demo_regions())
        names = [n for n, url in all_regions.items() if url in demo_urls]
    else:
        names = [n for n in all_regions if "DEMO" not in n.upper()]
    random.shuffle(names)
    return names


class PocketOptionTradingGateway:
    """TradingGateway backed by Pocket Option via pocketoptionapi-async."""

    def __init__(
        self,
        *,
        ssid: str,
        is_demo: bool = True,
        region: str | None = None,
        use_raw_auth_frame: bool = True,
        sdk_debug: bool = False,
    ) -> None:
        self._ssid = ssid
        self._is_demo = is_demo
        self._region = region
        self._use_raw_auth_frame = use_raw_auth_frame
        self._sdk_debug = sdk_debug
        self._client: AsyncPocketOptionClient | None = None
        self._lock = asyncio.Lock()

    async def _client_connected(self) -> AsyncPocketOptionClient:
        async with self._lock:
            if self._client is None:
                self._client = AsyncPocketOptionClient(
                    self._ssid,
                    is_demo=self._is_demo,
                    region=self._region,
                    enable_logging=self._sdk_debug,
                )
                _sync_client_from_auth_frame(self._client)
                if self._use_raw_auth_frame:
                    _use_raw_socket_auth_frame(self._client)
                attach_resilient_handshake(self._client._websocket)
                regions = _shuffled_broker_region_names(is_demo=self._client.is_demo)
                ok = await self._client.connect(regions=regions)
                if not ok:
                    self._client = None
                    raise BrokerUnavailableError(
                        "Pocket Option WebSocket session could not be established "
                        "(connect() returned false). Typical causes: expired SSID — copy a fresh "
                        '42["auth",{...}] message from the browser (DevTools → Network → WS); '
                        "firewall/VPN blocking *.po.market; or try POCKET_OPTION_SDK_DEBUG=true "
                        "to see pocketoptionapi-async logs in the server console."
                    )
            return self._client

    async def get_balance(self) -> AccountBalance:
        try:
            client = await self._client_connected()
            raw = await client.get_balance()
        except PocketOptionError as exc:
            logger.warning("Pocket Option balance error: %s", exc)
            raise BrokerUnavailableError(str(exc)) from exc
        except BrokerUnavailableError:
            raise
        except OSError as exc:
            logger.warning("Network error talking to Pocket Option: %s", exc)
            raise BrokerUnavailableError("Network error while contacting broker.") from exc

        return AccountBalance(
            amount=Decimal(str(raw.balance)),
            currency=raw.currency,
            is_demo=raw.is_demo,
        )

    async def aclose(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except PocketOptionError as exc:
                    logger.debug("Pocket Option disconnect error (ignored): %s", exc)
                finally:
                    self._client = None
