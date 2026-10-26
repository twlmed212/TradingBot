# AGENTS.md — handoff for AI coding agents (Codex, Claude, others)

Read `README.md` first (product, plan, rules). `CLAUDE.md` (local, not committed) holds the AWS project rules (single Region eu-north-1, say "project" not "account", saved guidance level MEDIUM).

## Current state (26 Oct 2026)

- Brand: **Kovaswap** (domains `kovaswap.com` / `.app` to be bought by the owner). We have no token; never imply one.

- Mission 1 in progress: `swapbot/app.py` (swap API: routes, validation, Jupiter order/execute with our referral fee, security headers) is written; the web app is next.
- Jupiter `GET /swap/v2/order` works keyless for development (checked 26 Oct). `JUPITER_API_KEY`, `REFERRAL_ACCOUNT` and `TELEGRAM_BOT_TOKEN` are not set yet (owner actions).

## Next tasks

Follow `ROADMAP.md`. Mission 1 = website (PWA) + Seeker app: web app with Wallet Standard and Solana Mobile's wallet library (bundled), swap API on AWS Lambda (`swapbot/app.py`), safety check, then wrap with Bubblewrap for the Solana dApp Store. Telegram comes in mission 3.

## Rules

- Never ask for, store, transmit or log a private key or seed phrase.
- Agents never create accounts, enter keys, sign transactions or move funds; the owner does those steps.
- No profit promises or "signals" marketing.
- Commit and push only when the owner asks; branch first when on `main`. The remote (`github.com/twlmed212/TradingBot`) is public.

## Environment (owner's Mac)

- Repo root: `/Users/twlmed212/Desktop/MySpace/TradingBot`. Python 3.14 system; test venv `.venv` (3.12, pytest): `.venv/bin/python -m pytest`.
- Secrets: `.env` (git-ignored); template `.env.example`. Never print or commit key values.
- AWS: profile `tradingbot`, Region eu-north-1, Free plan with $100 credit until 25 Apr 2027. Prefer the AWS MCP server for AWS API calls.
- EC2 server `i-0c468a3d52d2e242f` (t4g.micro, Ubuntu 24.04) is kept but **empty**: the old bot's services, data and backups were removed on 26 Oct 2026. SSH: `ssh tradingbot` (through AWS Session Manager; no inbound ports). When the AWS login expires, the owner runs `aws login --region eu-north-1 --profile tradingbot`.
