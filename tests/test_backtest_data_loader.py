from __future__ import annotations

import pytest

from strat_trade.domain.backtest.data_loader import parse_candles_csv_or_json
from strat_trade.domain.errors import InvalidMarketParametersError


def test_parse_valid_csv() -> None:
    csv_text = """datetime,open,high,low,close,volume
2026-01-01T00:00:00Z,1.1000,1.1010,1.0990,1.1005,50
2026-01-01T00:01:00Z,1.1005,1.1015,1.1000,1.1012,65
"""
    df = parse_candles_csv_or_json(csv_text)
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["open"].iloc[0] == 1.1000
    assert df["close"].iloc[1] == 1.1012


def test_parse_valid_json() -> None:
    json_text = """[
        {"time": 1700000000, "o": 1.23, "h": 1.25, "l": 1.22, "c": 1.24, "v": 100},
        {"time": 1700000060, "o": 1.24, "h": 1.26, "l": 1.23, "c": 1.25, "v": 120}
    ]"""
    df = parse_candles_csv_or_json(json_text)
    assert len(df) == 2
    assert df["open"].iloc[0] == 1.23
    assert df["volume"].iloc[1] == 120.0


def test_parse_invalid_csv_missing_columns() -> None:
    bad_csv = "time,foo,bar\n1,2,3"
    with pytest.raises(InvalidMarketParametersError):
        parse_candles_csv_or_json(bad_csv)


def test_parse_empty_content() -> None:
    with pytest.raises(InvalidMarketParametersError):
        parse_candles_csv_or_json("")
