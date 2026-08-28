"""Full-week verdict: reconcile with balance, then test whether the bot has an edge."""

from __future__ import annotations

import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DOWNLOADS = Path("/Users/vlados/Downloads")
DEPOSIT_START = 50000.0
DEPOSIT_NOW = 46494.0


def load() -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(DOWNLOADS / "Pocket Option*.csv"))):
        d = pd.read_csv(f)
        d["src"] = Path(f).name
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)
    dupes = raw.duplicated(subset=["Broker Order UUID"]).sum()
    df = raw.drop_duplicates(subset=["Broker Order UUID"]).copy()
    df.attrs["raw_rows"] = len(raw)
    df.attrs["dupes"] = int(dupes)

    df["Open Time"] = pd.to_datetime(df["Open Time"], utc=True)
    df["Close Time"] = pd.to_datetime(df["Close Time"], utc=True)
    df["conf"] = pd.to_numeric(
        df["Confidence %"].astype(str).str.rstrip("%"), errors="coerce"
    )
    df = df.sort_values("Open Time").reset_index(drop=True)

    df["is_win"] = df["Outcome"].eq("WIN")
    df["is_loss"] = df["Outcome"].eq("LOSS")
    df["stake"] = df["Trade Amount ($)"]
    df["pnl"] = df["Broker Profit ($)"]
    df["px"] = df["Broker Open Price"]
    df["move"] = df["Broker Close Price"] - df["Broker Open Price"]
    df["move_abs"] = df["move"].abs()
    df["move_bps"] = df["move"] / df["px"] * 1e4
    df["atr_bps"] = df["ATR"] / df["px"] * 1e4
    df["slip_bps"] = df["Slippage"] / df["px"] * 1e4
    df["signed_move"] = np.where(df.Direction == "CALL", df.move_bps, -df.move_bps)
    df["sec"] = df["Open Time"].dt.second
    df["day"] = df["Open Time"].dt.date
    df["hour"] = df["Open Time"].dt.hour
    df["is_otc"] = df["Asset"].str.contains("OTC", na=False)
    df["payout_real"] = np.where(df.is_win, df.pnl / df.stake, np.nan)
    return df


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def block(df: pd.DataFrame, key: str, be: float = 1 / 1.92) -> pd.DataFrame:
    rows = []
    for name, s in df.groupby(key, observed=True):
        w = int(s.is_win.sum())
        n = w + int(s.is_loss.sum())
        if n == 0:
            continue
        lo, hi = wilson(w, n)
        rows.append(
            {
                key: name,
                "n": n,
                "wr%": round(w / n * 100, 1),
                "lo95": round(lo * 100, 1),
                "hi95": round(hi * 100, 1),
                "pnl$": round(s.pnl.sum()),
                "turnover$": round(s.stake.sum()),
                "roi%": round(s.pnl.sum() / s.stake.sum() * 100, 2),
                "p>BE": round(stats.binomtest(w, n, be, alternative="greater").pvalue, 4),
            }
        )
    return pd.DataFrame(rows).sort_values("pnl$")


def hr(t: str) -> None:
    print("\n" + "=" * 108)
    print(t)
    print("=" * 108)


def main() -> None:
    df = load()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 400)
    pd.set_option("display.max_columns", 60)

    w = int(df.is_win.sum())
    l_ = int(df.is_loss.sum())
    n = w + l_
    wr = w / n
    pnl = df.pnl.sum()
    turn = df.stake.sum()
    avg_payout = df.payout_real.mean()
    be = 1 / (1 + avg_payout)

    hr("0. RECONCILIATION WITH THE ACTUAL DEMO BALANCE")
    print(f"raw CSV rows           : {df.attrs['raw_rows']}")
    print(f"duplicate order UUIDs  : {df.attrs['dupes']}  (removed)")
    print(f"unique trades          : {len(df)}")
    print(f"period                 : {df['Open Time'].min()}  ->  {df['Open Time'].max()}")
    span_h = (df["Open Time"].max() - df["Open Time"].min()).total_seconds() / 3600
    print(f"calendar span          : {span_h:.1f} h ({span_h/24:.1f} days)")
    print()
    print(f"deposit start          : ${DEPOSIT_START:,.0f}")
    print(f"deposit now            : ${DEPOSIT_NOW:,.0f}")
    print(f"actual change          : ${DEPOSIT_NOW - DEPOSIT_START:,.0f}")
    print(f"sum of CSV Broker Profit: ${pnl:,.0f}")
    print(f"unexplained difference : ${(DEPOSIT_NOW - DEPOSIT_START) - pnl:,.0f}")
    print(f"  -> {'MATCH (log is complete)' if abs((DEPOSIT_NOW-DEPOSIT_START)-pnl) < 50 else 'MISMATCH: the log does not fully explain the balance'}")
    print()
    print(f"Is Bot Trade   : {df['Is Bot Trade'].value_counts().to_dict()}")
    print(f"Outcome counts : {df['Outcome'].value_counts().to_dict()}")

    hr("1. VERDICT — is the bot profitable? (formal hypothesis test)")
    lo, hi = wilson(w, n)
    print(f"decisive trades  : {n}   (W={w}  L={l_}  draw/other={len(df)-n})")
    print(f"win rate         : {wr*100:.2f}%   95% CI = [{lo*100:.2f}% .. {hi*100:.2f}%]")
    print(f"realized payout  : mean {avg_payout*100:.2f}%  ->  breakeven WR = {be*100:.2f}%")
    print(f"gap to breakeven : {wr*100 - be*100:+.2f} pp")
    print(f"net PnL          : ${pnl:,.0f}  on ${turn:,.0f} turnover   ROI = {pnl/turn*100:.2f}%")
    print(f"EV per $1 staked : ${pnl/turn:+.4f}")
    print()
    p_gt = stats.binomtest(w, n, be, alternative="greater").pvalue
    p_lt = stats.binomtest(w, n, be, alternative="less").pvalue
    print("H0: WR = breakeven")
    print(f"  P(WR > BE)  one-sided p = {p_gt:.6f}   -> {'cannot claim profitable' if p_gt > 0.05 else 'PROFITABLE'}")
    print(f"  P(WR < BE)  one-sided p = {p_lt:.6f}   -> {'PROVEN UNPROFITABLE (p<0.05)' if p_lt < 0.05 else 'not proven unprofitable'}")
    print()
    print(f"Upper bound of the 95% CI is {hi*100:.2f}% vs breakeven {be*100:.2f}%")
    if hi < be:
        print("  -> Even the MOST OPTIMISTIC reading of this sample is below breakeven.")
        print("  -> The bot is statistically PROVEN to be unprofitable. This is not noise.")
    else:
        print(f"  -> CI still overlaps breakeven by {(hi-be)*100:.2f} pp.")

    # Monte Carlo
    rng = np.random.default_rng(7)
    sims = rng.binomial(n, be, 50000)
    sim_pnl = sims * 100 * avg_payout - (n - sims) * 100
    obs_pnl_norm = w * 100 * avg_payout - l_ * 100
    print()
    print(f"Monte-Carlo (50k runs) under H0 (p = BE), all at $100 flat:")
    print(f"  observed-equivalent PnL = ${obs_pnl_norm:,.0f}")
    print(f"  H0 mean = ${sim_pnl.mean():,.0f}  sd = ${sim_pnl.std():,.0f}")
    print(f"  P(H0 result <= observed) = {(sim_pnl <= obs_pnl_norm).mean():.5f}")

    # power
    print()
    print("Statistical power of THIS sample:")
    for target in [0.55, 0.56, 0.58, 0.60]:
        za, zb = 1.645, 0.842
        nn = ((za * math.sqrt(be * (1 - be)) + zb * math.sqrt(target * (1 - target))) / (target - be)) ** 2
        print(f"  n needed to prove a true {target*100:.0f}% WR : {nn:,.0f}   "
              f"({'HAVE ENOUGH' if n >= nn else f'have {n}, short by {nn-n:,.0f}'})")

    hr("2. EQUITY CURVE / DRAWDOWN")
    eq = DEPOSIT_START + df.pnl.cumsum()
    peak = eq.cummax()
    dd = eq - peak
    ddp = dd / peak * 100
    print(f"final equity (from log) : ${eq.iloc[-1]:,.0f}")
    print(f"max drawdown            : ${dd.min():,.0f}  ({ddp.min():.2f}% of peak)")
    print(f"peak equity             : ${peak.max():,.0f}")
    print(f"time under water        : {(dd < 0).mean()*100:.1f}% of all trades")
    seq = df.Outcome.tolist()
    mx = cur = 0
    for o in seq:
        cur = cur + 1 if o == "LOSS" else 0
        mx = max(mx, cur)
    print(f"longest losing streak   : {mx}")
    mxw = cur = 0
    for o in seq:
        cur = cur + 1 if o == "WIN" else 0
        mxw = max(mxw, cur)
    print(f"longest winning streak  : {mxw}")
    wins = df.is_win.astype(int).values
    runs = 1 + int((np.diff(wins) != 0).sum())
    n1, n2 = wins.sum(), len(wins) - wins.sum()
    er = 2 * n1 * n2 / (n1 + n2) + 1
    vr = (2 * n1 * n2 * (2 * n1 * n2 - n1 - n2)) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
    z = (runs - er) / math.sqrt(vr)
    print(f"runs test z={z:+.3f} p={2*(1-stats.norm.cdf(abs(z))):.4f} "
          f"({'outcomes are independent -> no streak structure to exploit' if abs(z)<1.96 else 'streaks are NOT random'})")

    hr("3. PER DAY")
    print(block(df, "day", be).sort_values("day").to_string(index=False))

    hr("4. PER SESSION FILE")
    print(block(df, "src", be).to_string(index=False))

    hr("5. PER STRATEGY")
    print(block(df, "Strategy Name", be).to_string(index=False))

    hr("6. PER DIRECTION  (the CALL leak, now with full power)")
    print(block(df, "Direction", be).to_string(index=False))
    call, put = df[df.Direction == "CALL"], df[df.Direction == "PUT"]
    cw, cn = int(call.is_win.sum()), int(call.is_win.sum() + call.is_loss.sum())
    pw, pn = int(put.is_win.sum()), int(put.is_win.sum() + put.is_loss.sum())
    ct = stats.chi2_contingency([[cw, cn - cw], [pw, pn - pw]])
    print(f"\nchi2 CALL vs PUT: chi2={ct.statistic:.3f}  p={ct.pvalue:.6f}")
    print(f"Fisher exact p  = {stats.fisher_exact([[cw, cn-cw], [pw, pn-pw]])[1]:.6f}")
    print(f"\nmean signed move | CALL = {call.signed_move.mean():+.3f} bps")
    print(f"mean signed move | PUT  = {put.signed_move.mean():+.3f} bps")
    print("\nCALL/PUT per strategy:")
    r = []
    for s, sub in df.groupby("Strategy Name"):
        for d, s2 in sub.groupby("Direction"):
            nn = int(s2.is_win.sum() + s2.is_loss.sum())
            if nn:
                r.append({"strategy": s, "dir": d, "n": nn,
                          "wr%": round(int(s2.is_win.sum()) / nn * 100, 1),
                          "pnl$": round(s2.pnl.sum())})
    print(pd.DataFrame(r).to_string(index=False))

    hr("7. DIRECTIONAL SKILL — does the signal predict the move at all?")
    sm = df.signed_move
    t = stats.ttest_1samp(sm.dropna(), 0)
    print("signed_move > 0 means price moved the way the bot bet (bps)")
    print(sm.describe(percentiles=[0.25, 0.5, 0.75]).round(3).to_string())
    print(f"\nmean = {sm.mean():+.4f} bps   t = {t.statistic:+.3f}   p = {t.pvalue:.5f}")
    print(f"median = {sm.median():+.4f} bps   Wilcoxon p = {stats.wilcoxon(sm.dropna()).pvalue:.5f}")
    if t.pvalue < 0.05 and sm.mean() < 0:
        print("  -> NEGATIVE directional skill is now STATISTICALLY SIGNIFICANT.")
    elif sm.mean() < 0:
        print("  -> negative but still within noise; the loss is driven by the payout spread.")
    print("\nsigned edge by strategy:")
    print(df.groupby("Strategy Name").signed_move.agg(["count", "mean", "median"]).round(3)
          .sort_values("mean").to_string())

    hr("8. INVERSION TEST — would the opposite bet be profitable?")
    for p in [avg_payout, 0.92, 0.85, 0.80, 0.75]:
        a = w * 100 * p - l_ * 100
        b = l_ * 100 * p - w * 100
        print(f"  payout {p*100:5.2f}%: as-is WR={wr*100:.2f}% PnL=${a:+,.0f}   |   "
              f"INVERTED WR={l_/n*100:.2f}% PnL=${b:+,.0f}")

    hr("9. EV AT LOWER PAYOUTS (the 75-85% question)")
    print(f"{'payout':>8} {'BE_WR':>8} {'gap_pp':>8} {'PnL@100flat':>14} {'ROI':>9}")
    for p in [0.92, 0.90, 0.88, 0.85, 0.82, 0.80, 0.77, 0.75]:
        bep = 1 / (1 + p)
        pl = w * 100 * p - l_ * 100
        print(f"{p*100:7.0f}% {bep*100:7.2f}% {(wr-bep)*100:+7.2f} {pl:+14,.0f} {pl/(n*100)*100:+8.2f}%")

    hr("10. CONFIDENCE CALIBRATION")
    print(block(df.dropna(subset=["conf"]), "conf", be).sort_values("conf").to_string(index=False))
    sub = df.dropna(subset=["conf"])
    r_, p_ = stats.pointbiserialr(sub.is_win.astype(int), sub.conf)
    print(f"\npoint-biserial corr(conf, win) = {r_:+.4f}  p = {p_:.4f}")
    print(f"mean conf | WIN = {sub.loc[sub.is_win,'conf'].mean():.2f}   "
          f"| LOSS = {sub.loc[sub.is_loss,'conf'].mean():.2f}")
    hi_, lo2 = sub[sub.conf >= 85], sub[sub.conf < 85]
    a, b = int(hi_.is_win.sum()), int(hi_.is_win.sum() + hi_.is_loss.sum())
    c, d = int(lo2.is_win.sum()), int(lo2.is_win.sum() + lo2.is_loss.sum())
    print(f"conf>=85: n={b} WR={a/b*100:.2f}%  |  conf<85: n={d} WR={c/d*100:.2f}%  "
          f"Fisher p={stats.fisher_exact([[a,b-a],[c,d-c]])[1]:.4f}")
    # monotonicity
    g = sub.groupby("conf").is_win.mean()
    rho, prho = stats.spearmanr(g.index, g.values)
    print(f"Spearman(conf_bucket, WR) = {rho:+.3f} p={prho:.3f}  "
          f"(a working score would be strongly positive)")

    hr("11. SLIPPAGE / EXECUTION")
    print(f"median |move to expiry| : {df.move_abs.div(df.px).mul(1e4).median():.2f} bps")
    print(f"median ATR              : {df.atr_bps.median():.2f} bps")
    print(f"median slippage         : {df.slip_bps.median():.2f} bps")
    print(f"median slip/ATR ratio   : {(df.slip_bps/df.atr_bps).median():.2f}")
    fl = df.Slippage > df.move_abs
    print(f"\ntrades where entry error > move to expiry: {fl.sum()}/{len(df)} = {fl.mean()*100:.1f}%")
    for f_, s in df.groupby(fl):
        nn = int(s.is_win.sum() + s.is_loss.sum())
        print(f"  error_dominates={f_}: n={nn:4d} WR={int(s.is_win.sum())/nn*100:5.2f}% PnL=${s.pnl.sum():+,.0f}")
    print("\nslippage by asset (worst 12):")
    g2 = df.groupby("Asset").agg(n=("slip_bps", "size"), slip=("slip_bps", "median"),
                                 atr=("atr_bps", "median"), pnl=("pnl", "sum"))
    g2["slip/atr"] = (g2.slip / g2.atr).round(2)
    print(g2.sort_values("slip", ascending=False).head(12).round(2).to_string())

    hr("12. CANDLE SYNC")
    df["sec_bin"] = pd.cut(df.sec, [-1, 2, 5, 10, 20, 60],
                           labels=["0-2", "3-5", "6-10", "11-20", "21-60"])
    print(block(df, "sec_bin", be).to_string(index=False))
    print(f"\nmean seconds into the M1 bar at entry: {df.sec.mean():.1f}")
    print(f"trades NOT aligned to the bar (sec>2) : {(df.sec>2).sum()}/{len(df)} = {(df.sec>2).mean()*100:.1f}%")

    hr("13. OTC vs SPOT")
    print(block(df, "is_otc", be).to_string(index=False))
    print()
    for f_, s in df.groupby("is_otc"):
        print(f"  {'OTC ' if f_ else 'SPOT'}: median ATR={s.atr_bps.median():.2f} bps  "
              f"median slip={s.slip_bps.median():.2f} bps  turnover_share={s.stake.sum()/turn*100:.0f}%")
    exotic = df[df.Asset.str.contains("MAD|KES|TND|YER|ARS|SGD|IDR|BHD|OMR|QAR|EGP|NGN|UAH|VND|PHP|COP|CLP|PKR|BDT|LBP|JOD|SAR|DZD|IRR|SYP|ZAR|BRL|MXN|TRY|INR", na=False)]
    if len(exotic):
        nn = int(exotic.is_win.sum() + exotic.is_loss.sum())
        print(f"\nEXOTIC synthetic OTC: n={nn} WR={int(exotic.is_win.sum())/nn*100:.2f}% PnL=${exotic.pnl.sum():+,.0f}")
        print("  assets:", sorted(exotic.Asset.unique()))

    hr("14. PER ASSET (with multiple-testing correction)")
    ba = block(df, "Asset", be)
    ntests = len(ba)
    ba["bonf_ok"] = ba["p>BE"] < 0.05 / ntests
    print(ba.to_string(index=False))
    print(f"\nassets tested = {ntests}; Bonferroni alpha = {0.05/ntests:.5f}")
    print(f"assets that survive correction as profitable: {int(ba.bonf_ok.sum())}")
    # Benjamini-Hochberg
    pv = np.sort(ba["p>BE"].values)
    m = len(pv)
    bh = pv <= (np.arange(1, m + 1) / m) * 0.05
    print(f"Benjamini-Hochberg FDR 5% discoveries: {int(bh.sum())}")

    hr("15. PER HOUR (UTC)")
    bh2 = block(df, "hour", be).sort_values("hour")
    bh2["bonf_ok"] = bh2["p>BE"] < 0.05 / len(bh2)
    print(bh2.to_string(index=False))

    hr("16. OVERFITTING FOOTPRINT")
    df["combo"] = df["Strategy Name"] + " | " + df["Strategy Parameters"].astype(str)
    cells = df.groupby(["Asset", "combo"]).size()
    print(f"distinct (asset x strategy x params) cells : {len(cells)}")
    print(f"trades                                    : {len(df)}")
    print(f"mean trades per cell                      : {cells.mean():.2f}")
    print(f"cells with <10 trades                     : {(cells<10).sum()} ({(cells<10).mean()*100:.0f}%)")
    print(f"cells with 1 trade                        : {(cells==1).sum()}")
    print(f"distinct assets / strategies / param-sets : "
          f"{df.Asset.nunique()} / {df['Strategy Name'].nunique()} / {df['Strategy Parameters'].nunique()}")
    print(f"expected false winners at alpha=.05       : {len(cells)*0.05:.1f}")

    hr("17. DATA INTEGRITY")
    for c in ["RSI", "ADX", "ATR", "Stoch %K", "Confidence %", "Slippage"]:
        nn = df[c].notna().sum()
        print(f"  {c:14s}: {nn:5d}/{len(df)} ({nn/len(df)*100:5.1f}%)")
    print()
    print("strategy-name aliases present:")
    print(df["Strategy Name"].value_counts().to_string())
    import ast
    mm = 0
    for _, row in df.iterrows():
        try:
            k = set(ast.literal_eval(str(row["Strategy Parameters"])).keys())
        except Exception:
            continue
        s = str(row["Strategy Name"]).lower()
        if ("pin" in s) and not ({"swing_window", "min_wick_ratio"} & k):
            mm += 1
        elif ("ema" in s or "ribbon" in s) and not ({"ema_fast", "ema_mid"} & k):
            mm += 1
        elif ("rsi" in s and "stoch" in s) and not ({"rsi_period", "rsi_oversold"} & k):
            mm += 1
    print(f"\ntrades whose logged params contradict their strategy schema: {mm}/{len(df)} ({mm/len(df)*100:.1f}%)")

    hr("18. STAKE / EXPIRATION")
    print(block(df, "stake", be).to_string(index=False))
    df["hold"] = (df["Close Time"] - df["Open Time"]).dt.total_seconds()
    print()
    print(block(df, "hold", be).to_string(index=False))

    hr("19. WHAT IT WOULD TAKE TO BREAK EVEN")
    print(f"current WR {wr*100:.2f}%, need {be*100:.2f}% -> must gain {(be-wr)*100:.2f} pp")
    extra = math.ceil(be * n - w)
    print(f"on this sample that is {extra} more wins out of the same {n} trades "
          f"({extra/n*100:.1f}% of all trades flipped)")
    print()
    print("If the CALL book were simply switched off (keep PUT only):")
    pw2, pl2 = int(put.is_win.sum()), int(put.is_loss.sum())
    print(f"  n={pw2+pl2}  WR={pw2/(pw2+pl2)*100:.2f}%  PnL=${put.pnl.sum():+,.0f}  "
          f"(BE={be*100:.2f}%)")
    print("If only trades with entry error < 1 ATR were taken:")
    cl = df[df.slip_bps < df.atr_bps]
    if len(cl):
        cw2, cl2 = int(cl.is_win.sum()), int(cl.is_loss.sum())
        print(f"  n={cw2+cl2}  WR={cw2/(cw2+cl2)*100:.2f}%  PnL=${cl.pnl.sum():+,.0f}")
    print("If SPOT only:")
    sp = df[~df.is_otc]
    sw, sl = int(sp.is_win.sum()), int(sp.is_loss.sum())
    if sw + sl:
        print(f"  n={sw+sl}  WR={sw/(sw+sl)*100:.2f}%  PnL=${sp.pnl.sum():+,.0f}")


if __name__ == "__main__":
    main()
