from __future__ import annotations

from typing import Any

import pandas as pd

from strat_trade.domain.errors import InvalidMarketParametersError

try:
    from tvDatafeed import Interval, TvDatafeed
except ImportError:  # pragma: no cover - until dependency is installed
    Interval = Any  # type: ignore[misc, assignment]
    TvDatafeed = Any  # type: ignore[misc, assignment]

TvIntervalLike = str | Any

_INTERVAL_TOKEN_TO_ATTR: dict[str, str] = {
    "1": "in_1_minute",
    "1m": "in_1_minute",
    "1min": "in_1_minute",
    "3m": "in_3_minute",
    "5m": "in_5_minute",
    "15m": "in_15_minute",
    "30m": "in_30_minute",
    "45m": "in_45_minute",
    "60m": "in_1_hour",
    "1h": "in_1_hour",
    "2h": "in_2_hour",
    "3h": "in_3_hour",
    "4h": "in_4_hour",
    "1d": "in_daily",
    "d": "in_daily",
    "daily": "in_daily",
    "1w": "in_weekly",
    "w": "in_weekly",
    "weekly": "in_weekly",
    "1mo": "in_monthly",
    "1month": "in_monthly",
    "monthly": "in_monthly",
}


def _coerce_tv_interval(interval: TvIntervalLike) -> Any:
    if not isinstance(interval, str):
        return interval
    raw = interval.strip()
    if raw == "1M":
        return Interval.in_monthly
    key = raw.lower()
    attr = _INTERVAL_TOKEN_TO_ATTR.get(key)
    if attr is None:
        msg = f"Unsupported TradingView interval token: {interval!r}."
        raise InvalidMarketParametersError(msg)
    return getattr(Interval, attr)


def normalize_tradingview_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize a tvdatafeed `get_hist` frame: lowercase OHLCV, `timestamp` column,
    ascending time, plain RangeIndex, no MultiIndex.
    """
    if raw.empty:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )

    work = raw.copy()
    if isinstance(work.columns, pd.MultiIndex):
        flat = []
        for c in work.columns:
            flat.append("_".join(map(str, c)) if isinstance(c, tuple) else str(c))
        work.columns = flat

    if isinstance(work.index, pd.MultiIndex):
        work = work.reset_index()
    else:
        work = work.reset_index()

    time_col = None
    for candidate in ("datetime", "index"):
        if candidate in work.columns:
            time_col = candidate
            break
    if time_col is None:
        time_col = str(work.columns[0])

    rename_map: dict[str, str] = {time_col: "timestamp"}
    for c in work.columns:
        cl = str(c).lower()
        if cl in {"open", "high", "low", "close", "volume"} and str(c) != cl:
            rename_map[str(c)] = cl
    work = work.rename(columns=rename_map)

    required = ["timestamp", "open", "high", "low", "close"]
    missing = [c for c in required if c not in work.columns]
    if missing:
        msg = f"Normalized OHLCV frame missing columns {missing}; got {list(work.columns)}."
        raise InvalidMarketParametersError(msg)

    if "volume" not in work.columns:
        work["volume"] = 0.0

    use = work[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    use["timestamp"] = pd.to_datetime(use["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        use[col] = pd.to_numeric(use[col], errors="coerce").astype("float64")

    use = use.dropna(subset=["timestamp", "open", "high", "low", "close"], how="any")
    use["volume"] = use["volume"].fillna(0.0)

    use = use.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    return use


class TradingViewGateway:
    """
    TradingView historical bars via `tvdatafeed` (blocking I/O — run in a thread pool
    from async code paths).
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self._client = client if client is not None else TvDatafeed(username, password)

    def get_historical_ohlcv(
        self,
        ticker: str,
        exchange: str,
        interval: TvIntervalLike,
        n_bars: int,
    ) -> pd.DataFrame:
        if n_bars < 1:
            raise InvalidMarketParametersError("n_bars must be >= 1.")
        tv_interval = _coerce_tv_interval(interval)
        raw: pd.DataFrame = self._client.get_hist(
            symbol=ticker,
            exchange=exchange,
            interval=tv_interval,
            n_bars=n_bars,
        )
        return normalize_tradingview_ohlcv(raw)
