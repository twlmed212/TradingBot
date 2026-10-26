# Pre-registration H3a: slow listing drift on Solana DEXs

**Hypothesis:** H3a  
**Registered:** 25 October 2026, before any event-window prices were fetched for the test (see Disclosure)  
**Status:** kill test, not a promotion gate. Passing justifies forward paper trading of the primary rule and building Milestones 0–2 for it; it is not evidence for G2.  
**Trials:** 6 variants (2 entry delays × 3 exits). The primary variant is fixed in advance.

## Hypothesis

When a major centralized exchange (Binance spot or futures, Upbit) announces a listing of a Solana-native token, the token's Solana DEX price, measured in SOL, keeps rising for hours to days after the announcement by more than the cost of a round trip. The edge is not a speed race: entry is at least one hour after the announcement.

## Events

- Source: `research/listing_events.py`. Announcements from 2021-01-01 with first-party evidence that the listed asset is a Solana-native token: a contract address in the announcement confirmed on-chain as a mint (**address**), a Binance description stating the token is on Solana plus a ticker and name match to a Jupiter-verified token (**text**), or a futures listing whose ticker is confirmed by another such announcement (**corroborated**). Tokenized stocks and wrapped tokens are excluded by construction.
- **Research window:** announcements before 2025-07-01. **Sealed holdout:** 2025-07-01 onward (prices not fetched).
- If a token has several announcements within 7 days, only the first counts (overlapping windows are not independent).
- An event is excluded, with the reason reported, if its token had no SOL- or USDC-quoted pool at entry, or if the entry or exit hour has fewer than 20 sampled swaps out of the 50 transactions (too thin to price or trade).

## Prices

Hourly price = median of the pool's own swap prices among the **first 50 successful transactions of each UTC hour**, i.e. the price near the start of the hour (`research/listing_prices.py`, Helius `getTransactionsForAddress`), in SOL terms. *Amended before any event prices were fetched: originally up to 100 per hour; reduced to 50 for bandwidth. Validated on PENGU, 18 Dec 2024 12:00 UTC: 1.563e-4 on-chain vs Binance 1-minute PENGU/SOL 1.536–1.577e-4 in the hour's first 10 minutes.* USDC pools are converted with Binance SOLUSDT hourly closes. One pool per token: among its SOL- or USDC-quoted pools that existed at the window start (GeckoTerminal's top pools, up to 6 checked), the one with the most swaps in the token's first announcement hour. *Amended before any returns were computed: originally the largest pool by today's reserve; the first fetch showed that pool was often not the one trading at the time (IO 0 of 672 hours with ≥ 20 swaps, SOON 1 of 528, TNSR 42 of 523, BONK 104 of 1,217). Only swap counts had been looked at, no prices or returns.*

## Rule

- **Entry:** the hourly price of the first full UTC hour starting at least *D* after the announcement's publish time.
- **Exit:** the hourly price at *X*.
- Grid: *D* ∈ {1 h (**primary**), 3 h} × *X* ∈ {first full hour after trading starts (**primary**), entry + 24 h, entry + 72 h}. If an announcement has no parsable trading start, or trading starts at or before the entry hour, the trading-start exit is entry + 24 h. "First full hour after trading starts" means the first hour beginning at or after the trading start time.
- Net return per event = exit / entry − 1 − round-trip cost, in SOL terms. Holding SOL earns ~0 over these horizons, so the benchmark is 0.

## Costs

- **Base:** the token's round-trip cost at $1k measured by the forward recorder (24 h median, 25 Oct 2026; saved in `research/data/h3a_costs_2026-10-25.json`), or 40 bps if not recorded, with a floor of 20 bps (Jupiter's 10 bps platform fee on each side). *Floor added before any event prices were seen: KMNO's median read ≤ 0 because its quotes were crossed.* **Stress:** 2× base plus 50 bps (event-time spreads are wider than today's).

## Pass criteria (all required, primary variant)

1. Mean net return per event > 0 under **stress** costs.
2. Median net return per event > 0 under base costs.
3. At least 55% of events have a positive net return under base costs.
4. One-sided 95% bootstrap confidence interval of the mean (10,000 resamples of events, base costs) lies above 0.
5. Removing the single best event, the mean under base costs stays > 0.
6. At least 4 of the 6 grid variants have a positive mean under base costs.

## Secondary (descriptive only, no pass/fail)

Post-listing drift: return from the first full hour after trading starts to +7 days and +14 days, in SOL terms. This informs an "avoid newly listed tokens" overlay; it cannot be traded long-only and makes no claim.

## Disclosure

While testing the price method on 25 Oct 2026, hourly PENGU/SOL prices for 18–20 Dec 2024 (inside the window of PENGU's Binance listing event) were viewed: 1.54e-4, 1.75e-4, 1.66e-4, 1.47e-4, 1.36e-4. No other event-window prices were seen before registration.

## Decision

- **Pass:** start forward paper trading of the primary rule with the live listings feed; prepare H3b (latency) only if forward results hold.
- **Fail:** record it, do not retune this family on this window, move to H4.

## Pre-run implementation audit (25 October 2026, before returns)

- The completed fetch accidentally extended beyond the sealed cutoff: metadata-only checks found 216 DEX hourly rows dated 1–9 July 2025 and 754 SOL reference hours dated 1 July–1 August 2025. Their price values and returns were not inspected in this audit. Existing rows are preserved, but bounded SQL reads and timestamp guards now exclude them from research. The fetcher now clips every window at 1 July and bounds Binance pagination. The holdout was prematurely fetched, so it must not be described as never fetched or wholly untouched; it has not been evaluated by this test.
- Enforced the already-registered 20 bps cost floor in code. Every value in the frozen cost snapshot already satisfies it. Only the selected pool is loaded. Corrected the descriptive drift anchor to the actual rounded trading start, not the primary rule's 24-hour fallback; missing starts and endpoints reaching the holdout are skipped.
- Pool metadata reveals a pre-existing selection deviation: JTO, JUP, BOME, TNSR, ME, TRUMP and SOON use the earliest-pool fallback because the selected pool did not exist seven days before the first announcement. Pools are not repicked. Enforced the registered requirement that the selected pool exist at the entry/exit hour (in particular, ME's selected pool was created at 09:21 UTC, after its 09:00 entry hour). This makes results conditional on the frozen, imperfect pool sample, not a strict replication of the window-start selection paragraph. Descriptive drift uses all deduplicated events with known trading starts and valid endpoint prices, not only priceable primary trades.
- No entry/exit rule, pool selection, cost snapshot, grid, or six pass thresholds changed. All primary entry/exit windows end before the cutoff. USD-equivalent primary returns are also reported descriptively, using the stored SOL/USD hourly closes; the SOL verdict is unchanged. These are per-event returns, not a compounded portfolio return.

## Result (run 25 October 2026) — **FAIL, 5 of 6 criteria**

Full output: `data/h3a_killtest_2026-10-25.txt`. Reproduce with `python3 research/h3a_killtest.py --costs research/data/h3a_costs_2026-10-25.json`. Of 27 research-window announcements, 23 remain after the registered seven-day deduplication; 13 primary events are priceable and 10 are excluded. Priced primary announcements span 22 November 2023–6 May 2025.

| Registered check (primary) | Measured result | Verdict |
|---|---|---|
| Mean net SOL return > 0, stress costs | +9.12% per event | Pass |
| Median net SOL return > 0, base costs | +0.91% | Pass |
| Positive base-cost events ≥ 55% | 8/13 (61.54%) | Pass |
| One-sided 95% bootstrap lower bound > 0 | **−1.92%** | **Fail** |
| Base mean without single best event > 0 | +2.40% | Pass |
| Positive base mean in ≥ 4/6 variants | 6/6 | Pass |

| Entry delay / exit | Mean net SOL (base) | Median net SOL | Hit rate | Events |
|---|---|---|---|---|
| **1 h / trading start (primary)** | **+9.91%** | **+0.91%** | 8/13 | 13 |
| 1 h / +24 h | +31.68% | +8.56% | 57% | 14 |
| 1 h / +72 h | +50.26% | −7.94% | 45% | 11 |
| 3 h / trading start | +26.75% | +1.60% | 53% | 15 |
| 3 h / +24 h | +28.10% | +8.73% | 56% | 16 |
| 3 h / +72 h | +32.02% | −12.87% | 35% | 17 |

- **Failed:** the bootstrap confidence bound crosses zero. A positive sample average is not reliable evidence of an edge. Do not launch the primary rule or choose a better-looking variant after this result; move to H4 without retuning H3a on this window.
- The primary mean is +9.91% in SOL per event (+9.12% with stressed costs), but BOME (+100.1% net) and MOODENG (+48.8%) dominate the average. Only 13 events qualify. USD-equivalent base returns average +10.15%, median +0.30%; these are equal-weight event observations, not a portfolio, annual return, or a staked-SOL comparison.
- Data limitations: current top-pool discovery and listed-token coverage create survivorship/selection bias; pool fallback deviations are disclosed above. Excluding thin or missing exit hours may select away untradeable exits. First-50-swap medians are not guaranteed fills, USDC conversion uses an hour-end SOL close, and today's measured costs are not historical event-time costs. Repeated tokens and simultaneous events also weaken the event-independent bootstrap assumption. No G2 claim is justified.
- Descriptive drift only: from actual trading start, +7-day mean +17.3%, median −2.0% (14 events); +14-day mean +6.4%, median −10.9% (15 events). Different endpoint coverage gives different samples. No holdout price was loaded or evaluated by this run; the earlier accidental fetch remains disclosed above. No post-result rule changes or new variants were tried.

### Primary exclusions

Counts are sampled swaps in the selected pool, not total market activity. The fixed rule requires at least 20 at both endpoints. A zero can mean a missing/unpriceable hour, not proof that no other pool traded.

| Token / announcement | Entry swaps | Exit swaps | Reason |
|---|---|---|---|
| JTO / 2023-12-07 | 0 | 19 | Entry missing/unpriceable; exit below 20 |
| BONK / 2023-12-15 | 45 | 6 | Exit below 20 |
| JUP / 2024-01-31 | 0 | 0 | Both endpoints missing/unpriceable |
| TNSR / 2024-04-08 | 0 | 49 | Entry missing/unpriceable |
| ME / 2024-12-10 | 0 | 33 | Selected pool created after entry hour began |
| KMNO / 2024-12-20 | 18 | 44 | Entry below 20 |
| IO / 2025-05-08 | 5 | 31 | Entry below 20 |
| PENGU / 2025-05-09 | 13 | 35 | Entry below 20 |
| SOON / 2025-05-23 | 0 | 0 | Both endpoints missing/unpriceable |
| RAY / 2025-06-19 | 1 | 46 | Entry below 20 |
