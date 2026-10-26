# Pre-registration H7: short a basket of Solana tokens vs long SOL (perps, research only)

**Registered:** 25 October 2026, before any run of `research/h7_short_basket_killtest.py`  
**Status:** research-only kill test. Trading this needs an explicit owner scope decision (perps, shorts). Passing is not evidence for G2.  
**Trials:** 4 variants (grid below); the primary variant is fixed in advance.

## Hypothesis

Solana ecosystem tokens decay against SOL often enough that a dollar-neutral position (short an equal-weight basket of them, long SOL, both on Hyperliquid perps) beats leaving the collateral in USDC lending, after trading costs and actual funding, without one squeeze or one token dominating the result.

## Why this is not just a re-run of H2

H2 observed that its basket of 21 Binance-listed tokens lost 68.6% vs SOL. H7 uses a **disjoint universe**: Solana-native tokens with Hyperliquid perps that were not in H2. The **period overlaps** H2 (the 2024–25 regime), so a pass may reflect that regime and must be confirmed on the sealed holdout before any G2 claim.

## Data

- Hyperliquid `candleSnapshot` daily candles (open, close, volume) and hourly `fundingHistory`, including delisted perps.
- Universe: POPCAT, MEW, GOAT, FARTCOIN, MOODENG, CHILLGUY, AI16Z, GRIFFAIN, ZEREBRO, MELANIA, GRASS, VINE, JELLY, MYRO, LAUNCHCOIN. Long leg: SOL perp.
- **Research window:** from the first Monday with at least 3 eligible tokens to 2025-06-30. **Sealed holdout:** 2025-07-01 onward; the script refuses to load it.

## Rule

- Rebalance on Mondays at the 00:00 UTC open, using data up to the Sunday close.
- **Eligible:** at least 30 days of Hyperliquid history, a candle on that Monday (still trading), and median daily notional volume (volume × close) over the previous 30 days ≥ $2M.
- **Position:** long SOL with notional 1.0× equity; short the selected tokens equally with total notional 1.0× equity. Coin quantities are fixed between rebalances. If fewer than 3 tokens qualify, hold no position.
- **Delisting:** a held token whose candles end mid-period is closed at its last daily close (settlement proxy).
- **Primary variant:** short all eligible tokens, weekly rebalance.
- **Grid (4 variants):** selection ∈ {all eligible, weakest half by trailing 28-day return vs SOL (at least the 3 weakest)} × rebalance ∈ {weekly, every 4 weeks}.

## Costs, funding, collateral

- **Base cost:** 10 bps per side on traded notional, both legs (Hyperliquid taker ~4.5 bps plus slippage). **Stress:** 20 bps per side.
- **Funding:** actual hourly rates; the short leg receives positive funding and the long SOL leg pays it, both on start-of-period notional.
- Collateral is USDC earning 0% on Hyperliquid. The benchmark is USDC lending at 6% APR; 0% is also reported.
- Equity is marked daily at closes for drawdown. Intraday squeezes are not modelled, so real drawdowns would be worse; that is why the drawdown limit is strict.

## Pass criteria (all required)

1. Primary variant beats USDC at 6% under **stress** costs, funding included.
2. Primary variant is positive in ≥ 70% of consecutive non-overlapping 8-week blocks.
3. Primary variant's maximum daily-marked drawdown ≤ 30%.
4. Removing the single largest contributing token, the primary variant still beats USDC at 6% at base cost.
5. At least 3 of the 4 variants beat USDC at 6% at base cost.

## Decision

- **Pass:** report to the owner as a candidate separate track; confirm on the holdout and on forward data only after an owner scope decision. No trading.
- **Fail:** record it and do not retune this family on this window.

## Result (run 25 October 2026) — **FAIL, 3 of 5 criteria passed; failed on risk**

Full output: `data/h7_short_basket_killtest_2026-10-25.txt` (regenerate with `python3 research/h7_short_basket_killtest.py`). Window 2024-11-25 → 2025-06-30 (31 weeks; earlier weeks had fewer than 3 eligible tokens).

| Variant | Return (base) | Return (stress) | Max DD |
|---|---|---|---|
| **Primary: all eligible, weekly** | +134.6% | +130.3% | **54.0%** |
| All eligible, every 4 weeks | +66.0% | +63.9% | 63.8% |
| Weakest half, weekly | +109.8% | +103.7% | 58.6% |
| Weakest half, every 4 weeks | +73.5% | +70.4% | 65.3% |
| USDC at 6% | +3.5% | | 0% |

- Passed: beats USDC under stress costs and funding; still beats it without the top contributor (GOAT); 4 of 4 variants beat USDC.
- **Failed:** max drawdown 54% (limit 30%), and only 2 of 3 eight-week blocks were positive. The last block was **−43%** (May–June 2025 meme rebound; FARTCOIN −29% and VINE −19% of starting equity).
- The window is short (31 weeks, one regime: the early-2025 memecoin crash), and daily marks hide intraday squeezes. JELLY's March 2025 squeeze and delisting would have hurt more intraday than daily closes show. Real risk was worse than reported.
- Reading: the decay effect is real and large in this window, but as registered the position is far too risky. Per the registration, this family is not retuned on this window. A risk-controlled version would be a new hypothesis, already shaped by these results, so it can only be judged on data not used here (forward paper trading or the sealed holdout).
