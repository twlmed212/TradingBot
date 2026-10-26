"""H5 data: daily on-chain prices (00:00 and 01:00 UTC samples) for the 15 Hyperliquid-listed Solana tokens.

    python3 research/h5_prices.py --plan   # pools and call estimate, no price samples
    python3 research/h5_prices.py          # fetch missing samples (resumable)

Rules are in research/registry/2026-10-25-h5-short-term-reversal.md. For each token-month the pool is the SOL- or
USDC-quoted pool with the most swaps in the month's first 00:00 UTC hour (swap counts only). Price samples reuse
`listing_prices.sample_hour` (median of the pool's swap prices among the first 50 successful transactions of the hour),
which refuses any hour on or after the 2025-07-01 holdout cutoff. Output: data/h5_prices.sqlite3.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from listing_prices import QUOTES, http_json, load_env, sample_hour, ts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "h5_prices.sqlite3"
HOLDOUT_CUTOFF = datetime(2025, 7, 1, tzinfo=timezone.utc)
PRE_HISTORY = timedelta(days=31)   # eligibility needs 30 days of DEX history before a decision day
HOURS = (0, 1)                     # decision and execution samples
WORKERS = 6

TOKENS = [  # symbol, mint, perp first day, perp last day (registry table)
    ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "2024-04-28", "2025-06-30"),
    ("MEW", "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5", "2024-06-17", "2025-06-30"),
    ("GOAT", "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump", "2024-10-23", "2025-06-30"),
    ("FARTCOIN", "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", "2024-12-20", "2025-06-30"),
    ("MOODENG", "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY", "2024-10-25", "2025-06-30"),
    ("CHILLGUY", "Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump", "2024-11-25", "2025-06-30"),
    ("AI16Z", "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC", "2025-01-01", "2025-06-30"),
    ("GRIFFAIN", "KENJSUYLASHUMfHyy5o4Hp2FdNqZg1AsUPhfH2kYvEP", "2025-01-02", "2025-06-30"),
    ("ZEREBRO", "8x5VqbHA8D7NkD52uNuS5nnt3PwA8pLD34ymskeSo2Wn", "2025-01-02", "2025-06-30"),
    ("MELANIA", "FUAfBo2jgks6gB4Z4LfZkqSZgzNucisEHqnNebaRxM1P", "2025-01-20", "2025-06-30"),
    ("GRASS", "Grass7B4RdKfBCjTKgSqnXkqjwiGvQyFbuSCUJr3XXjs", "2024-10-28", "2025-06-30"),
    ("VINE", "6AJcP7wuLwmRYLBNbi825wgguaPsWzPBEHcHndpRpump", "2025-01-23", "2025-06-30"),
    ("JELLY", "FeR8VBqNRSUD5NtXAj2n3j1dAHkZHfyDktKuLXD4pump", "2025-01-30", "2025-03-26"),
    ("MYRO", "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4", "2024-03-05", "2025-03-29"),
    ("LAUNCHCOIN", "Ey59PH7Z4BFU4HjyKnyMdWt5GGN76KazTAwQihoUXRnk", "2025-05-14", "2025-06-30"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (mint TEXT, pool TEXT, dex TEXT, quote_mint TEXT, created_at TEXT, reserve_usd_today REAL,
                                       PRIMARY KEY (mint, pool));
CREATE TABLE IF NOT EXISTS pool_months (mint TEXT, month TEXT, pool TEXT, quote_mint TEXT, anchor_swaps INTEGER,
                                        PRIMARY KEY (mint, month));
CREATE TABLE IF NOT EXISTS hourly (mint TEXT, hour TEXT, pool TEXT, n_txs INTEGER, n_swaps INTEGER, price_quote REAL,
                                   PRIMARY KEY (mint, hour));
CREATE TABLE IF NOT EXISTS sol_usd_open (hour TEXT PRIMARY KEY, open REAL NOT NULL);
"""


def day0(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def candidates(db: sqlite3.Connection, mint: str) -> list[dict]:
    rows = db.execute("SELECT pool, dex, quote_mint, created_at, reserve_usd_today FROM candidates WHERE mint=?", (mint,)).fetchall()
    if not rows:
        pools = http_json(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/pools?page=1")["data"]
        time.sleep(2.1)
        for p in pools:
            a, rel = p["attributes"], p["relationships"]
            base = rel["base_token"]["data"]["id"].split("_", 1)[1]
            quote = rel["quote_token"]["data"]["id"].split("_", 1)[1]
            if base == mint and quote in QUOTES:
                db.execute("INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?)",
                           (mint, a["address"], rel["dex"]["data"]["id"], quote, a.get("pool_created_at"), float(a.get("reserve_in_usd") or 0)))
        db.commit()
        rows = db.execute("SELECT pool, dex, quote_mint, created_at, reserve_usd_today FROM candidates WHERE mint=?", (mint,)).fetchall()
    return [{"pool": r[0], "dex": r[1], "quote": r[2],
             "created": datetime.fromisoformat(r[3].replace("Z", "+00:00")) if r[3] else None, "reserve": r[4]} for r in rows]


def window(first: str, last: str, cands: list[dict]) -> tuple[datetime, datetime]:
    earliest_pool = min((c["created"] for c in cands if c["created"]), default=day0(first) - PRE_HISTORY)
    start = max(day0(first) - PRE_HISTORY, earliest_pool.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    end = min(day0(last) + timedelta(days=1), HOLDOUT_CUTOFF)
    return start, end


def pick_month(db, rpc, mint: str, cands: list[dict], month_start: datetime) -> tuple[str, str] | None:
    key = month_start.strftime("%Y-%m")
    row = db.execute("SELECT pool, quote_mint FROM pool_months WHERE mint=? AND month=?", (mint, key)).fetchone()
    if row:
        return row[0], row[1]
    existing = [c for c in cands if c["created"] and c["created"] <= month_start]
    if not existing:
        return None
    best, best_n = None, -1
    for c in sorted(existing, key=lambda c: -c["reserve"])[:6]:
        try:
            n = sample_hour(rpc, c["pool"], mint, c["quote"], month_start)["n_swaps"]
        except Exception:
            n = -1
        if n > best_n:
            best, best_n = c, n
    db.execute("INSERT OR REPLACE INTO pool_months VALUES (?,?,?,?,?)", (mint, key, best["pool"], best["quote"], best_n))
    db.commit()
    return best["pool"], best["quote"]


def sol_opens(db: sqlite3.Connection, start: datetime, end: datetime) -> None:
    cur, stop = ts(start) * 1000, ts(min(end, HOLDOUT_CUTOFF)) * 1000
    while cur < stop:
        rows = http_json(f"https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1h&startTime={cur}&endTime={stop - 1}&limit=1000")
        if not rows:
            break
        db.executemany("INSERT OR REPLACE INTO sol_usd_open VALUES (?,?)",
                       [(datetime.fromtimestamp(k[0] / 1000, timezone.utc).isoformat(), float(k[1])) for k in rows if k[0] < stop])
        cur = rows[-1][0] + 3_600_000
        time.sleep(0.2)
    db.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    load_env()
    rpc = os.environ["SOLANA_RPC_URL"]
    db = sqlite3.connect(DB, check_same_thread=False)
    db.executescript(SCHEMA)

    jobs, overall_start = [], HOLDOUT_CUTOFF
    for sym, mint, first, last in TOKENS:
        cands = candidates(db, mint)
        if not cands:
            print(f"  {sym:10} no SOL/USDC pools on GeckoTerminal; skipped")
            continue
        start, end = window(first, last, cands)
        overall_start = min(overall_start, start)
        have = {r[0] for r in db.execute("SELECT hour FROM hourly WHERE mint=?", (mint,))}
        todo, months = [], set()
        d = start
        while d < end:
            month_start = d.replace(day=1) if d.replace(day=1) >= start else start
            pick = ("?", "?") if args.plan else pick_month(db, rpc, mint, cands, month_start)
            if pick:
                months.add(month_start.strftime("%Y-%m"))
                for h in HOURS:
                    hour = d + timedelta(hours=h)
                    if hour < HOLDOUT_CUTOFF and hour.isoformat() not in have:
                        todo.append((sym, mint, pick[0], pick[1], hour))
            d += timedelta(days=1)
        jobs += todo
        print(f"  {sym:10} {start:%Y-%m-%d} → {end:%Y-%m-%d}  pools picked for {len(months)} month(s)  {len(todo)} samples to fetch", flush=True)
    print(f"\n{len(jobs)} samples ≈ {len(jobs) * 10:,} Helius credits")
    if args.plan or not jobs:
        return
    sol_opens(db, overall_start, HOLDOUT_CUTOFF)
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(sample_hour, rpc, pool, mint, quote, hour): (sym, mint, pool, hour) for sym, mint, pool, quote, hour in jobs}
        for f in as_completed(futs):
            sym, mint, pool, hour = futs[f]
            try:
                r = f.result()
            except Exception as e:
                print(f"  {sym} {hour:%Y-%m-%d %H}: {e}")
                continue
            db.execute("INSERT OR REPLACE INTO hourly VALUES (?,?,?,?,?,?)",
                       (mint, hour.isoformat(), pool, r["n_txs"], r["n_swaps"], r["price_quote"]))
            done += 1
            if done % 300 == 0:
                db.commit()
                print(f"  {done}/{len(jobs)}", flush=True)
    db.commit()
    print(f"done: {done}/{len(jobs)} samples")


if __name__ == "__main__":
    main()
