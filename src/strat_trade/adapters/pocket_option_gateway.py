from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from BinaryOptionsToolsV2.config import Config
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync

from strat_trade.domain.entities import AccountBalance, Candle
from strat_trade.domain.errors import BrokerUnavailableError, InvalidMarketParametersError

logger = logging.getLogger(__name__)

# Pocket Option WebSocket history supports these native bar periods (seconds).
_PO_NATIVE_PERIODS: frozenset[int] = frozenset({1, 5, 15, 30, 60, 300})

_WS_URL_PATTERN = re.compile(r"^wss?://", re.IGNORECASE)


def _looks_like_ws_url(value: str) -> bool:
    return bool(_WS_URL_PATTERN.match(value.strip()))


def _coerce_timeframe_seconds(timeframe: int | str) -> int:
    if isinstance(timeframe, bool) or not isinstance(timeframe, (int, str)):
        msg = f"timeframe must be int or str seconds, got {type(timeframe).__name__}"
        raise InvalidMarketParametersError(msg)
    if isinstance(timeframe, str):
        stripped = timeframe.strip()
        if not stripped.isdigit():
            msg = "timeframe string must be a positive integer (seconds)."
            raise InvalidMarketParametersError(msg)
        tf = int(stripped)
    else:
        tf = int(timeframe)
    if tf < 1:
        raise InvalidMarketParametersError("timeframe_seconds must be >= 1.")
    return tf


def _epoch_seconds_to_utc(ts: float) -> datetime:
    """Normalize broker timestamps (seconds or milliseconds since epoch)."""
    if ts > 1e11:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, tz=UTC)


def _extract_epoch_value(row: dict[str, Any]) -> float | None:
    for key in ("time", "timestamp", "t", "from", "ts"):
        v = row.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _ohlc_sane(o: float, h: float, low: float, c: float) -> bool:
    prices = (o, h, low, c)
    mx, mn = max(prices), min(prices)
    tol = max(1e-6, 1e-8 * max(abs(mx), 1.0))
    return abs(h - mx) <= tol and abs(low - mn) <= tol


def _list_to_candle_dict(item: Sequence[Any]) -> dict[str, Any]:
    if len(item) < 5:
        msg = f"Pocket Option candle row has fewer than 5 values: {item!r}"
        raise BrokerUnavailableError(msg)
    t, o, a, b, c = item[0], item[1], item[2], item[3], item[4]
    o_f, a_f, b_f, c_f = float(o), float(a), float(b), float(c)
    # [t, open, high, low, close]
    if _ohlc_sane(o_f, a_f, b_f, c_f):
        res = {"time": t, "open": o, "high": a, "low": b, "close": c}
    # [t, open, close, high, low] — typical Pocket Option wire order
    elif _ohlc_sane(o_f, b_f, c_f, a_f):
        res = {"time": t, "open": o, "high": b, "low": c, "close": a}
    else:
        res = {"time": t, "open": o, "high": b, "low": c, "close": a}
    if len(item) >= 6 and item[5] is not None:
        res["volume"] = item[5]
    return res


def _expand_columnar_candles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ts = payload.get("t")
    if not isinstance(ts, list) or not ts:
        return []

    def col(short: str, long: str) -> list[Any] | None:
        v = payload.get(short)
        if isinstance(v, list) and len(v) == len(ts):
            return v
        v = payload.get(long)
        if isinstance(v, list) and len(v) == len(ts):
            return v
        return None

    opens = col("o", "open")
    closes = col("c", "close")
    if opens is None or closes is None:
        return []
    highs = col("h", "high")
    lows = col("l", "low")
    vols = col("v", "volume")
    out: list[dict[str, Any]] = []
    for i in range(len(ts)):
        o_f, c_f = float(opens[i]), float(closes[i])
        if highs is not None and lows is not None:
            hi, lo = float(highs[i]), float(lows[i])
        else:
            hi, lo = max(o_f, c_f), min(o_f, c_f)
        row: dict[str, Any] = {
            "time": ts[i],
            "open": opens[i],
            "high": hi,
            "low": lo,
            "close": closes[i],
        }
        if vols is not None:
            row["volume"] = vols[i]
        out.append(row)
    return out


def _canonical_candle_row(row: dict[str, Any]) -> dict[str, Any]:
    ts = _extract_epoch_value(row)
    o = row.get("open", row.get("o"))
    h = row.get("high", row.get("h"))
    low = row.get("low", row.get("l"))
    c = row.get("close", row.get("c"))
    vol = row.get("volume", row.get("v"))
    out: dict[str, Any] = {}
    if ts is not None:
        out["time"] = ts
    if o is not None:
        out["open"] = o
    if h is not None:
        out["high"] = h
    if low is not None:
        out["low"] = low
    if c is not None:
        out["close"] = c
    if vol is not None:
        out["volume"] = vol
    return out


def _normalize_candles_payload(raw: object) -> list[dict[str, Any]]:
    """BTV2 / PO may return list[dict], columnar dict, or list of OHLC tuples."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        expanded = _expand_columnar_candles(raw)
        if expanded:
            return expanded
        for key in ("candles", "data", "history", "values", "result", "items"):
            inner = raw.get(key)
            if inner is not None:
                return _normalize_candles_payload(inner)
        canon = _canonical_candle_row(raw)
        if _extract_epoch_value(canon) is not None:
            return [canon]
        logger.debug("Pocket Option candles: unrecognized dict keys: %s", list(raw.keys())[:20])
        return []
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                canon = _canonical_candle_row(item)
                if _extract_epoch_value(canon) is not None:
                    out.append(canon)
                else:
                    logger.debug(
                        "Pocket Option candles: dict row missing epoch; keys=%s",
                        list(item.keys())[:20],
                    )
            elif isinstance(item, (list, tuple)):
                out.append(_list_to_candle_dict(item))
            else:
                logger.debug("Pocket Option candles: skip row type=%s", type(item).__name__)
        return out
    logger.debug("Pocket Option candles: unexpected payload type=%s", type(raw).__name__)
    return []


def _candle_from_dict(row: dict[str, Any]) -> Candle:
    raw_t = row.get("time")
    if raw_t is None:
        msg = "Pocket Option candle payload missing time (after normalization)"
        raise BrokerUnavailableError(msg)
    try:
        open_time = _epoch_seconds_to_utc(float(raw_t))
    except (TypeError, ValueError, OSError) as exc:
        msg = f"Pocket Option candle time is not a valid epoch: {raw_t!r}"
        raise BrokerUnavailableError(msg) from exc

    def _dec(key: str) -> Decimal:
        v = row[key]
        return Decimal(str(v))

    vol = row.get("volume")
    return Candle(
        open_time=open_time,
        open=_dec("open"),
        high=_dec("high"),
        low=_dec("low"),
        close=_dec("close"),
        volume=None if vol is None else Decimal(str(vol)),
    )


def _sort_and_tail(rows: list[dict[str, Any]], *, count: int) -> list[dict[str, Any]]:
    def _sort_key(r: dict[str, Any]) -> float:
        v = _extract_epoch_value(r)
        return float(v) if v is not None else 0.0

    ordered = sorted(rows, key=_sort_key)
    if len(ordered) > count:
        return ordered[-count:]
    return ordered


def _history_offset_seconds(*, period: int, count: int) -> int:
    """Seconds of history to request (bounded for broker limits)."""
    span = period * max(count, 1) + period
    return min(max(span, period * 2), 86400 * 400)


def _extract_price(payload: object, keys: Sequence[str]) -> Decimal | None:
    """Reads the first usable positive price from a broker deal payload."""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = Decimal(str(raw))
        except (ArithmeticError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


class PocketOptionTradingGateway:
    """TradingGateway + CandleFeed via BinaryOptionsToolsV2 (PocketOptionAsync)."""

    def __init__(
        self,
        *,
        ssid: str,
        is_demo: bool = True,
        region: str | None = None,
        use_raw_auth_frame: bool = True,
        sdk_debug: bool = False,
        balance_currency: str = "USD",
    ) -> None:
        self._ssid = ssid
        self._is_demo = is_demo
        self._region = (region or "").strip() or None
        self._use_raw_auth_frame = use_raw_auth_frame
        if self._use_raw_auth_frame:
            logger.debug(
                "POCKET_OPTION_USE_RAW_AUTH_FRAME is set; BinaryOptionsToolsV2 sanitizes SSID "
                "internally — this flag is kept for config compatibility only."
            )
        self._sdk_debug = sdk_debug
        self._balance_currency = balance_currency.strip() or "USD"
        self._client: PocketOptionAsync | None = None
        self._lock = asyncio.Lock()
        self._candles_lock = asyncio.Lock()
        self._payouts_cache: dict[str, float] = {}
        self._payouts_updated_at: float = 0.0

    def _optional_ws_url(self) -> str | None:
        if not self._region:
            return None
        if _looks_like_ws_url(self._region):
            return self._region.strip()
        logger.warning(
            "POCKET_OPTION_REGION is not a ws/wss URL (%r); ignoring (BTV2 picks hosts from SSID).",
            self._region,
        )
        return None

    def _client_config(self) -> Config | None:
        if not self._sdk_debug:
            return None
        return Config(terminal_logging=True, log_level="DEBUG")

    async def _client_connected(self) -> PocketOptionAsync:
        async with self._lock:
            if self._client is None:
                url = self._optional_ws_url()
                cfg = self._client_config()
                self._client = PocketOptionAsync(self._ssid, url=url, config=cfg)
                try:
                    await self._client.wait_for_assets(timeout=120.0)
                except Exception as exc:
                    self._client = None
                    logger.warning("Pocket Option wait_for_assets failed: %s", exc)
                    raise BrokerUnavailableError(
                        "Pocket Option session could not be established (asset sync failed). "
                        "Typical causes: expired SSID, network/VPN blocking, or invalid SSID. "
                        'Copy a fresh ssid / 42["auth",…] from the browser if needed.'
                    ) from exc
            return self._client

    async def _reset_client(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.shutdown()
                except Exception:
                    pass
                self._client = None

    def _is_connection_error(self, exc: Exception) -> bool:
        err_msg = str(exc).lower()
        return any(
            x in err_msg
            for x in (
                "half closed channel",
                "channel sender error",
                "connection has dropped",
                "shut down",
                "closed channel",
                "connection reset",
                "broken pipe",
                "websocket",
            )
        )

    async def get_balance(self) -> AccountBalance:
        for attempt in range(2):
            try:
                client = await self._client_connected()
                amount = await client.balance()
                is_demo = bool(client.is_demo())
                return AccountBalance(
                    amount=Decimal(str(amount)),
                    currency=self._balance_currency,
                    is_demo=is_demo,
                )
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    logger.info(
                        "Pocket Option connection dropped during balance check; reconnecting..."
                    )
                    await self._reset_client()
                    continue
                if isinstance(exc, BrokerUnavailableError):
                    raise
                logger.warning("Pocket Option balance error: %s", exc)
                raise BrokerUnavailableError(str(exc)) from exc

        raise BrokerUnavailableError("Failed to fetch balance after reconnect retry.")

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        period = _coerce_timeframe_seconds(timeframe)
        if period not in _PO_NATIVE_PERIODS:
            supported = ", ".join(str(x) for x in sorted(_PO_NATIVE_PERIODS))
            raise InvalidMarketParametersError(
                f"Pocket Option native candle periods are {supported} seconds; got {period}."
            )
        if count < 1:
            raise InvalidMarketParametersError("count must be >= 1.")

        for attempt in range(2):
            async with self._candles_lock:
                try:
                    client = await self._client_connected()
                    offset = _history_offset_seconds(period=period, count=count)
                    if end_time is None:
                        end_dt = datetime.now(UTC)
                    else:
                        end_dt = end_time if end_time.tzinfo else end_time.replace(tzinfo=UTC)
                    end_u = int(end_dt.astimezone(UTC).timestamp())
                    raw_list = await asyncio.wait_for(
                        client.get_candles_advanced(asset.strip(), period, offset, end_u),
                        timeout=8.0,
                    )
                    normalized = _normalize_candles_payload(raw_list)
                    rows = _sort_and_tail(normalized, count=count)
                    return [_candle_from_dict(r) for r in rows]
                except TimeoutError as exc:
                    if attempt == 0:
                        logger.debug(
                            "Candles request timed out for %s, resetting connection...", asset
                        )
                        await self._reset_client()
                        continue
                    logger.warning("Pocket Option candles timeout for asset %s", asset)
                    raise BrokerUnavailableError(f"Candles request timed out for {asset}") from exc
                except InvalidMarketParametersError:
                    raise
                except ValueError as exc:
                    logger.info("Pocket Option rejected candle parameters: %s", exc)
                    raise InvalidMarketParametersError(str(exc)) from exc
                except Exception as exc:
                    if attempt == 0 and self._is_connection_error(exc):
                        logger.info(
                            "Pocket Option channel error on candles (%s); auto-reconnecting...",
                            asset,
                        )
                        await self._reset_client()
                        continue
                    if isinstance(exc, BrokerUnavailableError):
                        raise
                    logger.warning("Pocket Option candles error: %s", exc)
                    raise BrokerUnavailableError(str(exc)) from exc

        raise BrokerUnavailableError(f"Failed to fetch candles for {asset} after retry.")

    async def get_assets(self) -> list[dict[str, Any]]:
        for attempt in range(2):
            try:
                client = await self._client_connected()
                active = await client.active_assets()
                out: list[dict[str, Any]] = []
                if isinstance(active, list):
                    for a in active:
                        if not isinstance(a, dict):
                            continue
                        sym = str(a.get("symbol", "")).strip()
                        if not sym:
                            continue
                        raw_type = str(a.get("asset_type", "")).strip().lower()
                        if not raw_type or raw_type == "none":
                            if sym.startswith("#"):
                                raw_type = "stock"
                            elif any(
                                c in sym.upper()
                                for c in (
                                    "BTC",
                                    "ETH",
                                    "BNB",
                                    "SOL",
                                    "MATIC",
                                    "DOGE",
                                    "XRP",
                                    "AVAX",
                                    "ADA",
                                    "DOT",
                                    "LTC",
                                    "TON",
                                    "TRX",
                                    "SHIB",
                                )
                            ):
                                raw_type = "cryptocurrency"
                            elif any(
                                c in sym.upper()
                                for c in ("GOLD", "SILVER", "OIL", "BRENT", "WTI", "CRUDE", "GAS")
                            ):
                                raw_type = "commodity"
                            elif any(
                                c in sym.upper()
                                for c in (
                                    "AUS200",
                                    "DJI30",
                                    "SP500",
                                    "NAS100",
                                    "US30",
                                    "GER40",
                                    "UK100",
                                    "INDEX",
                                    "100GBP",
                                    "E35EUR",
                                    "F40EUR",
                                )
                            ):
                                raw_type = "index"
                            else:
                                raw_type = "currency"

                        out.append(
                            {
                                "symbol": sym,
                                "name": str(a.get("name", sym)).strip(),
                                "payout": int(a.get("payout", 80)),
                                "is_otc": bool(a.get("is_otc", "otc" in sym.lower())),
                                "asset_type": raw_type,
                            }
                        )
                    if out:
                        return out
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    logger.info("Pocket Option connection dropped on assets query; reconnecting...")
                    await self._reset_client()
                    continue
                logger.warning("Pocket Option get_assets error (using fallback): %s", exc)
                break
        return []

    async def get_asset_payout(self, asset: str) -> float:
        """Returns the real-time live broker payout rate for an asset (e.g. 0.92 for 92%)."""
        now_ts = time.time()
        # Refresh cached payouts if older than 20 seconds
        if now_ts - self._payouts_updated_at > 20.0 or not self._payouts_cache:
            try:
                active_list = await self.get_assets()
                if active_list:
                    new_map = {
                        a["symbol"].strip().upper(): a["payout"] / 100.0 for a in active_list
                    }
                    self._payouts_cache = new_map
                    self._payouts_updated_at = now_ts
            except Exception as e:
                logger.debug("Failed to refresh live asset payouts: %s", e)

        sym = asset.strip().upper()
        if sym in self._payouts_cache:
            return self._payouts_cache[sym]

        # Normalized lookup
        clean_sym = sym.replace("_", "").replace("-", "")
        for k, v in self._payouts_cache.items():
            if k.replace("_", "").replace("-", "") == clean_sym:
                return v

        return 0.92 if "OTC" in sym else 0.80

    async def open_trade(
        self,
        asset: str,
        action: str,
        amount: float,
        expiration_seconds: int,
    ) -> tuple[str, dict[str, Any]]:
        """Executes a binary options trade (CALL or PUT) via Pocket Option WebSocket."""
        act = action.strip().upper()
        amt = float(amount)
        exp_sec = int(expiration_seconds)

        if act not in ("CALL", "PUT"):
            msg = f"Invalid trade action: {action!r}. Must be 'CALL' or 'PUT'."
            raise ValueError(msg)

        for attempt in range(2):
            try:
                client = await self._client_connected()
                if act == "CALL":
                    res = await client.buy(asset=asset, amount=amt, time=exp_sec)
                else:
                    res = await client.sell(asset=asset, amount=amt, time=exp_sec)

                if isinstance(res, tuple) and len(res) >= 2:
                    order_id = str(res[0])
                    deal_info = res[1] if isinstance(res[1], dict) else {"raw": res[1]}
                    return order_id, deal_info
                if isinstance(res, str):
                    return res, {"order_id": res}
                if isinstance(res, dict):
                    order_id = str(res.get("id", res.get("order_id", "demo_order")))
                    return order_id, res
                return str(res), {"result": res}
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    logger.info("Pocket Option disconnected during trade; reconnecting...")
                    await self._reset_client()
                    continue
                logger.error(
                    "Failed to open trade %s on %s ($%.2f, %ds): %s", act, asset, amt, exp_sec, exc
                )
                raise BrokerUnavailableError(f"Trade execution failed: {exc}") from exc

        raise BrokerUnavailableError("Trade execution failed after reconnection retry.")

    async def get_deal_entry_price(self, order_id: str) -> Decimal | None:
        """Returns the price the broker actually filled an order at.

        The candle feed only serves closed bars, so the last close can be a full
        bar behind the market. Reading the fill back from the broker is the only
        way to anchor a trade to the price it was really opened at.
        """
        if not order_id:
            return None
        try:
            client = await self._client_connected()
            for fetch in (client.get_opened_deal, client.get_closed_deal):
                deal = await fetch(order_id)
                price = _extract_price(deal, ("entry_price", "openPrice", "open_price", "price"))
                if price is not None:
                    return price
        except Exception as exc:
            logger.debug("Could not read broker entry price for %s: %s", order_id, exc)
        return None

    async def get_trade_result(self, order_id: str) -> dict[str, Any] | None:
        """Returns the broker's own verdict on a settled trade, or None if pending.

        Never blocks waiting for expiry: `get_closed_deal` answers only once the
        broker has settled the deal, so a None means "ask again later".
        """
        if not order_id:
            return None
        try:
            client = await self._client_connected()
            deal = await client.get_closed_deal(order_id)
        except Exception as exc:
            logger.debug("Could not read broker result for %s: %s", order_id, exc)
            return None

        if not isinstance(deal, dict):
            return None

        outcome = str(deal.get("result", "")).strip().lower()
        profit = deal.get("profit")
        if outcome not in ("win", "loss", "draw") and profit is None:
            return None

        if outcome not in ("win", "loss", "draw"):
            try:
                value = float(profit)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            outcome = "win" if value > 0 else ("loss" if value < 0 else "draw")

        return {
            "result": outcome,
            "profit": None if profit is None else Decimal(str(profit)),
            "close_price": _extract_price(deal, ("close_price", "closePrice")),
            "entry_price": _extract_price(deal, ("entry_price", "openPrice", "open_price")),
        }

    async def aclose(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.shutdown()
                except Exception as exc:
                    logger.debug("Pocket Option shutdown error (ignored): %s", exc)
                finally:
                    self._client = None
