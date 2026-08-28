"""
Empirical Quant Math & Monte Carlo Verification Script
Challenger 1: Mathematical and Simulation Verification of STRESS_TEST_REPORT.md
"""

import math
import numpy as np
import pandas as pd

def print_header(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)

# ----------------------------------------------------------------------
# 1. Breakeven Win Rates & Profit Factor Formulas
# ----------------------------------------------------------------------
def verify_breakeven_tables():
    print_header("1. BREAKEVEN WIN RATES & PROFIT FACTORS")
    payouts = [0.70, 0.75, 0.80, 0.85, 0.90, 0.92]
    results = []
    for P in payouts:
        p_be = 1.0 / (1.0 + P)
        min_wins_100 = math.ceil(p_be * 100)
        # PF = (p * P) / (1 - p) => p * P = PF - p * PF => p * (P + PF) = PF => p = PF / (P + PF)
        p_pf_120 = 1.20 / (P + 1.20)
        p_pf_140 = 1.40 / (P + 1.40)
        results.append({
            "Payout": f"{P*100:.1f}%",
            "p_BE (%)": f"{p_be*100:.4f}%",
            "Min Wins/100": min_wins_100,
            "Target WR (PF=1.20)": f"{p_pf_120*100:.2f}%",
            "Target WR (PF=1.40)": f"{p_pf_140*100:.2f}%"
        })
    df = pd.DataFrame(results)
    print(df.to_string(index=False))
    return df

# ----------------------------------------------------------------------
# 2. Mathematical Expectancy Worked Examples & Sensitivity Matrix
# ----------------------------------------------------------------------
def verify_ev_and_sensitivity():
    print_header("2. EXPECTANCY (EV) CALCULATIONS & SENSITIVITY MATRIX")
    
    # Worked Example A
    ev_a = 0.56 * 0.80 - (1 - 0.56)
    ret_500_a = 500 * 10.0 * ev_a
    print(f"Example A (p=56%, P=80%, S=$10): EV = {ev_a:+.4f} ($/stake), 500-Trade Return = ${ret_500_a:+.2f}")
    assert math.isclose(ev_a, 0.008, rel_tol=1e-5), f"Example A mismatch: {ev_a}"
    assert math.isclose(ret_500_a, 40.0, rel_tol=1e-5), f"Example A 500-trade mismatch: {ret_500_a}"

    # Worked Example B
    ev_b = 0.56 * 0.75 - (1 - 0.56)
    ret_500_b = 500 * 10.0 * ev_b
    print(f"Example B (p=56%, P=75%, S=$10): EV = {ev_b:+.4f} ($/stake), 500-Trade Return = ${ret_500_b:+.2f}")
    assert math.isclose(ev_b, -0.020, rel_tol=1e-5), f"Example B mismatch: {ev_b}"
    assert math.isclose(ret_500_b, -100.0, rel_tol=1e-5), f"Example B 500-trade mismatch: {ret_500_b}"

    # Worked Example C
    ev_c1 = 0.53 * 0.92 - (1 - 0.53)
    ev_c2 = 0.53 * 0.80 - (1 - 0.53)
    print(f"Example C1 (p=53%, P=92%): EV = {ev_c1:+.4f} ($/stake)")
    print(f"Example C2 (p=53%, P=80%): EV = {ev_c2:+.4f} ($/stake)")
    assert math.isclose(ev_c1, 0.0176, rel_tol=1e-5), f"Example C1 mismatch: {ev_c1}"
    assert math.isclose(ev_c2, -0.0460, rel_tol=1e-5), f"Example C2 mismatch: {ev_c2}"

    # Sensitivity Matrix ($ per $100 staked)
    p_vals = [0.50, 0.52, 0.53, 0.54, 0.55, 1.0/1.80, 0.56, 0.57, 0.58, 0.60, 0.62, 0.65]
    payouts = [0.70, 0.75, 0.80, 0.85, 0.90, 0.92]
    
    sens_matrix = []
    for p in p_vals:
        row = {"WR": f"{p*100:.2f}%" if not math.isclose(p, 1.0/1.80) else "55.56% (p_BE 80%)"}
        for P in payouts:
            ev_100 = 100.0 * (p * P - (1 - p))
            row[f"P {int(P*100)}%"] = f"${ev_100:+.2f}"
        sens_matrix.append(row)
    df_sens = pd.DataFrame(sens_matrix)
    print("\nSensitivity Matrix (EV in $ per $100 Staked):")
    print(df_sens.to_string(index=False))

    # Death Zone thresholds
    print("\nDeath Zone P_crit = (1 - p) / p:")
    for p in [0.54, 0.55, 0.56, 0.57, 0.58]:
        p_crit = (1.0 - p) / p
        print(f"  p = {p*100:.1f}% -> P_crit = {p_crit*100:.2f}%")

    return df_sens

# ----------------------------------------------------------------------
# 3. Gambler's Ruin, Kelly Criterion & Variance
# ----------------------------------------------------------------------
def verify_kelly_and_ruin():
    print_header("3. GAMBLER'S RUIN, KELLY CRITERION & VARIANCE FORMULAS")
    
    # Kelly: f* = (p(1+P) - 1) / P
    win_rates = [0.55, 0.56, 0.57, 0.58, 0.60]
    payouts = [0.75, 0.80, 0.85, 0.92]
    kelly_rows = []
    for p in win_rates:
        row = {"WR": f"{p*100:.1f}%"}
        for P in payouts:
            f_star = (p * (1.0 + P) - 1.0) / P
            if f_star <= 0:
                row[f"P {int(P*100)}%"] = "0.00% (Neg EV)"
            else:
                row[f"P {int(P*100)}%"] = f"{f_star*100:.2f}%"
        kelly_rows.append(row)
    df_kelly = pd.DataFrame(kelly_rows)
    print("Kelly Fractions f*:")
    print(df_kelly.to_string(index=False))

    # Gambler's ruin diffusion approximation: P_ruin approx exp(-2 * mu * B / sigma^2)
    print("\nGambler's Ruin Probabilities (B0=$1,000, S=$10 -> B=100 units):")
    for p in [0.56, 0.57]:
        P = 0.80
        mu = p * P - (1.0 - p)
        sigma2 = ((1.0 + P)**2) * p * (1.0 - p)
        exponent = -2.0 * mu * 100.0 / sigma2
        p_ruin = math.exp(exponent)
        print(f"  p={p*100:.1f}%, P={P*100:.0f}%: mu={mu:+.4f}, sigma2={sigma2:.4f}, exp={exponent:.4f} -> P_ruin = {p_ruin*100:.2f}%")

    # Single-trade variance & 100-trade CI for p=0.53, P=0.80
    p = 0.53
    P = 0.80
    S = 10.0
    var_unit = ((1.0 + P)**2) * p * (1.0 - p)
    std_unit = math.sqrt(var_unit)
    std_stake = S * std_unit
    std_100 = math.sqrt(100) * std_stake
    mean_100 = 100 * S * (p * P - (1 - p))
    ci_lower = mean_100 - 1.96 * std_100
    ci_upper = mean_100 + 1.96 * std_100
    print(f"\n100-Trade Drag Analysis (p=53%, P=80%, S=$10):")
    print(f"  Single trade variance: {var_unit:.4f}, std per $10: ${std_stake:.2f}")
    print(f"  Mean 100-trade PnL: ${mean_100:.2f}, Std 100-trade: ${std_100:.2f}")
    print(f"  95% CI: [${ci_lower:.2f}, ${ci_upper:.2f}]")

# ----------------------------------------------------------------------
# 4. Wilson Score Interval & Binomial P-Values (Sample Size Deconstruction)
# ----------------------------------------------------------------------
def verify_wilson_and_significance():
    print_header("4. WILSON 95% CONFIDENCE INTERVALS & BINOMIAL P-VALUES")
    
    cases = [
        ("1 Trade / 1 Win", 1, 1),
        ("2 Trades / 2 Wins", 2, 2),
        ("3 Trades / 2 Wins", 3, 2),
        ("5 Trades / 4 Wins", 5, 4),
        ("10 Trades / 7 Wins", 10, 7),
        ("30 Trades / 18 Wins", 30, 18),
        ("100 Trades / 58 Wins", 100, 58),
        ("380 Trades / 228 Wins", 380, 228),
    ]
    
    z = 1.959963984540054  # 95% two-sided normal quantile
    p0 = 1.0 / 1.80       # 55.5556% breakeven at 80% payout
    
    results = []
    for label, n, w in cases:
        p_hat = w / n
        # Wilson score interval formula:
        denominator = 1.0 + (z**2) / n
        center = (p_hat + (z**2) / (2.0 * n)) / denominator
        spread = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / n) + ((z**2) / (4.0 * (n**2))))
        
        ci_lower = max(0.0, center - spread)
        ci_upper = min(1.0, center + spread)
        
        # Exact one-tailed Binomial P-value: P(X >= w | n, p0)
        p_val = sum(math.comb(n, k) * (p0**k) * ((1.0 - p0)**(n - k)) for k in range(w, n + 1))
        
        results.append({
            "Setup": label,
            "n": n,
            "w": w,
            "p_hat (%)": f"{p_hat*100:.1f}%",
            "Wilson 95% Lower": f"{ci_lower*100:.2f}%",
            "Wilson 95% Upper": f"{ci_upper*100:.2f}%",
            "Binomial p-value (H0: p<=pBE)": f"{p_val:.4f}",
            "Significant (p < 0.05)?": "YES" if p_val < 0.05 else "NO"
        })
        
    df = pd.DataFrame(results)
    print(df.to_string(index=False))
    return df

# ----------------------------------------------------------------------
# 5. Theoretical SNR Derivation Verification
# ----------------------------------------------------------------------
def verify_snr_derivation():
    print_header("5. SIGNAL-TO-NOISE RATIO (SNR) COLLAPSE DERIVATION")
    
    # SNR(tau) = |mu| * sqrt(tau) / sqrt(sigma^2 + 2 * sigma_eta^2 / tau)
    # sigma_eta / sigma = 0.35 min^(1/2) => sigma_eta^2 / sigma^2 = 0.1225 min
    # 2 * sigma_eta^2 / sigma^2 = 0.2450 min
    # Let sigma = 1, |mu| = 1
    timeframes = [
        ("M15", 15.0),
        ("M5", 5.0),
        ("M1", 1.0),
        ("S30", 0.5),
    ]
    
    snr_vals = {}
    for name, tau in timeframes:
        diff_term = math.sqrt(tau)
        noise_term = 0.2450 / tau
        denom = math.sqrt(1.0 + noise_term)
        snr = diff_term / denom
        snr_vals[name] = (tau, diff_term, noise_term, snr)
        
    snr_m15 = snr_vals["M15"][3]
    
    table = []
    for name, (tau, diff_term, noise_term, snr) in snr_vals.items():
        rel_snr = snr / snr_m15
        snr_loss = (1.0 - rel_snr) * 100.0
        table.append({
            "Timeframe": name,
            "Lookback (min)": tau,
            "Diffusion Term": f"{diff_term:.3f} sigma",
            "Noise Term": f"{noise_term:.4f} sigma^2",
            "Absolute SNR": f"{snr:.4f} |mu|/sigma",
            "Relative SNR (vs M15)": f"{rel_snr*100:.2f}%",
            "Theoretical SNR Loss": f"-{snr_loss:.2f}%" if snr_loss > 0 else "Baseline"
        })
    df_snr = pd.DataFrame(table)
    print(df_snr.to_string(index=False))
    return df_snr

if __name__ == "__main__":
    verify_breakeven_tables()
    verify_ev_and_sensitivity()
    verify_kelly_and_ruin()
    verify_wilson_and_significance()
    verify_snr_derivation()
