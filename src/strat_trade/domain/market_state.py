from pydantic import BaseModel


class SMCStructure(BaseModel):
    last_swing_high_price: float | None
    last_swing_low_price: float | None
    has_recent_bullish_fvg: bool
    has_recent_bearish_fvg: bool
    distance_to_nearest_bull_fvg: float | None
    distance_to_nearest_bear_fvg: float | None


class MarketRegime(BaseModel):
    adx_14: float | None
    atr_14: float | None
    is_choppy: bool  # True if ADX < 20
    volume_trend: str  # "INCREASING", "DECREASING" or "FLAT"


class PriceAction(BaseModel):
    rsi_14: float | None
    rsi_divergence: str  # "REGULAR_BULLISH", "REGULAR_BEARISH", or "NONE"


class MarketStateVector(BaseModel):
    current_price: float
    regime: MarketRegime
    smc: SMCStructure
    price_action: PriceAction
