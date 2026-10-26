# Measurement plan: Solana DEX arbitrage — how much profit exists, who takes it, and can a slower bot reach it

**Type:** market measurement with a go/no-go rule (not a strategy backtest; uses no hypothesis slot)  
**Registered:** 26 October 2026, after a 2-block pilot (used only to check data format and the detector), before the sample is drawn  
**Owner decision (26 Oct 2026):** stop waiting on research results and look for a faster way to make money on DEXs; chose "arbitrage bot, measure first" over a fee-earning tool and passive yield. No funds, keys or live transactions are involved in this measurement.

## Questions

1. **Size:** how much net profit do on-chain atomic arbitrage transactions make per day on Solana (after transaction fees and visible tips)?
2. **Concentration:** what share goes to the largest searchers?
3. **Competition:** how many transactions fail per successful arbitrage?
4. **Reachability:** how much of that profit comes from price gaps that stayed open for **≥ 3 slots (≈ 1.2 s)**, the kind a well-built but non-colocated bot (AWS + Helius, no ShredStream or validator deals) could plausibly reach?

## Data

- **Stage A (census):** 2,000 slots drawn uniformly at random from the 7 days before the draw; full blocks from Helius `getBlock` (JSON, all transactions, version ≤ 1). Skipped slots are replaced by new random draws. Raw blocks are kept (gzip) so the analysis can be rerun.
- **Stage B (reachability):** 300 arbitrage transactions drawn at random from Stage A (profit-weighted draws are not used). For each, every writable account other than the signer, the signer's own token accounts, tip accounts and programs is checked for the last successful transaction that touched it before the arbitrage: earlier in the same block (from the block itself), otherwise via Helius `getTransactionsForAddress` (slot < arbitrage slot, status succeeded, limit 1). The opportunity age is the smallest gap across those accounts.
- SOL/USD: Binance SOLUSDT hourly closes. USDC and USDT count as $1.

## Arbitrage detector (fixed now)

A successful transaction is an atomic arbitrage when, from token balance changes (`preTokenBalances`/`postTokenBalances`, WSOL counted as SOL):
- **User swaps are excluded:** if the fee payer's own token holdings changed in two mints (one up, one down), the transaction is a user's swap, not a loop. (Added after the pilot, before the sample: without it, a user's buy plus a per-coin creator fee looked like a loop.)
- **Pools** are owners whose token holdings changed in at least two mints, with at least one increase and one decrease.
- At least **two pools** are involved, and summed over all pools exactly **one mint** has a net change beyond tolerance (|net| > 0.01% of the pools' gross flow in that mint), and that change is **negative** (the pools together paid out value). Every intermediate mint nets to ~zero: the trade was a loop.
- **Profit** goes to the non-pool owners who received that mint, excluding **fee receivers**. A fee receiver is an owner seen receiving a single mint in at least 20 non-arbitrage swap transactions in the sample. Net profit = what those owners received − the transaction fee − Jito tips paid in the transaction (8 known tip accounts). Tips paid in a separate bundle transaction are not visible; where the same fee payer sends a tip-only transaction in the same block, it is subtracted.
- Profit in SOL, USDC or USDT is valued in USD; loops that start in any other mint are counted but not valued, and their share is reported.
- **Searcher group** = the first top-level program that is not a standard program (System, Compute Budget, Token, Token-2022, Associated Token, Memo); if the arbitrage calls DEX programs directly or goes through Jupiter, the group is the fee payer.
- **Failed arbitrage attempts** = failed transactions whose top-level programs include a searcher-group program seen in successful arbitrage in the sample.

### Detector fixes after the first run (26 Oct 2026, disclosed)

The first run reported $1.58M/day of net profit. Inspection showed false positives, fixed as below. **No go/no-go threshold was changed**, and reachability (Stage B) had not been measured yet.

1. **Nobody outside the pools may pay in.** The top two "earners" were users selling through a separate account (for example a vault or order account) that got a few cents back, so it looked like a pool; one "pool" priced the token 30,000x differently from the other. Any non-pool owner with a net decrease now means it is not a loop.
2. **Fee receivers count on the pools' side only where they receive.** A gasless-swap relayer's accounts had been tagged as fee receivers, which turned users' swaps (with a fixed $0.10 service fee) into "loops".
3. **Sane prices:** the take must be at most the pools' inflow of that mint (output at most 2x input). The 39 detections above that bound held 77% of the first run's profit; detections between 20% and 1,000% margin held under 0.5%.
4. **Pools are program accounts.** After fixes 1–3 ($278k/day), the largest group (59%) was a swap service settling real users' orders with round amounts (exactly 5.00 USDC in, 4.90 out, 0.10 fee): each user's wallet looked like a pool. A pool owner must now be a program-derived address (not a valid ed25519 key) and not a signer of the transaction. Checked on known wallets (on the curve) and known pool authorities (off it).

After the fixes, a random audit of detections is reported with the results.

**Stage B addition (before Stage B ran):** besides the registered age (all writable pool-side accounts), Stage B reports a **vaults-only** age (only the pools' token vaults) and which account most often set a same-slot age. Some exchanges write an exchange-wide account on every trade, which would make every gap look same-slot. The GO test still uses the registered age; the vaults-only figure is a sensitivity check.

## Go / no-go rule (all three required for GO)

GO means: build a **shadow-mode prototype** (detects and simulates opportunities, sends nothing, no funds) and measure our own latency. NO-GO means: do not build an arbitrage bot; report the numbers.

1. Estimated net arbitrage profit from opportunities that stayed open **≥ 3 slots** is at least **$1,000 per day** market-wide (so a 10% share would be ≥ $100/day).
2. In that ≥ 3-slot class, no single searcher group takes more than **50%** of the profit, and the top 10 groups take less than **90%**.
3. The median net profit per ≥ 3-slot arbitrage is at least **$0.50** (above our likely fee, tip and error costs).

Daily figures are scaled from the sample: (profit in sampled blocks) × (blocks in 7 days ÷ sampled blocks) ÷ 7, with a 95% bootstrap interval over blocks; the GO test uses the point estimate and reports the interval.

## Disclosures

- Only arbitrage that someone already captured is visible; missed opportunities are not. Sandwich attacks are excluded by design (they harm users and are out of scope).
- Profit sent through separate bundle tips or private deals is overstated where the tip is invisible. Prop AMMs that update prices without moving tokens can make an opportunity look older than it was; Stage B uses all writable pool accounts, not only token vaults, to limit this.
- Thresholds are the owner's business bar, fixed before the sample; they are not changed after seeing results.

## Result (run 26 October 2026) — **FAIL: NO-GO, 0 of 3 criteria**

Reproduce: `python3 research/arb_census.py analyze` then `reach` (raw blocks in `data/arb_blocks/`, 1.2 GB, on the Mac).

**Stage A (2,000 random blocks, 19–26 Oct 2026, 1.28M transactions, 22% failed):**
- 1,897 atomic arbitrage loops in the sample, about **380,000 per day**; 99% loop through SOL, USDC or USDT.
- Net profit, all searchers combined: **≈ $56,000/day** (95% interval $22k–$106k); gross $68.5k/day; transaction fees 109 SOL/day; visible Jito tips 10 SOL/day.
- Per arbitrage: median **$0.000**, 90th percentile $0.05, 99th $1.84, largest $64.66; 15% net ≤ 0.
- 194 searcher groups; the top 1 takes 29%, top 5 73%, top 10 82%.
- **13 failed attempts per success** by arbitrage programs.
- Audit: 20 random detections and the 10 most profitable were all checked by hand; all 30 are genuine single-signer loops through program-owned pools.

**Stage B (300 random arbitrages): how long the price gap had been open**
- **Same slot: 75%** of arbitrages, holding almost all the profit ($23.28 of $23.88 in the sample): searchers backrun the trade that created the gap inside the same block.
- 1–2 slots: 21% ($0.20). **≥ 3 slots: 4% ($0.40)**, i.e. about **$505/day market-wide**, median $0.000, one group takes 87%.
- Sensitivity (pool vaults only): 7% are ≥ 3 slots old, $0.31 in the sample. No single exchange-wide account explains the same-slot ages (the most frequent set 12 of 225).

| Criterion | Result | Pass? |
|---|---|---|
| ≥ $1,000/day from gaps open ≥ 3 slots | $505/day | No |
| Top group ≤ 50%, top 10 < 90% (≥ 3-slot class) | 87%, 100% | No |
| Median net per ≥ 3-slot arbitrage ≥ $0.50 | $0.000 | No |

**Reading:** on-chain arbitrage on Solana is a same-block speed race. The money ($56k/day in total) goes to a few searchers who see a trade before it lands and place their transaction right behind it (Jito bundles, ShredStream, validator proximity). Gaps that stay open long enough for a normal bot are worth about $500/day across the whole market, with a median of zero. Not measured: CEX–DEX arbitrage (needs exchange accounts and inventory, and is dominated by market makers).

Side finding: the transactions that looked most profitable at first were **fee businesses**: a swap service charging $0.10 per user swap, and a trading-bot program taking about 6% of a user's buy.
