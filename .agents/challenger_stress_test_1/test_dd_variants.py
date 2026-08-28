"""
Check variations of drawdown calculation:
1. Max peak-to-trough in % of peak equity
2. Max peak-to-trough in $ / initial bankroll
3. Max drawdown from initial bankroll (underwater from $1,000)
"""

import numpy as np

np.random.seed(42)
num_runs = 10000
trades = 500
stake = 10.0
payout = 0.80
wr = 0.57
initial_balance = 1000.0

dd_pct_peak = []
dd_pct_initial = []
underwater_initial = []

for _ in range(num_runs):
    outcomes = (np.random.rand(trades) < wr).astype(int)
    pnl = np.where(outcomes == 1, stake * payout, -stake)
    equity = initial_balance + np.cumsum(pnl)
    equity_with_init = np.insert(equity, 0, initial_balance)
    
    peaks = np.maximum.accumulate(equity_with_init)
    dd_dlr = peaks - equity_with_init
    
    dd_pct_peak.append(np.max(dd_dlr / peaks) * 100)
    dd_pct_initial.append(np.max(dd_dlr / initial_balance) * 100)
    underwater_initial.append(max(0.0, (initial_balance - np.min(equity_with_init)) / initial_balance * 100))

print(f"Peak-to-trough DD (% of Peak): Mean={np.mean(dd_pct_peak):.2f}%, Median={np.median(dd_pct_peak):.2f}%, 95th={np.percentile(dd_pct_peak, 95):.2f}%")
print(f"Peak-to-trough DD (% of $1,000 Init): Mean={np.mean(dd_pct_initial):.2f}%, Median={np.median(dd_pct_initial):.2f}%, 95th={np.percentile(dd_pct_initial, 95):.2f}%")
print(f"Underwater from $1,000 Init: Mean={np.mean(underwater_initial):.2f}%, Median={np.median(underwater_initial):.2f}%, 95th={np.percentile(underwater_initial, 95):.2f}%")
