# Pre-registration H6: copy profitable Solana wallets (replaces the old H6)

**Hypothesis:** H6 (owner-approved replacement of "filtered post-launch tokens")  
**Registered:** 25 October 2026, before any wallet data was fetched  
**Status:** kill test. Uses slot 4 of 6. Not a promotion gate.  
**Trials:** 4 variants (2 list sizes × 2 copy delays); primary fixed in advance.

## Hypothesis

Wallets that made the most money trading Solana tokens over the previous 3 months keep doing so; copying their buys and sells a few minutes late, at real later prices and costs, beats holding staked SOL.

## Data (Helius, on-chain; nothing on/after 2025-07-01)

1. **Discovery:** signers of swaps in the main pools of the token universe (the 15 H5 tokens plus the research-window listing-event tokens), sampled from the first 20 transactions every 4 hours (amended before any data: 20 instead of 50 for bandwidth), 2024-10-01 → 2025-06-30. Candidates: wallets with swaps in ≥ 3 different tokens and ≥ 10 sampled swaps.
2. **Wallet histories:** each candidate's full transaction history 2024-10-01 → 2025-06-30, parsed into trades: token, side, amount, price in SOL (SOL or USDC leg; USDC converted with Binance SOLUSDT).
3. **Copy prices:** the token's pool price from the first swaps after *t + delay*.

## Ranking (point-in-time, re-done monthly)

At the start of each month from 2025-01 to 2025-06: score each candidate on trades in the **previous 3 months only**: realized SOL profit on closed positions minus 30 bps per trade. Exclusions, also using only past data: wallets with > 2,000 trades in the 3 months (bots), wallets with < 10 closed trades, and wallets where > 30% of buys happened within 5 minutes of the token's first pool (likely insiders/snipers). Follow the top *N*.

## Copy rule

- When a followed wallet buys a token worth ≥ 1 SOL, buy that token for 1/*N* of current equity (if not already held), at the pool price at *t + delay*. Copy its sell (first sell of that token after our buy) at *t_sell + delay*; otherwise exit after 7 days.
- Positions per token: one. Cash stays in staked SOL (6% APR).
- Costs: base 30 bps per side (memecoins at size), stress 60 bps per side. A missing copy price (no swaps within 15 minutes) skips the entry; a missing exit price uses the next available within 24 h, else −100%.
- Grid: *N* ∈ {10 (**primary**), 25} × delay ∈ {2 min (**primary**), 10 min}.

## Pass criteria (all required, primary, copy period 2025-01-01 → 2025-06-30)

1. Beats staked SOL under stress costs.
2. Daily Sharpe (excess over staking, SOL terms) > 0.
3. Positive in ≥ 4 of 6 calendar months.
4. Max drawdown ≤ 40%.
5. Still beats staked SOL without its single best copied trade.
6. ≥ 3 of 4 variants beat staked SOL under base costs.

## Disclosures

Discovery only sees wallets that traded our ~30 tokens' main pools (not all of Solana); multi-hop or aggregator trades are parsed from the signer's net balance changes; the period overlaps H5/H7 (same decaying token group dominates). A pass would need a forward paper test before anything else.

## Amendments (before any wallet history was fetched)

- Discovery result: 1,265 candidates (≥ 3 tokens, ≥ 10 sampled swaps) from 47,106 samples.
- Bot pre-filter: wallets with > 6,000 transactions between 2024-10-01 and 2025-06-30 (counted from signatures) are excluded as bots before downloading full histories (the 2,000-trades-per-3-months rule still applies afterwards).
- Scope: trades are parsed, scored and copied only for the token universe used in discovery (tokens with known pools), so every copy can be priced.

## Result (run 25 October 2026) — **FAIL, 1 of 6 criteria**

Full output: `data/h6_killtest_2026-10-25.txt` (reproduce with `python3 research/h6_discover.py`, `research/h6_wallets.py`, `research/h6_killtest.py`). Copy period 2025-01-01 → 2025-06-30; staked SOL +2.9% over the period.

| Variant | Return in SOL (base) | Stress | Max DD |
|---|---|---|---|
| **Primary: top 10, copy 2 min late** | **−19.3%** | −20.3% | 21.5% |
| Top 10, 10 min late | −18.4% | −19.4% | 21.4% |
| Top 25, 2 min late | −6.3% | −6.8% | 8.0% |
| Top 25, 10 min late | −5.9% | −6.4% | 8.0% |

- Monthly vs staking (primary): −5.0%, −0.0%, −0.1%, −13.9%, −4.1%, −0.0%; no positive month. 130 copy signals, 51 copies made (others skipped: token already held, no price within 15 minutes, or no free cash).
- Main finding: of 1,265 wallets active in these tokens' pools, **1,252 were bots** (> 6,000 transactions in 9 months; 33 of 40 sampled made > 30,000). Only 13 human-paced wallets remained, so "top 10" is nearly all of them and "top 25" is all of them; the larger list loses less only because positions are smaller (1/25 of equity).
- Limits: discovery sees only wallets trading our ~34 tokens' main pools; positions are marked at entry until exit (step curve); "without best trade" subtracts that trade's PnL. A broader universe (all Solana tokens) would need Dune or far more Helius scanning. This family is not retuned on this window.
