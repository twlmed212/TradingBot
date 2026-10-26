# AGENTS.md — handoff for AI coding agents (Codex, Claude, others)

Last updated: 25 October 2026 by Codex (H4 source audit and document archive). Read this whole file, then `PLAN.md`, before changing anything.

## 1. What this project is

A Solana trading bot built **research-first**. SOL is the numeraire: the bot holds staked SOL by default and buys Solana ecosystem tokens only when a pre-registered, tested rule says a token will beat staked SOL after measured costs. Execution is planned through Jupiter Swap API V2. **Everything is paper or research today: no wallet keys exist, nothing signs or sends transactions, and no agent may add live trading.**

- `PLAN.md` is the canonical plan (revision 3). Its "What the evidence says so far", "Hypothesis queue", "Milestone R" and "Stop rule" sections are the current state of the project.
- The owner communicates in short, simple English and wants plain-language summaries. They value honesty over optimism: report failures as failures.

## 2. Current state (25 Oct 2026)

| Area | State |
|---|---|
| Research | H1 (SOL/USDC 15-min trend) **failed**, H2 (ecosystem momentum vs SOL) **failed**, H7 (short ecosystem basket vs SOL, perps, research-only) **failed on risk** (+130% but 54% drawdown). Details in `research/registry/`. |
| **H3a (complete)** | **Failed 5/6.** 13 priced primary events; base mean +9.91% SOL, stress +9.12%, median +0.91%, but bootstrap lower bound −1.92%. USD-equivalent base mean +10.15%; event returns, not portfolio returns. Read the registry's pre-run audit and pool-selection deviations. No paper promotion or retuning. |
| Data | Forward Jupiter quote recorder and exchange-listing collector run 24/7 on an AWS server; on-chain prices rebuilt with Helius. |
| Bot code | `deskbot/` paper engine. The two Milestone 0 bugs are fixed and tested (SOL units; protective exits run first, kill switch flattens). Grok still proposes side/size (Milestone 0 item still open). Not running anywhere. |
| UI | Watch-only console (FastAPI + React) on the server; no controls yet (by plan). |
| Stop rule | If nothing passes by **31 Jan 2027** or after 6 hypotheses beyond H1–H2 (2 used: H7, H3a), stop or pivot. |

> **Done (25 Oct 2026, Claude):** H4 on-chain unlock coverage check (`research/unlock_onchain.py`, report `reports/h4-onchain-coverage-2026-10-25.md`). Result: 0 provable big-unlock windows in the research window across 45 tokens; a historical H4 test is not possible without hindsight. H4 stays unregistered (no trial used). Next step is an owner decision: forward-only unlock collection, a paid feed with provable publication dates, or moving on to H5.

> **Done (25 Oct 2026, Claude):** H5 quick test FAILED 1/6 (primary −60% in SOL). Hypotheses used: 3 of 6. Next is an owner decision (H6, forward unlock collection, or separate tracks).

> **Done (26 Oct 2026, Claude): arbitrage measurement NO-GO (0/3)** — ≈$56k/day total, same-block speed race; gaps open ≥ 3 slots ≈ $505/day market-wide. Next: owner to choose between a fee-earning tool and passive yield. Original note: owner chose to measure Solana DEX arbitrage before building a bot (`research/registry/2026-10-26-arb-market-measurement.md`, `research/arb_census.py fetch|analyze|reach`; raw blocks in `data/arb_blocks/`, results in `data/arb_census.sqlite3`). Read-only RPC on the Mac with the Helius key from `.env`; no transactions, no funds. Do not change the detector or thresholds after the sample is drawn.

> **Done (25 Oct 2026, Claude):** H6 copy-smart-wallets FAILED 1/6 (−19.3% in SOL; 1,252 of 1,265 wallets were bots). Hypotheses used: 4 of 6 (H7, H3a, H5, H6). Then H8 slow trend filter on SOL FAILED 3/6 (registry `2026-10-25-h8-slow-trend-sol.md`). **Hypotheses used: 6 of 6.** The last slot is H9, a forward paper test (registry `2026-10-25-h9-short-basket-forward.md`) running hourly on the server via `deskbot-h9.timer` since 25 Oct 2026 23:00 UTC until 31 Jan 2027. Check it with `ssh tradingbot 'sudo -u deskbot python3 /opt/deskbot/research/h9_paper.py --status'`. Do not change its rules or code during the window (bug fixes only, disclosed in the registry). Paper only: no orders, no keys. The console's **H9 paper test** card (`/api/h9` in `console/api/main.py`) shows equity vs USDC 5%, the five pass criteria so far, positions with stop distance, P&L by token, weekly results and engine events; it counts the criteria exactly as the registry's *Clarifications* section (added 25 Oct 23:30 UTC, before any weekly results) defines them, so use the same rules for the 31 Jan verdict. Backups (26 Oct 2026): daily SQLite copies (`deploy/backup_sqlite.py`, `deskbot-backup.timer`, 03:15 UTC) and a daily EBS snapshot (DLM policy, 03:30 UTC, 7 kept); failed H9 runs retry every 4 min. Restore steps are in `deploy/SERVER.md`; log any restore in the H9 registry's *Operations log*. **Verdict on/after 1 Feb 2027:** `ssh tradingbot 'cd /opt/deskbot && sudo -u deskbot python3 research/h9_verdict.py'` (written 26 Oct, before results; the console card uses the same `evaluate()`). The engine freezes itself after 31 Jan 23:59 UTC so the verdict reads the end-of-window state.

## 3. Next task: prepare H4 (unlock overlay)

**Data preparation completed:** read `reports/h4-data-readiness-2026-10-25.md`. Four first-party documents (JTO, PYTH, JUP, DRIFT) were captured successfully by `research/unlock_sources.py --fetch` into `data/unlock_sources.sqlite3`. Manifest: `research/data/unlock_sources.json`. This is document-only capture, not a historical dataset, registration or return test. Next recover independently timestamped historical versions/revisions, verify dated circulating supply and mint mapping, then produce a metadata-only coverage report. No source is yet accepted as historical H4 evidence. The collector is manual, local-only; no service was installed. Do not treat current receipt times or page publication labels as historical version proof.

1. H3a is finished and failed. Full output: `data/h3a_killtest_2026-10-25.txt`; rules, audit disclosure, six checks, grid and exclusions are in `research/registry/2026-10-25-h3a-listing-drift.md`. Do not retune this family on this window or select another variant after seeing returns.
2. Verify point-in-time unlock data availability before registering H4: original publication time, unlock time, amount, circulating supply as known then, mint mapping and revisions. Do not use today's corrected schedule as if it were known historically. No paid data purchase without the owner.
3. Preregister H4's exact universe, ≥2% circulating-supply/14-day overlay definition from PLAN, baseline, costs, trial count and pass/fail criteria before evaluating returns. If historical publication vintages cannot be established, collect forward observations instead of manufacturing a historical test.
4. Keep holdout prices sealed. All fetchers and evaluators must reject endpoints on/after 2025-07-01. H3a's earlier fetcher accidentally stored 216 DEX hourly rows and 754 SOL reference hours beyond cutoff; only timestamps/counts were inspected in the audit. Those rows are preserved but excluded from research reads. No claim that the holdout was never fetched; the H3a run did not load or evaluate it.
5. Price fetch is complete (`python3 research/listing_prices.py --plan`: zero remaining). Outage hours are stored empty. Regression coverage is in `tests/test_h3a_research_guards.py`; no real prices/network are used by these tests.
6. Research verdicts are served by the watch-only console; deploy changes with `bash deploy/deploy_console.sh`. No wallet, signer, live trading, or new strategy process is authorized.

## 4. Research rules (non-negotiable)

- Write a registry file (`research/registry/<date>-<id>-<name>.md`) with rules, data, grid, costs and pass criteria **before** running anything. Count every variant tried.
- Any change after registration must be recorded in the file as an amendment, and is only allowed before results are seen.
- A failed family is never retuned on the same data window.
- **Sealed holdout: everything on or after 2025-07-01.** Scripts refuse to load it; never fetch or evaluate holdout events except for the final G2 check.
- Measure in SOL against staked SOL, show USD alongside, use costs measured by the recorder (round trip, 20 bps floor), and include a 2× stress case.
- Name and report known biases (survivorship, listing selection, pool choice).

## 5. Repository map

| Path | Purpose |
|---|---|
| `PLAN.md` | Canonical plan, gates G0–G6, milestones, hypothesis queue, data budget |
| `reports/` | Research memo (`Solana DEX AI trading bots.md`) and the 25 Oct reality check |
| `research/registry/` | Pre-registrations and results (H1, H2, H7, H3a) |
| `research/*_killtest.py` | One script per hypothesis; reproduce any result by re-running it |
| `research/announcements.py` | Binance and Upbit announcement archive → `data/announcements.sqlite3` (also runs on the server every 10 min) |
| `research/listing_events.py` | Turns announcements into Solana listing events with first-party evidence → table `listing_events`, `research/data/listing_events.csv` |
| `research/listing_prices.py` | Rebuilds hourly DEX prices around events from on-chain swaps (Helius) → `data/listing_prices.sqlite3` |
| `research/data/` | Small research artifacts that are versioned (event CSV, cost snapshot) |
| `recorder/quote_recorder.py`, `recorder/universe.json` | Forward Jupiter quote recorder (SOL/USDC + 21 tokens vs SOL) |
| `deskbot/` | Paper trading engine, risk, safety screen, ledger, CLI |
| `tests/` | `PYTHONPATH=. .venv/bin/python -m pytest -q tests` (69 tests passing, including synthetic H3a guards and unlock archive tests) |
| `console/api/main.py` | Read-only dashboard API |
| `console/web/` | React app (Vite, TypeScript); `npm run build` → `console/web/dist` |
| `deploy/` | Server bootstrap, systemd units, `deploy_console.sh`, `SERVER.md` |
| `scripts/check_env.py` | Checks `.env` keys work without printing them |
| `data/` | **Git-ignored** local data (SQLite files, caches, test outputs) |

## 6. Local environment (owner's Mac)

- Repo root: `/Users/twlmed212/Desktop/MySpace/TradingBot/Untitled` (git; first commit "Starting the repo", many later changes uncommitted; commit only when the owner asks).
- Python: system `python3` is 3.14; research scripts use only the standard library. Test venv: `.venv` (Python 3.12, pytest, httpx). Console venv: `console/.venv` (Python 3.12, FastAPI, uvicorn).
- Node 24 for the console web app (`cd console/web && npm install && npm run build`).
- Port 8080 on the Mac is taken by another app; the console uses **8787**.
- macOS privacy rules stop some app-launched processes from reading `~/Desktop`; run servers from a normal shell.

## 7. Secrets

- Keys live only in `.env` at the repo root on the Mac (git-ignored, mode 600): `HELIUS_API_KEY` and `SOLANA_RPC_URL` (Helius RPC with the key). `XAI_API_KEY` and `JUPITER_API_KEY` are empty.
- Check them with `python3 scripts/check_env.py`, which never prints key values. **Never print, log, commit, or copy keys to the server.** Decision: keys stay on the Mac until the paper bot runs on the server.
- Helius Developer plan (paid, 10M credits/month). About 216k credits were used on 25 Oct for H3a prices.

## 8. Server and SSH

AWS "new experience" **project** (account ID: see `aws sts get-caller-identity --profile tradingbot`), **selected Region eu-north-1** (Stockholm), Free plan with $100 credit until 25 Apr 2027. AWS CLI profile: `tradingbot`. Also read `../CLAUDE.md` (AWS project rules: single Region, say "project", etc.). Full details: `deploy/SERVER.md`.

| Item | Value |
|---|---|
| Instance | `i-0c468a3d52d2e242f`, t4g.micro (Arm, 1 GiB + 2 GB swap), Ubuntu 24.04, eu-north-1a |
| Public IP | 13.53.89.50 (outbound only; **no inbound ports are open**) |
| Security group | `sg-006d5dbd589e49b44`, zero inbound rules. Keep it that way. |
| Instance role | `tradingbot-recorder-ssm` (only `AmazonSSMManagedInstanceCore`) |
| Login user | `ubuntu` (sudo). Services run as locked-down user `deskbot`; app lives in `/opt/deskbot` |

**How SSH works:** SSH runs through AWS Session Manager, so it works from any IP and needs no open port. Requirements on the Mac:

- the owner's key `~/.ssh/id_ed25519` (the public key is installed on the server; never move or print the private key);
- AWS CLI in `~/.local/bin` and the Session Manager plugin (`~/.local/bin/session-manager-plugin`);
- a valid AWS login for profile `tradingbot`. It lasts 12 h and renews for up to 90 days. When it expires, **the owner** must run this, because it opens a browser:
  ```bash
  aws login --region eu-north-1 --profile tradingbot
  ```

`~/.ssh/config` already contains:

```
Host tradingbot
  HostName i-0c468a3d52d2e242f
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  HostKeyAlias tradingbot-recorder
  ProxyCommand sh -c "PATH=$HOME/.local/bin:$PATH aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters portNumber=%p --region eu-north-1 --profile tradingbot"

Host tradingbot-console
  (same as above, plus)
  LocalForward 8787 127.0.0.1:8787
  SessionType none
  ExitOnForwardFailure yes
  ServerAliveInterval 30
```

Everyday commands:

```bash
ssh tradingbot                                   # shell on the server
ssh tradingbot 'systemctl is-active deskbot-recorder deskbot-console deskbot-announcements.timer'
ssh tradingbot-console                           # keep open, then browse http://localhost:8787
bash deploy/deploy_console.sh                    # build + deploy console, collector, research and recorder files
scp tradingbot:/opt/deskbot/data/quotes.sqlite3 data/quotes-server.sqlite3   # copy recorder data (read via sqlite backup if busy)
```

Server services (systemd, auto-restart): `deskbot-recorder` (quotes every minute → `/opt/deskbot/data/quotes.sqlite3`), `deskbot-announcements.timer` (every 10 min → `announcements.sqlite3`), `deskbot-console` (127.0.0.1:8787 only). A recorder code change needs `sudo systemctl restart deskbot-recorder`; `deploy_console.sh` copies files but deliberately does not restart the recorder.

## 9. Known gotchas

- Jupiter keyless API rate-limits bursts: the recorder pauses 1 s between requests (`--pause`); lookups in research scripts retry with back-off. Never treat a failed lookup as "no token".
- Upbit's announcement site blocks AWS IPs; on the server, Upbit events come from Upbit's official market list (diffed each run). Upbit notice bodies can only be fetched from the Mac.
- GeckoTerminal public API: about 30 calls/min, history only 180 days (inside the holdout), so it is used only to find pools.
- Binance CMS rate-limits body fetches; `listing_events.py` caches bodies in `announcement_bodies`.
- Hourly on-chain price = median of the first 50 pool transactions of the hour; validated against Binance within ~0.5%.
- The AWS MCP server (if available to you) is preferred for AWS API calls; otherwise use the AWS CLI with `--profile tradingbot --region eu-north-1`.

## 10. Do not

- add live trading, wallet keys, signing, or anything that moves funds;
- open inbound ports or put API keys on the server;
- let an LLM choose trade side, size, or risk limits;
- run or peek at holdout data, or retune a failed hypothesis on its own window;
- change `PLAN.md` decisions without telling the owner (factual progress updates are fine).

## 11. Open owner decisions

- How much capital is exposed to SOL at all (the plan measures in SOL; reports must show USD too).
- Whether to start the separate tracks outside spot V1: perps short-basket vs SOL (H7 family) and the lend/carry switcher.
- Buying Dune when H5/H6 start; upgrading the AWS project to the paid plan before 25 Apr 2027.
