# Pre-registration H8: slow trend filter on SOL vs USDC

**Hypothesis:** H8  
**Registered:** 25 October 2026, before any H8 computation  
**Status:** kill test; uses slot 5 of 6. Not a promotion gate.  
**Trials:** 6 variants (3 moving averages + 3 momentum lookbacks); primary fixed in advance.

## Hypothesis

Holding SOL only while it is in a slow uptrend, and USDC (earning lending interest) otherwise, gives a better risk-adjusted return and much smaller drawdowns than holding SOL, after costs. This answers the plan's open "SOL exposure" decision with a rule. Unlike H1 (15-minute signals, about 2 trades per day), this trades a few times per month.

## Data

- Binance spot daily closes (00:00 UTC): SOLUSDT; BTCUSDT and ETHUSDT for robustness.
- **Window A (primary, never used by any test):** 2021-03-01 → 2023-05-31 (signals warm up from 2020-08-11).
- **Window B (second check):** 2023-06-01 → 2025-06-30. H1 used this window's 15-minute SOL prices; a slow trend rule was not tested on it.
- **Sealed holdout:** 2025-07-01 onward; not loaded.

## Rule

- At each daily close *t*: signal = 1 (hold SOL) if the rule is positive, else 0 (hold USDC). The position changes at the close of *t + 1* (one full day of delay).
- **Primary: close > 100-day simple moving average.**
- Grid (6): moving average ∈ {50, 100, 200} days; momentum (close vs close *L* days ago > 0) with *L* ∈ {28, 56, 112} days.
- USDC earns 5% APR while held. Costs: 10 bps per side (base; Jupiter SOL/USDC measured 2–4 bps today), 20 bps per side (stress).
- Returns in USD. Benchmarks: holding SOL, USDC at 5%, 50/50 SOL/USDC rebalanced monthly.

## Pass criteria (all required)

1. Primary daily Sharpe (excess over 5% USDC) above holding SOL's, in **window A and window B**.
2. Primary maximum drawdown at most 60% of holding SOL's (cuts the worst drop by ≥ 40%), in both windows.
3. Primary total return beats USDC at 5% under stress costs, in both windows.
4. At least 4 of 6 variants have Sharpe above holding SOL in window A.
5. Robustness: the primary rule's Sharpe beats buy-and-hold on at least one of BTC or ETH in window A.
6. Not one-period luck: removing the primary's single best calendar month, its window-A Sharpe still beats holding SOL's.

## Disclosures

General knowledge of SOL's history (the 2021 rise, the 2022 crash) is unavoidable; window B prices were seen in H1 at 15-minute resolution. That is why window A is primary and both windows must pass. A pass makes this an exposure overlay (when to hold SOL), not a token strategy; it would go to forward paper tracking first.

## Result (run 25 October 2026) — **FAIL, 3 of 6 criteria**

Full output: `data/h8_slow_trend_2026-10-25.txt` (reproduce with `python3 research/h8_slow_trend.py`).

| | Window A 2021-03 → 2023-05 (primary) | Window B 2023-06 → 2025-06 |
|---|---|---|
| Hold SOL | +39%, Sharpe 0.73, max DD 96% | +656%, Sharpe 1.47, max DD 60% |
| **Primary: SMA-100 filter** | **+216%, Sharpe 0.96, max DD 75%** (37 trades) | **+171%, Sharpe 0.95, max DD 63%** (55 trades) |
| USDC at 5% | +11.6% | +10.7% |

- Passed: beats USDC under stress in both windows; all 6 variants beat SOL's Sharpe in window A; the rule beat buy-and-hold on BTC (not ETH) in window A.
- **Failed:** in window B (a strong SOL bull market) the filter's Sharpe was lower than holding (0.95 vs 1.47) and it gave up most of the gain; the drawdown cut was too small (75% vs 96% in A; 63% vs 60% in B); window A's edge depends on August 2021 (Sharpe 0.46 without it).
- Reading: a slow trend filter helped in the crash-heavy period and hurt in the bull period, with large drawdowns either way. Other variants look better in hindsight (e.g. 112-day momentum in A, 28-day in B) but differ by window; choosing one now would be selection after the fact. This family is not retuned on these windows.
