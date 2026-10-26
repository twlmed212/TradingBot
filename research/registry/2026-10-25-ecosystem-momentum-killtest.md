# Pre-registration: Solana ecosystem cross-sectional momentum vs SOL (kill test)

**Hypothesis:** H2  
**Registered:** 25 October 2026, before any run of `research/ecosystem_momentum_killtest.py`  
**Status:** kill test, not a promotion gate. Passing only justifies building the ecosystem plan's Milestones 0–2; it is not evidence for G2.  
**Trials counted against this hypothesis:** 9 parameter variants. The earlier SOL/USDC trend test (`2026-10-25-trend-killtest.md`, failed) is a separate, already-spent hypothesis.

## Hypothesis

Among liquid Solana ecosystem tokens, those that have outperformed SOL over the last 1–4 weeks keep outperforming SOL over the next week by more than the cost of rotating into them. A weekly long-only rotation, quoted and measured in SOL, beats holding staked SOL.

## Data

- Binance spot daily klines, `XUSDT` divided by `SOLUSDT` to get each token's price in SOL. Binance is used as the historical price reference because public DEX OHLCV (GeckoTerminal) only covers the last 180 days, which lies inside the sealed holdout.
- Candidate universe (Solana-native SPL tokens with Binance spot history in the window): RAY, GMT, FIDA, BONK, JTO, JUP, PYTH, WIF, BOME, W, TNSR, IO, RENDER (RNDRUSDT until 2024-07-22, RENDERUSDT after), PNUT, ACT, ORCA, ME, PENGU, TRUMP, LAYER, KMNO.
- **Research window:** 2023-06-01 to 2025-06-30. **Sealed holdout:** 2025-07-01 onward; the script refuses to load it.
- Known biases: tokens never listed on Binance (most memecoins, including those that died) are absent, and Binance lists tokens after they have already succeeded. Both biases flatter momentum, so a pass is weak evidence and a fail is strong evidence.

## Rule

- Rebalance weekly at the Monday 00:00 UTC open, using daily closes up to and including Sunday.
- **Eligible** on a rebalance date: at least 30 days of history, and median Binance daily quote volume over the previous 30 days ≥ $5M (point-in-time liquidity proxy; historical DEX liquidity is unavailable).
- **Score:** trailing L-day return in SOL terms.
- **Hold:** the top K eligible tokens whose score is > 0, each at weight 1/K. Unfilled slots stay in SOL. Rebalance fully to target weights each week.
- Grid (9 variants): L ∈ {7, 14, 28} days × K ∈ {1, 3, 5}.

## Costs and cash

- **Base cost:** 15 bps per side on traded notional (≈30 bps round trip, the median of liquid names at $1k–$10k from live Jupiter V2 quotes on 25 Oct 2026, including Jupiter's 10 bps platform fee on X/SOL swaps).
- **Stress cost:** 30 bps per side.
- The SOL leg earns **6% APR** staking (JitoSOL-class average over 2023–25). A 0% variant is reported alongside.

## Walk-forward

- The universe is too thin before 2024, so the first training window starts 2024-01-01.
- Train 4 months → test the next 2 months; step 2 months. Seven outer folds starting 2024-05, 2024-07, 2024-09, 2024-11, 2025-01, 2025-03, 2025-05 (the last ends 2025-06-30).
- In each fold, pick the variant with the highest training Sharpe (base cost, 6% staking) and apply it unchanged to the test window.

## Benchmarks (all in SOL terms)

Staked SOL at 6%; an equal-weight basket of all eligible tokens, rebalanced weekly at base cost. Holding SOL in USD terms is reported for context.

## Pass criteria (all required)

1. Beats staked SOL in **at least 5 of 7** outer folds.
2. Concatenated outer return beats staked SOL under **stress** costs.
3. Concatenated outer Sharpe (excess over staking, SOL terms) is > 0 and above the equal-weight basket's.
4. Concatenated outer max drawdown in SOL terms ≤ 40%.
5. At least 6 of the 9 fixed variants beat staked SOL over the whole outer period.

## Decision

- **Pass:** proceed to Milestones 0–2 of the ecosystem plan with this rule as the deterministic challenger, and buy or record DEX-native data to repeat the test without the Binance biases before any G2 claim.
- **Fail:** record the result, do not retune this family on this window, choose the next hypothesis.

## Result (run 25 October 2026) — **FAIL, 0 of 5 criteria**

Full output: `data/ecosystem_momentum_killtest_2026-10-25.txt` (regenerate with `python3 research/ecosystem_momentum_killtest.py`). Outer period 2024-05-06 → 2025-06-30 (60 weeks), all returns in SOL terms.

| | Return vs SOL | Sharpe (excess) | Max DD |
|---|---|---|---|
| Walk-forward momentum, base cost | −48.9% | −0.18 | 72.7% |
| Walk-forward momentum, stress cost | −54.7% | −0.28 | 73.7% |
| Equal-weight ecosystem basket | **−68.6%** | −1.47 | 71.4% |
| Staked SOL | +6.9% | — | 0% |

- Beat staked SOL in 3 of 7 folds; 0 of 9 fixed variants beat staked SOL (range −42% to −95%).
- Costs were not the main cause (turnover 80× → ~12% at base cost). Buying the prior 1–4 week winner lost because winners mean-reverted.
- The equal-weight basket of Binance-listed Solana ecosystem tokens lost about two thirds of its value against SOL, despite Binance listing and survivorship biases that should flatter it.
- Per the registration, this family is not retuned on this window. A short-term-reversal idea suggested by these results would be data-snooped on this window and must be tested on different data.
