# LLM / Grok trading evidence

## xAI product fact

- xAI ships a general Grok API (chat/completions, tools, embeddings). No official Solana DEX trading product as of Oct 2026 docs (x.ai/api, docs.x.ai).
- Third-party GitHub wrappers exist (e.g. marketing “Grok-powered Solana perps agent”). Treat as unofficial; many request private keys in `.env` — same class of risk as SlowMist cases.

## Experimental finance (Grok specifically)

- arXiv 2502.15800 (Caltech-style experimental markets): 20 copies of each model. Claude 3.5 Sonnet and GPT-4o stayed near fundamental value. Grok-2 showed bubble-crash cycles and highest correlation with human markets (PCC 0.558). This is lab asset markets, not Solana DEX.

## Live LLM crypto contest (Nof1 Alpha Arena)

- Season 1: 18 Oct–3 Nov 2025, $10k each, crypto perps on Hyperliquid (not Solana DEX), same prompts, no human intervention.
- Archived leaderboard (TradeRank citing nof1.ai snapshot 6 Aug 2026): Qwen 3 Max +22.31%; DeepSeek V3.1 +4.89%; Claude Sonnet 4.5 -42%; Gemini 2.5 Pro -45.6%; Grok 4 -57.9%; GPT-5 -58.7%.
- Protos: early PnL dominated by overtrading/fees; win rates ~25–30%.
- Independent analysis (Magnus Ross): remaining winners not clearly better than random given sample and vol.
- Season 1.5 (19 Nov–3 Dec 2025, US equities): “Mystery Model” revealed as Grok 4.20, announced +12.11% aggregate — different market, not proof of Solana DEX alpha.

## Academic crypto LLM trading

- arXiv 2410.12464 FS-ReasoningAgent: claimed ~7% profit improvement on BTC (and related) with fact vs subjectivity split. Backtest/research setting; not live Solana memecoins.
- arXiv 2609.30705 “Price of Thought”: extra test-time reasoning did not reliably improve net portfolio returns; repeated generations unstable.

Implication: Grok is useful as a narrative/news/X copilot with human-like speculative bias in lab settings. It is a poor fully autonomous execution brain; contests show overtrading, fee bleed, and large drawdowns.
