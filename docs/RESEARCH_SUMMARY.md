# Research summary (25–26 Oct 2026)

Before building the product we tested whether a trading strategy on Solana DEXs could beat simply holding SOL (or USDC lending) after real costs. Every test had its rules and pass criteria written down **before** it ran. Full code, registries and reports: branch [`archive/2026-10-26-snapshot`](https://github.com/twlmed212/TradingBot/tree/archive/2026-10-26-snapshot) (`research/`, `research/registry/`, `reports/`, `PLAN.md`).

## Results

| Test | Idea | Result |
|---|---|---|
| H1 | SOL/USDC 15-minute trend | **Failed 0/5:** −5.6% vs USDC +9.4% over 1.5 years |
| H2 | Weekly momentum across 21 Solana tokens vs SOL | **Failed 0/5:** −48.9%; an equal-weight basket lost **68.6% against SOL** |
| H3a | Buy after Binance/Upbit listing announcements | **Failed 5/6:** mean +9.9% per event, but only 13 events and the 95% lower bound was −1.9% |
| H4 | Avoid tokens before big unlocks | **Not testable:** no point-in-time unlock data |
| H5 | Buy recent losers (short-term reversal) | **Failed 1/6:** −60% in SOL terms |
| H6 | Copy the most profitable wallets | **Failed 1/6:** −19.3%; 1,252 of 1,265 active "smart" wallets were bots |
| H7 | Short weak tokens vs long SOL (perps) | **Failed on risk:** +130% but a 54% drawdown |
| H8 | Hold SOL only above its 100-day average | **Failed 3/6:** helped in the 2022 crash, hurt in the 2023–25 bull |
| H9 | H7 with stops and a drawdown brake, forward paper test | **Running** on the server until 31 Jan 2027 (paper only) |
| Arbitrage | Measured on-chain over 2,000 random blocks | **NO-GO 0/3:** ≈ $56k/day for all searchers combined; 75% of it is same-block backrunning; gaps a normal bot could reach are worth ≈ $500/day market-wide, median $0 |

Measured costs: a Jupiter round trip costs about **20–50 bps** at $1k–$10k on liquid tokens, and **100–1,200 bps** on thin ones.

## What this means for the product

1. **The average Solana token loses value against SOL** (emissions, unlocks, post-listing selling). Users who trade a lot mostly lose; we should not promise profits or sell "signals".
2. **Speed wins arbitrage** (same-block, special infrastructure), and a few players take most of it.
3. **Fee takers win reliably.** Trading bots and terminals charge about 1% per trade (Axiom, Photon, Trojan, BONKbot have each earned $100M+). On-chain we also saw a swap service charging $0.10 per user swap and a bot program taking about 6% of a user's buy.
4. Our edge as a product: **non-custodial** (no key handover), **lower fee** (0.5%), and **honest cost and safety information** using the cost recorder and listing collector we already run.
