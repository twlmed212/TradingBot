# True stories: Solana DEX bots, MEV, AI agents

Sources accessed 2026-10-25.

## MEV / sandwich (verified infra + academic)

- Jito Labs suspended its Block Engine mempool on 8 Mar 2024 after sandwich attacks on retail. CoinDesk, The Block, Blockworks. Solana itself has no native mempool; Jito had created one. Searchers had been violating Jito ToS. Jito said rejecting sandwich bundles became a cat-and-mouse game.
- The Block: Jan 2024, a Solana MEV bot reportedly earned ~$1.8M in seconds back-running a dogwifhat (WIF) buyer.
- Helius “Solana MEV Report”: Jito processed >3B bundles in a year, 3.75M SOL in tips. Arbitrage detector: 90.4M successful arbs, avg profit $1.58, max single arb $3.7M, $142.8M total (88.7% in SOL). DeezNode private mempool sandwich bot `vpeNAL..oax38b`: 1.55M sandwiches 7 Dec–5 Jan, 65,880 SOL (~$13.43M), ~half of observed sandwiches, avg 0.0425 SOL (~$8.67) per attack.
- ACM IMC 2025 (Gerzon et al.): >500k Jito sandwich attacks in early 2025 measurement window, >$7.7M victim losses; users spent >$2.4M on defensive behaviors.
- sandwiched.me May 2025: Nov 2024 peak sandwich extraction ~600k SOL.

## Fake “open source” Pump.fun bots (verified SlowMist)

- Jul 2025 SlowMist: GitHub `zldp2002/solana-pumpfun-bot` and later `audiofilter/pumpfun-pumpswap-sniper-copy-trading-bot` stole `.env` private keys via obfuscated npm (`crypto-layout-utils-1.3.1` → githubshadow.xyz). Coin Edition: one documented victim loss 0.9897 SOL (~$149 at report time); funds to FixedFloat. Pattern is larger than that one wallet; repos used fake stars/forks.

## Pump.fun deployer-funded snipers (on-chain analytics)

- Pine Analytics “Exit Liquidity Machines” (21 Apr 2025): one-month high-confidence subset of deployer-funded same-block snipes: >15,000 SOL realized profit, 15,000+ launches, 4,600+ sniper wallets, 10,400+ deployers, 87% of those snipes profitable. This is extractive launch farming, not a retail AI edge.

## Truth Terminal / GOAT (verified journalism)

- Jun 2024: Andy Ayrey launches Truth Terminal on X (fine-tuned Llama 3.1; Ayrey approves posts).
- 9–10 Jul 2024: Marc Andreessen grants $50k BTC after DM (Decrypt, TechCrunch). Not a Solana trading product.
- 10 Oct 2024: anonymous Pump.fun launch of GOAT; Ayrey asked the model repeatedly, then approved an endorsement tweet. CoinDesk: GOAT ~$1.8M mcap before posts; later ~$300M then ~$800M. Bot did not create the token. Wallet decisions were human+council, not autonomous DEX execution.
- BBC (8 Oct 2025): wallet peak ~$50M (other sources cite Dune ~$66M early 2025), almost all gifted memecoins. Fartcoin similarly launched by others from the bot’s chat ideas.

## AI agent token boom/bust

- Cointelegraph 6 Feb 2025: AI agent tokens down up to 90% from highs (ARC, ElizaOS/AI16Z, VIRTUAL 75–90% from Jan).
- Decrypt 11 Mar 2025: Virtuals daily revenue $1.02M early Jan → $34,792 late Feb (~96% drop); new agents 1,300/day Nov peak → <10/day Feb; active wallets 181k → 7,642.
- crypto.news Jan 2025: Nansen — top ai16z trader ~$39M then sold out.
- CoinDesk 5 Aug 2026: Shaw Walters declared ELIZAOS token “completely dead”; AI16Z had peaked ~$2.39B on 2 Jan 2025; successor ~97% down. Class-action allegations of misleading “autonomous AI” claims.
