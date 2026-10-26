# Solana swap bot

A **non-custodial** Solana swap tool (Telegram bot plus a signing page) that earns a **per-trade fee** through Jupiter's Referral Program. Users keep their own keys: our server builds the swap, the user's wallet signs it, and Jupiter executes it. We never hold funds or private keys.

**Why this product:** earlier testing (8 trading strategies plus an on-chain arbitrage measurement) found that DEX money goes to speed players and fee takers, not to strategies we could run. A fee on every swap earns whether users win or lose.

**Status (26 Oct 2026):** milestone 1 in progress: swap API and signing page. Plan and milestones: [docs/PRODUCT.md](docs/PRODUCT.md).

## Layout

| Path | What it is |
|---|---|
| `swapbot/` | **The product.** AWS Lambda app: swap API (`/api/order`, `/api/execute`), signing page (`static/`), Telegram bot (milestone 2). Tests in `swapbot/tests/` |
| `server/` | Always-on EC2 services that feed the product: Jupiter quote/cost recorder (`recorder/`), Binance/Upbit listing collector (`research/announcements.py`), watch-only dashboard (`console/`), the still-running H9 paper test (`research/h9_*`), and the deploy scripts (`deploy/`) |
| `tools/` | `check_env.py`: checks the keys in `.env` without printing them |
| `docs/` | Product plan and operations (AWS server, SSH, backups) |
| `AGENTS.md` | Handoff for AI coding agents (Codex, Claude) |

Research code, reports and the old Grok-bot scaffold are kept on the branch [`archive/2026-10-26-snapshot`](https://github.com/twlmed212/TradingBot/tree/archive/2026-10-26-snapshot).

## Quick start (development, on the Mac)

```bash
cp .env.example .env        # then fill in values
python3 tools/check_env.py  # verifies keys without printing them
.venv/bin/python -m pytest  # all tests (swapbot + server)
```

Server operations (SSH through AWS Session Manager, deploys, backups): [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Rules

- Never ask for, store, or log a private key or seed phrase. Users sign in their own wallet.
- Secrets live in `.env` locally (git-ignored) and in AWS SSM Parameter Store in production; they never go into git.
- This repository is public: no account numbers, keys or personal data in commits.
