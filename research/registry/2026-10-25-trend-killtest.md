# Pre-registration: SOL/USDC dual-horizon trend kill test

**Registered:** 25 October 2026, before any run of `research/trend_killtest.py`  
**Status:** kill test, not a promotion gate. Passing only justifies building Milestones 0–2 of [PLAN.md](../../PLAN.md); it is not evidence for G2.  
**Trials counted against this hypothesis:** 9 parameter variants (grid below). Any later change is a new registration.

## Hypothesis

A long-SOL-or-cash rule that is long only when both a fast and a slow trailing SOL return are positive, sized by volatility targeting, beats holding USDC at lending yield after realistic Jupiter costs, and has better risk-adjusted return than buy-and-hold SOL.

## Data

- Binance spot `SOLUSDT` 15-minute klines (price reference only; PLAN.md allows CEX candles for the price component of historical research).
- **Research window:** 2023-06-01 00:00 UTC to 2025-06-30 23:45 UTC.
- **Sealed holdout:** 2025-07-01 onward. The script refuses to load bars at or after the cutoff. The holdout is not opened by this test.

## Rule (decided at each 15-minute close *t*, executed at the open of bar *t+1*)

- `fast_ret` = log return over the last F hours; `slow_ret` = log return over the last S days.
- `signal` = 1 if `fast_ret > 0` and `slow_ret > 0`, else 0.
- `target_weight` = `signal × min(1, 0.50 / realized_vol)`, where `realized_vol` is the annualised standard deviation of 15-minute log returns over the trailing 7 days.
- Trade only when `|target_weight − current_weight| ≥ 0.10` (no-trade band); otherwise hold. A signal-off exit to 0 always executes, even inside the band.
- Execution delay: signals use prices up to the open of bar *i* and the trade fills at the open of bar *i+1*, i.e. one full 15-minute bar of decision/landing delay (more conservative than filling at the decision price).
- Sharpe is computed on daily returns in excess of the cash rate, annualised with √365.
- Grid (9 variants): F ∈ {4h, 12h, 24h} × S ∈ {3d, 7d, 14d}.

## Costs and cash

- **Base cost:** 5 bps of traded notional per side (Jupiter V2 platform fee 2 bps + ~3 bps quoted price impact/spread for $100–$100k on 25 Oct 2026, from the forward recorder's first cycle).
- **Stress cost:** 10 bps per side.
- Idle USDC earns **6% APR** (prevailing Kamino/Jupiter Lend range 5–8%). A 0% cash variant is reported alongside.
- Network fees ignored (< $0.01 per swap).

## Walk-forward

- Train 6 months → test the next 3 months; step 3 months. Six outer test folds: 2023-12, 2024-03, 2024-06, 2024-09, 2024-12, 2025-03 (each 3 months).
- In each fold, choose the variant with the highest net Sharpe (base cost, 6% cash) on the training window only; apply it unchanged to the test window.

## Benchmarks (same costs and cash rate)

USDC at 6%; buy-and-hold SOL; 50/50 SOL/USDC rebalanced daily.

## Pass criteria (all required)

1. Walk-forward strategy beats USDC-at-6% in **at least 5 of 6** outer folds (PLAN.md's ≥70%).
2. Concatenated outer-fold return beats USDC-at-6% under **stress** costs.
3. Concatenated outer-fold Sharpe exceeds buy-and-hold SOL's Sharpe over the same period.
4. Concatenated outer-fold max drawdown ≤ 25%.
5. At least 6 of the 9 fixed variants, run unselected across the whole outer period, also beat USDC-at-6% (not dependent on one parameter choice).

## Decision

- **Pass:** proceed to PLAN.md Milestone 0–2 with this rule as the deterministic challenger; the holdout stays sealed for G2.
- **Fail:** record the result, do not retune this family on the same window, and choose the next hypothesis.

## Result (run 25 October 2026) — **FAIL, 0 of 5 criteria**

Full output: `data/trend_killtest_2026-10-25.txt` (regenerate with `python3 research/trend_killtest.py`).

| | Return (1.5 y outer) | Sharpe (excess) | Max DD |
|---|---|---|---|
| Walk-forward, base cost | −5.6% | −0.16 | 33.8% |
| Walk-forward, stress cost | −47.9% | −1.37 | 60.8% |
| USDC at 6% | +9.4% | — | 0% |
| Buy & hold SOL | +163.7% | 1.10 | 67.0% |
| 50/50 daily | +96.6% | 1.09 | 40.4% |

- Beat USDC in 2 of 6 folds; only 1 of 9 fixed variants (F=24h, S=7d, +16.9%) beat USDC.
- Main cause: turnover of ~1,188× notional in 1.5 years (about 2.2× per day). With no hysteresis, the fast signal whipsaws around zero; at 5 bps per side that alone costs ~59%.
- Per the registration, this family is not retuned on this window. The holdout remains sealed.
