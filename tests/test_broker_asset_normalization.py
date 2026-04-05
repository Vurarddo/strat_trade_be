from strat_trade.adapters.broker_asset_normalization import (
    flatten_allowed_candles,
    normalize_broker_asset_row,
)


def test_flatten_allowed_candles_from_time_dicts() -> None:
    raw = [{"time": 60}, {"time": 120}]
    assert flatten_allowed_candles(raw) == [60, 120]


def test_normalize_broker_asset_row_replaces_allowed_candles() -> None:
    row = {"symbol": "X", "allowed_candles": [{"time": 5}, {"time": 15}]}
    out = normalize_broker_asset_row(row)
    assert out["allowed_candles"] == [5, 15]
    assert row["allowed_candles"] == [{"time": 5}, {"time": 15}]
