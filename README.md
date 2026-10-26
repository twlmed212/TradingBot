# Kovaswap

A **non-custodial** Solana swap tool (website, Solana Seeker app, then a Telegram bot) that earns a **fee on every swap** through Jupiter's Referral Program. Users keep their own keys: our server builds the swap, the user's wallet signs it, and Jupiter executes it. We never hold funds or private keys.

## How it makes money

- Every swap goes through Jupiter `GET https://api.jup.ag/swap/v2/order` with our `referralAccount` and `referralFee`.
- **Fee: 0.5% by default** (allowed 0.5–2.55%). Jupiter keeps 20% of it, so we net 0.4%.
- Example: $1M of monthly volume → about $4,000/month. Revenue depends on users, not on predicting prices.

## Plan

The full plan (product map, missions, loyalty points, invites, Seeker perks): [ROADMAP.md](ROADMAP.md).

## Layout

| Path | What it is |
|---|---|
| `swapbot/app.py` | Lambda handler: signing page, `/api/config`, `/api/tokens`, `/api/order`, `/api/execute` |
| `swapbot/static/` | Signing page (no third-party scripts; wallets via the Wallet Standard) |
| `swapbot/tests/` | Tests |
| `AGENTS.md` | Handoff for AI coding agents |

Earlier research, the old server code and plans are kept only on branch `archive/2026-10-26-snapshot`.

## Development

```bash
cp .env.example .env              # fill in values; never commit .env
.venv/bin/python -m pytest        # tests
```

## Rules

- Never ask for, store or log a private key or seed phrase. Users sign in their own wallet.
- Secrets live in `.env` locally and in AWS SSM Parameter Store in production, never in git.
- This repository is public: no account numbers, keys or personal data in commits.
