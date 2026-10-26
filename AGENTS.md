# AGENTS.md — handoff for AI coding agents (Codex, Claude, others)

Read `README.md` first (product, plan, rules). The parent folder's `../CLAUDE.md` holds the AWS project rules (single Region eu-north-1, say "project" not "account", saved guidance level MEDIUM).

## Current state (26 Oct 2026)

- Fresh start: `main` contains only the swap-bot product. Research, old server code, plans and data were removed; history is on branch `archive/2026-10-26-snapshot`. Do not bring old plans or data back.
- Milestone 1 in progress: `swapbot/app.py` is written (routes, input validation, Jupiter order/execute, security headers). Next: `swapbot/static/` (index.html, app.js, app.css), tests with a mocked Jupiter, a local dev server, then the AWS Lambda deployment.
- Jupiter `GET /swap/v2/order` works keyless for development (checked 26 Oct). `JUPITER_API_KEY`, `REFERRAL_ACCOUNT` and `TELEGRAM_BOT_TOKEN` are not set yet (owner actions).

## Next tasks (milestone 1)

1. Signing page with the **Wallet Standard** (`standard:connect`, `solana:signTransaction`); no third-party scripts; the wallet only signs and the server calls `/swap/v2/execute`. Request transaction version 0.
2. Tests for validation, routing and the referral parameters.
3. Deploy one Python 3.13 arm64 Lambda with a function URL in eu-north-1. The IAM role may only write its logs and read `/swapbot/*` from SSM. Secrets go in SSM SecureString, entered by the owner.
4. The owner makes a $1–2 test swap from their wallet; the fee shows in the referral account.

## Rules

- Never ask for, store, transmit or log a private key or seed phrase.
- Agents never create accounts, enter keys, sign transactions or move funds; the owner does those steps.
- No profit promises or "signals" marketing.
- Commit and push only when the owner asks; branch first when on `main`. The remote (`github.com/twlmed212/TradingBot`) is public.

## Environment (owner's Mac)

- Repo root: `/Users/twlmed212/Desktop/MySpace/TradingBot/Untitled`. Python 3.14 system; test venv `.venv` (3.12, pytest): `.venv/bin/python -m pytest`.
- Secrets: `.env` (git-ignored); template `.env.example`. Never print or commit key values.
- AWS: profile `tradingbot`, Region eu-north-1, Free plan with $100 credit until 25 Apr 2027. Prefer the AWS MCP server for AWS API calls.
