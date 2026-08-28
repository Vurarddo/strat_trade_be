import numpy as np
import math

payouts = [0.70, 0.75, 0.80, 0.85, 0.90, 0.92]
print('=== BREAKEVEN WIN RATES ===')
for P in payouts:
    be = 1.0 / (1.0 + P)
    print(f'Payout: {P*100:.0f}% -> Breakeven WR: {be*100:.4f}%')

print('\n=== SENSITIVITY MATRIX: EV per $100 bet ===')
win_rates = [0.50, 0.52, 0.53, 0.54, 0.55, 0.5556, 0.56, 0.57, 0.58, 0.60, 0.62, 0.65]
header = 'WR \\ Payout\t' + '\t'.join([f'{int(p*100)}%' for p in payouts])
print(header)
for wr in win_rates:
    row = [f'{wr*100:.2f}%\t']
    for p in payouts:
        ev = (wr * p - (1.0 - wr)) * 100.0
        row.append(f'{ev:+.2f}')
    print('\t'.join(row))

print('\n=== KELLY CRITERION TABLE (Full Kelly f*) ===')
header_k = 'WR \\ Payout\t' + '\t'.join([f'{int(p*100)}%' for p in payouts])
print(header_k)
for wr in win_rates:
    row = [f'{wr*100:.2f}%\t']
    for p in payouts:
        f_star = (wr * (1.0 + p) - 1.0) / p
        row.append(f'{max(0.0, f_star)*100:.2f}%')
    print('\t'.join(row))

print('\n=== MONTE CARLO SIMULATION (10,000 runs, 500 trades) ===')
np.random.seed(42)
M = 10000
N = 500
base_wr = 0.57  # baseline 57% win rate
initial_deposit = 1000.0
stake = 10.0

# 1. Base model: fixed 80% payout, constant 57% WR
trades_outcomes = np.random.rand(M, N) < base_wr
pnl_base = np.where(trades_outcomes, stake * 0.80, -stake)
cum_pnl_base = np.cumsum(pnl_base, axis=1)
final_pnl_base = cum_pnl_base[:, -1]
equity_curve_base = initial_deposit + np.hstack([np.zeros((M, 1)), cum_pnl_base])
peak_equity_base = np.maximum.accumulate(equity_curve_base, axis=1)
drawdowns_base = (peak_equity_base - equity_curve_base) / peak_equity_base
max_dd_base = np.max(drawdowns_base, axis=1) * 100.0

print(f'Base Model (Fixed 80% Payout, 57% WR):')
print(f'Mean Final PnL: ${np.mean(final_pnl_base):.2f} (std: ${np.std(final_pnl_base):.2f})')
print(f'Median Final PnL: ${np.median(final_pnl_base):.2f}')
print(f'Mean Max DD: {np.mean(max_dd_base):.2f}% (95th percentile Max DD: {np.percentile(max_dd_base, 95):.2f}%)')
print(f'Ruin Prob (Balance <= 0): {np.mean(np.min(equity_curve_base, axis=1) <= 0)*100:.2f}%')
print(f'Severe DD Prob (DD >= 20%): {np.mean(max_dd_base >= 20.0)*100:.2f}%')

# 2. Dynamic Model: Payout uniform(0.72, 0.88), Regime noise +-2% per 50-trade block
payout_matrix = np.random.uniform(0.72, 0.88, (M, N))
block_shifts = np.random.uniform(-0.02, 0.02, (M, 10))
block_shifts_expanded = np.repeat(block_shifts, 50, axis=1)
effective_wr = base_wr + block_shifts_expanded
dynamic_outcomes = np.random.rand(M, N) < effective_wr
pnl_dynamic = np.where(dynamic_outcomes, stake * payout_matrix, -stake)
cum_pnl_dynamic = np.cumsum(pnl_dynamic, axis=1)
final_pnl_dynamic = cum_pnl_dynamic[:, -1]
equity_curve_dynamic = initial_deposit + np.hstack([np.zeros((M, 1)), cum_pnl_dynamic])
peak_equity_dynamic = np.maximum.accumulate(equity_curve_dynamic, axis=1)
drawdowns_dynamic = (peak_equity_dynamic - equity_curve_dynamic) / peak_equity_dynamic
max_dd_dynamic = np.max(drawdowns_dynamic, axis=1) * 100.0

print(f'\nDynamic Model (Fluctuating Payout 72-88%, Regime Shifts +-2%):')
print(f'Mean Final PnL: ${np.mean(final_pnl_dynamic):.2f} (std: ${np.std(final_pnl_dynamic):.2f})')
print(f'Median Final PnL: ${np.median(final_pnl_dynamic):.2f}')
print(f'5th Percentile PnL (Worst 5%): ${np.percentile(final_pnl_dynamic, 5):.2f}')
print(f'95th Percentile PnL: ${np.percentile(final_pnl_dynamic, 95):.2f}')
print(f'Mean Max DD: {np.mean(max_dd_dynamic):.2f}% (95th percentile Max DD: {np.percentile(max_dd_dynamic, 95):.2f}%)')
print(f'Ruin Prob (Balance <= 0): {np.mean(np.min(equity_curve_dynamic, axis=1) <= 0)*100:.2f}%')
print(f'Severe DD Prob (DD >= 20%): {np.mean(max_dd_dynamic >= 20.0)*100:.2f}%')
print(f'Loss Sequence Prob (Final PnL < 0): {np.mean(final_pnl_dynamic < 0)*100:.2f}%')

# Max Loss Streak distribution
def max_loss_streak(row):
    max_s = 0
    cur_s = 0
    for win in row:
        if not win:
            cur_s += 1
            if cur_s > max_s:
                max_s = cur_s
        else:
            cur_s = 0
    return max_s

streaks = np.apply_along_axis(max_loss_streak, 1, dynamic_outcomes)
print(f'\nMax Consecutive Loss Streak Distribution (500 trades):')
print(f'Median: {np.median(streaks):.1f}')
print(f'75th Percentile: {np.percentile(streaks, 75):.1f}')
print(f'90th Percentile: {np.percentile(streaks, 90):.1f}')
print(f'95th Percentile: {np.percentile(streaks, 95):.1f}')
print(f'99th Percentile: {np.percentile(streaks, 99):.1f}')
print(f'Max observed streak: {np.max(streaks)}')
