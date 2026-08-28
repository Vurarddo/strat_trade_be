"""Statistical per-asset capital governor.

Replaces the hand-curated toxic-name blacklist as the *primary* asset control.

The blacklist was tested against the 24-28.08 live sample and failed as a
forward rule: an asset's ROI in the first half of the week had essentially zero
rank correlation with its ROI in the second half (Spearman rho = -0.011,
p = 0.96). A list of names derived from past PnL therefore carries no
predictive information — it only encodes the sample it was built from.

What did survive out-of-sample was structural, not nominal: OTC quotes are
broker-generated and lost money (win rate 48.91% against a 52.08% break-even,
p = 0.0256) while exchange-backed spot quotes did not (56.09%).

So this module governs assets by two mechanisms only:

* a structural stake haircut for OTC, which must be *earned back* with
  measured results rather than assumed;
* a Wilson lower-bound mute that switches an asset off once its own record is
  statistically incompatible with break-even.

Both are measured at runtime, so the rule set updates itself instead of
freezing last week's losers into code.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from strat_trade.domain.trading.asset_filter import canonical_asset_key, is_otc_asset

logger = logging.getLogger(__name__)


class AssetTier(StrEnum):
    NORMAL = "NORMAL"
    PROBATION = "PROBATION"
    MUTED = "MUTED"


@dataclass(frozen=True)
class AssetGovernorConfig:
    """Tuning knobs for the governor.

    Defaults encode the measured week: OTC starts at a quarter stake, and the
    payout floor for OTC is set above its 52.08% break-even so a trade is only
    taken when the maths is not already negative.
    """

    otc_stake_multiplier: float = 0.25
    otc_min_payout_rate: float = 0.90
    spot_min_payout_rate: float = 0.85
    min_trades_for_mute: int = 20
    # Muting is cheap and reversible, so it runs at one-sided 90% confidence.
    # Promotion commits real capital and is held to one-sided 95%.
    mute_confidence_z: float = 1.2816
    promotion_confidence_z: float = 1.645
    mute_duration_minutes: int = 240
    promotion_min_trades: int = 400
    max_stake_multiplier: float = 1.0


@dataclass
class AssetStats:
    wins: int = 0
    losses: int = 0
    muted_until: datetime | None = None
    mute_count: int = 0
    promoted: bool = False

    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.decided if self.decided else 0.0


@dataclass(frozen=True)
class AssetVerdict:
    tier: AssetTier
    stake_multiplier: float
    min_payout_rate: float
    reason: str

    @property
    def is_tradable(self) -> bool:
        return self.tier is not AssetTier.MUTED


def break_even_win_rate(payout_rate: float) -> float:
    """Win rate at which a binary option with this payout is EV-neutral."""
    if payout_rate <= 0:
        return 1.0
    return 1.0 / (1.0 + payout_rate)


def _wilson_interval(wins: int, total: int, z: float) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation because live samples are small and
    win rates sit near 0.5, where the naive interval misbehaves.
    """
    if total <= 0:
        return 0.0, 1.0
    phat = wins / total
    denom = 1.0 + z * z / total
    centre = phat + z * z / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * total)) / total)
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Evidence that the true win rate is *at least* this high."""
    return _wilson_interval(wins, total, z)[0]


def wilson_upper_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Evidence that the true win rate is *at most* this high."""
    if total <= 0:
        return 1.0
    return _wilson_interval(wins, total, z)[1]


class AssetGovernor:
    """Decides whether an asset may trade and at what fraction of the stake."""

    def __init__(self, config: AssetGovernorConfig | None = None) -> None:
        self.config = config or AssetGovernorConfig()
        self._stats: dict[str, AssetStats] = {}

    def reset(self) -> None:
        self._stats.clear()

    def stats_for(self, asset: str) -> AssetStats:
        key = canonical_asset_key(asset)
        if key not in self._stats:
            self._stats[key] = AssetStats()
        return self._stats[key]

    def snapshot(self) -> dict[str, AssetStats]:
        return dict(self._stats)

    def min_payout_for(self, asset: str) -> float:
        cfg = self.config
        return cfg.otc_min_payout_rate if is_otc_asset(asset) else cfg.spot_min_payout_rate

    def base_stake_multiplier(self, asset: str) -> float:
        if not is_otc_asset(asset):
            return self.config.max_stake_multiplier
        return self.config.otc_stake_multiplier

    def evaluate(self, asset: str, now: datetime | None = None) -> AssetVerdict:
        """Reads current governance state for an asset. Does not mutate it."""
        now = now or datetime.now(UTC)
        st = self.stats_for(asset)
        min_payout = self.min_payout_for(asset)

        if st.muted_until and now < st.muted_until:
            remaining = (st.muted_until - now).total_seconds() / 60.0
            return AssetVerdict(
                tier=AssetTier.MUTED,
                stake_multiplier=0.0,
                min_payout_rate=min_payout,
                reason=(
                    f"Muted by governor for {remaining:.0f} more min "
                    f"({st.wins}W/{st.losses}L, WR {st.win_rate:.1%})"
                ),
            )

        multiplier = self.base_stake_multiplier(asset)
        if st.promoted:
            multiplier = min(
                self.config.max_stake_multiplier,
                multiplier * 2.0,
            )

        if multiplier >= self.config.max_stake_multiplier:
            return AssetVerdict(
                tier=AssetTier.NORMAL,
                stake_multiplier=multiplier,
                min_payout_rate=min_payout,
                reason="Full stake",
            )

        return AssetVerdict(
            tier=AssetTier.PROBATION,
            stake_multiplier=multiplier,
            min_payout_rate=min_payout,
            reason=(
                f"OTC probation at {multiplier:.0%} stake "
                f"({st.decided} decided trades, {st.wins}W/{st.losses}L)"
            ),
        )

    def record_outcome(
        self,
        asset: str,
        is_win: bool,
        payout_rate: float,
        now: datetime | None = None,
    ) -> AssetVerdict:
        """Folds a settled trade into the asset's record and re-runs governance."""
        now = now or datetime.now(UTC)
        st = self.stats_for(asset)

        if st.muted_until and now >= st.muted_until:
            # A finished mute starts a clean measurement window, otherwise the
            # losses that caused the mute would keep it muted forever.
            st.wins = 0
            st.losses = 0
            st.muted_until = None

        if is_win:
            st.wins += 1
        else:
            st.losses += 1

        self._apply_mute_rule(asset, st, payout_rate, now)
        self._apply_promotion_rule(asset, st, payout_rate)
        return self.evaluate(asset, now)

    def _apply_mute_rule(
        self, asset: str, st: AssetStats, payout_rate: float, now: datetime
    ) -> None:
        cfg = self.config
        if st.decided < cfg.min_trades_for_mute:
            return

        # Mute only on evidence that the asset is below break-even, i.e. when even
        # the optimistic end of its confidence interval does not reach it. Testing
        # the pessimistic end instead would mute almost every asset, because at
        # n=20 the interval is far too wide to clear break-even from below.
        upper = wilson_upper_bound(st.wins, st.decided, cfg.mute_confidence_z)
        break_even = break_even_win_rate(payout_rate)
        if upper >= break_even:
            return

        # Repeat offenders are muted for progressively longer.
        duration = cfg.mute_duration_minutes * max(1, st.mute_count + 1)
        st.muted_until = now + timedelta(minutes=duration)
        st.mute_count += 1
        st.promoted = False
        logger.warning(
            "ASSET GOVERNOR: muting %s for %d min. %dW/%dL (WR %.1f%%), "
            "Wilson upper bound %.1f%% is still below break-even %.1f%%.",
            asset,
            duration,
            st.wins,
            st.losses,
            st.win_rate * 100.0,
            upper * 100.0,
            break_even * 100.0,
        )

    def _apply_promotion_rule(self, asset: str, st: AssetStats, payout_rate: float) -> None:
        cfg = self.config
        if st.promoted or st.decided < cfg.promotion_min_trades:
            return

        lower = wilson_lower_bound(st.wins, st.decided, cfg.promotion_confidence_z)
        if lower <= break_even_win_rate(payout_rate):
            return

        st.promoted = True
        logger.info(
            "ASSET GOVERNOR: promoting %s. %dW/%dL (WR %.1f%%), Wilson lower bound "
            "%.1f%% clears break-even on %d trades.",
            asset,
            st.wins,
            st.losses,
            st.win_rate * 100.0,
            lower * 100.0,
            st.decided,
        )
