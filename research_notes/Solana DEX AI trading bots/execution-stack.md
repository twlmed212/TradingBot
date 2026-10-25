# Solana DEX execution stack (2025–2026)

## Venues

- Routing: Jupiter is the default aggregator. DefiLlama 25 Oct 2026: Jupiter ~$506M 24h agg volume, ~$13.2B 30d on Solana; chain agg 24h ~$959M.
- Launchpads / early memes: pump.fun still large (openchainbench summer 2026 snapshot: ~$187M 24h in one scrape — treat as a point-in-time, not a constant).
- AMMs: Raydium, Orca, Meteora DLMM, etc. Serious bots often hit pools directly after Jupiter quote, or use Jupiter Swap API for v1.

## Latency classes (do not mix)

- Milliseconds: arb, sandwich, same-block snipes. Needs Yellowstone gRPC / Geyser, colocated RPC (Helius/Triton), Jito bundles, stake-weighted QoS, priority fees. LLMs cannot sit on this path.
- Seconds–minutes: copy trade, telegram snipe, new-pool alerts. Crowded; terminals already productized.
- Minutes–hours: narrative, news, regime, size/risk, SOL-stable inventory. LLM-compatible.

## MEV reality after public mempool shutdown

- Public Jito mempool died Mar 2024; private mempools and validator-exclusive orderflow continued (Helius/DeezNode). Retail high-slippage meme swaps remain sandwich bait.
- Protection concepts (Solana docs DontFront, Jito bundles for your own atomic flow) — use as defense, not as a searcher business unless you are already a searcher shop.

## Terminals (competition, not infra to copy blindly)

- 2025: Photon, BullX, Trojan dominated Telegram/web memecoin UX (Gate/Dune: billions of 2-month volume).
- 2026: Axiom / Fomo / GMGN took share; Photon/BullX/Trojan volumes much smaller in summer 2026 benches. Building another Photon clone is a distribution fight, not an AI fight.

## Security

- Never put hot-wallet keys in random GitHub bot `.env`. SlowMist 2025 drainers used exactly that.
- Signing: dedicated trading wallet with capped SOL; hardware or remote signer; allowlists; no mint-authority interaction.
