from __future__ import annotations

import pytest

from strat_trade.api.indicator_payload import trim_leading_none_indicator_values


def test_trim_leading_nones() -> None:
    start, vals = trim_leading_none_indicator_values([None, None, 1.5, 2.0])
    assert start == 2
    assert vals == [1.5, 2.0]


def test_trim_all_none() -> None:
    start, vals = trim_leading_none_indicator_values([None, None])
    assert start == 2
    assert vals == []


def test_trim_internal_none_raises() -> None:
    with pytest.raises(TypeError):
        trim_leading_none_indicator_values([1.0, None, 2.0])
