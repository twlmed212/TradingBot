"""H6 step 1: discover candidate wallets (signers of swaps in our tokens' pools). Rules: research/registry/2026-10-25-h6-copy-smart-wallets.md.

    python3 research/h6_discover.py --plan
    python3 research/h6_discover.py

Samples the first 20 successful transactions of a pool every 4 hours, 2024-10-01 → 2025-06-30, and records the fee payer
(signer) of each swap that changed the pool's token and quote balances. Pool per token-month: H5's monthly pool map,
or the H3a pool for listing-event tokens. Output: data/h6.sqlite3 (table `sightings`). Never requests data >= 2025-07-01.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from listing_prices import http_json, load_env, ts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "h6.sqlite3"
START, CUTOFF = datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)
STEP = timedelta(hours=4)
TXS = 20
WORKERS = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (mint TEXT, pool TEXT, hour TEXT, signer TEXT, n INTEGER, PRIMARY KEY (mint, hour, signer));
CREATE TABLE IF NOT EXISTS sampled (mint TEXT, hour TEXT, n_txs INTEGER, PRIMARY KEY (mint, hour));
"""


def pool_for() -> dict[str, dict[str, tuple[str, str]]]:
    """mint -> {YYYY-MM: (pool, quote_mint)}"""
    out: dict[str, dict[str, tuple[str, str]]] = {}
    h5 = sqlite3.connect(ROOT / "data" / "h5_prices.sqlite3")
    for mint, month, pool, quote in h5.execute("SELECT mint, month, pool, quote_mint FROM pool_months"):
        out.setdefault(mint, {})[month] = (pool, quote)
    lp = sqlite3.connect(ROOT / "data" / "listing_prices.sqlite3")
    for mint, pool, quote in lp.execute("SELECT mint, pool, quote_mint FROM pools"):
        if mint not in out:
            out[mint] = {"*": (pool, quote)}
    return out


def sample(rpc: str, mint: str, pool: str, quote: str, hour: datetime) -> tuple[int, dict[str, int]]:
    if hour + timedelta(hours=1) > CUTOFF:
        raise ValueError("sealed holdout")
    res = http_json(rpc, {"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [pool, {
        "transactionDetails": "full", "sortOrder": "asc", "limit": TXS, "encoding": "json", "maxSupportedTransactionVersion": 0,
        "filters": {"blockTime": {"gte": ts(hour), "lt": ts(hour + timedelta(hours=1))}, "status": "succeeded"}}]})
    if "error" in res:
        if "did not produce a valid range" in str(res["error"].get("message", "")):
            return 0, {}
        raise RuntimeError(res["error"])
    signers: dict[str, int] = {}
    for tx in res["result"]["data"]:
        meta = tx["meta"]
        keys = tx["transaction"]["message"]["accountKeys"]
        payer = keys[0] if isinstance(keys[0], str) else keys[0].get("pubkey")
        moved = {e["mint"] for e in meta["preTokenBalances"] + meta["postTokenBalances"] if e.get("owner") == pool}
        if mint in moved and quote in moved:
            signers[payer] = signers.get(payer, 0) + 1
    return len(res["result"]["data"]), signers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    load_env()
    rpc = os.environ["SOLANA_RPC_URL"]
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    done = {(m, h) for m, h in db.execute("SELECT mint, hour FROM sampled")}
    jobs = []
    for mint, months in pool_for().items():
        h = START
        while h + timedelta(hours=1) <= CUTOFF:
            p = months.get(h.strftime("%Y-%m")) or months.get("*")
            if p and (mint, h.isoformat()) not in done:
                jobs.append((mint, p[0], p[1], h))
            h += STEP
    print(f"{len(jobs)} samples ≈ {len(jobs) * 10:,} credits")
    if args.plan:
        return
    n = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(sample, rpc, m, p, q, h): (m, p, h) for m, p, q, h in jobs}
        for f in as_completed(futs):
            m, p, h = futs[f]
            try:
                ntx, signers = f.result()
            except Exception as e:
                print(f"  {m[:6]} {h:%Y-%m-%d %H}: {e}")
                continue
            db.execute("INSERT OR REPLACE INTO sampled VALUES (?,?,?)", (m, h.isoformat(), ntx))
            db.executemany("INSERT OR REPLACE INTO sightings VALUES (?,?,?,?,?)", [(m, p, h.isoformat(), s, c) for s, c in signers.items()])
            n += 1
            if n % 1000 == 0:
                db.commit()
                print(f"  {n}/{len(jobs)}", flush=True)
    db.commit()
    print(f"done {n}/{len(jobs)}")


if __name__ == "__main__":
    main()
