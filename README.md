# Solana swap bot

A **non-custodial** Solana swap tool (Telegram bot plus a signing page) that earns a **fee on every swap** through Jupiter's Referral Program. Users keep their own keys: our server builds the swap, the user's wallet signs it, and Jupiter executes it. We never hold funds or private keys.

## How it makes money

- Every swap goes through Jupiter `GET https://api.jup.ag/swap/v2/order` with our `referralAccount` and `referralFee`.
- **Fee: 0.5% by default** (allowed 0.5–2.55%). Jupiter keeps 20% of it, so we net 0.4%.
- Example: $1M of monthly volume → about $4,000/month. Revenue depends on users, not on predicting prices.

## Plan

| # | Milestone | Done when |
|---|---|---|
| 1 | Swap API + signing page on AWS Lambda | A $1–2 test swap from the owner's wallet lands and the fee reaches our referral account |
| 2 | Telegram bot: wallet link, `/buy`, `/sell`, `/price`, safety checks | The owner trades end to end from Telegram |
| 3 | Listing alerts with buy links, trade log, simple dashboard | Alerts arrive; volume and fees are visible |
| 4 | Growth from zero: user referral rewards, shareable trade links, Solana groups and X | Weekly users, volume, fees |

**Owner actions:**
- Create a Jupiter API key (developer portal).
- Create the referral account at [referral.jup.ag](https://referral.jup.ag/) with your own wallet, and share only its **public** address.
- Create the Telegram bot with @BotFather (milestone 2).
- Check local rules for running a swap interface that charges fees.

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
