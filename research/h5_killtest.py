"""H5: short-term reversal vs SOL on 15 Hyperliquid-listed Solana tokens — kill test.

Rules are frozen in research/registry/2026-10-25-h5-short-term-reversal.md.

    python3 research/h5_killtest.py

Reads data/h5_prices.sqlite3 (research/h5_prices.py). Never loads anything on or after the 2025-07-01 cutoff.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h5_prices import DB, TOKENS  # noqa: E402

HOLDOUT_CUTOFF = datetime(2025, 7, 1, tzinfo=timezone.utc)
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MIN_SWAPS = 20
MIN_HISTORY = timedelta(days=30)
EXIT_GRACE_DAYS = 7
STAKE_APR = 0.06
BASE_COST, STRESS_COST = 0.0015, 0.0030
LOOKBACKS, BASKETS = (1, 3, 7), (1, 3)
PRIMARY = (3, 3)


class Data:
    def __init__(self):
        db = sqlite3.connect(DB)
        quote = {pool: q for pool, q in db.execute("SELECT pool, quote_mint FROM candidates")}
        sol = {h: o for h, o in db.execute("SELECT hour, open FROM sol_usd_open WHERE hour < ?", (HOLDOUT_CUTOFF.isoformat(),))}
        self.sol_usd = sol
        self.px: dict[str, dict[datetime, tuple[float | None, int]]] = defaultdict(dict)
        self.first_obs: dict[str, datetime] = {}
        for mint, hour, pool, n, p in db.execute(
                "SELECT mint, hour, pool, n_swaps, price_quote FROM hourly WHERE hour < ? ORDER BY hour", (HOLDOUT_CUTOFF.isoformat(),)):
            h = datetime.fromisoformat(hour)
            val = None
            if p is not None:
                if quote.get(pool) == USDC:
                    s = sol.get(hour)
                    val = p / s if s else None
                else:
                    val = p
            self.px[mint][h] = (val, n or 0)
            if val is not None and mint not in self.first_obs:
                self.first_obs[mint] = h
        self.perp = {m: (datetime.fromisoformat(a).replace(tzinfo=timezone.utc), datetime.fromisoformat(b).replace(tzinfo=timezone.utc))
                     for _s, m, a, b in TOKENS}
        self.sym = {m: s for s, m, _a, _b in TOKENS}

    def good(self, mint: str, hour: datetime) -> float | None:
        v, n = self.px[mint].get(hour, (None, 0))
        return v if v is not None and n >= MIN_SWAPS else None

    def eligible(self, mint: str, day: datetime) -> bool:
        first, last = self.perp[mint]
        fo = self.first_obs.get(mint)
        return (first <= day <= last and fo is not None and fo <= day - MIN_HISTORY
                and self.good(mint, day) is not None and self.good(mint, day + timedelta(hours=1)) is not None)

    def exit_price(self, mint: str, day: datetime) -> float:
        """Execution-hour price on `day`, else the next valid one within the grace period, else 0 (position lost)."""
        for k in range(EXIT_GRACE_DAYS + 1):
            hour = day + timedelta(days=k, hours=1)
            if hour >= HOLDOUT_CUTOFF:
                # the grace period would reach sealed data (never loaded): exit at the last valid price before the cutoff
                for back in range(1, EXIT_GRACE_DAYS + 1):
                    q = self.good(mint, day - timedelta(days=back) + timedelta(hours=1))
                    if q is not None:
                        return q
                return 0.0
            p = self.good(mint, hour)
            if p is not None:
                return p
        return 0.0

    def mark(self, mint: str, day: datetime, last: float) -> float:
        p = self.good(mint, day + timedelta(hours=1))
        return p if p is not None else last


def window(data: Data) -> tuple[datetime, datetime]:
    days = sorted({h.replace(hour=0) for m in data.px for h in data.px[m]})
    start = next(d for d in days if sum(data.eligible(m, d) for m in data.px) >= 3)
    end = min(HOLDOUT_CUTOFF - timedelta(days=1), days[-1])
    return start, end


def simulate(data: Data, L: int, K: int | None, cost: float, start: datetime, end: datetime, exclude: set[str] = frozenset()):
    """K=None means the equal-weight basket of all eligible tokens. Returns daily equity, per-token PnL, rebalances."""
    stake_d = (1 + STAKE_APR) ** (1 / 365) - 1
    eq, curve, contrib = 1.0, [], defaultdict(float)
    weights: dict[str, float] = {}
    d = start
    while d + timedelta(days=L) <= end:
        cands = []
        for m in data.px:
            if m in exclude or not data.eligible(m, d):
                continue
            prev = data.good(m, d - timedelta(days=L))
            now = data.good(m, d)
            if prev and now:
                cands.append((now / prev - 1, m))
        if K is None:
            target = {m: 1 / len(cands) for _, m in cands} if cands else {}
        else:
            losers = sorted(c for c in cands if c[0] <= 0)[:K]
            target = {m: 1 / K for _, m in losers}
        traded = sum(abs(target.get(m, 0) - weights.get(m, 0)) for m in set(target) | set(weights))
        eq *= 1 - cost * traded
        entry = {m: data.good(m, d + timedelta(hours=1)) for m in target}
        exit_day = d + timedelta(days=L)
        exits = {m: data.exit_price(m, exit_day) for m in target}
        # daily marks inside the holding period
        last = dict(entry)
        sol_w = 1 - sum(target.values())
        for k in range(1, L + 1):
            day = d + timedelta(days=k)
            if k == L:
                last = dict(exits)
            else:
                last = {m: data.mark(m, day, last[m]) for m in target}
            value = sum(w * last[m] / entry[m] for m, w in target.items()) + sol_w * (1 + stake_d) ** k
            curve.append((day, eq * value))
        growth = {m: exits[m] / entry[m] for m in target}
        period_sol = sol_w * (1 + stake_d) ** L
        new_eq = eq * (sum(w * growth[m] for m, w in target.items()) + period_sol)
        for m, w in target.items():
            contrib[m] += eq * w * (growth[m] - 1) - eq * cost * abs(w - weights.get(m, 0))
        # drifted weights for the next rebalance's turnover
        weights = {m: eq * w * growth[m] / new_eq for m, w in target.items() if new_eq > 0}
        eq = new_eq
        d = exit_day
    return curve, contrib


def stats(curve, days_total: int) -> dict:
    eqs = [1.0] + [e for _, e in curve]
    rets = [b / a - 1 for a, b in zip(eqs, eqs[1:]) if a > 0]
    stake_d = (1 + STAKE_APR) ** (1 / 365) - 1
    xs = [r - stake_d for r in rets]
    sd = statistics.pstdev(xs) if len(xs) > 1 else 0
    peak, mdd = 1.0, 0.0
    for x in eqs:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak if peak else 0)
    return {"ret": eqs[-1] - 1, "sharpe": statistics.mean(xs) / sd * math.sqrt(365) if sd else 0.0, "mdd": mdd}


def blocks(curve, start: datetime) -> list[float]:
    by_day = dict(curve)
    out, b0, prev = [], start, 1.0
    stake_block = (1 + STAKE_APR) ** (28 / 365) - 1
    while True:
        b1 = b0 + timedelta(days=28)
        e = by_day.get(b1)
        if e is None:
            break
        out.append(e / prev - 1 - stake_block)
        prev, b0 = e, b1
    return out


def main() -> None:
    data = Data()
    start, end = window(data)
    days = (end - start).days
    stake = (1 + STAKE_APR) ** (days / 365) - 1
    print(f"Window {start:%Y-%m-%d} → {end:%Y-%m-%d} ({days} days). Staked SOL: {stake * 100:+.1f}% (SOL terms). Nothing on or after {HOLDOUT_CUTOFF:%Y-%m-%d} loaded.")
    print("Eligible tokens per month:", " ".join(
        f"{(start + timedelta(days=30 * i)):%y-%m}:{sum(data.eligible(m, start + timedelta(days=30 * i)) for m in data.px)}"
        for i in range(days // 30 + 1)))

    results = {}
    print("\nvariant            cost     return(SOL)  Sharpe(xs)  maxDD")
    for L in LOOKBACKS:
        for K in BASKETS:
            for label, c in (("base", BASE_COST), ("stress", STRESS_COST)):
                curve, contrib = simulate(data, L, K, c, start, end)
                st = stats(curve, days)
                results[(L, K, label)] = (st, curve, contrib)
                print(f"L={L}d K={K}{' (primary)' if (L, K) == PRIMARY else '          '}  {label:6}  {st['ret'] * 100:+9.1f}%   {st['sharpe']:6.2f}   {st['mdd'] * 100:5.1f}%")
    basket_curve, _ = simulate(data, PRIMARY[0], None, BASE_COST, start, end)
    bst = stats(basket_curve, days)
    print(f"equal-weight basket (L=3, base)   {bst['ret'] * 100:+9.1f}%   {bst['sharpe']:6.2f}   {bst['mdd'] * 100:5.1f}%")

    pst, pcurve, pcontrib = results[(*PRIMARY, "base")]
    sst = results[(*PRIMARY, "stress")][0]
    print("\nPrimary per-token contribution (fraction of starting equity, base costs):")
    for m, v in sorted(pcontrib.items(), key=lambda kv: -kv[1]):
        print(f"  {data.sym[m]:10} {v * 100:+7.1f}%")
    top = max(pcontrib, key=pcontrib.get) if pcontrib else None
    ex = stats(simulate(data, *PRIMARY, BASE_COST, start, end, exclude={top})[0], days) if top else {"ret": -1}
    bl = blocks(pcurve, start)
    pos_blocks = sum(1 for b in bl if b > 0)
    vwins = sum(1 for L in LOOKBACKS for K in BASKETS if results[(L, K, "base")][0]["ret"] > stake)
    sol0 = data.sol_usd.get(start.isoformat())
    sol1 = data.sol_usd.get((end).isoformat())
    if sol0 and sol1:
        print(f"\nDescriptive USD: primary {((1 + pst['ret']) * sol1 / sol0 - 1) * 100:+.1f}%, holding SOL {(sol1 / sol0 - 1) * 100:+.1f}%")
    print(f"4-week blocks above staking (primary, base): {' '.join(f'{b * 100:+.0f}%' for b in bl)}")

    checks = [
        (f"beats staked SOL under stress costs ({sst['ret'] * 100:+.1f}% vs {stake * 100:+.1f}%)", sst["ret"] > stake),
        (f"Sharpe > 0 and above the basket ({pst['sharpe']:.2f} vs {bst['sharpe']:.2f})", pst["sharpe"] > 0 and pst["sharpe"] > bst["sharpe"]),
        (f"positive in >= 60% of 4-week blocks ({pos_blocks}/{len(bl)})", bool(bl) and pos_blocks / len(bl) >= 0.60),
        (f"max drawdown <= 40% ({pst['mdd'] * 100:.1f}%)", pst["mdd"] <= 0.40),
        (f"without top contributor {data.sym.get(top, '-')}: beats staked SOL ({ex['ret'] * 100:+.1f}%)", ex["ret"] > stake),
        (f">= 4 of 6 variants beat staked SOL at base ({vwins}/6)", vwins >= 4),
    ]
    print("\nPre-registered criteria:")
    for text, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")


if __name__ == "__main__":
    main()
