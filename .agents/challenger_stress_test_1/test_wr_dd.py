"""
Examine drawdown across various WRs (55%, 56%, 57%) and Dynamic Model
"""

import numpy as np

np.random.seed(42)
num_runs = 10000
trades = 500
stake = 10.0
initial_balance = 1000.0

for wr in [0.55, 0.56, 0.57]:
    for model in ["base_80", "dynamic"]:
        dd_pct_peak = []
        streak_max = []
        for _ in range(num_runs):
            if model == "base_80":
                payouts = np.full(trades, 0.80)
                outcomes = (np.random.rand(trades) < wr).astype(int)
            else:
                payouts = np.random.uniform(0.72, 0.88, size=trades)
                block_drifts = np.random.uniform(-0.02, 0.02, size=10)
                block_wrs = wr + block_drifts
                wrs = np.repeat(block_wrs, 50)
                outcomes = (np.random.rand(trades) < wrs).astype(int)
            
            pnl = np.where(outcomes == 1, stake * payouts, -stake)
            equity = initial_balance + np.cumsum(pnl)
            equity_with_init = np.insert(equity, 0, initial_balance)
            peaks = np.maximum.accumulate(equity_with_init)
            dd_pct = (peaks - equity_with_init) / peaks
            dd_pct_peak.append(np.max(dd_pct) * 100)
            
        print(f"WR={wr*100:.1f}%, Model={model}: Mean Max DD={np.mean(dd_pct_peak):.2f}%, Median={np.median(dd_pct_peak):.2f}%, 95th={np.percentile(dd_pct_peak, 95):.2f}%")
