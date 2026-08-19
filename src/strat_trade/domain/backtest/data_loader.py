from __future__ import annotations

import io
import json

import pandas as pd

from strat_trade.domain.errors import InvalidMarketParametersError


def parse_candles_csv_or_json(content: str | bytes, filename: str = "") -> pd.DataFrame:
    """
    Parse CSV or JSON string/bytes into a canonical DataFrame:
    columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    """
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = str(content)

    text = text.strip()
    if not text:
        raise InvalidMarketParametersError("Uploaded file content is empty.")

    is_json = text.startswith("[") or text.startswith("{") or filename.endswith(".json")

    if is_json:
        try:
            data = json.loads(text)
        except Exception as exc:
            raise InvalidMarketParametersError(f"Invalid JSON format: {exc}") from exc

        if isinstance(data, dict):
            for key in ("candles", "data", "history", "items", "result"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break

        if not isinstance(data, list) or not data:
            raise InvalidMarketParametersError(
                "JSON payload must contain a non-empty list of candle objects."
            )
        df = pd.DataFrame(data)
    else:
        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception as exc:
            raise InvalidMarketParametersError(f"Could not parse CSV: {exc}") from exc

    if df.empty:
        raise InvalidMarketParametersError("Candle data contains no rows.")

    # Normalize column names to lowercase
    rename_map = {}
    for col in df.columns:
        c_str = str(col).strip()
        c_low = c_str.lower()
        if c_low in ("time", "datetime", "date", "timestamp", "t", "ts"):
            rename_map[col] = "timestamp"
        elif c_low in ("open", "o"):
            rename_map[col] = "open"
        elif c_low in ("high", "h", "max"):
            rename_map[col] = "high"
        elif c_low in ("low", "l", "min"):
            rename_map[col] = "low"
        elif c_low in ("close", "c", "price"):
            rename_map[col] = "close"
        elif c_low in ("volume", "vol", "v"):
            rename_map[col] = "volume"

    df = df.rename(columns=rename_map)

    required = ["timestamp", "open", "high", "low", "close"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise InvalidMarketParametersError(
            f"Missing required columns in dataset: {missing}. Found: {list(df.columns)}"
        )

    if "volume" not in df.columns:
        df["volume"] = 0.0

    # Clean and parse types
    # Handle epoch integer/float vs string timestamps
    first_ts = df["timestamp"].iloc[0]
    if isinstance(first_ts, (int, float)) or (isinstance(first_ts, str) and first_ts.isdigit()):
        # Epoch
        unit = "ms" if float(first_ts) > 1e11 else "s"
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(float), unit=unit, utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()
    if df.empty:
        raise InvalidMarketParametersError(
            "No valid rows remaining after filtering missing or invalid prices."
        )

    df["volume"] = df["volume"].fillna(0.0)
    df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    return df[["timestamp", "open", "high", "low", "close", "volume"]]
