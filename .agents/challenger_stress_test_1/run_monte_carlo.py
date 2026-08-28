"""
Independent Monte Carlo Simulation Harness
Challenger 1: Empirical Verification of STRESS_TEST_REPORT.md Deliverable R2
"""

import numpy as np
import pandas as pd
import time

def run_monte_carlo(
    num_runs=10000,
    trades_per_run=500,
    initial_balance=1000.0,
    stake=10.0,
    base_wr=0.57,
    seed=42
):
    print("=" * 80)
    print(f" MONTE CARLO SIMULATION ({num_runs:,} runs x {trades_per_run} trades)")
    print(f" Initial Balance: ${initial_balance:,.2f} | Stake: ${stake:,.2f} | Base WR: {base_wr*100:.1f}%")
    print("=" * 80)

    np.random.seed(seed)
    start_time = time.time()

    # Model A: Base Model (Fixed 80% Payout, Constant 57% Win Rate)
    # Model B: Dynamic Model (Uniform(0.72, 0.88) Payout, +/-2% OTC Drift per 50-trade block)

    def simulate(model_type="base"):
        final_pnls = np.zeros(num_runs)
        max_drawdowns_pct = np.zeros(num_runs)
        max_drawdowns_dlr = np.zeros(num_runs)
        max_loss_streaks = np.zeros(num_runs)
        ruin_count = 0
        loss_count = 0
        dd_gte_5pct = 0
        dd_gte_8pct = 0
        dd_gte_10pct = 0
        dd_gte_15pct = 0
        dd_gte_18pct = 0
        dd_gte_20pct = 0

        num_blocks = trades_per_run // 50

        for run in range(num_runs):
            # Generate win/loss outcomes and payouts for 500 trades
            if model_type == "base":
                payouts = np.full(trades_per_run, 0.80)
                outcomes = (np.random.rand(trades_per_run) < base_wr).astype(int)
            else: # dynamic
                payouts = np.random.uniform(0.72, 0.88, size=trades_per_run)
                # Drift per 50 trades
                block_drifts = np.random.uniform(-0.02, +0.02, size=num_blocks)
                block_wrs = base_wr + block_drifts
                wrs = np.repeat(block_wrs, 50)
                outcomes = (np.random.rand(trades_per_run) < wrs).astype(int)

            # Profit / loss per trade: Win -> +stake * payout, Loss -> -stake
            trade_pnl = np.where(outcomes == 1, stake * payouts, -stake)
            
            # Balance path
            equity_curve = initial_balance + np.cumsum(trade_pnl)
            equity_with_init = np.insert(equity_curve, 0, initial_balance)
            
            # Peak and Drawdown
            peaks = np.maximum.accumulate(equity_with_init)
            drawdowns_dlr = peaks - equity_with_init
            drawdowns_pct = drawdowns_dlr / peaks
            
            max_dd_pct = np.max(drawdowns_pct)
            max_dd_dlr = np.max(drawdowns_dlr)
            
            final_pnl = equity_curve[-1] - initial_balance
            final_pnls[run] = final_pnl
            max_drawdowns_pct[run] = max_dd_pct
            max_drawdowns_dlr[run] = max_dd_dlr
            
            if np.min(equity_curve) <= 0:
                ruin_count += 1
            if final_pnl < 0:
                loss_count += 1
                
            # Circuit breaker thresholds (relative to peak equity)
            if max_dd_pct >= 0.05:
                dd_gte_5pct += 1
            if max_dd_pct >= 0.08:
                dd_gte_8pct += 1
            if max_dd_pct >= 0.10:
                dd_gte_10pct += 1
            if max_dd_pct >= 0.15:
                dd_gte_15pct += 1
            if max_dd_pct >= 0.18:
                dd_gte_18pct += 1
            if max_dd_pct >= 0.20:
                dd_gte_20pct += 1

            # Loss streaks
            # Count consecutive 0s in outcomes
            current_streak = 0
            max_streak = 0
            for out in outcomes:
                if out == 0:
                    current_streak += 1
                    if current_streak > max_streak:
                        max_streak = current_streak
                else:
                    current_streak = 0
            max_loss_streaks[run] = max_streak

        metrics = {
            "Mean PnL ($)": np.mean(final_pnls),
            "Std PnL ($)": np.std(final_pnls),
            "Median PnL ($)": np.median(final_pnls),
            "5th Pct PnL ($)": np.percentile(final_pnls, 5),
            "95th Pct PnL ($)": np.percentile(final_pnls, 95),
            "Mean Max DD (%)": np.mean(max_drawdowns_pct) * 100,
            "Median Max DD (%)": np.median(max_drawdowns_pct) * 100,
            "95th Pct Max DD (%)": np.percentile(max_drawdowns_pct, 95) * 100,
            "Prob Net Loss (PnL < 0) (%)": (loss_count / num_runs) * 100,
            "Prob Severe DD (>=20%) (%)": (dd_gte_20pct / num_runs) * 100,
            "Prob Absolute Ruin (%)": (ruin_count / num_runs) * 100,
            # Loss streak percentiles
            "Median Streak": np.median(max_loss_streaks),
            "75th Pct Streak": np.percentile(max_loss_streaks, 75),
            "90th Pct Streak": np.percentile(max_loss_streaks, 90),
            "95th Pct Streak": np.percentile(max_loss_streaks, 95),
            "99th Pct Streak": np.percentile(max_loss_streaks, 99),
            "Max Observed Streak": np.max(max_loss_streaks),
            # Breach rates
            "Breach 5% DD (%)": (dd_gte_5pct / num_runs) * 100,
            "Breach 8% DD (%)": (dd_gte_8pct / num_runs) * 100,
            "Breach 10% DD (%)": (dd_gte_10pct / num_runs) * 100,
            "Breach 15% DD (%)": (dd_gte_15pct / num_runs) * 100,
            "Breach 18% DD (%)": (dd_gte_18pct / num_runs) * 100,
            "Breach 20% DD (%)": (dd_gte_20pct / num_runs) * 100,
        }
        return metrics

    base_results = simulate("base")
    dyn_results = simulate("dynamic")
    
    elapsed = time.time() - start_time
    print(f"Simulation finished in {elapsed:.2f} seconds.\n")

    # Format comparison table
    df_compare = pd.DataFrame([
        {"Metric": k, "Base Model": f"{base_results[k]:.2f}", "Dynamic Model": f"{dyn_results[k]:.2f}"}
        for k in base_results.keys()
    ])
    print(df_compare.to_string(index=False))

    return base_results, dyn_results

if __name__ == "__main__":
    run_monte_carlo()
