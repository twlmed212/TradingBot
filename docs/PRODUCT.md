# Product plan: non-custodial Solana swap bot that earns a fee per trade

**Status:** owner chose this route on 26 Oct 2026, after 8 strategy tests and the arbitrage measurement (see `docs/RESEARCH_SUMMARY.md`) showed that DEX profit goes to speed players and fee takers.  
**Owner decisions (26 Oct 2026):** first users come from **marketing from zero** (no existing audience), so growth features (a referral reward for users who invite others, shareable trade links) are part of milestone 4. Production secrets (Jupiter API key, Telegram bot token) go in **AWS SSM Parameter Store**; the owner enters the values, Claude never handles them.  
**Revenue model:** every swap made through our tool carries an integrator fee through Jupiter's Referral Program. We earn whether users win or lose; no trading capital, no price predictions.

## How the money works

- Jupiter `GET https://api.jup.ag/swap/v2/order` with `referralAccount` + `referralFee` (50–255 bps). Jupiter keeps 20% of that fee, and no separate Jupiter platform fee applies.
- **Default fee: 50 bps (0.5%)**, the minimum, so we keep **0.4%**. That is about half what custodial Telegram bots charge (≈ 1%).
- Fees land in our referral token accounts (SOL, USDC and others; Jupiter picks the fee mint) and are claimed on [referral.jup.ag](https://referral.jup.ag/).
- Example: $1M of monthly volume through the tool → about **$4,000/month** net. Getting there needs users; the tool alone earns nothing.

## What users get (MVP)

A Telegram bot plus a signing page:

1. `/buy <token> <amount>` and `/sell`: the bot shows the quote, our measured round-trip cost, the fee, and token safety checks (mint/freeze authority, liquidity, holder concentration).
2. A **Sign** button opens our page inside the user's wallet app (Phantom/Solflare in-app browser). The page builds a fresh Jupiter order for the user's wallet, the wallet **signs only**, and our server submits it with `/swap/v2/execute` (required for Jupiter's RFQ routes). The bot confirms the result.
3. Alerts: Binance/Upbit listing announcements for Solana tokens (our existing collector), with a one-tap buy link. No profit promises (our H3a test found no reliable edge).

**Non-custodial:** we never hold keys or funds and never ask for a seed phrase. That is a selling point against custodial bots, which have been hacked before.

## Architecture (AWS, selected Region eu-north-1)

- **One Python Lambda function with a function URL** (HTTPS built in, no server to patch):
  - `GET /` serves the signing page;
  - `POST /api/order` builds a Jupiter order (our API key stays server-side);
  - `POST /api/execute` forwards the signed transaction;
  - `POST /tg/<secret>` receives the Telegram webhook (verified with Telegram's secret-token header).
- **DynamoDB:** users (Telegram id → public wallet address, never private keys) and a trade log (for the dashboard: users, volume, fees).
- **Secrets** (Jupiter API key, Telegram bot token) in SSM Parameter Store (SecureString). The owner puts them there; Claude never handles the raw values.
- Reserved Lambda concurrency caps cost and abuse. Expected cost at MVP scale: near $0 (free tiers).
- The existing EC2 server (`server/`) keeps the cost recorder, listing collector, console and the H9 paper test; the console gets a **Business** card (users, volume, fees earned).

## Milestones

| # | Deliverable | Proof it works |
|---|---|---|
| 1 (days 1–4) | Lambda + signing page: swap with our fee from the owner's own wallet | A $1–2 test swap lands, and the fee shows in our referral account |
| 2 (days 5–10) | Telegram bot: `/start`, wallet link, `/buy`, `/sell`, `/price`, safety checks, confirmations | Owner trades through Telegram end to end |
| 3 (days 10–14) | Listing alerts with buy links, trade log, console Business card | Alerts arrive and the dashboard shows volume and fees |
| 4 | First users: owner's channels/communities; referral rewards for users who invite others | Weekly active users, volume, fees |

## Owner actions (Claude cannot do these)

1. Create the Telegram bot with @BotFather and store its token in SSM (command provided).
2. Create the Jupiter referral account and its token accounts at [referral.jup.ag](https://referral.jup.ag/) with your own wallet (a small on-chain rent fee). Share the **public** referral account address.
3. Create a Jupiter API key on the Jupiter developer portal (the `.env` value is empty today; keyless works for development) and store it in SSM (command provided).
4. Check whether running a swap interface that charges fees needs a licence where you live (not legal advice).

## Risks

- **Distribution is the real risk:** the market is crowded (Axiom, Photon, Trojan, BONKbot, GMGN). We compete on lower fees, no custody, and honest cost and safety information.
- **Phishing:** users must only trust links from our bot. The page shows exactly what is being signed, and the wallet simulates it.
- Jupiter API changes and rate limits; wallet support for version-1 transactions (we request version 0).
