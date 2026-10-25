# Reality check: which Solana strategies beat lending? (25 October 2026)

Exploratory measurements taken on live public data on 25 October 2026, before [PLAN.md](../PLAN.md) existed. These numbers are exploratory, not pre-registered: use them to choose what to test, never as evidence for promotion gates. Not investment advice.

## The bar

| Alternative | Yield (DefiLlama, 25 Oct 2026) |
|---|---|
| USDC lending (Kamino, Jupiter Lend) | **5–8% APR** |
| Liquid-staked SOL (JitoSOL, JupSOL, mSOL…) | ~4.6–5.4% APR |

Any strategy whose cash leg sits idle has to beat this, not 0%.

## Results

| Strategy | Window | Result |
|---|---|---|
| Orca SOL-USDC Whirlpool (0.04%, $28.8M TVL), fees vs LVR at the active tick | 24h | LP fees ~$20.4k vs continuous-time LVR ~$47.8k → **fees/LVR ≈ 0.43**. Continuous LVR overstates loss when fee ≫ per-block volatility (Solana 400 ms), so this is an upper bound on loss, not a measurement |
| Same pool, simulated LP position ±1% … ±25%, re-centred when out of range | 30 days, SOL −15.5% | **Unhedged:** −5.9% to −16.1% (50/50 hold −7.7%). **Delta-hedged on Hyperliquid:** −0.3% to −9.0%. USDC lending ≈ +0.5% |
| Short SOL perp for funding (Hyperliquid) | 12 months | Mean funding **+0.8% APR**; 36% of hours negative; trailing-7d never above 14% |
| BTC / ETH perp funding (Hyperliquid) | 12 months | +5.8% / +6.4% APR, i.e. no better than lending |
| Hyperliquid vs Binance funding-spread arb (SOL, BTC, ETH), trailing-signal entry, 0.2% round-trip cost | ~11 months | **Negative or zero at every threshold/lookback tested** (−53% to 0% APR on notional). Spreads mean-revert before they pay |
| Lend USDC; switch to JitoSOL + short SOL perp when trailing-7d funding > 15–30% | Jun 2023 → Oct 2026 | **12.7–13.9% APR vs 6.2% always-lend.** All of the excess came from 2023–24 (SOL funding averaged 14% in 2023, 28% in 2024, 5% in 2025, 0.5% in 2026); in the last 12 months it never left lending |

## Caveats

- LP backtest assumes today's fee-per-liquidity for the whole 30 days and hourly closes; one falling-market month.
- The switcher assumes a flat 6% lending rate (2024 lending paid more, which narrows the gap), 7% LST yield, 1/3 margin on the short leg with no liquidation modelling, and only three market regimes of history. It carries exchange, protocol, and liquidation risk.
- Snapshot cross-venue funding gaps (for example SOL: Hyperliquid +10.6% vs Binance −4.8% APR on the day) look large but did not persist in history.

## What this changes in the plan

1. The "cash" baseline in every report should earn the prevailing USDC lending rate, with 0% shown alongside.
2. LP on the main SOL-USDC pool and cross-venue funding arbitrage are deprioritised by evidence, consistent with PLAN.md's non-goals.
3. The lending/carry switcher is the only tested idea with positive excess history; it is regime-dependent and out of V1 scope (perps). Candidate for a separate track.

## Sources

Hyperliquid `info` API (`metaAndAssetCtxs`, `fundingHistory`, `candleSnapshot`); Binance futures `premiumIndex`, `fundingInfo`, `fundingRate`; Bybit v5 tickers; Orca `api.orca.so/v2/solana/pools`; DefiLlama `yields.llama.fi/pools`. LP simulation: [research/reality_check/lp_backtest.py](../research/reality_check/lp_backtest.py).
