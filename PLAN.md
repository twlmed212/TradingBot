# Solana ecosystem trading bot — build plan (SOL-quoted)

**Status:** canonical implementation plan  
**Revised:** 25 October 2026 (revision 3: research-first ordering, explicit SOL exposure, slow listing test first, relative-value research track, stop rule, data budget. Revision 2 changed the universe from SOL/USDC to SOL against Solana ecosystem tokens)  
**Scope:** Solana spot DEX trading through Jupiter. SOL is the numeraire: every position is a token bought with SOL and sold back to SOL, idle capital stays in SOL (staked where practical), and success is measured against holding staked SOL.

This is an engineering and research plan, not a promise of profit or investment advice. No model or architecture guarantees an edge. The staged gates below exist to find out whether an edge exists without mistaking a backtest, an LLM's confidence, or an assumed paper fill for evidence.

## Decision

We are building a provider-neutral, cost-aware trading system that rotates between SOL and vetted Solana ecosystem tokens when, and only when, a pre-registered and tested hypothesis says a token will beat staked SOL after costs. It has:

1. deterministic data, universe, portfolio, risk, and execution code;
2. simple, pre-registered signal rules first, statistical models only if they add stable lift;
3. an optional LLM that turns frozen news/social text (for example exchange listing announcements) into bounded event features; and
4. a signer isolated from the data, model, and LLM processes.

We are **not** building an autonomous Grok trader, a new-launch sniper, or a bot that buys "whatever is pumping." Grok's useful role is reading X and announcements into structured events; it never chooses side, size, expected edge, or permission to trade. Expect AI to be a modest helper: the edge, if one exists, will come from data quality and discipline.

**Research first.** No strategy has passed yet, so the next 2–3 weeks go to data and kill tests, with only a watch-only screen. The full control console, signer gateway, and live execution are built after a hypothesis passes G2, not before.

**Stop rule.** If no hypothesis passes its kill test by **31 January 2027**, or after **6 hypotheses** beyond H1–H2 (whichever comes first), stop the trading-strategy search. Then either end the project or pivot to the product route (a tool traders pay for), which is the most reliably profitable business in this market. The stop rule is fixed now and is not moved after seeing results.

## What the evidence says so far

All measured 25 October 2026. Exploratory results: [reports/reality-check-2026-10-25.md](reports/reality-check-2026-10-25.md). Pre-registered kill tests: [research/registry/](research/registry/).

| Test | Result | Consequence for this plan |
|---|---|---|
| H1: SOL/USDC 15-minute dual-horizon trend (pre-registered) | **Failed 0/5.** −5.6% vs +9.4% for USDC at 6% over 1.5 years; turnover ~2× per day | Minute-to-hour timing is not the default clock |
| H2: weekly cross-sectional momentum, 21 Binance-listed Solana tokens vs SOL (pre-registered) | **Failed 0/5.** Walk-forward −48.9% vs staked SOL +6.9%; 0 of 9 variants beat staked SOL | Buying recent winners is not a strategy here; prior winners mean-reverted |
| H3a: slow listing drift on Solana DEXs (pre-registered, implementation deviations disclosed) | **Failed 5/6.** 13 priced primary events: mean +9.91% SOL (+9.12% stressed), median +0.91%, but the 95% bootstrap lower bound is **−1.92%**. USD-equivalent base mean +10.15%; these are event returns, not portfolio returns | No trading promotion; no retuning this family on this window. Next: H4 unlock overlay |
| Equal-weight basket of those tokens held vs SOL (May 2024 – Jun 2025) | **−68.6% in SOL terms** | The average ecosystem token decays against SOL (emissions, unlocks, post-listing reversal). SOL is the default position; token exposure is the exception that must justify itself |
| Jupiter V2 execution vs SOL (live quotes) | Platform fee **10 bps per side** on X/SOL (JUP 0; SOL/USDC 2). Round trip **~20–50 bps** at $1k–$10k on liquid names; **100–1,200 bps** at $10k on thin names (TNSR, IO, ME); FIDA, GMT, LAYER have no usable DEX liquidity | Each trade must expect more than 2× its measured round-trip cost; size is capped by quoted cost, not only by dollars |
| LP on SOL-USDC, funding carry, cross-venue funding arb (exploratory) | Zero or negative after costs in the last year | Out of scope for spot V1 |

What remains to test is information- and event-driven, not price-pattern-driven. See the hypothesis queue.

## Scope clarification

Jupiter-routed Raydium, Orca, Meteora, and similar liquidity are **DEXs**. Binance, Coinbase, Upbit and others are CEXs: their prices and announcements may be read-only features, never execution venues in this project. Binance candles are used for historical research only because public DEX history is short (GeckoTerminal's public API serves 180 days, which falls inside the sealed holdout).

## Why the current prototype cannot establish an edge

`deskbot/` is a paper-trading scaffold with useful safeguards (paper-only, no wallet key, allowlist, honeypot and Token-2022 screen, anti-sandwich caps, protective exits, append-only ledger, CLI and tests). It is not yet a strategy:

- **Unit bug after the switch to SOL as quote:** buys quote `size_usd × 10^9` lamports, so a "$150" buy is a 150 SOL order, and paper fills record SOL amounts as USD. All paper P&L is currently wrong by roughly the SOL price.
- **Protective exits are not independent:** they run after the global-halt return and after the Grok call, so a halt, model outage, or data failure blocks every exit.
- **The edge gate is circular:** Grok invents `side`, `size_usd`, `confidence`, and `expected_edge_bps`, and the risk engine compares those self-reported numbers with thresholds.
- **No entry hypothesis has been tested.** Take-profit / stop-loss / time-stop brackets shape the distribution of outcomes but do not create an edge; with ~20–50 bps round-trip cost and an ecosystem that drifts down against SOL, a bracket on an untested entry has negative expectancy.
- Paper fills come from one quote with a fixed haircut; there is no latency, expiry, failure, or exit-cost model, no dataset, no backtester, and quotes still use Jupiter Swap V1 instead of V2.

Keep every safeguard; fix the two bugs first (Milestone 0).

## Numeraire and benchmarks

- Capital, P&L, drawdown, and limits are denominated in **SOL**, with USD shown alongside.
- Idle SOL is held in a liquid-staking token (for example JitoSOL, ~4.8% APR today) only when the expected idle period covers the SOL↔LST swap cost; otherwise plain SOL.
- Every report shows side by side: staked SOL, unstaked SOL, an equal-weight basket of the eligible universe, and the strategy, plus SOL in USD terms for context.
- **SOL exposure is an explicit, separate owner decision.** Measuring in SOL means the bot is always fully exposed to SOL's USD price: it can beat its benchmark while losing half its dollar value if SOL halves. Every report therefore shows USD results next to SOL results, and the owner chooses (and records in the config) how much capital is exposed to SOL at all, independent of any strategy. Hedging SOL beta is a separate future decision.

## Universe and token safety (point-in-time)

A token is eligible on a decision date only if, using data available at that moment:

| Check | Rule |
|---|---|
| Age | First Solana pool at least 30 days old (no new-launch sniping) |
| Liquidity (core universe) | Aggregated DEX liquidity ≥ $1M and 30-day median DEX volume ≥ $1M/day. A lower floor (down to the prototype's $25k) is allowed only inside a separately registered small-cap hypothesis with its own size caps |
| Cost | Live Jupiter round trip at the intended size ≤ 50 bps |
| Anti-honeypot | Freeze and mint authority revoked (unless explicitly trusted), zero transfer fee, no dangerous Token-2022 extensions (transfer hook, permanent delegate, non-transferable, default-frozen accounts, pausable), and a sell route back to SOL that quotes within tolerance before any buy |
| Pool and rug defense | Top-10 holders < 40%; LP burned or locked where the pool type has fungible LP tokens (CLMM/DLMM positions are NFTs, so concentration and liquidity trend are used instead) |
| Anti-sandwich | Slippage ceiling 50 bps, price-impact cap 200 bps, landing through Jupiter V2 managed execution |
| Supply events | Not inside a known large-unlock window (once unlock data exists; see H4) |

Eligibility, liquidity, and safety are recomputed at every decision and every exclusion is logged with its reason. Delisted, rugged, and illiquid tokens stay in the historical dataset; a backtest containing only today's survivors is invalid.

## V1 strategy contract

| Item | V1 rule |
|---|---|
| Venue | Solana spot through Jupiter Swap API V2, which routes across Raydium, Orca, Meteora, and others. Direct pool integrations come later, only if measured to improve net results |
| Pairs | SOL against point-in-time eligible ecosystem tokens; cash held in SOL |
| Position | Long selected tokens or hold SOL; no shorts, leverage, borrowing, LP, or perps |
| Decision clock | Daily by default. A faster clock (for example every completed 15-minute interval) is allowed only for a hypothesis that pre-registers it and survives measured costs |
| Holding horizon | Set by the hypothesis; expected edge per round trip must exceed 2× the measured round-trip cost at the intended size |
| Entry | Only a signal from a pre-registered hypothesis that has passed its kill test |
| Size | Deterministic: min(policy cap, size at which the quoted round trip ≤ 50 bps, fixed % of pool liquidity); never LLM-proposed |
| Concentration | At most N concurrent tokens, at most 1/N of equity each, total token exposure capped; the rest stays in SOL |
| Exit | Signal, time, stop, take-profit, safety-screen breach, liquidity collapse, delisting, or emergency flatten to SOL. Exits run first and never wait for the model, a halt, or entry throttles |
| Exit parameters | The prototype's +15% take-profit, −7% stop-loss, and 4-hour time stop are grid parameters of each hypothesis, not defaults |
| Capital | Paper and shadow only until every promotion gate passes |

## Hypothesis queue

Each hypothesis gets a registry file with rules, data, costs, grid, and pass criteria **before** it is run. A failed family is not retuned on the same data.

| ID | Hypothesis | Status | Data needed | Where an LLM helps |
|---|---|---|---|---|
| H1 | SOL/USDC 15-minute trend | **Failed** | — | — |
| H2 | Weekly momentum rotation vs SOL | **Failed** | — | — |
| H3a | **Slow listing drift.** Primary: entry at first full UTC hour ≥ 1 h after announcement; exit at rounded trading start, with registered +24 h fallback. Six fixed variants | **Failed 5/6.** Mean +9.91% SOL per event, but confidence lower bound −1.92%; only 13 priced events, 10 excluded. Frozen pool-selection deviations disclosed in registry. No retuning or paper promotion | Binance/Upbit announcement archive and Helius-rebuilt DEX swap prices; recorded cost snapshot | Deterministic parser used; no LLM trade decisions |
| H3b | **Fast listing reaction.** Entry seconds to minutes after the announcement. Professional news bots act in under a second, so this is tested only if H3a and measured latency show a realistic window for us | Later | Same as H3a plus minute data and measured end-to-end latency | Only if it beats the parser on speed and accuracy |
| H4 | **Supply-event overlay.** Avoid holding tokens into large unlocks (for example ≥ 2% of circulating supply within 14 days); test as a filter that reduces losses vs the basket | **Data not available for a fair historical test; not registered, no trial used.** Off-chain docs cannot prove what was published when (`reports/h4-data-readiness-2026-10-25.md`), and on-chain lockers (Streamflow, Jupiter Lock) show 0 provable big-unlock windows in the research window: large on-chain vesting only starts in 2025–26 (JUP, KMNO, RAY, PUMP, MET, WET); other projects vest off-chain (`reports/h4-onchain-coverage-2026-10-25.md`). Option: forward-only collection | Point-in-time unlock calendars, supply denominators and on-chain vesting evidence; current calendars alone are insufficient | Parse unlock announcements and governance posts |
| H5 | **Short-term reversal** among liquid tokens vs SOL, suggested by H2's failure | **Failed 1/6** (quick test, 15 Hyperliquid-listed tokens, Jul 2024–Jun 2025): primary −60% in SOL vs staked SOL +6%, 88% drawdown; 1 of 6 variants positive. Buying recent losers in a decaying group fails (`research/registry/2026-10-25-h5-short-term-reversal.md`) | Must use data not used in H2: DEX-native tokens outside H2's universe, or forward-recorded data | — |
| H6 | **Copy profitable wallets** (replaced the old filtered-post-launch idea, owner approved): rank wallets monthly on the previous 3 months' realized profit, drop bots and snipers, copy the top 10 two minutes late | **Failed 1/6:** primary −19.3% in SOL vs staked SOL +2.9% (Jan–Jun 2025), 0 of 6 months positive. 1,252 of 1,265 active wallets were bots; only 13 human-paced wallets could be copied (`research/registry/2026-10-25-h6-copy-smart-wallets.md`) | Helius wallet histories | — |

| H8 | **Slow trend filter on SOL vs USDC** (hold SOL above its 100-day average, else USDC at 5%) | **Failed 3/6:** better than holding SOL in the crash-heavy 2021–23 window (Sharpe 0.96 vs 0.73) but worse in the 2023–25 bull (0.95 vs 1.47); drawdown cut too small (75% vs 96%); window A depends on Aug 2021 (`research/registry/2026-10-25-h8-slow-trend-sol.md`) | Binance daily closes | — |
| H9 | **Risk-controlled short basket vs SOL (H7 family), forward paper test**: short up to 25 liquid Solana tokens (0.5× equity) vs long SOL on public Hyperliquid prices; +30% per-token stop, 15% drawdown brake, weekly rebalance | **Running since 25 Oct 2026 23:00 UTC** (server timer `deskbot-h9`); verdict on 31 Jan 2027. Paper only, no orders or keys (`research/registry/2026-10-25-h9-short-basket-forward.md`). Verdict code `research/h9_verdict.py` written 26 Oct before any results; daily backups and run retries on the server | Hyperliquid public API, forward | — |
| H7 | **Relative value: short weak ecosystem tokens vs long SOL** on perps, the most direct way to monetise the decay measured in H2. **Research only:** trading it needs an owner scope decision (perps, shorts, squeeze and funding risk). Tested on tokens H2 never saw | **Failed on risk** (3/5): +130% vs USDC +3.5% over 31 weeks after stress costs and funding, but 54% max drawdown and a −43% eight-week block. Strongest effect found so far; a risk-controlled version can only be judged on unused data | Hyperliquid perp candles and funding history | — |

Separate track outside spot V1, needing an explicit owner decision: a staking/lending vs hedged-carry switcher (the only exploratory idea with positive history, all of it from 2023–24).

## System architecture

```text
Jupiter / Solana / CEX reference data ──► immutable observations ──► point-in-time universe + features
Announcements, X, unlock calendars ────► optional event extractor ──┘                │
                                                                                     ▼
                                                        registered signal rules / calibrated models
                                                                                     │
                                                                                     ▼
                                                        deterministic portfolio and risk policy (SOL)
                                                                                     │
                                                                                     ▼
                                                        fresh executable quote + transaction validator
                                                                                     │
                                                                                     ▼
                                                           isolated signer ──► Jupiter ──► Solana
                                                                                     │
                                                                                     ▼
                                                               confirmation and balance reconciler
```

The backtester and live bot call the same universe, feature, signal, portfolio, and cost interfaces. Only the clock, data source, and execution adapter change.

### 1. Point-in-time data layer

Every observation is keyed by at least `(observed_at, slot, mint, source, schema_version)` and keeps its raw payload hash. Publication time is not observation time.

Record per token:

- returns and realized/downside volatility in SOL and USD terms;
- DEX liquidity, volume, buy/sell flow, unique traders, holder changes;
- executable Jupiter V2 `/order` probes vs SOL at the intended size and a larger size (depth curve), with fee, impact, router, and latency;
- Jupiter Price V3 and CEX prices as references, never as fills;
- safety-screen facts at each observation;
- daily snapshots of the candidate token list, so the universe can be rebuilt for any past date; and
- immutable event documents (listing announcements, unlock notices, X posts) with source, URL, author, content hash, and first-seen time.

**Running now:** `recorder/quote_recorder.py` probes SOL/USDC every minute and 21 ecosystem tokens vs SOL at $1k and $10k (each token every 5 minutes) into `data/quotes.sqlite3`. It must move to an always-on host to meet G1's coverage requirement.

**Data budget (owner approved 25 Oct 2026; the owner signs up and enters keys):**

| Service | Plan | Price | Use | Duration |
|---|---|---|---|---|
| Helius | Developer (**paid**) | $49/mo | Production RPC, websockets, webhooks, and **historical swaps** (`getTransactionsForAddress`, 10 credits per 100 transactions) used to rebuild DEX prices for any past window, dead tokens included | Keep |
| Dune | Analyst | $75/mo | All Solana DEX trades, for a survivorship-free *universe* (which tokens existed when) | **Deferred** until H5/H6 need it |
| CoinGecko on-chain | Analyst | $129/mo | Pool OHLCV back to 2021 | **Not needed**: Helius swap history replaces it (decided 25 Oct 2026; validated against Binance: PENGU/SOL 1.536e-4 on-chain vs 1.504e-4 Binance) |
| Jupiter, Binance, Upbit, Coinbase, Hyperliquid, DefiLlama | Free | $0 | Quotes, announcements, reference prices, perp funding | Keep |

Current spend: Helius $49/month plus the AWS server (≈ $11.60/month from the free-plan credit). Birdeye (multi-token endpoints from $699/mo) and Helius Business with LaserStream ($499/mo) are deferred until a passing hypothesis needs them.

### 2. Signal layer

Challenger order for every hypothesis:

1. hold staked SOL;
2. equal-weight basket of eligible tokens;
3. the pre-registered deterministic rule;
4. a regularized linear/logistic model on the same features;
5. a gradient-boosted tree only if simpler models leave stable residual signal; and
6. the winning model plus an optional LLM event feature.

The signal service emits a typed forecast (model/version, token, horizon, expected net return in SOL or calibrated probability, uncertainty, feature timestamp, expiry). It emits no transaction bytes.

### 3. LLM event layer

If enabled, Grok or another provider receives a frozen, already-collected text corpus and returns only:

```json
{
  "event_type": "cex_listing|unlock|exploit|outage|delisting|regulatory|protocol_change|other",
  "venue": "binance|coinbase|upbit|bybit|okx|robinhood|other|null",
  "affected_mints": ["..."],
  "polarity": -1.0,
  "novelty": 0.0,
  "event_time": "ISO-8601",
  "valid_until": "ISO-8601",
  "source_ids": ["..."],
  "ambiguity": 0.0
}
```

Parser first: clean first-party feeds (exchange announcement APIs and pages) are parsed with deterministic code, which is faster and more accurate. The LLM is used for messy text such as unlock terms, exploit reports, governance posts, and third-party X posts, and only where it measurably beats the parser.

It cannot output side, size, expected edge, risk limits, a destination address, or an execution instruction. Text is untrusted and may contain prompt injection. Fake listing announcements are a known scam vector, so an event needs a first-party source (the exchange's own domain or verified account) before it can become a feature. The LLM process has read-only data credentials and no RPC send method, execute credential, key, or signer.

Evaluate each provider on a labeled event set for extraction accuracy, source grounding, run-to-run stability, latency, and cost. Keep the LLM only if the strategy with its features beats the identical strategy without them.

### 4. Portfolio and risk layer

All limits are code-enforced, denominated in SOL, and fail closed. Model output may reduce risk but never widen a limit.

- Separate entry policy from exit policy. Exits run first in every cycle and do not depend on the model, a halt, or entry throttles.
- Allowlisted token programs, route programs, and destination accounts; universe eligibility and the safety screen re-checked before every entry.
- Per-token cap (1/N of equity), concurrent-token cap, total token exposure cap, turnover and trade-frequency caps.
- Size limited by quoted round-trip cost and by a fixed fraction of pool liquidity.
- Maximum all-in cost, slippage, priority fee, and tip; maximum feature, quote, and price-reference age.
- Daily and weekly loss stops and a peak-to-trough drawdown stop, in SOL.
- Circuit breakers for liquidity collapse, safety-screen change, delisting, RPC failure, landing failure, and reconciliation mismatch.
- Independent manual kill switch; emergency flatten to SOL that does not depend on any forecast or LLM.

Risk-budget numbers must be explicitly approved before a live key can be enabled. Missing live limits are a startup error, not defaults.

### 5. Execution and reconciliation layer

Use Jupiter Swap API V2 for all V1 trades:

1. `GET /swap/v2/order` for a fresh quote and assembled transaction;
2. independently validate and sign it; and
3. `POST /swap/v2/execute` for managed landing, priority fees, retry, and result parsing.

Measure actual input and output amounts including Jupiter's platform fee (10 bps on most X/SOL swaps) rather than trusting a headline price. Sign and send immediately; abandon and re-quote expired or economically stale orders. Use `/swap/v2/build` with a private RPC or Jito only after measurement shows it materially improves net results. A successful submission is not a fill.

```text
CANDIDATE -> RISK_APPROVED -> QUOTED -> VALIDATED -> SIGNED
          -> SUBMITTED -> CONFIRMED -> FINALIZED -> RECONCILED
                         \-> FAILED | EXPIRED | CANCELLED
```

Each intent has an idempotency key. Persist request IDs, signature, blockhash, last-valid block height, quote/submit times, expected and actual amounts, fee/tip budgets, route, confirmation state, and errors. On-chain balances are the source of truth.

### 6. Signer boundary

Cold treasury plus a separately funded, balance-capped strategy wallet. Production keys live in a KMS/HSM/MPC or equivalent managed signer, never in `.env`.

Before any signature the signer gateway independently verifies the fee payer, the exact input/output mints (one side must be SOL/wSOL), maximum input and minimum output, token-account ownership, every program ID and instruction, no unknown signers or writable accounts, only capped transfers to approved tip accounts, compute/priority/platform-fee/tip caps, and a fresh quote matching an approved intent.

## Validation protocol

### Research rules

- Pre-register hypothesis, universe rule, labels, features, parameter grid, cost model, number of trials, metrics, and pass thresholds before any run. Keep a trial ledger that includes failures (H1 and H2 are the first entries).
- Chronological walk-forward only; purge training samples whose labels overlap the test window and embargo at least the label horizon.
- Fit every transformation, eligibility threshold, and calibration inside training folds.
- Sealed holdout: **1 July 2025 onward**, across all research data. It is evaluated once, for G2, never during exploration. H3a's original fetcher accidentally stored 216 DEX hours and 754 SOL reference hours beyond the cutoff; this was found from metadata before returns. They remain preserved but excluded from loading/evaluation. Fetch windows and readers now enforce the cutoff; see the registry audit disclosure. Do not describe this holdout as never fetched.
- Point-in-time universe including dead and delisted tokens; state any survivorship or listing bias explicitly. A pass on biased data is weak evidence; a fail is strong.
- Costs from measured Jupiter quotes at the intended size, per token, with a 2× stress scenario and a capacity sweep.
- Report net return in SOL and USD, excess return over staked SOL, autocorrelation-robust Sharpe, Sortino, max drawdown, time under water, turnover, tail loss, implementation shortfall, capacity per token, and results by regime. Use block bootstrap intervals, Deflated Sharpe Ratio, and Probability of Backtest Overfitting when comparing variants.

### Promotion gates

Thresholds may change only before an evaluation window begins, never after seeing its result.

| Gate | Minimum evidence to advance |
|---|---|
| G0 — runnable | CLI, deterministic replay, unit/integration tests, schema validation, failure injection; unit-consistent SOL accounting; exits proven to run during halts, model outages, and data failures; no signing code enabled |
| G1 — data | Point-in-time replay deterministic; leakage tests pass; recorder ≥ 99.5% of expected snapshots with all gaps marked; universe rebuildable for any past date |
| G2 — research | Outer-fold excess return over staked SOL positive in ≥ 70% of folds, survives 2× measured costs, within the drawdown budget, Deflated-Sharpe confidence ≥ 95%, PBO ≤ 10% when variants were compared, not dominated by one token, trade, or period, and confirmed on DEX-native data, not only Binance |
| G3 — AI | The LLM event feature adds stable net lift over the identical no-AI strategy in outer folds and the holdout; otherwise ship without AI |
| G4 — shadow | ≥ 8 weeks and ≥ 100 eligible intents across ≥ 5 different tokens; delayed re-quotes keep positive expectancy at observed P95 costs; modeled vs observed cost and latency inside frozen tolerances |
| G5 — canary | Separate capped wallet, manual approval for the first 20 entries, ≥ 30 days, zero signer-policy violations or unreconciled balances, realized execution inside shadow tolerances |
| G6 — scale | Raise one limit at a time, by no more than 2×, after a fresh review window; automatic rollback on breach |

Failing a gate means diagnose, write a new registration, and start a new window. It never means lowering the threshold afterwards.

## Repository delivery order

### Milestone R — research sprint (first, 2–3 weeks)

- ~~Owner buys the data plans above~~ Helius bought; event-window prices are rebuilt from on-chain swaps (`research/listing_prices.py`). Dune only when H5/H6 start.
- ~~Build the listing-announcement archive (free first-party sources) and run H3a.~~ Done 25 Oct 2026: failed 5/6; confidence criterion failed.
- Run H7 (research only) and H4 once unlock data exists.
- Build only a **watch-only screen**: recorder data health, universe and costs, test results. No control actions, keys, or wallet panels yet.
- ~~Fix the two `deskbot/` bugs (Milestone 0, first two items).~~ Done 25 Oct 2026.
- Watch-only console: done 25 Oct 2026 (`console/`, served on the server at 127.0.0.1:8787, opened with `ssh tradingbot-console`).

**Exit:** at least one hypothesis passes its kill test (continue to Milestones 0–2 in full), or the stop rule applies.

**Progress (25 Oct 2026):** H7 failed on risk. Listing archive built with `research/announcements.py`: 2,287 Binance and 803 Upbit announcements, parsed by rules. `research/listing_events.py` built 63 Solana events with first-party evidence, 27 in the research window. H3a price fetch is complete; the fixed test failed 5/6 (23 deduplicated events, 13 priced primary trades). Bootstrap lower bound −1.92%; no promotion. The pre-run audit repaired holdout guards and documented pool-selection deviations without repicking pools or changing thresholds. **2 of 6 hypotheses beyond H1–H2 used: H7 and H3a. Next: preregister H4 once point-in-time unlock data is verified; no paid data purchase without owner approval.**

H4 data preparation update (25 Oct 2026): `research/unlock_sources.py` archives four first-party documents with receipt timestamps and raw hashes, without prices or keys. Current captures do not prove historical availability. The source audit is in `reports/h4-data-readiness-2026-10-25.md`; H4 remains pending and the hypothesis count stays 2/6. No paid data purchase or server service was added.

H5 (25 Oct 2026): quick test on the 15 Hyperliquid-listed tokens failed 1/6 (primary −60% in SOL). Hypotheses used beyond H1–H2: 6 of 6 (H7, H3a, H5, H6, H8, H9). H9 is a forward paper test running until 31 Jan 2027; no further hypotheses before the stop-rule date. H8 (slow trend filter on SOL) failed 3/6. H6 (copy smart wallets) failed 1/6: −19.3% in SOL; 1,252 of 1,265 active wallets were bots.

H4 on-chain check (25 Oct 2026): `research/unlock_onchain.py` scanned Streamflow and Jupiter Lock for 45 tokens. Zero big-unlock windows (≥ 2% of supply in 14 days) are provable in the research window. A historical H4 kill test is not possible without hindsight; forward-only collection or a paid feed with provable publication dates are the remaining options (owner decision).

**Owner decision (26 Oct 2026):** waiting until 31 Jan 2027 for H9 is not acceptable as the only path. H9 keeps running in the background (no cost, no attention needed). The owner chose to **measure Solana DEX arbitrage before building anything** (other options offered: a fee-earning trading tool via Jupiter's referral program; passive yield). Measurement plan and go/no-go rule: `research/registry/2026-10-26-arb-market-measurement.md`; code `research/arb_census.py`. This is a market measurement, not a strategy backtest, and uses no hypothesis slot. GO only builds a shadow-mode prototype (no funds, no transactions sent). **Result (26 Oct 2026): NO-GO, 0 of 3.** Solana atomic arbitrage nets about $56k/day across all searchers (top 10 take 82%; 13 failed attempts per success). 75% of arbitrages and nearly all the profit come from same-block backruns; gaps open ≥ 3 slots are worth about $505/day market-wide with a median of $0. Do not build an arbitrage bot.

### Milestone 0 — make the scaffold truthful and runnable

- ~~Fix SOL-quote unit handling in `deskbot/engine.py` (`_quote` and `_paper_fill`) and move all accounting to SOL with explicit USD conversion.~~ Done 25 Oct 2026: sizes convert at the live SOL price, the ledger keeps cash and cost basis in SOL, take-profit/stop-loss are measured in SOL terms.
- ~~Run protective exits before the halt check and before any model call, independent of model and data availability for already-held positions.~~ Done 25 Oct 2026: exits run first every cycle; the kill switch flattens to SOL even without fresh prices; model sells skip entry throttles. Covered by `tests/test_engine_units_and_exits.py`.
- Remove `side`, `size_usd`, `confidence`, and `expected_edge_bps` from the LLM schema; replace with the event schema above.
- Migrate quotes to Jupiter Swap API V2 on `https://api.jup.ag`; batch token lookups.
- Introduce interfaces: `MarketDataSource`, `UniverseBuilder`, `FeatureBuilder`, `SignalModel`, `EventExtractor`, `RiskPolicy`, `ExecutionAdapter`, `SignerGateway`, `Reconciler`.
- Enforce finite, ranged values and timestamps at every boundary.

**Gate:** G0.

### Milestone 1 — build the evidence dataset

- Keep the forward quote recorder running on an always-on host; add daily token-list snapshots for the point-in-time universe.
- Decide and acquire historical DEX-native data (owner decision above).
- Build the listing-announcement archive (H3) and unlock calendar (H4) with first-seen timestamps.
- Add data-quality, staleness, gap, and clock-drift monitoring.

**Gate:** G1.

### Milestone 2 — replay, baselines, and the next kill tests

- One event-driven replay engine shared with live interfaces, with latency, expiry, failure, fee, impact, and exit-cost models from recorder data.
- Baselines: staked SOL, SOL, equal-weight basket.
- Pre-register and run H3 and H4; then H5 on data not used in H2; H6 last.

**Gate:** a deterministic rule must pass G2 before any learned model complicates it.

### Milestone 3 — models and optional text

- Regularized models first, then one tree challenger, calibrated inside training windows.
- Evaluate Grok and other extractors on a labeled listing/unlock event set; run with/without ablations.

**Gates:** G2 and G3.

### Milestone 4 — shadow execution

- Run the exact live loop without signing; re-quote after the measured decision delay; log 1m/5m/1h/4h/24h markouts per token.
- Model landing, expiry, min-out failure, and signer-policy rejection.

**Gate:** G4.

### Milestone 5 — guarded canary and gradual scale

- Isolated signer, capped hot wallet, transaction parser, redundant private RPC, confirmation, reconciliation.
- Manual entry approval at first; risk exits automatic and independent.
- Exercise kill switches, RPC failover, duplicate-send protection, stale-quote rejection, and emergency flatten to SOL before funding.

**Gates:** G5, then G6.

## Explicit non-goals for V1

- Autonomous LLM decisions or signing
- New-launch / pump.fun sniping, copy trading, or sandwiching
- Momentum rotation on CEX-listed alts (H2 failed) or minute-level SOL/USDC timing (H1 failed)
- Trading shorts, perps, leverage, LP, or bridges (H7 is research only; trading it needs an explicit owner decision)
- Direct pool integrations, custom Jito bundles, or colocated infrastructure, until measurement justifies them
- A token for the bot, a promotion agent, or a public terminal product
- Optimizing many strategies until one backtest looks profitable

## Definition of success

V1 succeeds when it gives an auditable answer to:

> After every observable Solana execution cost, with a point-in-time universe that includes dead tokens and an untouched test, does this exact rule hold ecosystem tokens that beat staked SOL, at a known capacity and drawdown, and does the AI feature improve it?

If the answer is "no," the correct result is a safe, reproducible rejection and SOL stays the position — not a live wallet attached to a more persuasive prompt.

## Primary and official references

- [Jupiter Swap API V2 overview](https://developers.jup.ag/docs/swap/index)
- [Jupiter order and managed execution](https://developers.jup.ag/docs/swap/order-and-execute)
- [Jupiter Tokens V2](https://developers.jup.ag/docs/tokens/token-information)
- [Jupiter Price V3](https://developers.jup.ag/docs/price)
- [Solana production readiness](https://solana.com/docs/tools/production-readiness)
- [Solana RPC and commitment levels](https://solana.com/docs/rpc)
- [Solana fee mechanics](https://solana.com/docs/core/fees)
- [Solana production signing guidance](https://solana.com/docs/core/transactions/signing-in-production)
- [Solana Token Extensions](https://solana.com/docs/tokens/extensions)
- [Jito low-latency transactions and bundles](https://docs.jito.wtf/lowlatencytxnsend/)
- [Yellowstone Dragon's Mouth gRPC](https://docs.triton.one/project-yellowstone/dragons-mouth-grpc-subscriptions)
- [AI-Trader live LLM benchmark](https://arxiv.org/abs/2512.10971)
- [Agentic Trading: When LLM Agents Meet Financial Markets](https://arxiv.org/abs/2605.19337)
- [Pretrained time-series models for return forecasting](https://arxiv.org/abs/2606.27100)
- [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Indirect prompt injection against tool-using LLMs](https://arxiv.org/abs/2302.12173)
- Internal: [reality check](reports/reality-check-2026-10-25.md), [H1 registry](research/registry/2026-10-25-trend-killtest.md), [H2 registry](research/registry/2026-10-25-ecosystem-momentum-killtest.md)
