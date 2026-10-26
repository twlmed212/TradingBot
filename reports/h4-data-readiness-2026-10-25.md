# H4 unlock overlay — data-readiness audit

25 October 2026. **Status: not ready for a historical kill test.** This is a source audit, not a pre-registration, a failed strategy, or a return evaluation. H4 has not consumed a hypothesis trial; the count remains 2/6 beyond H1–H2.

## Findings

The sources reviewed provide useful allocation and vesting descriptions, but we have not yet verified a complete point-in-time dataset of schedules, revisions and circulating supply. A page retrieved today with a 2023 publication label is not proof that today's text was available in 2023. No H4 price series was fetched or evaluated.

| Source inspected | What it supports | What remains missing for historical use |
|---|---|---|
| [Jito launch announcement](https://www.jito.network/blog/announcing-jto-the-jito-governance-token/) (page dated 27 Nov 2023) | Investor/contributor vesting description; explicitly allows governance-dependent distribution changes | Archived version, exact tranche timestamps, subsequent changes, denominator known at each decision |
| [Pyth distribution documentation](https://docs.pyth.network/pyth-token/pyth-distribution) | Initial supply and scheduled lockup intervals | Historical page versions, precise release times, historical circulating-supply observations; initial supply is not a permanent denominator |
| [Jupiter February 2025 audit](https://discuss.jup.ag/t/jup-community-audit-feb-2025/34764) | Dated discussion of burns, reduced allocations, Jupiter Lock and voluntary re-locks | Verified revision history, earliest available notices, event-specific supply. A retrospective February audit cannot inform a January decision |
| [Drift launch announcement](https://www.drift.trade/governance/introducing-the-drift-governance-token) (page dated 16 Apr 2024) | Allocation categories and contributor lockup/vesting terms | Exact investor schedule, version proof and supply history; broad allocation percentages do not define every event |
| [Kamino former token-info URL](https://docs.kamino.finance/kmno/token-info) | Currently redirects to the general documentation homepage | Recover the original document/version before interpreting token rules; do not treat the redirected homepage as equivalent evidence |
| [DefiLlama SDK documentation](https://github.com/DefiLlama/api-sdk) | Documents emissions endpoints as requiring a Pro API key | No purchase made. Historical schedule values do not alone prove historical publication vintages; a paid feed must explicitly supply those before being considered sufficient |

The attempted public `DefiLlama/emissions-adapters` repository URL returned 404 through the research browser. This is an access outcome, not proof that no archive or alternative source exists.

## Concrete work completed

`research/unlock_sources.py` captures the four first-party documents above into `data/unlock_sources.sqlite3`. All four initial captures succeeded. `research/data/unlock_sources.json` holds the explicit source list, not a trading universe.

- Raw response bytes are SHA-256 keyed; observations record UTC receipt time, requested/final URL, content type and the untrusted Last-Modified claim separately.
- Repeated captures append observations; changed content creates a new document. SQLite triggers reject updates/deletes through the normal connection. This is an append-only local archive, not tamper-proof external timestamping.
- URLs and redirects are restricted to configured HTTPS hosts, without query-string credentials. Response sizes are bounded. The collector loads no secrets, calls no price/RPC endpoint and contains no signing code.
- Captures made now are suitable for documenting what is available now. They do **not** make any historical row eligible. These documents are source material only, not automatically parsed or approved unlock signals.

Manual commands (no recurring service installed):

```bash
python3 research/unlock_sources.py --plan
python3 research/unlock_sources.py --fetch
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_unlock_sources.py
```

## Required evidence record before registration

For each event, retain mint and mapping evidence; source URL and raw hash; publication claim; independently verified version-availability time and its evidence; our receipt time; scheduled release timestamp and precision; amount in token units; beneficiary category; cliff/linear/claimable/discretionary classification; amendments/cancellations/re-locks; and circulating supply with its definition, measurement time, publication time and source version. Total minted, vested, unlocked, claimable, transferred and circulating amounts are not interchangeable.

Use only a version independently evidenced as available at or before the decision. For newly captured forward documents, availability cannot precede receipt. Never silently substitute current balances for historical circulation. Store competing interpretations and unresolved data as unknown, not zero unlocks.

A source must establish coverage of all relevant tranches before absence of a listed event can mean “no large unlock.” A handful of hand-selected public announcements does not provide complete calendar coverage or a survivorship-free universe.

## H4 design requirements, not yet frozen

Preserve PLAN's intended question: does avoiding tokens with scheduled unlocks totaling at least 2% of then-known circulation within the next 14 days improve an otherwise identical basket? Aggregate overlapping tranches without counting the same event twice. An overlay is a risk filter, not a standalone entry strategy.

Before returns are read, register the universe and evaluation window, exact decision/execution clock, supply-age tolerance, release classification, handling of revisions/unknowns, re-entry rule, universe exclusions, one primary variant and any explicit trial grid. Freeze the basket weights and allocate excluded weight to SOL rather than silently levering remaining names. Compare against the identical unfiltered basket, plain SOL and a specified staked-SOL benchmark; show USD too. Include both legs' turnover, minimum 20 bps round-trip costs and stressed costs.

Register minimum sample breadth and time coverage, a paired improvement test that handles overlapping windows/repeated tokens, concentration limits, drawdown budget and absolute benchmark requirements. Do not declare success merely because a losing basket loses less. Do not recycle H2's failed momentum rules as an allegedly new baseline, and disclose any reused research window.

## Next work

1. Recover independent pre-decision snapshots/revisions for the four candidate sources, then verify dated circulating supply and mint mappings. The snapshots captured today are not a substitute.
2. Build a metadata-only coverage report, including missing/ambiguous records, before selecting any historical price windows. All research endpoints must remain before 1 July 2025.
3. Only if coverage is sufficient, freeze the H4 registration and implement its evaluator. Otherwise continue document-only forward capture. A forward price evaluation needs an explicit protocol separating new observations from the currently sealed ≥1 July 2025 data; do not silently bypass the existing cutoff.
4. No paid subscription, historical return run, server deployment, live trade, or automated trading process was started in this audit.
