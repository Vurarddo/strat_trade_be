"""Map broker-specific asset payloads to stable API shapes."""

from __future__ import annotations

from typing import Any


def flatten_allowed_candles(raw: Any) -> list[int]:
    """Turn Pocket Option `[{"time": 60}, ...]` into `[60, ...]`."""
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        if isinstance(item, dict):
            t = item.get("time")
            if t is not None:
                try:
                    out.append(int(t))
                except (TypeError, ValueError):
                    continue
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        elif isinstance(item, str) and item.strip().isdigit():
            out.append(int(item.strip()))
    return out


def normalize_broker_asset_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy with `allowed_candles` as a list of period seconds."""
    out = dict(row)
    if "allowed_candles" in out:
        out["allowed_candles"] = flatten_allowed_candles(out["allowed_candles"])
    return out


def normalize_broker_asset_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [normalize_broker_asset_row(dict(r)) for r in rows if isinstance(r, dict)]
