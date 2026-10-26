# Pre-registration H5: short-term reversal vs SOL (quick test, 15 Hyperliquid-listed tokens)

**Hypothesis:** H5  
**Registered:** 25 October 2026, before any H5 price data was fetched  
**Status:** kill test, not a promotion gate. Uses 1 of the 6 hypothesis slots (3 of 6 after H7 and H3a). The owner chose this quick version over buying Dune for a broader universe.  
**Trials:** 6 variants (3 lookbacks × 2 basket sizes). The primary variant is fixed in advance; there is no walk-forward selection.

## Hypothesis

Solana meme/ecosystem tokens that fell the most against SOL over the last 1–7 days bounce back against SOL over the same horizon, by more than trading costs. A long-only rotation into the recent losers, measured in SOL, beats holding staked SOL.

## Universe (fixed list, point-in-time eligibility)

Solana-native tokens with Hyperliquid perps, including delisted ones (H2's 21 tokens are excluded by construction):

| Token | Mint | Hyperliquid perp listed (first → last day) |
|---|---|---|
| POPCAT | 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr | 2024-04-28 → 2025-06-30 |
| MEW | MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5 | 2024-06-17 → 2025-06-30 |
| GOAT | CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump | 2024-10-23 → 2025-06-30 |
| FARTCOIN | 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump | 2024-12-20 → 2025-06-30 |
| MOODENG | ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY | 2024-10-25 → 2025-06-30 |
| CHILLGUY | Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump | 2024-11-25 → 2025-06-30 |
| AI16Z | HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC | 2025-01-01 → 2025-06-30 |
| GRIFFAIN | KENJSUYLASHUMfHyy5o4Hp2FdNqZg1AsUPhfH2kYvEP | 2025-01-02 → 2025-06-30 |
| ZEREBRO | 8x5VqbHA8D7NkD52uNuS5nnt3PwA8pLD34ymskeSo2Wn | 2025-01-02 → 2025-06-30 |
| MELANIA | FUAfBo2jgks6gB4Z4LfZkqSZgzNucisEHqnNebaRxM1P | 2025-01-20 → 2025-06-30 |
| GRASS | Grass7B4RdKfBCjTKgSqnXkqjwiGvQyFbuSCUJr3XXjs | 2024-10-28 → 2025-06-30 |
| VINE | 6AJcP7wuLwmRYLBNbi825wgguaPsWzPBEHcHndpRpump | 2025-01-23 → 2025-06-30 |
| JELLY (jellyjelly) | FeR8VBqNRSUD5NtXAj2n3j1dAHkZHfyDktKuLXD4pump | 2025-01-30 → 2025-03-26 |
| MYRO | HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4 | 2024-03-05 → 2025-03-29 |
| LAUNCHCOIN | Ey59PH7Z4BFU4HjyKnyMdWt5GGN76KazTAwQihoUXRnk | 2025-05-14 → 2025-06-30 |

Mints were resolved by name and verified on-chain (AI16Z and MYRO: Jupiter search returned later look-alike tokens; the originals were confirmed by name and first transaction date, 2024-10-25 and 2023-11-07). Perp dates are the first and last daily candles in the H7 dataset, clipped at the cutoff.

A token is **eligible** on day *d* if its perp is listed on *d*, its first Solana DEX price observation is at least 30 days before *d*, and both the decision-hour and execution-hour samples have at least 20 swaps. *Clarified before any H5 price data was read: the lookback sample (00:00 on day d − L) must also have at least 20 swaps; the research window starts on the first day with at least 3 tokens meeting the eligibility rule; a delayed exit (next valid sample within 7 days) is booked at the scheduled rebalance with the later price. If that grace period would reach the sealed cutoff, the position exits at its last valid execution price before the cutoff (sealed data is never loaded, so it must not be read as a total loss).*

## Data

- Solana DEX prices from on-chain swaps (Helius `getTransactionsForAddress`): price = median of the pool's own swap prices among the first 50 successful transactions of the hour. Two hours per day: **00:00 UTC (decision)** and **01:00 UTC (execution)**.
- Pool: re-chosen at the start of each calendar month as the SOL- or USDC-quoted pool (GeckoTerminal's top pools, up to 6 checked) with the most swaps in that month's first 00:00 UTC hour among pools that existed then. This follows liquidity migrations (for example to PumpSwap in 2025) using swap counts only.
- USDC-quoted prices are converted to SOL with the Binance SOLUSDT **open** of the same hour (start-of-hour, matching the sample).
- **Research window:** from the first day with at least 3 eligible tokens to 2025-06-30. **Sealed holdout:** 2025-07-01 onward; nothing on or after the cutoff is fetched or loaded.

## Rule

- Every *L* days at 00:00 UTC: rank eligible tokens by their trailing *L*-day return in SOL (00:00 sample on day *d* vs day *d − L*). Buy the *K* lowest whose trailing return is ≤ 0, at 1/*K* of equity each, at the 01:00 execution price. Unfilled slots stay in SOL.
- Hold *L* days, then fully rebalance at the next decision.
- Exit when a held token has no valid execution sample: sell at the next valid execution-hour sample within 7 days; if none, the position counts as −100%.
- Grid: *L* ∈ {1, 3, 7} days × *K* ∈ {1, 3}. **Primary: L = 3, K = 3.**
- The SOL leg earns 6% APR staking (as in H2). Returns are in SOL terms; USD is reported alongside.

## Costs

- **Base:** 15 bps per side on traded notional (≈ 30 bps round trip, in line with measured $1k Jupiter costs for POPCAT and FARTCOIN). **Stress:** 30 bps per side.

## Benchmarks

Staked SOL (6% APR). Equal-weight basket of all eligible tokens, rebalanced on the same *L*-day clock at base cost.

## Pass criteria (all required, primary variant)

1. Total return beats staked SOL over the window under **stress** costs.
2. Daily Sharpe (excess over staking, SOL terms) > 0 and above the equal-weight basket's.
3. Positive (above staking) in at least 60% of consecutive non-overlapping 4-week blocks.
4. Maximum drawdown in SOL terms ≤ 40%.
5. Removing the single best-contributing token, it still beats staked SOL under base costs.
6. At least 4 of the 6 variants beat staked SOL under base costs.

## Disclosures

- Same tokens and period as H7, which found these tokens fell sharply against SOL (a short basket made +130% with a 54% drawdown). That prior works against a long-only rule. The test is run anyway at the owner's request, and the overlap is the main limitation.
- The universe is selected by Hyperliquid listing (tokens popular enough for a perp), not survivorship-free across all Solana tokens. The window is short (roughly 6–9 months with enough eligible tokens).

## Decision

- **Pass:** forward paper-trade the primary rule on live data before any further step; confirm on a broader universe (Dune) before any G2 claim.
- **Fail:** record it, do not retune this family on this window; the remaining queue is H6 (filtered post-launch tokens), the forward unlock collection, and the separate tracks needing an owner decision.

## Result (run 25 October 2026) — **FAIL, 1 of 6 criteria**

Full output: `data/h5_killtest_2026-10-25.txt` (reproduce with `python3 research/h5_killtest.py`). Window 2024-07-01 → 2025-06-30 (364 days); 3–11 eligible tokens per month.

| Variant | Return in SOL (base) | Return (stress) | Max DD |
|---|---|---|---|
| **Primary: every 3 days, 3 biggest losers** | **−60.0%** | −66.8% | 88.2% |
| Every 7 days, 3 losers | +78.5% | +64.6% | 76.7% |
| Every 1 day, 3 losers | −90.9% | −94.6% | 93.7% |
| Any variant holding only 1 loser | −100% | −100% | 100% |
| Equal-weight basket | −79.8% | | 93.5% |
| Staked SOL | +6.0% | | 0% |

- Only criterion 2 passed (Sharpe 0.02 vs the basket's −0.77): buying losers lost less than holding everything, but both lost heavily against SOL. In USD the primary lost 58% while SOL gained 4.6%.
- Single-loser variants hit −100%: buying the single biggest loser repeatedly ends up in a token that keeps falling or stops trading.
- The one positive variant (7-day, +78.5%) still had a 77% drawdown and is not a pass; choosing it now would be selection after the fact.
- As disclosed: same tokens and period as H7, where these tokens decayed against SOL. "Buy the dip" in a decaying group fails. This family is not retuned on this window.
