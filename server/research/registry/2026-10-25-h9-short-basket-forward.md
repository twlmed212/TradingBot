# Pre-registration H9: risk-controlled short basket vs SOL — forward paper test (H7 family)

**Hypothesis:** H9 (H7 family, judged only on new data)  
**Registered:** 25 October 2026, before the paper engine's first run  
**Status:** last of the 6 slots (6 of 6). **Paper only**: public Hyperliquid prices, no account, no keys, no orders. Owner approved paper testing with Hyperliquid prices.  
**Evaluation window:** first engine run → **31 January 2027** (the stop-rule date). Forward data only; no historical data is used for the verdict.

## Hypothesis

Solana ecosystem tokens keep losing value against SOL (H2: basket −69% vs SOL; H7: short basket +130% but a 54% drawdown). A **smaller, stop-protected** dollar-neutral position — short a basket of liquid Solana tokens, long SOL, on Hyperliquid perps — earns more than USDC lending with drawdowns small enough to live with.

## Universe (fixed list)

Solana-native or Solana-based tokens with live Hyperliquid perps on 25 Oct 2026: PUMP, FARTCOIN, GRASS, USELESS, PYTH, TRUMP, PENGU, kBONK, JUP, JTO, WIF, W, RENDER, POPCAT, GOAT, MOODENG, PNUT, ME, GRIFFAIN, MELANIA, LAYER, BOME, TNSR, IO, SKR. Long leg: SOL perp. Tokens listed later are not added. A token delisted by Hyperliquid while held is closed at its last mark.

## Rule (checked every hour; rebalanced weekly)

- **Weekly rebalance**, first run after Monday 00:00 UTC. A token is eligible if: listed on Hyperliquid ≥ 30 days; median daily notional volume over the last 30 days ≥ **$1M**; 24 h price change ≤ +40% (do not short into a squeeze); funding ≥ −50% APR (do not pay heavily to stay short); not blacklisted.
- **Size:** gross 1.0× equity: shorts total 0.5× equity, equal-weight across eligible tokens (each ≤ 0.1× equity); long SOL perp equal to the short total. Fewer than 5 eligible tokens: shorts scale down to n/5 of 0.5×.
- **Per-token stop:** if a short's price rises ≥ 30% above its entry, close it at the hourly mark and blacklist the token for 14 days.
- **Drawdown brake:** if equity falls ≥ 15% below its peak, halve all positions and keep gross at half for 7 days.
- **Costs:** 10 bps per side on traded notional (Hyperliquid taker ≈ 4.5 bps plus slippage). **Funding:** actual hourly rates (shorts receive positive funding, the SOL long pays it).
- Collateral: $10,000 paper USDC, earning nothing on Hyperliquid; the benchmark is USDC lending at 5% APR.

## Pass criteria (all required, at 31 Jan 2027)

1. Net return (after costs and funding) above USDC at 5% for the same period.
2. Maximum drawdown (hourly marks) ≤ 15%.
3. At least 55% of completed weeks are positive.
4. No single token contributes more than 50% of total profit.
5. The engine completed ≥ 95% of expected hourly runs (data quality).

## Disclosures

About 14 weeks is a short window; a pass would only justify continuing the paper test, never live trading. Liquidity in these perps is thin today, so the basket may often be under 5 names. This uses the last hypothesis slot; after it, the stop rule applies on 31 Jan 2027.

## Clarifications (added 25 Oct 2026, 23:30 UTC, after only the opening hourly run; no weekly or per-token results exist yet)

How the criteria are counted, written down before the numbers exist (the console shows the same calculations as "so far"):

- **Weeks (criterion 3):** a week runs Monday 00:00 → Monday 00:00 UTC. Its return = equity at its last hourly run ÷ equity at the previous week's last run (the opening run for the first week). The opening hour (Sun 25 Oct 23:00) belongs to no week; the 14 weeks from 26 Oct 2026 to 31 Jan 2027 are the ones counted. The net return (criterion 1) still includes that hour.
- **Token share (criterion 4):** a token's contribution = realized P&L + funding − costs + unrealized P&L at the final hourly mark. SOL (the long leg) counts as a token. It is checked only when total profit is positive (otherwise criterion 1 already fails).
- **Drawdown (criterion 2):** measured on hourly equity from a running peak that starts at $10,000, the same peak the engine's brake uses.
- **Runs (criterion 5):** expected runs = every hour from the opening run through 31 Jan 2027 23:00 UTC (2,353 hours).

## Operations log

- **26 Oct 2026, 01:55 UTC:** no code or rule change. Hardening only: a failed hourly run now retries every 4 minutes within the hour (systemd `Restart=on-failure`), daily SQLite copies at 03:15 UTC and daily disk snapshots at 03:30 UTC (7 kept). Any restore from a backup will be logged here.
- **26 Oct 2026, ~02:05 UTC — engine fix, disclosed:** `h9_paper.py` now does nothing after 31 Jan 2027 23:59 UTC. Before this, the hourly runs would have kept applying stops, funding and hedge changes after the window, changing the positions and per-token P&L the verdict reads. No effect inside the window. Same time: the verdict code `research/h9_verdict.py` was written (before any weekly or per-token result existed). It counts the criteria as in *Clarifications* and takes the final per-token prices from the open of the last hour's Hyperliquid 1-hour candle, because the engine stores equity but not per-token marks. The console card calls the same code. Tests: `tests/test_h9_verdict.py`.
