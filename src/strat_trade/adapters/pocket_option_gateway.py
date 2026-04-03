from __future__ import annotations

import asyncio
import logging
import re
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
        return {"time": t, "open": o, "high": a, "low": b, "close": c}
    # [t, open, close, high, low] — typical Pocket Option wire order
    if _ohlc_sane(o_f, b_f, c_f, a_f):
        return {"time": t, "open": o, "high": b, "low": c, "close": a}
    return {"time": t, "open": o, "high": b, "low": c, "close": a}


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

    async def get_balance(self) -> AccountBalance:
        try:
            client = await self._client_connected()
            amount = await client.balance()
            is_demo = bool(client.is_demo())
        except BrokerUnavailableError:
            raise
        except Exception as exc:
            logger.warning("Pocket Option balance error: %s", exc)
            raise BrokerUnavailableError(str(exc)) from exc

        return AccountBalance(
            amount=Decimal(str(amount)),
            currency=self._balance_currency,
            is_demo=is_demo,
        )

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

        try:
            client = await self._client_connected()
            if end_time is None:
                raw_list = await client.candles(asset.strip(), period)
            else:
                et = end_time if end_time.tzinfo else end_time.replace(tzinfo=UTC)
                et = et.astimezone(UTC)
                end_u = int(et.timestamp())
                offset = _history_offset_seconds(period=period, count=count)
                raw_list = await client.get_candles_advanced(asset.strip(), period, offset, end_u)
        except InvalidMarketParametersError:
            raise
        except ValueError as exc:
            logger.info("Pocket Option rejected candle parameters: %s", exc)
            raise InvalidMarketParametersError(str(exc)) from exc
        except BrokerUnavailableError:
            raise
        except Exception as exc:
            logger.warning("Pocket Option candles error: %s", exc)
            raise BrokerUnavailableError(str(exc)) from exc

        normalized = _normalize_candles_payload(raw_list)
        rows = _sort_and_tail(normalized, count=count)
        return [_candle_from_dict(r) for r in rows]

    async def aclose(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.shutdown()
                except Exception as exc:
                    logger.debug("Pocket Option shutdown error (ignored): %s", exc)
                finally:
                    self._client = None

    async def place_trade(
        self, asset: str, direction: str, amount: float, expiration_in_seconds: int
    ) -> dict[str, Any]:
        if direction not in ("BUY", "SELL"):
            return {"success": False, "trade_id": None, "strike_price": 0.0}

        try:
            client = await self._client_connected()
            if direction == "BUY":
                trade_id, trade_dict = await client.buy(asset.strip(), amount, expiration_in_seconds)
            else:
                trade_id, trade_dict = await client.sell(asset.strip(), amount, expiration_in_seconds)

            # Extract details from the BinaryOptionsToolsV2 response
            is_success = True
            
            # trade_dict is the second element of the tuple
            if isinstance(trade_dict, dict):
                # Different brokers/versions might use different keys for the entry price
                strike_price = float(trade_dict.get("openPrice", trade_dict.get("open_price", trade_dict.get("start_price", trade_dict.get("strike", 0.0)))))
                if not trade_id:
                    trade_id = str(trade_dict.get("id", trade_dict.get("uuid", "")))
            else:
                strike_price = float(getattr(trade_dict, "openPrice", getattr(trade_dict, "open_price", getattr(trade_dict, "start_price", 0.0))))
                if not trade_id:
                    trade_id = str(getattr(trade_dict, "id", getattr(trade_dict, "uuid", "")))

            if not strike_price:
                logger.warning(f"⚠️ Could not parse exact strike price from broker, falling back to 0.0. Trade dict: {trade_dict}")

            if not trade_id:
                logger.warning(f"⚠️ Trade ID is empty. Trade might have failed. Trade dict: {trade_dict}")
                is_success = False

            print(
                f"🟢 [AUTO-TRADE] Placed {direction} on {asset} for "
                f"${amount} ({expiration_in_seconds}s) | Trade ID: {trade_id} | Strike: {strike_price} | Success: {is_success}",
                flush=True,
            )
            return {
                "success": is_success,
                "trade_id": trade_id,
                "strike_price": strike_price,
                "raw_response": trade_dict
            }
        except Exception as exc:
            logger.error("Failed to place auto-trade: %s", exc)
            return {"success": False, "trade_id": None, "strike_price": 0.0}

    async def get_available_assets(self) -> list[dict[str, Any]]:
        """Return a list of available assets and their full data from the broker."""
        try:
            client = await self._client_connected()
            return await client.active_assets()
        except BrokerUnavailableError:
            raise
        except Exception as exc:
            logger.warning("Pocket Option get_available_assets error: %s", exc)
            raise BrokerUnavailableError(str(exc)) from exc

    async def get_asset_payout(self, asset: str) -> int:
        """Return the current integer payout percentage for the given asset (e.g., 80 for 80%)."""
        try:
            client = await self._client_connected()
            payout = await client.payout(asset.strip())
            if payout is None:
                return 0
            return int(payout)
        except Exception as exc:
            logger.warning("Pocket Option get_asset_payout error: %s", exc)
            return 0
