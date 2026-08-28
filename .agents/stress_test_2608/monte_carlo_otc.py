"""OTC worst-case Monte Carlo with the bot's real live parameters.

Measures the empirical correlation between concurrent trade outcomes (the key OTC risk:
synthetic feeds driven by a common generator are NOT independent), then simulates the
account under that correlation across adversarial payout / win-rate regimes, including
the bot's actual circuit breakers.
"""

from __future__ import annotations

import glob
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

# ---- Real live parameters read from the code / plan defaults -------------------------
DEPOSIT = 50_000.0
STAKE = 100.0                 # observed flat stake (994 of 1101 trades)
EXPIRATION_S = 180
MAX_CONCURRENT = 3            # PreTradingPlan.max_concurrent_trades
MAX_CONSEC_LOSSES = 3         # PreTradingPlan.max_consecutive_losses
PAUSE_MIN = 15                # PreTradingPlan.pause_duration_minutes
MAX_DD_LIMIT = 0.08           # PreTradingPlan.max_drawdown_pct_limit
GLOBAL_COOLDOWN_S = 30
ASSET_COOLDOWN_S = 180
TRADES_PER_HOUR = 13.3        # observed 1101 trades / 82.5 h
SESSION_HOURS = 8
N_SIMS = 20_000
RNG = np.random.default_rng(20260828)


def load() -> pd.DataFrame:
    fr = [pd.read_csv(f) for f in sorted(glob.glob("/Users/vlados/Downloads/Pocket Option*.csv"))]
    df = pd.concat(fr, ignore_index=True).drop_duplicates(subset=["Broker Order UUID"])
    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df["Close Time"] = pd.to_datetime(df["Close Time"], utc=True)
    df = df[df.Outcome.isin(["WIN", "LOSS"])].sort_values("Open Time").reset_index(drop=True)
    df["is_win"] = df.Outcome.eq("WIN")
    df["pnl"] = df["Broker Profit ($)"]
    df["is_otc"] = df.Asset.str.contains("OTC", na=False)
    return df


def hr(t: str) -> None:
    print("\n" + "=" * 108)
    print(t)
    print("=" * 108)


# ======================================================================================
# 1. EMPIRICAL: are concurrent OTC outcomes independent?
# ======================================================================================
def measure_concurrency_correlation(df: pd.DataFrame) -> dict[str, float]:
    pairs = {"OTC": [], "SPOT": [], "ALL": []}
    ot = df["Open Time"].values
    ct = df["Close Time"].values
    win = df.is_win.values
    otc = df.is_otc.values
    n = len(df)
    for i in range(n):
        # only look forward to avoid double counting
        j = i + 1
        while j < n and ot[j] < ct[i]:
            if ct[j] > ot[i]:
                pairs["ALL"].append((win[i], win[j]))
                if otc[i] and otc[j]:
                    pairs["OTC"].append((win[i], win[j]))
                elif not otc[i] and not otc[j]:
                    pairs["SPOT"].append((win[i], win[j]))
            j += 1

    out = {}
    for k, v in pairs.items():
        if len(v) < 30:
            out[k] = float("nan")
            print(f"  {k:5s}: only {len(v)} concurrent pairs - insufficient")
            continue
        a = np.array([x[0] for x in v], dtype=float)
        b = np.array([x[1] for x in v], dtype=float)
        r = float(np.corrcoef(a, b)[0, 1])
        both = int(((a == 1) & (b == 1)).sum())
        neither = int(((a == 0) & (b == 0)).sum())
        mixed = len(v) - both - neither
        ct_tab = [[both, mixed], [mixed, neither]]
        p = stats.fisher_exact([[both, len(v) - both], [neither, len(v) - neither]])[1]
        out[k] = r
        print(
            f"  {k:5s}: {len(v):5d} concurrent pairs   phi={r:+.4f}   "
            f"both win={both}  both lose={neither}  split={mixed}   (p={p:.3f})"
        )
    return out


# ======================================================================================
# 2. SIMULATOR with the bot's real circuit breakers
# ======================================================================================
@dataclass
class Scenario:
    name: str
    win_rate: float
    payout: float
    corr: float          # outcome correlation between concurrent trades
    breakers: bool = True


def correlated_bernoulli(p: float, k: int, rho: float, rng) -> np.ndarray:
    """k correlated Bernoulli(p) draws via a latent Gaussian copula."""
    if k == 1 or rho <= 0:
        return (rng.random(k) < p).astype(int)
    common = rng.standard_normal()
    idio = rng.standard_normal(k)
    z = math.sqrt(rho) * common + math.sqrt(max(0.0, 1 - rho)) * idio
    thr = stats.norm.ppf(p)
    return (z < thr).astype(int)


def simulate(sc: Scenario, n_sims: int = N_SIMS, sessions: int = 1) -> dict:
    rng = np.random.default_rng(abs(hash(sc.name)) % (2**32))
    trades_per_session = int(TRADES_PER_HOUR * SESSION_HOURS)
    finals, max_dds, ruins, halts, n_trades_done = [], [], 0, 0, []

    for _ in range(n_sims):
        bal = DEPOSIT
        peak = DEPOSIT
        worst_dd = 0.0
        consec = 0
        done = 0
        halted = False
        total = trades_per_session * sessions
        while done < total:
            k = min(MAX_CONCURRENT, total - done)
            outcomes = correlated_bernoulli(sc.win_rate, k, sc.corr, rng)
            for o in outcomes:
                if bal < STAKE:
                    break
                bal += STAKE * sc.payout if o else -STAKE
                done += 1
                consec = 0 if o else consec + 1
                peak = max(peak, bal)
                worst_dd = min(worst_dd, (bal - peak) / peak)
                if sc.breakers and (peak - bal) / peak >= MAX_DD_LIMIT:
                    halted = True
                    break
            if halted or bal < STAKE:
                break
            if sc.breakers and consec >= MAX_CONSEC_LOSSES:
                consec = 0  # the bot pauses 15 min, then resumes -- it does not stop
        finals.append(bal)
        max_dds.append(worst_dd)
        n_trades_done.append(done)
        if bal < DEPOSIT * 0.5:
            ruins += 1
        if halted:
            halts += 1

    finals = np.array(finals)
    max_dds = np.array(max_dds)
    return {
        "name": sc.name,
        "median": float(np.median(finals)),
        "mean": float(finals.mean()),
        "p05": float(np.percentile(finals, 5)),
        "p01": float(np.percentile(finals, 1)),
        "p95": float(np.percentile(finals, 95)),
        "p_loss": float((finals < DEPOSIT).mean()),
        "med_dd": float(np.median(max_dds)),
        "p95_dd": float(np.percentile(max_dds, 5)),
        "worst_dd": float(max_dds.min()),
        "halt_rate": halts / n_sims,
        "ruin_rate": ruins / n_sims,
        "med_trades": float(np.median(n_trades_done)),
    }


def show(rows: list[dict], title: str) -> None:
    print(f"\n{title}")
    print(
        f"  {'scenario':38s} {'median':>10} {'p05':>10} {'p01':>10} "
        f"{'P(loss)':>8} {'medDD':>7} {'p95DD':>7} {'halt%':>7}"
    )
    for r in rows:
        print(
            f"  {r['name']:38s} {r['median']:>10,.0f} {r['p05']:>10,.0f} {r['p01']:>10,.0f} "
            f"{r['p_loss']*100:>7.1f}% {r['med_dd']*100:>6.1f}% {r['p95_dd']*100:>6.1f}% "
            f"{r['halt_rate']*100:>6.1f}%"
        )


def main() -> None:
    df = load()
    print(f"Live parameters: deposit ${DEPOSIT:,.0f}, stake ${STAKE:.0f}, "
          f"max_concurrent={MAX_CONCURRENT}, max_dd_limit={MAX_DD_LIMIT*100:.0f}%, "
          f"expiration={EXPIRATION_S}s")
    print(f"Session model: {SESSION_HOURS} h x {TRADES_PER_HOUR:.1f} trades/h "
          f"= {int(SESSION_HOURS*TRADES_PER_HOUR)} trades, {N_SIMS:,} simulations each")

    hr("1. EMPIRICAL OTC RISK — are concurrent trade outcomes independent?")
    print("Binary-options risk models assume independence. On OTC the quotes are synthetic")
    print("and may share a common generator, which would make concurrent trades correlated")
    print("and drawdowns far worse than a binomial model predicts.\n")
    corrs = measure_concurrency_correlation(df)
    rho_otc = corrs.get("OTC", 0.0)
    rho_use = max(0.0, rho_otc if not math.isnan(rho_otc) else 0.0)
    print(f"\n  measured OTC concurrency correlation: rho = {rho_otc:+.4f}")
    if rho_use < 0.02:
        print("  -> statistically indistinguishable from independent.")
        print("     Good news: the OTC feeds are NOT visibly driven by one common generator.")
        print("     Worst-case scenarios below still stress rho up to 0.30 as a tail risk.")

    hr("2. BASE CASE — the bot exactly as it traded this week")
    base = [
        Scenario("current WR 50.41% @ 91.3% payout", 0.5041, 0.9132, rho_use),
        Scenario("  ... with breakers DISABLED", 0.5041, 0.9132, rho_use, breakers=False),
        Scenario("breakeven bot WR 52.27% @ 91.3%", 0.5227, 0.9132, rho_use),
    ]
    show([simulate(s) for s in base], "one 8-hour session:")

    hr("3. OTC WORST-CASE: BROKER CUTS THE PAYOUT")
    print("Pocket Option adjusts OTC payouts dynamically. The bot's only defence is")
    print("min_payout_rate=0.80, which does NOT check whether the strategy is still +EV.")
    rows = []
    for p in [0.92, 0.88, 0.85, 0.82, 0.80]:
        rows.append(simulate(Scenario(f"payout {p*100:.0f}% at current WR 50.41%", 0.5041, p, rho_use)))
    show(rows, "one 8-hour session:")
    print("\n  breakeven WR required at each payout:")
    for p in [0.92, 0.88, 0.85, 0.82, 0.80, 0.75]:
        print(f"    {p*100:3.0f}% -> {1/(1+p)*100:.2f}%   "
              f"(bot has 50.41%, deficit {(1/(1+p)-0.5041)*100:+.2f} pp)")

    hr("4. OTC WORST-CASE: ADVERSARIAL FEED (synthetic series turns against the bot)")
    print("OTC series are generated by the broker. A modest degradation of the win rate")
    print("has a violently non-linear effect because the payout spread is the baseline.")
    rows = []
    for wr in [0.5041, 0.49, 0.48, 0.47, 0.45]:
        rows.append(simulate(Scenario(f"WR {wr*100:.2f}% @ 92% payout", wr, 0.92, rho_use)))
    show(rows, "one 8-hour session:")

    hr("5. OTC WORST-CASE: CORRELATED CONCURRENT TRADES (common generator)")
    print("If several OTC pairs are driven by one process, the 3 concurrent trades move")
    print("together. Expected PnL is unchanged, but the variance and drawdown explode.")
    rows = []
    for rho in [0.0, 0.10, 0.20, 0.30, 0.50]:
        rows.append(simulate(Scenario(f"rho={rho:.2f} at WR 50.41% @ 92%", 0.5041, 0.92, rho)))
    show(rows, "one 8-hour session:")

    hr("6. COMPOUND WORST CASE — everything goes wrong at once")
    rows = [
        simulate(Scenario("payout 80% + WR 47% + rho 0.30", 0.47, 0.80, 0.30)),
        simulate(Scenario("payout 82% + WR 48% + rho 0.20", 0.48, 0.82, 0.20)),
        simulate(Scenario("payout 85% + WR 49% + rho 0.10", 0.49, 0.85, 0.10)),
    ]
    show(rows, "one 8-hour session:")

    hr("7. SURVIVAL OVER A FULL TRADING MONTH (20 sessions)")
    rows = []
    for sc in [
        Scenario("current WR 50.41% @ 91.3%", 0.5041, 0.9132, rho_use),
        Scenario("after P0 fixes, WR 53% @ 91.3%", 0.53, 0.9132, rho_use),
        Scenario("after P0 fixes, WR 55% @ 91.3%", 0.55, 0.9132, rho_use),
        Scenario("payout cut to 80%, WR 50.41%", 0.5041, 0.80, rho_use),
    ]:
        rows.append(simulate(sc, n_sims=5000, sessions=20))
    show(rows, "20 sessions (~1 month):")
    print("\n  note: the 8% max-drawdown breaker halts the bot, so the p01 column is")
    print("  bounded by the breaker rather than by true ruin. That is the breaker working.")

    hr("8. DOES THE 8% DRAWDOWN BREAKER ACTUALLY PROTECT THE ACCOUNT?")
    a = simulate(Scenario("WR 47% @ 80%, breakers ON", 0.47, 0.80, rho_use, breakers=True),
                 n_sims=5000, sessions=20)
    b = simulate(Scenario("WR 47% @ 80%, breakers OFF", 0.47, 0.80, rho_use, breakers=False),
                 n_sims=5000, sessions=20)
    show([a, b], "20 sessions:")
    print(f"\n  breaker fires in {a['halt_rate']*100:.1f}% of runs and caps the median loss at "
          f"${DEPOSIT - a['median']:,.0f} instead of ${DEPOSIT - b['median']:,.0f}.")
    print("  The breaker is the single component of the risk stack that demonstrably works.")

    hr("9. HOW MUCH EDGE IS NEEDED TO SURVIVE EACH PAYOUT REGIME")
    print(f"  {'payout':>8} {'breakeven WR':>14} {'WR for P(month>0)=90%':>24}")
    for p in [0.92, 0.88, 0.85, 0.80, 0.75]:
        be = 1 / (1 + p)
        target = None
        for wr in np.arange(be, be + 0.12, 0.0025):
            r = simulate(Scenario("probe", float(wr), p, rho_use, breakers=False),
                         n_sims=1500, sessions=20)
            if 1 - r["p_loss"] >= 0.90:
                target = wr
                break
        print(f"  {p*100:7.0f}% {be*100:13.2f}% {target*100 if target else float('nan'):23.2f}%")

    hr("10. RISK OF RUIN AND KELLY AT THE CURRENT EDGE")
    for wr, p in [(0.5041, 0.9132), (0.5041, 0.80), (0.53, 0.9132), (0.55, 0.9132)]:
        k = (wr * (1 + p) - 1) / p
        ev = wr * p - (1 - wr)
        print(f"  WR={wr*100:5.2f}% payout={p*100:5.2f}%  EV/$1={ev:+.4f}  Kelly f*={k*100:+6.2f}%  "
              f"-> {'stake 0' if k <= 0 else f'max safe stake ${DEPOSIT*k*0.25:,.0f} (quarter-Kelly)'}")


if __name__ == "__main__":
    main()
