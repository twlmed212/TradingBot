# Solana DEX systematic trading bot — build plan

**Status:** canonical implementation plan  
**Revised:** 25 October 2026  
**Scope:** Solana spot DEX trading, initially SOL/USDC, long-or-cash, 15-minute decisions and a 1–4 hour forecast horizon

This is an engineering and research plan, not a promise of profit or investment advice. No model or architecture guarantees an edge. The purpose of the staged gates below is to discover whether an edge exists without mistaking a backtest, an LLM's confidence, or an assumed paper fill for evidence.

## Decision

We are **not** building an autonomous Grok trader.

We are building a provider-neutral, cost-aware quantitative trading system with:

1. deterministic data, portfolio, risk, and execution code;
2. a simple statistical forecast model trained on point-in-time data;
3. an optional LLM that converts frozen news/social text into bounded event features; and
4. a signer isolated from the data, model, and LLM processes.

Grok remains useful because its API can search X and return structured data, but it is a candidate text extractor, not the source of direction, expected edge, position size, or permission to trade. It ships only if it beats the same strategy with no text feature on untouched data and in forward shadow trading.

## Scope clarification

Solana venues such as Jupiter-routed Raydium, Orca, and Meteora liquidity are **DEXs**, not CEXs. A CEX such as Binance, Coinbase, or Kraken is a different execution and custody system. This plan targets Solana DEX execution. CEX prices or order books may later be read-only reference features, but a CEX execution adapter must be a separate project with separate accounting and risk controls.

## Why the current prototype cannot establish an edge

The repository contains useful safeguards, but it is currently a paper-trading scaffold rather than a strategy:

- `deskbot/grok.py` asks Grok to invent `side`, `size_usd`, `confidence`, and `expected_edge_bps`. The risk engine compares those self-reported numbers with thresholds, so the most important gate is circular rather than empirical.
- There is no historical dataset, reproducible feature pipeline, explicit alpha hypothesis, benchmark, backtester, calibration, or walk-forward evaluation.
- A paper fill is assumed immediately from one quote, with an arbitrary half-slippage haircut and fixed network fee. It does not model quote expiry, decision latency, failed transactions, dynamic priority fees, Jupiter fees, route changes, adverse selection, or exit costs.
- Entry throttles can also block protective exits. A daily trade cap, cooldown, low model confidence, global halt, or model outage must never prevent risk reduction.
- Invalidation conditions are stored as prose and never run as stop, time, or thesis exits.
- The configured public Solana RPC is unsuitable for production, and the code uses Jupiter Swap V1 plus the old Lite base instead of the current Swap API V2 path.
- The package is not runnable end to end: the declared `deskbot.cli` is missing, tests are empty, and there is no scheduler or implemented approval flow.

Keep the good parts: paper-only operation today, no wallet key in `.env`, typed model output, token allowlisting, deterministic hard limits, token-extension checks, and the append-only decision/fill ledger.

## V1 strategy contract

The first strategy is deliberately narrow so that results are interpretable.

| Item | V1 rule |
|---|---|
| Venue | Solana spot through Jupiter |
| Pair | SOL/USDC only |
| Position | Long SOL or cash in USDC; no short, leverage, borrowing, LP, or perps |
| Decision clock | Every completed 15-minute interval; no intrabar look-ahead |
| Holding horizon | 1–4 hours, with a machine-readable time exit |
| Objective | Predict the net executable outcome, not raw price direction |
| Entry | Only when a conservative forecast clears the complete round-trip cost plus a frozen safety margin |
| Size | Deterministic volatility/depth sizing capped by risk policy; never LLM-proposed |
| Exit | Signal exit, time exit, risk stop, stale-data stop, or emergency flatten; exits bypass entry throttles |
| Initial capital | Paper and shadow only until every promotion gate passes |

The first deterministic challenger is a predeclared dual-horizon trend/regime rule with volatility targeting. Exact horizons and thresholds are chosen using only the training period, written into the experiment registry, and frozen before outer testing. The first learned models are regularized logistic/linear models; a gradient-boosted tree is allowed only if it adds stable outer-fold lift. Reinforcement learning, deep sequence models, multi-agent committees, and memecoin discovery are explicitly out of V1.

### Prediction target

For each decision time and intended order size, predict either:

- expected 1-hour and 4-hour **net** return with uncertainty; or
- `P(net round-trip return > hurdle)`.

The label starts at the executable quote available **after** the measured decision delay and subtracts:

- entry and exit route price impact;
- AMM/RFQ and Jupiter platform fees;
- token transfer fees when applicable;
- base and priority fees, optional tips, and failed-send costs;
- observed quote-to-fill slippage and adverse selection; and
- a frozen safety buffer.

A raw next-price prediction is not a tradable label.

## System architecture

```text
Jupiter / Pyth / Solana data ──► immutable observations ──► versioned features
News and social snapshots ─────► optional event extractor ─┘        │
                                                                    ▼
                                   baseline + calibrated signal model
                                                                    │
                                                                    ▼
                                   deterministic portfolio/risk policy
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

The backtester and live bot must call the same feature, signal, portfolio, and cost interfaces. Only the clock, data source, and execution adapter change.

### 1. Point-in-time data layer

Every observation is keyed by at least `(observed_at, slot, mint, source, schema_version)` and retains its raw payload hash. Publication time is not observation time.

Record:

- 5m/15m/1h/4h returns and realized/downside volatility;
- buy/sell volume, unique traders, and liquidity changes;
- Jupiter route and DEX mix;
- executable `/order` quote probes at the intended size and at a larger size for a depth curve;
- quote output, fees, price impact, expiry, and request latency;
- Jupiter Price V3 as a reference, not as a fill;
- Pyth price, confidence, and freshness as an independent divergence/staleness check;
- priority-fee conditions and, later, landing/tip observations; and
- immutable news/social documents with source ID, URL, author, content hash, and first-seen timestamp.

Use Jupiter Tokens V2 for metadata and screening, and batch known mints in one call. Treat verification, organic score, holder concentration, and liquidity as features—not guarantees of safety. Start with HTTP at the 15-minute horizon. Add Yellowstone/other sub-slot streaming only after an ablation or latency test proves that faster data changes net results enough to justify its cost and complexity.

Historical research may use Pyth or reputable CEX candles for the price component, but historical candles cannot recreate old Jupiter routes. A forward quote recorder is therefore mandatory before any claim about executable DEX performance.

### 2. Signal layer

Models are tried in this order:

1. hold USDC;
2. hold SOL;
3. fixed-weight SOL/USDC rebalance;
4. one deterministic trend/regime strategy;
5. regularized logistic/linear or quantile model;
6. gradient-boosted tree, only if simpler models leave stable residual signal; and
7. the winning structured-data model plus an optional LLM event feature.

Candidate structured features are limited to a pre-registered set: multi-horizon returns, realized/downside volatility, volume imbalance, trader-count change, liquidity change, standardized quote impact, route mix, Pyth/Jupiter divergence, broad-market regime, and time-of-week. Feature discovery happens in training data only.

The signal service emits a typed forecast with model/version, horizon, expected net return or calibrated probability, uncertainty, feature timestamp, and expiry. It emits no transaction bytes.

### 3. LLM event layer

If enabled, Grok or another provider receives a frozen, already-collected text corpus and returns only:

```json
{
  "event_type": "exploit|outage|listing|regulatory|protocol_change|other",
  "affected_mints": ["..."],
  "polarity": -1.0,
  "novelty": 0.0,
  "event_time": "ISO-8601",
  "valid_until": "ISO-8601",
  "source_ids": ["..."],
  "ambiguity": 0.0
}
```

It cannot output side, size, expected edge, risk limits, a destination address, or an execution instruction. Text is untrusted and may contain prompt injection. The LLM process has read-only data credentials, no RPC send method, no Jupiter execute credential, and no key or signer capability.

Evaluate each provider on a labeled event set for extraction accuracy, source grounding, stability across repeated runs, latency, and cost. Compare every strategy with and without its event features. If the feature does not add stable net outer-fold and shadow lift, remove the LLM entirely.

### 4. Portfolio and risk layer

All limits are code-enforced and fail closed. Model output may reduce risk but cannot widen a limit.

Required controls:

- separate entry policy from exit policy;
- allowlisted mints, token programs, route programs, and destination accounts;
- position, gross exposure, turnover, and trade-frequency caps;
- volatility targeting and quote-depth/impact sizing;
- maximum all-in cost, slippage, priority fee, and tip;
- maximum feature age, quote age, oracle divergence, and route-price deviation;
- daily and weekly loss stops plus peak-to-trough drawdown stop;
- volatility, liquidity, depeg, RPC, landing, and reconciliation circuit breakers;
- independent manual kill switch;
- no new entries after a halt, while protective exits remain available through an independent path; and
- emergency flatten that does not depend on an LLM or forecast service.

Risk-budget numbers must be explicitly approved and configured before a live key can be enabled. Missing live limits are a startup error, not defaults.

### 5. Execution and reconciliation layer

Use the current Jupiter Swap API V2 Meta-Aggregator for ordinary V1 spot trades:

1. `GET /swap/v2/order` for a fresh quote and assembled transaction;
2. independently validate and sign it; and
3. `POST /swap/v2/execute` for managed RTSE, priority-fee strategy, landing, retry, and result parsing.

All available routers can compete on this path. Measure the actual `totalInputAmount` and `totalOutputAmount`, including Jupiter/platform costs, rather than trusting a headline price. Sign and send immediately; abandon and re-quote expired or economically stale orders.

Use `/swap/v2/build` plus a private RPC/Jito only after measurements show that custom instructions or lower fees materially improve the strategy. Direct Jito is not needed for the first minutes-to-hours system. A successful RPC submission is not a fill.

The execution state machine is:

```text
CANDIDATE -> RISK_APPROVED -> QUOTED -> VALIDATED -> SIGNED
          -> SUBMITTED -> CONFIRMED -> FINALIZED -> RECONCILED
                         \-> FAILED | EXPIRED | CANCELLED
```

Each intent has an idempotency key. Persist request IDs, transaction hash, signature, blockhash, last-valid block height, quote/submit times, expected amounts, fee/tip budgets, route, confirmation state, actual balance deltas, and errors. On-chain balances and confirmed/finalized transactions are the source of truth; the local paper ledger is not.

### 6. Signer boundary

Use a cold treasury and a separately funded, balance-capped strategy wallet. Production keys must be held by a KMS/HSM/MPC or equivalent managed signer, not a raw `.env` secret.

Before any signature, the signer gateway deserializes the transaction and independently verifies:

- expected fee payer and strategy wallet;
- exact input/output mints and maximum input/minimum output;
- token-account ownership and approved destinations;
- every program ID and instruction;
- no unknown signers or writable accounts outside policy;
- only known, capped System transfers to approved tip accounts;
- compute, priority-fee, platform-fee, and tip caps; and
- fresh quote/expiry and matching approved intent.

The model and LLM never receive opaque signing access.

## Validation protocol

### Research rules

- Register the hypothesis, universe, labels, features, parameter grid, cost model, number of trials, metrics, and promotion thresholds before the final test.
- Keep a trial ledger that includes losing experiments.
- Use chronological nested walk-forward evaluation. Never shuffle time-series samples.
- Purge observations whose forward labels overlap a fold boundary and embargo at least the maximum label horizon.
- Fit normalization, calibration, token eligibility, and every data transformation inside each training fold only.
- Keep a final holdout sealed and evaluate it once.
- Include dead/delisted routes and point-in-time universe rules when the universe expands.
- Replay the event sequence: observation -> decision delay -> available quote -> build/sign delay -> landing probability -> confirmation -> exit.
- Run base, 2x-cost, and stressed latency/failure scenarios plus an order-size capacity sweep.
- Use block bootstrap confidence intervals, Deflated Sharpe Ratio, and Probability of Backtest Overfitting when comparing variants.

Report net/excess return, autocorrelation-robust Sharpe, Sortino, max drawdown and time under water, Calmar, turnover, CVaR/tail loss, quote-to-fill implementation shortfall, landing/failure/expiry rate, fee and tip spend, capacity, calibration, and results by volatility/liquidity regime. Always show cash, buy-and-hold, fixed allocation, deterministic strategy, learned model, and learned model plus text feature side by side.

### Promotion gates

Thresholds below are the starting research policy. They may be changed only before an evaluation window begins, never after seeing its result.

| Gate | Minimum evidence to advance |
|---|---|
| G0 — runnable | CLI, deterministic replay, unit/integration tests, schema validation, and failure injection pass; no signing code enabled |
| G1 — data | Point-in-time replay is deterministic; no leakage tests fail; forward recorder has at least 99.5% expected snapshots and explicitly marks all gaps/stale data |
| G2 — research | Outer-fold net expectancy is positive in at least 70% of folds, survives 2x modeled costs, stays within the predeclared drawdown budget, has Deflated-Sharpe confidence at least 95%, PBO at most 10% when multiple variants were tried, and is not dominated by one trade or period |
| G3 — AI | The AI feature adds stable net lift over the identical no-AI strategy in outer folds and the sealed holdout without increasing drawdown or turnover beyond policy; otherwise ship without AI |
| G4 — shadow | At least 8 weeks and 100 eligible trade intents, whichever is later; delayed quotes and landing simulation retain positive expectancy under observed P95 costs; modeled versus observed cost/latency errors stay inside frozen tolerances |
| G5 — canary | Separate capped wallet, manual approval for the first 20 entries, at least 30 calendar days, zero signer-policy violations or unreconciled balances, and realized execution remains inside shadow tolerances |
| G6 — scale | Increase one risk limit at a time, by no more than 2x, only after a fresh review window passes the same risk and execution tests; automatically return to the previous limit on breach |

Failure at a gate means diagnose, revise the pre-registration, and start a new evaluation window. It never means lower the threshold retroactively.

## Repository delivery order

### Milestone 0 — make the scaffold truthful and runnable

- Add the missing package initialization, CLI, scheduler, manual approver, and tests.
- Change the Jupiter base to `https://api.jup.ag`, batch token lookups, and migrate quotes/execution design from Swap V1 to Swap V2.
- Introduce provider-neutral interfaces: `MarketDataSource`, `FeatureBuilder`, `SignalModel`, `EventExtractor`, `RiskPolicy`, `ExecutionAdapter`, `SignerGateway`, and `Reconciler`.
- Remove side, size, confidence, and expected edge from the LLM schema.
- Enforce finite/ranged values and timestamps in every boundary schema.
- Split entry halts from exit handling and turn invalidation/time exits into executable conditions.

**Gate:** G0.

### Milestone 1 — build the evidence dataset

- Implement an append-only observation/quote store and immutable experiment registry.
- Backfill point-in-time major-pair prices where provenance permits.
- Start the Jupiter quote recorder immediately; collect standardized-size depth probes and all costs.
- Add data quality, staleness, gap, and clock-drift monitoring.

**Gate:** G1.

### Milestone 2 — build the replay and baselines

- Implement one event-driven replay engine shared with live interfaces.
- Add realistic latency, expiry, failure, fee, impact, and exit-cost models.
- Implement cash, buy-and-hold, fixed allocation, and deterministic trend/regime baselines.
- Produce reproducible walk-forward reports and a complete trial ledger.

**Gate:** the deterministic strategy must pass G2 before a learned model is allowed to complicate it.

### Milestone 3 — add calibrated machine learning and optional text

- Train regularized models first, then one tree challenger.
- Calibrate probabilities only inside training/validation windows.
- Add Grok/other extractors only against stored documents and a labeled event evaluation set.
- Run feature and provider ablations; retain only stable incremental lift.

**Gates:** G2 and G3.

### Milestone 4 — shadow execution

- Run the exact live decision loop without signing.
- Re-quote after measured decision/sign delay and log 1m/5m/1h/4h markouts.
- Model whether each order would have landed, expired, failed min-out, or been rejected by signer policy.
- Tune execution policy only in a new registered window.

**Gate:** G4.

### Milestone 5 — guarded canary and gradual scale

- Add the isolated signer, capped hot wallet, transaction parser, redundant private RPC, confirmation, and reconciliation.
- Require manual entry approval at first; risk exits remain independent and automatic.
- Exercise kill switches, RPC failover, duplicate-send protection, stale-quote rejection, and emergency flatten before funding.
- Expand to JUP/USDC or faster data only after the original system passes canary and an ablation justifies the change.

**Gates:** G5, then G6.

## Explicit non-goals for V1

- Fully autonomous LLM decisions or signing
- Pump.fun/new-token sniping, copy trading, or sandwiching
- Perpetuals, leverage, liquidation strategies, or cross-chain bridges
- Direct pool integrations, custom Jito bundles, or colocated sub-slot infrastructure
- A token for the bot, social-media promotion agent, or public terminal product
- Optimizing dozens of strategies until one backtest looks profitable

## Definition of success

V1 is successful when it produces an auditable answer to this question:

> After every observable Solana execution cost, with point-in-time data and an untouched test, does this exact strategy have a stable edge, at a known capacity and drawdown, and does the AI feature improve it?

If the answer is “no,” the correct result is a safe, reproducible rejection—not a live wallet attached to a more persuasive prompt.

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
- [Pyth price subscription and freshness](https://docs.pyth.network/pro/subscribe-to-prices)
- [Yellowstone Dragon's Mouth gRPC](https://docs.triton.one/project-yellowstone/dragons-mouth-grpc-subscriptions)
- [AI-Trader live LLM benchmark](https://arxiv.org/abs/2512.10971)
- [Audit of LLM trading-agent evidence](https://arxiv.org/abs/2605.19337)
- [Pretrained time-series models for return forecasting](https://arxiv.org/abs/2606.27100)
- [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Indirect prompt injection against tool-using LLMs](https://arxiv.org/abs/2302.12173)

