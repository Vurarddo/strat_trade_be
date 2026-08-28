from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strat_trade.domain.backtest.models import BacktestTrade, TradeAction, TradeOutcome
from strat_trade.domain.trading.correlation import (
    extract_currency_pair,
    get_directional_exposure,
    get_pair_correlation,
    get_portfolio_currency_exposure,
    is_correlated_conflict,
    normalize_symbol,
)
from strat_trade.domain.trading.entities import IndicatorSnapshot, LiveTradeRecord


def _make_live_trade(asset: str, action: str) -> LiveTradeRecord:
    return LiveTradeRecord(
        trade_id="t-mock",
        asset=asset,
        action=action,
        stake=Decimal("10.00"),
        open_time=datetime.now(UTC),
        expiration_seconds=180,
        open_price=Decimal("1.0000"),
        strategy_id="mock_strat",
        strategy_name="Mock Strategy",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )


def test_normalize_symbol():
    assert normalize_symbol("AUDUSD_otc") == "AUDUSD"
    assert normalize_symbol("EUR/USD (OTC)") == "EURUSD"
    assert normalize_symbol("usd/chf-otc") == "USDCHF"
    assert normalize_symbol("GBP-USD") == "GBPUSD"
    assert normalize_symbol("") == ""
    assert normalize_symbol(None) == ""


def test_extract_currency_pair_standard_and_otc():
    assert extract_currency_pair("EURUSD") == ("EUR", "USD")
    assert extract_currency_pair("EURUSD_otc") == ("EUR", "USD")
    assert extract_currency_pair("USDCHF_otc") == ("USD", "CHF")
    assert extract_currency_pair("AUDNZD_otc") == ("AUD", "NZD")
    assert extract_currency_pair("USD/CHF OTC") == ("USD", "CHF")
    assert extract_currency_pair("eur/usd") == ("EUR", "USD")
    assert extract_currency_pair("GBP-USD_otc") == ("GBP", "USD")
    assert extract_currency_pair("BTCUSD_otc") == ("BTC", "USD")


def test_extract_currency_pair_invalid_symbols():
    assert extract_currency_pair("AAPL") is None
    assert extract_currency_pair("GOLD") is None
    assert extract_currency_pair("USDUSD") is None
    assert extract_currency_pair("") is None
    assert extract_currency_pair(None) is None
    assert extract_currency_pair("123456") is None


def test_directional_exposure_call_put():
    # CALL on EURUSD -> Long EUR, Short USD
    assert get_directional_exposure("EURUSD_otc", "CALL") == ("EUR", "USD")
    # PUT on EURUSD -> Long USD, Short EUR
    assert get_directional_exposure("EURUSD_otc", "PUT") == ("USD", "EUR")
    # CALL on USDCHF -> Long USD, Short CHF
    assert get_directional_exposure("USDCHF", "CALL") == ("USD", "CHF")
    # PUT on USDCHF -> Long CHF, Short USD
    assert get_directional_exposure("USDCHF", "PUT") == ("CHF", "USD")
    # Invalid action or asset
    assert get_directional_exposure("EURUSD_otc", "HOLD") is None
    assert get_directional_exposure("AAPL", "CALL") is None


def test_same_base_correlated_conflict_aud():
    # Active trade: CALL on AUDUSD (Long AUD, Short USD)
    active = [_make_live_trade("AUDUSD_otc", "CALL")]

    # Candidate: CALL on AUDNZD (Long AUD, Short NZD) -> Double Long AUD
    conflict, reason = is_correlated_conflict("AUDNZD_otc", "CALL", active)
    assert conflict is True
    assert "Double Long AUD" in reason

    # Candidate: PUT on AUDCAD (Long CAD, Short AUD) -> No double long or short
    conflict, reason = is_correlated_conflict("AUDCAD_otc", "PUT", active)
    assert conflict is False


def test_same_quote_correlated_conflict_usd():
    # Active trade: CALL on EURUSD (Long EUR, Short USD)
    active = [_make_live_trade("EURUSD_otc", "CALL")]

    # Candidate: CALL on GBPUSD (Long GBP, Short USD) -> Double Short USD
    conflict, reason = is_correlated_conflict("GBPUSD_otc", "CALL", active)
    assert conflict is True
    assert "Double Short USD" in reason

    # Candidate: CALL on AUDUSD (Long AUD, Short USD) -> Double Short USD
    conflict, reason = is_correlated_conflict("AUDUSD_otc", "CALL", active)
    assert conflict is True
    assert "Double Short USD" in reason


def test_inverse_pair_correlated_conflict_eurusd_usdchf():
    # Active trade: CALL on EURUSD (Long EUR, Short USD)
    active = [_make_live_trade("EURUSD_otc", "CALL")]

    # Candidate: PUT on USDCHF (Long CHF, Short USD) -> Double Short USD
    conflict, reason = is_correlated_conflict("USDCHF_otc", "PUT", active)
    assert conflict is True
    assert "Double Short USD" in reason

    # Active trade: PUT on EURUSD (Long USD, Short EUR)
    active_put = [_make_live_trade("EURUSD_otc", "PUT")]

    # Candidate: CALL on USDCHF (Long USD, Short CHF) -> Double Long USD
    conflict, reason = is_correlated_conflict("USDCHF_otc", "CALL", active_put)
    assert conflict is True
    assert "Double Long USD" in reason


def test_uncorrelated_diversified_trades():
    # Active trade: CALL on EURUSD (Long EUR, Short USD)
    active = [_make_live_trade("EURUSD_otc", "CALL")]

    # Candidate: CALL on AUDNZD (Long AUD, Short NZD) -> No common currencies
    conflict, reason = is_correlated_conflict("AUDNZD_otc", "CALL", active)
    assert conflict is False
    assert reason == ""


def test_polymorphic_trade_inputs():
    # BacktestTrade instance
    bt_trade = BacktestTrade(
        entry_index=10,
        exit_index=13,
        entry_time=datetime.now(UTC),
        exit_time=datetime.now(UTC),
        action=TradeAction.CALL,
        entry_price=Decimal("1.0"),
        exit_price=Decimal("1.0"),
        stake=Decimal("10.0"),
        payout_rate=Decimal("0.92"),
        pnl=Decimal("0.0"),
        outcome=TradeOutcome.DRAW,
        balance_after=Decimal("1000.0"),
        confidence=0.8,
        expiration_seconds=180,
        asset="EURUSD_otc",
    )
    conflict, reason = is_correlated_conflict("GBPUSD_otc", "CALL", [bt_trade])
    assert conflict is True
    assert "Double Short USD" in reason

    # Dict input
    dict_trade = {"asset": "EURUSD_otc", "action": "CALL"}
    conflict, reason = is_correlated_conflict("GBPUSD_otc", "CALL", [dict_trade])
    assert conflict is True
    assert "Double Short USD" in reason


def test_opposing_exposure_flag():
    active = [_make_live_trade("EURUSD_otc", "CALL")]  # Short USD
    # Candidate: CALL on USDCHF (Long USD)
    # Default: check_opposing=False -> No double concentration conflict
    conflict_def, _ = is_correlated_conflict("USDCHF_otc", "CALL", active, check_opposing=False)
    assert conflict_def is False

    # check_opposing=True -> Flags opposing USD
    conflict_opp, reason_opp = is_correlated_conflict(
        "USDCHF_otc", "CALL", active, check_opposing=True
    )
    assert conflict_opp is True
    assert "Opposing USD" in reason_opp


def test_portfolio_currency_exposure_aggregation():
    active = [
        _make_live_trade("EURUSD_otc", "CALL"),  # Long EUR, Short USD
        _make_live_trade("GBPUSD_otc", "CALL"),  # Long GBP, Short USD
        _make_live_trade("USDJPY_otc", "PUT"),  # Long JPY, Short USD
    ]
    exp = get_portfolio_currency_exposure(active)
    assert exp["EUR"] == 1
    assert exp["GBP"] == 1
    assert exp["JPY"] == 1
    assert exp["USD"] == -3


def test_get_pair_correlation():
    assert get_pair_correlation("EURUSD_otc", "GBPUSD_otc") == 0.82
    assert get_pair_correlation("EURUSD", "USDCHF") == -0.91
    assert get_pair_correlation("EURUSD", "EURUSD") == 1.0
    assert get_pair_correlation("EURUSD", "UNKNOWN_PAIR") is None
