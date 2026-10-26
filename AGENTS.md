# AGENTS.md — handoff for AI coding agents (Codex, Claude, others)

Read this first, then `README.md`, `docs/PRODUCT.md` and `docs/OPERATIONS.md`. The parent folder's `../CLAUDE.md` holds the AWS project rules (single Region eu-north-1, say "project" not "account", saved guidance level MEDIUM).

## 1. What this project is

A **non-custodial Solana swap tool** (Telegram bot + signing page) that earns a per-trade fee through Jupiter's Referral Program. The owner chose this on 26 Oct 2026 after the research phase showed no tradable edge. Research code, plans and reports live only on branch `archive/2026-10-26-snapshot`; do not bring old plans back into `main`.

## 2. Current state (26 Oct 2026)

- **Repo reorganized** to product-only on branch `restructure/product-main` (to be merged into `main` by the owner). Layout: `swapbot/` (product), `server/` (EC2 services), `tools/`, `docs/`.
- **Milestone 1 in progress:** `swapbot/app.py` (Lambda handler: signing page, `/api/config`, `/api/tokens`, `/api/order`, `/api/execute`) is written. Next: `swapbot/static/` (index.html, app.js, app.css), tests, a local dev server, then the AWS Lambda deployment.
- Jupiter `GET /swap/v2/order` works **keyless** for development (verified 26 Oct). `JUPITER_API_KEY` and `REFERRAL_ACCOUNT` are not set yet (owner actions).
- The EC2 server keeps running unchanged: quote recorder, listing collector (every 10 min), console, H9 paper test (until 31 Jan 2027), daily backups.

## 3. Next tasks (milestone 1, see docs/PRODUCT.md)

1. Signing page using the **Wallet Standard** (`standard:connect`, `solana:signTransaction`): no third-party scripts on the page. The wallet only signs; the server calls `/swap/v2/execute`. Request transaction version 0.
2. Tests for validation, routing and the referral parameters (mock Jupiter).
3. Deploy: one Python 3.13 arm64 Lambda with a function URL in eu-north-1; IAM role limited to its logs and `ssm:GetParameters` on `/swapbot/*`; secrets in SSM SecureString, entered by the owner.
4. Owner test: a $1–2 swap from the owner's wallet; the fee appears in the referral account.

## 4. Product rules (non-negotiable)

- **Never** ask for, store, transmit or log a private key or seed phrase. Users sign in their own wallet.
- Keep the signing page free of third-party scripts; strict CSP; show the user exactly what they will sign.
- No profit promises or "signals" marketing; listing alerts are information, not advice.
- Agents never create accounts, enter keys, sign transactions or move funds. The owner does those steps.

## 5. Repository map

| Path | Notes |
|---|---|
| `swapbot/app.py` | Lambda entry `handler(event)`; stdlib only (boto3 from the Lambda runtime for SSM) |
| `swapbot/static/` | Signing page assets (to write) |
| `swapbot/tests/` | Product tests (conftest adds the repo root to `sys.path`) |
| `server/recorder/` | Jupiter quote/cost recorder (systemd `deskbot-recorder`) |
| `server/research/announcements.py` | Binance/Upbit listing collector (timer every 10 min); source for listing alerts |
| `server/research/h9_*.py` | H9 forward paper test and its verdict code, running on the server until 31 Jan 2027; do not change them (its rules document is on the archive branch) |
| `server/console/` | Watch-only dashboard (FastAPI + React), 127.0.0.1:8787 on the host |
| `server/deploy/` | `bootstrap.sh`, systemd units, `deploy_console.sh`, `backup_sqlite.py` |
| `server/tests/` | H9 verdict + console agreement tests (conftest adds `server/` to `sys.path`) |
| `tools/check_env.py` | Checks `.env` keys without printing them |

`server/` mirrors `/opt/deskbot/` on the host, so every script's `ROOT = parents[1]` works in both places.

## 6. Local environment (owner's Mac)

- Repo root: `/Users/twlmed212/Desktop/MySpace/TradingBot/Untitled`. Remote `origin` = `github.com/twlmed212/TradingBot` (**public**). Commit and push only when the owner asks; branch first when on `main`.
- Python: system `python3` 3.14. Test venv `.venv` (3.12, pytest): `.venv/bin/python -m pytest`. Console venv `server/console/.venv` (3.12, FastAPI); it was moved, so call `server/console/.venv/bin/python -m uvicorn ...` instead of its scripts.
- Node 24 for the console web app (`cd server/console/web && npm run build`). Port 8080 is taken on the Mac; the console uses 8787.
- Local-only data (git-ignored) is in `data/`, including `data/archive/` (old research data and 1.2 GB of arbitrage sample blocks).

## 7. Secrets

- Local: `.env` at the repo root (git-ignored); template `.env.example`. `HELIUS_API_KEY` and `SOLANA_RPC_URL` are set; `JUPITER_API_KEY`, `REFERRAL_ACCOUNT` and `TELEGRAM_BOT_TOKEN` are empty.
- Production: AWS SSM Parameter Store under `/swapbot/` (SecureString), owner-entered (approved 26 Oct 2026).
- Never print, log or commit key values; the repository is public. No AWS account numbers in commits either.

## 8. Server and AWS

See `docs/OPERATIONS.md` (instance, SSH via Session Manager, services, backups, costs). Prefer the AWS MCP server for AWS API calls (profile `tradingbot`, Region eu-north-1). The project is on the Free plan with $100 credit until 25 Apr 2027; it must be upgraded to the paid plan before then to keep the server.

## 9. Open owner decisions

- Fee level (default 0.5%, allowed 0.5–2.55%).
- When to make the GitHub repository private (recommended).
- Upgrading the AWS project to the paid plan before 25 Apr 2027.
