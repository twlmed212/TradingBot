"""H3a: slow listing drift on Solana DEXs — kill test. Rules are frozen in research/registry/2026-10-25-h3a-listing-drift.md.

    python3 research/h3a_killtest.py --costs costs.json   # costs: {mint: round-trip bps at $1k}; else 40 bps each

Reads events from data/announcements.sqlite3 (listing_events) and hourly on-chain prices from
data/listing_prices.sqlite3 (research/listing_prices.py). Never touches holdout events (on/after 2025-07-01).
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_DB = ROOT / "data" / "announcements.sqlite3"
PRICES_DB = ROOT / "data" / "listing_prices.sqlite3"
HOLDOUT_CUTOFF = datetime(2025, 7, 1, tzinfo=timezone.utc)
MIN_SWAPS = 20
DEFAULT_COST_BPS = 40.0
DELAYS = {"1h": timedelta(hours=1), "3h": timedelta(hours=3)}
EXITS = ("trading_start", "24h", "72h")
PRIMARY = ("1h", "trading_start")
SEED = 20261025


def ceil_hour(dt: datetime) -> datetime:
    floor = dt.replace(minute=0, second=0, microsecond=0)
    return floor if floor == dt else floor + timedelta(hours=1)


def load_events() -> list[dict]:
    db = sqlite3.connect(EVENTS_DB)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM listing_events WHERE announced_at < ? ORDER BY announced_at", (HOLDOUT_CUTOFF.isoformat(),))]
    rows = [r for r in rows if datetime.fromisoformat(r["announced_at"]) < HOLDOUT_CUTOFF]
    kept, last_by_mint = [], {}
    for r in rows:  # first announcement per token within any 7-day cluster
        a = datetime.fromisoformat(r["announced_at"])
        prev = last_by_mint.get(r["mint"])
        if prev is None or a - prev >= timedelta(days=7):
            kept.append(r)
        last_by_mint[r["mint"]] = a if prev is None or a - prev >= timedelta(days=7) else prev
    return kept


class Prices:
    def __init__(self):
        db = sqlite3.connect(f"file:{PRICES_DB}?mode=ro", uri=True)
        self.pool = {m: (p, q) for m, p, q in db.execute("SELECT mint, pool, quote_mint FROM pools")}
        self.created = {m: datetime.fromisoformat(created) for m, created in db.execute(
            "SELECT mint, pool_created_at FROM pools WHERE pool_created_at IS NOT NULL")}
        self.sol = {h: c for h, c in db.execute(
            "SELECT hour, close FROM sol_usd WHERE hour < ?", (HOLDOUT_CUTOFF.isoformat(),))}
        self.hours: dict[str, dict[str, tuple[float | None, int]]] = {}
        for m, h, px, n in db.execute(
            "SELECT h.mint, h.hour, h.price_quote, h.n_swaps FROM hourly h "
            "JOIN pools p ON h.mint = p.mint AND h.pool = p.pool WHERE h.hour < ?",
            (HOLDOUT_CUTOFF.isoformat(),)):
            self.hours.setdefault(m, {})[h] = (px, n)
        db.close()

    def at(self, mint: str, hour: datetime) -> tuple[float | None, int]:
        """Price in SOL and swap count for the hour starting at `hour`."""
        if hour >= HOLDOUT_CUTOFF or mint not in self.pool:
            return None, 0
        if mint in self.created and hour < self.created[mint]:
            return None, 0
        px, n = self.hours.get(mint, {}).get(hour.isoformat(), (None, 0))
        if px is None:
            return None, n
        quote = self.pool[mint][1]
        if quote.startswith("So111"):
            return px, n
        sol = self.sol.get(hour.isoformat())
        return (px / sol, n) if sol else (None, n)


def evaluate(events, prices, costs, delay_key, exit_key, cost_mode):
    out, excluded = [], []
    for e in events:
        a = datetime.fromisoformat(e["announced_at"])
        entry_h = ceil_hour(a + DELAYS[delay_key])
        if exit_key == "trading_start":
            ts = datetime.fromisoformat(e["trading_start_at"]) if e["trading_start_at"] else None
            exit_h = ceil_hour(ts) if ts and ceil_hour(ts) > entry_h else entry_h + timedelta(hours=24)
        else:
            exit_h = entry_h + timedelta(hours=int(exit_key[:-1]))
        if a >= HOLDOUT_CUTOFF or entry_h >= HOLDOUT_CUTOFF or exit_h >= HOLDOUT_CUTOFF:
            excluded.append((e, "entry or exit reaches the sealed holdout"))
            continue
        p0, n0 = prices.at(e["mint"], entry_h)
        p1, n1 = prices.at(e["mint"], exit_h)
        if p0 is None or p1 is None or n0 < MIN_SWAPS or n1 < MIN_SWAPS:
            excluded.append((e, f"thin or missing: entry {n0} swaps, exit {n1} swaps"))
            continue
        base = max(20.0, costs.get(e["mint"], DEFAULT_COST_BPS)) / 1e4
        cost = base if cost_mode == "base" else 2 * base + 0.005
        out.append({**e, "entry_h": entry_h, "exit_h": exit_h, "gross": p1 / p0 - 1, "net": p1 / p0 - 1 - cost})
    return out, excluded


def secondary_anchor(event: dict) -> datetime | None:
    """The registered descriptive anchor is actual trading start, never the primary fallback exit."""
    if not event["trading_start_at"]:
        return None
    hour = ceil_hour(datetime.fromisoformat(event["trading_start_at"]))
    return hour if hour < HOLDOUT_CUTOFF else None


def bootstrap_lower(nets, n=10_000, q=0.05):
    rng = random.Random(SEED)
    means = sorted(statistics.mean(rng.choices(nets, k=len(nets))) for _ in range(n))
    return means[int(q * n)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--costs", help="JSON file {mint: round-trip bps at $1k}")
    args = ap.parse_args()
    costs = json.loads(Path(args.costs).read_text()) if args.costs else {}
    events = load_events()
    prices = Prices()
    print(f"{len(events)} research-window events after the 7-day de-duplication; prices from {HOLDOUT_CUTOFF.date()} excluded from loading/evaluation")

    grid = {}
    for d in DELAYS:
        for x in EXITS:
            res, excl = evaluate(events, prices, costs, d, x, "base")
            grid[(d, x)] = (res, excl)
    res, excl = grid[PRIMARY]
    stress, _ = evaluate(events, prices, costs, *PRIMARY, "stress")

    print(f"\nPrimary (entry +1 h, exit at trading start): {len(res)} events priced, {len(excl)} excluded")
    for e, why in excl:
        print(f"  excluded {e['ticker']:8} {e['announced_at'][:10]} {e['event_type']}: {why}")
    print("\n  announced   ticker   type                      evidence      entry            exit             gross     net")
    for r in res:
        print(f"  {r['announced_at'][:10]}  {r['ticker']:8} {r['event_type']:25} {r['evidence']:12} "
              f"{r['entry_h']:%m-%d %H:%M}  {r['exit_h']:%m-%d %H:%M}  {r['gross'] * 100:+7.1f}%  {r['net'] * 100:+7.1f}%")

    if len(res) < 5:
        print("\nToo few priced events for a verdict.")
        return
    nets = [r["net"] for r in res]
    best_removed = sorted(nets)[:-1]
    lower = bootstrap_lower(nets)
    variants_pos = sum(1 for k, (rs, _) in grid.items() if rs and statistics.mean(r["net"] for r in rs) > 0)
    print("\nGrid (base costs): mean net / median net / hit rate / n")
    for (d, x), (rs, _) in grid.items():
        if rs:
            ns = [r["net"] for r in rs]
            print(f"  entry +{d:3} exit {x:14} {statistics.mean(ns) * 100:+6.2f}% / {statistics.median(ns) * 100:+6.2f}% / "
                  f"{sum(n > 0 for n in ns) / len(ns) * 100:4.0f}% / {len(ns)}")

    s_nets = [r["net"] for r in stress]
    checks = [
        (f"mean net > 0 under stress costs ({statistics.mean(s_nets) * 100:+.2f}%)", statistics.mean(s_nets) > 0),
        (f"median net > 0 under base costs ({statistics.median(nets) * 100:+.2f}%)", statistics.median(nets) > 0),
        (f">= 55% of events positive ({sum(n > 0 for n in nets)}/{len(nets)})", sum(n > 0 for n in nets) / len(nets) >= 0.55),
        (f"bootstrap 95% lower bound of mean > 0 ({lower * 100:+.2f}%)", lower > 0),
        (f"mean without the best event > 0 ({statistics.mean(best_removed) * 100:+.2f}%)", statistics.mean(best_removed) > 0),
        (f">= 4 of 6 grid variants positive ({variants_pos}/6)", variants_pos >= 4),
    ]
    print("\nPre-registered criteria:")
    for text, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")

    usd_nets = []
    for r in res:
        s0, s1 = prices.sol.get(r["entry_h"].isoformat()), prices.sol.get(r["exit_h"].isoformat())
        if s0 and s1:
            usd_nets.append((1 + r["net"]) * s1 / s0 - 1)
    if usd_nets:
        print(f"\nDescriptive USD-equivalent primary returns (base costs, same event allocations; not a portfolio): "
              f"mean {statistics.mean(usd_nets) * 100:+.2f}%, median {statistics.median(usd_nets) * 100:+.2f}%, n={len(usd_nets)}")

    print("\nSecondary (descriptive): post-listing drift from the trading-start hour, SOL terms")
    for days in (7, 14):
        drifts = []
        for r in events:
            anchor = secondary_anchor(r)
            if anchor is None or anchor + timedelta(days=days) >= HOLDOUT_CUTOFF:
                continue
            p0, n0 = prices.at(r["mint"], anchor)
            p1, n1 = prices.at(r["mint"], anchor + timedelta(days=days))
            if p0 and p1 and n0 >= MIN_SWAPS and n1 >= MIN_SWAPS:
                drifts.append(p1 / p0 - 1)
        if drifts:
            print(f"  +{days:2} d: mean {statistics.mean(drifts) * 100:+.1f}%, median {statistics.median(drifts) * 100:+.1f}%, "
                  f"{sum(d < 0 for d in drifts)}/{len(drifts)} negative")


if __name__ == "__main__":
    main()
