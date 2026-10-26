# Kovaswap roadmap

**Mission:** the safest and cheapest way to swap on Solana, from any device, without ever giving up your keys.

**How we earn:** every swap carries our fee through Jupiter's Referral Program (default 0.5%; Jupiter keeps 20%, we net 0.4%). We earn whether users win or lose, so we never need to predict prices.

## 1. Product map

One engine, several doors. The engine is the same everywhere: Jupiter swap with our fee, a token safety check, user accounts by wallet sign-in, points and referrals.

| Door | What it is | Mission |
|---|---|---|
| **Website (PWA)** | Swap page for desktop wallets (Phantom, Solflare, Backpack) and Android phone wallets (Mobile Wallet Adapter) | 1 |
| **Seeker app** | The same web app wrapped as an Android app (Trusted Web Activity) and published on the Solana dApp Store; signs with Seed Vault Wallet | 1 |
| **Telegram bot** | Alerts and "buy" buttons that open the swap page in the user's wallet | 3 |
| **Share links / partner widget** | "Buy X" links and an embeddable swap box for token communities | 4 |

iPhone has no Mobile Wallet Adapter, so iPhone users open the website inside the Phantom or Solflare app (deep link).

## 2. Features

**Mission 1 (minimum product):**
- Swap any token with live quote, price impact and the full cost shown before signing (fee included).
- Basic safety check before buying: freeze or mint authority still active, low liquidity, top-10 holder share, and a "can it be sold" quote test. A clear warning, never a block.
- Swap history for the connected wallet.

**Later:** limit orders (Jupiter Trigger API, which also supports referral fees), portfolio and profit/loss view, price alerts, listing alerts (Binance/Upbit), watched wallets, trade cards.

## 3. Growth programs

### Loyalty points (seasons)

| Earn | Rule |
|---|---|
| Swaps | Points per $1 of fees paid, capped per day (stops wash trading) |
| Streaks | Bonus for swapping on 3, 5 and 7 days of a week |
| Missions | First swap, sign in, verify Seeker, invite a friend, set an alert, try a limit order |
| Invites | 10% of the points your invited friends earn (one level only, no pyramid) |
| Seeker owners | 1.5× multiplier on all points |

| Spend / unlock | |
|---|---|
| SOL cashback | Redeem points for cashback paid from the rewards pool |
| Tiers | Bronze, Silver, Gold, Diamond by points in the last 30 days; higher tiers get more cashback, priority alerts and badges |
| Partner airdrops | Token projects pay us to distribute their airdrops to active, verified users (also a revenue stream) |
| Early access | New features (limit orders, alerts) open to top tiers first |

- **Seasons** last 8 weeks, each with a fixed reward pool and a leaderboard. Tiers reset each season.
- **Funding rule:** all rewards (cashback, points redemptions, prizes) come from at most **25% of net fee revenue**. The program can never cost more than it earns.
- **Anti-farming:** daily caps, wallet age and activity checks, and stronger trust for Seeker Genesis Token holders (one per real device).
- **Wording:** points are loyalty rewards. We never promise a token, a price or an airdrop of our own.

### Invite & earn
- Each user gets an invite link. Inviters earn **25% of our fee** on their friends' swaps for 12 months, paid weekly in SOL (with a minimum payout). Invited friends get **10% cashback** on their first month.
- Partners (communities, influencers, token projects) get their own Jupiter referral account under our project, so their share is paid on-chain automatically.

### Seeker owner perks
- Verify the Seeker Genesis Token (one non-transferable token per device) on sign-in.
- Perks: 1.5× points, extra cashback, a Seeker badge, and Seeker-only missions.
- Apply for dApp Store featuring and Solana Mobile's Seeker reward seasons.

## 4. Missions

| # | Mission | Main tasks | Done when |
|---|---|---|---|
| 1 | **Website + Seeker app** | Brand and domain; web app (PWA) with wallet connect on desktop and Android; swap API on AWS Lambda; safety check; terms of use; wrap with Bubblewrap and submit to the dApp Store | A real swap pays our fee; the app is installable on the owner's Seeker |
| 2 | **Accounts, points, invites, Seeker perks** | Wallet sign-in; points ledger; seasons and tiers; invite links and weekly SOL payouts; Genesis Token check | First season live; first payouts sent |
| 3 | **Telegram bot** | Alerts (listings, prices), buy buttons into the swap page, points and invite stats in chat | The owner trades from Telegram end to end |
| 4 | **Grow** | Share links, partner widget and on-chain partner shares, limit orders, portfolio | Partners embed us; weekly users grow |

## 5. Technology

- **Web app:** Vite + TypeScript; Wallet Standard plus Solana Mobile's wallet library for Android (bundled at build time; no scripts loaded from other sites); PWA manifest and service worker.
- **Seeker app:** Bubblewrap (Trusted Web Activity), signed APK, dApp Store publishing, with Digital Asset Links on our domain.
- **Backend:** Python on AWS Lambda (Region eu-north-1) with the existing `swapbot/app.py`; DynamoDB for users, swaps, points and referrals; secrets in SSM Parameter Store.
- **Hosting:** to decide in mission 1. Options: AWS S3 + CloudFront (a custom domain needs a certificate in us-east-1; check against the AWS project rules) or a static host such as Cloudflare Pages.

## 6. Rules

- Non-custodial: never ask for, store or log a private key or seed phrase.
- No profit promises, no "signals", no prizes for trading more (volume contests).
- Show the full cost before every swap; warn honestly about risky tokens.
- Check local rules for running a swap service with fees, rewards and cashback before launch.

## 7. What we measure

Weekly active wallets, swaps, volume, fees earned, rewards paid (must stay ≤ 25% of net fees), 30-day retention, invites per user, Seeker share of users.

## 8. Brand

- **Name: Kovaswap** (chosen 26 Oct 2026). `kovaswap.com`, `kovaswap.app` and `kovaswap.xyz` were unregistered on 26 Oct; the owner buys them (at least `.com` and `.app`) and reserves `@kovaswap` on X and Telegram.
- **Language: English only**, for users worldwide (decided 26 Oct 2026).
- Some tiny Solana memecoins are called KOVA. We have **no token**; say so clearly on the site and in the FAQ, and warn users that any "Kovaswap token" is a scam.

## 9. Open decisions

- Fee level (0.5% default; 0.5–2.55% allowed).
- Hosting choice (section 5).
