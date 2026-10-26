"""H6 step 2: fetch candidate wallets' histories and parse their trades in our token universe.

    python3 research/h6_wallets.py

Candidates: wallets in data/h6.sqlite3 `sightings` with >= 3 tokens and >= 10 sampled swaps. Bots (> 6,000 transactions
2024-10-01 → 2025-06-30, counted from signatures) are skipped. Trades: in each transaction signed by the wallet, the
wallet's net change of exactly one universe token against an opposite SOL (lamports + wSOL, fee added back) or USDC
change. USDC is converted to SOL with Binance SOLUSDT hourly opens. Resumable. Never requests data >= 2025-07-01.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from listing_prices import http_json, load_env, ts  # noqa: E402
from h6_discover import DB, START, CUTOFF, pool_for  # noqa: E402

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BOT_TXS = 6000
WORKERS = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (wallet TEXT PRIMARY KEY, n_sigs INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS trades (wallet TEXT, sig TEXT, t INTEGER, mint TEXT, side TEXT, token_amt REAL, quote TEXT, quote_amt REAL,
                                   PRIMARY KEY (sig, mint));
"""


def rpc(method, params):
    res = http_json(os.environ["SOLANA_RPC_URL"], {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in res:
        raise RuntimeError(res["error"])
    return res["result"]


def window_filter():
    return {"blockTime": {"gte": ts(START), "lt": ts(CUTOFF)}, "status": "succeeded"}


def count_sigs(wallet: str) -> int:
    n, token = 0, None
    while True:
        p = {"transactionDetails": "signatures", "sortOrder": "asc", "limit": 1000, "filters": window_filter()}
        if token:
            p["paginationToken"] = token
        r = rpc("getTransactionsForAddress", [wallet, p])
        n += len(r["data"])
        token = r.get("paginationToken")
        if not token or not r["data"] or n > BOT_TXS:
            return n


def parse(wallet: str, tx: dict, universe: set[str]) -> list[tuple]:
    meta, msg = tx["meta"], tx["transaction"]["message"]
    keys = [k if isinstance(k, str) else k.get("pubkey") for k in msg["accountKeys"]]
    if keys[0] != wallet:
        return []
    delta: dict[str, float] = {}
    for side, entries in ((-1, meta["preTokenBalances"]), (1, meta["postTokenBalances"])):
        for e in entries:
            if e.get("owner") == wallet:
                delta[e["mint"]] = delta.get(e["mint"], 0.0) + side * float(e["uiTokenAmount"]["uiAmount"] or 0)
    sol = (meta["postBalances"][0] - meta["preBalances"][0] + meta["fee"]) / 1e9 + delta.pop(WSOL, 0.0)
    usdc = delta.pop(USDC, 0.0)
    moved = {m: d for m, d in delta.items() if abs(d) > 0}
    if len(moved) != 1:
        return []
    mint, d = next(iter(moved.items()))
    if mint not in universe:
        return []
    quote, q = ("USDC", usdc) if abs(usdc) > 0 else ("SOL", sol)
    if not q or (d > 0) == (q > 0):
        return []
    sig = tx["transaction"]["signatures"][0]
    return [(wallet, sig, tx["blockTime"], mint, "buy" if d > 0 else "sell", abs(d), quote, abs(q))]


def fetch_trades(wallet: str, universe: set[str]) -> list[tuple]:
    out, token = [], None
    while True:
        p = {"transactionDetails": "full", "sortOrder": "asc", "limit": 100, "encoding": "json",
             "maxSupportedTransactionVersion": 0, "filters": window_filter()}
        if token:
            p["paginationToken"] = token
        r = rpc("getTransactionsForAddress", [wallet, p])
        for tx in r["data"]:
            if tx.get("blockTime") and tx["blockTime"] < ts(CUTOFF):
                out += parse(wallet, tx, universe)
        token = r.get("paginationToken")
        if not token or not r["data"]:
            return out


def work(wallet: str, universe: set[str]) -> tuple[str, int, str, list]:
    n = count_sigs(wallet)
    if n > BOT_TXS:
        return wallet, n, "bot", []
    return wallet, n, "ok", fetch_trades(wallet, universe)


def main() -> None:
    load_env()
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    universe = set(pool_for())
    cands = [w for (w,) in db.execute(
        "SELECT signer FROM sightings GROUP BY signer HAVING COUNT(DISTINCT mint) >= 3 AND SUM(n) >= 10")]
    done = {w for (w,) in db.execute("SELECT wallet FROM wallets")}
    todo = [w for w in cands if w not in done]
    print(f"{len(cands)} candidates, {len(todo)} to fetch", flush=True)
    n = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(work, w, universe): w for w in todo}
        for f in as_completed(futs):
            try:
                w, cnt, status, trades = f.result()
            except Exception as e:
                print(f"  {futs[f][:8]}: {e}")
                continue
            db.execute("INSERT OR REPLACE INTO wallets VALUES (?,?,?)", (w, cnt, status))
            db.executemany("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?)", trades)
            n += 1
            if n % 50 == 0:
                db.commit()
                print(f"  {n}/{len(todo)}", flush=True)
    db.commit()
    print("done", db.execute("SELECT status, COUNT(*) FROM wallets GROUP BY 1").fetchall(),
          "trades:", db.execute("SELECT COUNT(*) FROM trades").fetchone()[0])


if __name__ == "__main__":
    main()
