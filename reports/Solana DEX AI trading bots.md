# Solana DEX AI trading bots

> **Implementation update — 25 October 2026:** The build sequence in this research memo is superseded by the repository's [canonical implementation plan](../PLAN.md). The replacement plan is provider-neutral, trades SOL against vetted Solana ecosystem tokens with staked SOL as the benchmark, treats Grok only as an optional event extractor, uses Jupiter Swap API V2, and requires pre-registered kill tests plus backtest, walk-forward, shadow, signer, and capped-wallet promotion gates before live capital. This memo remains supporting background and incident research.

**Research date:** 25 October 2026  
**Question:** What should an experienced crypto trader build if they want an AI bot on Solana DEXes, using Grok, and which true stories actually happened?

This is architecture and incident research, not investment advice. Automated trading can lose money quickly; several documented cases show the fastest way to lose is a stolen key, not a bad signal.

## Bottom line

The money on Solana DEXes in 2024–2026 went to three groups: (1) latency and MEV shops, (2) launch-pad insiders and snipers, (3) terminal products that won distribution (Photon/BullX/Trojan, later Axiom/Fomo/GMGN). Large language models, including Grok, did not show a reliable edge when they were allowed to trade by themselves. The one famous “AI crypto millionaire” (Truth Terminal) did not trade a DEX; it posted on X, a human approved the posts, and other people launched Pump.fun coins around it.

Use Grok as a **research and risk copilot**. Execute with **deterministic code** on Jupiter (and later direct pools), with a human or hard rules on the trigger. Do not put Grok on the millisecond path, and do not download a GitHub “Pump.fun sniper” that wants your private key.

## True stories (sourced)

### 1. Sandwich bots extracted real millions from Solana traders

Solana has no native mempool. Jito Labs added one in its Block Engine so searchers could bid for order. Sandwich bots used that window. After a six-week fight, Jito **turned the public mempool off on 8 March 2024** (CoinDesk, The Block, Blockworks). Jito said rejecting sandwich bundles had become a cat-and-mouse game. The Block also reported a January 2024 MEV bot that made about **$1.8 million in seconds** back-running a dogwifhat (WIF) buyer.

The public mempool shutdown did not end extraction. Helius’s Solana MEV report attributed nearly half of observed sandwiches to one program tied to DeezNode’s private mempool (`vpeNAL…`). Over **7 December–5 January** that program ran **1.55 million** sandwiches for **65,880 SOL (~$13.43 million)**, about **0.0425 SOL (~$8.67)** per hit. Helius also counted **90.4 million** successful arbitrages in a year, **$142.8 million** in arb profit (average **$1.58**; largest single arb **$3.7 million**). An ACM IMC 2025 measurement of Jito in early 2025 found **over 500,000** sandwiches and **over $7.7 million** in victim losses, plus **over $2.4 million** spent on defensive behavior that mainly just avoided sandwiches. sandwiched.me put November 2024 sandwich extraction near **600k SOL**.

**Lesson:** if your bot sends high-slippage meme swaps through the public path, you are the feedstock. If you try to become the sandwicher, you are competing with validator-adjacent private order flow, not with ChatGPT.

### 2. “Open source trading bots” on GitHub stole keys

In July 2025 SlowMist documented GitHub repos marketed as Pump.fun snipers/copy-traders (`zldp2002/solana-pumpfun-bot`, later `audiofilter/pumpfun-pumpswap-sniper-copy-trading-bot`). They read `.env` private keys and exfiltrated them (obfuscated npm package `crypto-layout-utils-1.3.1` to `githubshadow.xyz`). Coin Edition’s write-up of one victim: **0.9897 SOL** drained to FixedFloat. Fake stars/forks made the repos look legitimate.

**Lesson:** write your own signer path. Never paste a hot key into a stranger’s bot. A dedicated trading wallet with a hard cap beats any “AI sniper” README.

### 3. Pump.fun sniping is often the deployer farming you

Pine Analytics (21 April 2025) isolated deployer-funded, same-block snipes with a one-hop funding filter. In one month: **15,000+ SOL** realized profit, **15,000+** launches, **4,600+** sniper wallets, **10,400+** deployers, **87%** of those snipes profitable. That is an exit-liquidity machine, not an LLM opportunity.

**Lesson:** a v1 “AI that snipes every new coin” is structurally late to insiders and early to rugs.

### 4. Truth Terminal got rich from attention, not from DEX alpha

Andy Ayrey launched Truth Terminal on X in June 2024 (Llama 3.1 fine-tune; Ayrey approved posts). On 9–10 July 2024 Marc Andreessen sent a **$50,000 Bitcoin grant** after a public DM (Decrypt, TechCrunch). On 10 October 2024 an anonymous user launched **GOAT** on Pump.fun. Ayrey queried the model several times, then approved an endorsement. CoinDesk: GOAT went from about **$1.8 million** market cap before the posts to hundreds of millions (later prints near **$800 million**). The bot did not create the token. Wallet moves required Ayrey and a council. BBC (October 2025): holdings peaked around **$50 million**, almost all gifted memecoins; other tallies cite Dune near **$66 million** in early 2025. Fartcoin was likewise launched by others from the bot’s chat logs.

**Lesson:** the only well-documented “Grok-like” crypto fortune on Solana was **narrative contagion + human approval**, not autonomous swapping. If you want that loop you are building a media agent with a legal/compliance problem, not a trading engine.

### 5. “AI agent tokens” were a 2024–25 mania, then a wipeout

Cointelegraph (6 February 2025): AI-agent names down as much as **90%** from highs. Decrypt (11 March 2025): Virtuals daily revenue **$1.02 million → $34,792** (~96%); new agents **~1,300/day → under 10**; active wallets **181,000 → 7,642**. crypto.news: Nansen’s top ai16z wallet made ~**$39 million** then sold. CoinDesk (5 August 2026): Eliza Labs founder Shaw Walters called **ELIZAOS** “completely dead” after a lawsuit, rebrand from AI16Z (peak about **$2.39 billion** on 2 January 2025), and a ~**97%** crash. A proposed class action alleged misleading “autonomous AI” claims.

**Lesson:** do not finance the bot by launching an “AI agent coin.” The documented outcome is speculative premium, then legal and reputational wreckage.

### 6. When Grok (and other LLMs) actually traded, most lost money

xAI’s official API is a general model API. There is **no official Solana trading product**. Wrappers on GitHub that combine Grok with a wallet are third-party.

Nof1 **Alpha Arena Season 1** (18 October–3 November 2025): six models, **$10,000** each, crypto perps on **Hyperliquid** (not Solana DEX), identical prompts, no human. Archived nof1 figures: **Qwen 3 Max +22.3%**, **DeepSeek V3.1 +4.9%**, Claude Sonnet 4.5 **-42%**, Gemini 2.5 Pro **-46%**, **Grok 4 -58%**, GPT-5 **-59%**. Protos: win rates ~25–30%; early PnL eaten by **overtrading and fees**. Independent analysis (Magnus Ross) argued the two winners were not clearly better than chance. Season 1.5 on **US equities** later had a “Mystery Model” revealed as **Grok 4.20** at a reported **+12.1%** aggregate — a different market, two weeks, not Solana DEX proof.

A Caltech-style experimental paper (arXiv 2502.15800) put 20 copies of each model in lab asset markets. **Claude 3.5 and GPT-4o** hugged fundamental value. **Grok-2** ran **bubble-crash** paths and correlated most with humans. That is interesting for a *sentiment* agent. It is a warning if you let Grok size live memecoins.

A 2026 paper on test-time reasoning in LLM trading (arXiv 2609.30705) found extra “thinking” did **not** reliably raise net returns and that repeated samples were unstable.

## How Solana DEX bots actually work (so Grok is not in the wrong layer)

| Time budget | Strategy | Who wins today | Role for Grok |
|---|---|---|---|
| Milliseconds | Arb, sandwich, same-block snipe | Searchers + private mempools + Jito bundles + gRPC | None |
| Seconds | Copy-trade, new-pool alerts | Crowded terminals | Weak (too slow, too noisy) |
| Minutes–hours | News, X narrative, regime, risk | Experienced desks with filters | Strong |
| Days | Inventory, events, research | Humans + tools | Strong |

**Routing:** Jupiter is still the default aggregator. DefiLlama on 25 October 2026: Jupiter about **$506 million** 24h and **$13.2 billion** 30-day Solana aggregator volume (chain aggregators about **$959 million** 24h).

**Terminals:** Photon, BullX, and Trojan took a huge share of 2025 Telegram/web meme flow (Dune/Gate: multi-billion two-month volumes). By 2026 benches, **Axiom, Fomo, GMGN** had taken much of that. Cloning a terminal is a distribution war. Adding “powered by Grok” on top of the same sniper UX does not create a moat.

**Execution stack for a serious private bot:** Yellowstone gRPC or a premium RPC for data; Jupiter Quote + Swap (or direct pool instructions) for fills; Jito bundles / priority fees / DontFront-style protection for *your* transaction, not for attacking others; a signer that never exposes the seed to the LLM process.

## Ideas that fit an experienced trader + Grok

**1. Desk copilot (build this first).** Every N minutes Grok receives a structured packet: prices, liquidity, holder concentration, freeze/tax flags, recent X posts, your positions. It returns JSON: thesis, invalidation, suggested size, confidence. A human clicks approve, or a rule engine fires only if checks pass. This is how Truth Terminal actually moved the world: model proposes, human gates.

**2. Fact vs narrative filter.** Inspired by FS-ReasoningAgent (arXiv 2410.12464): split on-chain facts from social claims. Grok is allowed to argue about the story only after code has marked mint authority, freeze authority, transfer fees, LP status, and top-holder %. Most Pump.fun “AI signals” die here.

**3. Deployer-snipe radar (defense).** Implement Pine-style funding-graph heuristics so you *skip* coins whose first buyers are deployer-funded. That is negative alpha avoidance, which compounds.

**4. Risk overlay that fights LLM overtrading.** Alpha Arena’s main documented failure mode was fees and churn. Hard caps: max trades/day, min expected edge vs fee+slippage, kill switch on RPC errors, daily loss limit, allowlist of mints for v1 (start with SOL/USDC and a handful of majors).

**5. Event-driven SOL/stable sleeve.** Slow. Grok watches outages, exploit headlines, ETF/macro prints. Execution is boring Jupiter swaps with tight slippage. This is the opposite of a sniper and much closer to how a veteran actually survives.

**6. Optional later: maker inventory on liquid pairs.** Only after the copilot and risk engine are boringly reliable. Still no LLM in the quote loop.

**Do not build as v1:** fully autonomous Grok signer; same-block Pump.fun sniper; sandwich searcher; a token that “represents the agent.”

## Suggested v1 architecture

```
X / news / Discord  ─┐
On-chain stats      ─┼─► feature store ─► Grok (JSON opinion)
Token safety checks ─┘                      │
                                            ▼
                              risk engine (deterministic)
                                            │
                              paper Jupiter  →  tiny live wallet
                                            │
                              hardware or remote signer (capped SOL)
```

Keep the Grok API key and the wallet key in **different** processes and machines. Log every model output versus every fill so you can see, in a month, whether the copilot changed anything besides your sleep.

## Sources (selected)

- Helius, “Solana MEV Report”: https://www.helius.dev/blog/solana-mev-report  
- CoinDesk, Jito mempool shutdown, 8 Mar 2024: https://www.coindesk.com/business/2024/03/08/solana-client-developer-jito-announces-end-of-mempool-function  
- The Block, Jito / $1.8M WIF bot: https://www.theblock.co/news/ecosystems/2024-03-09-solana-client-jito-labs-axes-mempool-function-following-increase-in-mev-attacks-281504  
- ACM IMC 2025 sandwich measurement: https://dl.acm.org/doi/10.1145/3730567.3764493  
- SlowMist, malicious Pump.fun GitHub bots, Jul 2025: https://slowmist.medium.com/threat-intelligence-an-analysis-of-a-malicious-solana-open-source-trading-bot-ab580fd3cc89  
- Pine Analytics, “Exit Liquidity Machines,” 21 Apr 2025: https://pineanalytics.substack.com/p/exit-liquidity-machines  
- CoinDesk / Cointelegraph / BBC on Truth Terminal and GOAT (Oct 2024–Oct 2025)  
- Decrypt, Andreessen $50k BTC, 10 Jul 2024: https://decrypt.co/239340/marc-andreessen-sends-50k-in-bitcoin-to-an-ai-bot-on-twitter  
- Cointelegraph, AI tokens down 90%, 6 Feb 2025; Decrypt, Virtuals revenue crash, 11 Mar 2025; CoinDesk, ELIZAOS “dead,” 5 Aug 2026  
- Nof1 Alpha Arena recaps: Protos; TradeRank archive of nof1.ai (6 Aug 2026)  
- arXiv 2502.15800 (LLM lab markets, includes Grok-2); arXiv 2410.12464; arXiv 2609.30705  
- DefiLlama Jupiter / Solana aggregator pages, accessed 25 Oct 2026  
- xAI API: https://x.ai/api (general inference; not a DEX bot)
