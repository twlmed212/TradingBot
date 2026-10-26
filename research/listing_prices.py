"""Rebuild hourly on-chain prices around each H3 listing event from Solana DEX swaps (Helius).

    python3 research/listing_prices.py              # fetch missing hours for research-window events
    python3 research/listing_prices.py --plan       # show events, pools and credit estimate; fetch nothing

For each event's token it picks one DEX pool (GeckoTerminal candidates: the SOL- or USDC-quoted pool that existed at the
window start and had the most swaps in the announcement hour), then samples the first 50 successful transactions of each UTC hour with Helius `getTransactionsForAddress`
(10 credits per call). From each swap it takes the pool's own balance changes (the account owner that holds both
the token and the quote mint, preferring the pool address), so price = |Δquote| / |Δtoken|. The hourly value is the
median of those swap prices. USDC prices are converted to SOL with Binance SOLUSDT hourly closes.

Window: 7 days before the announcement to 21 days after. Events announced on or after the holdout cutoff
(2025-07-01) are not fetched; they stay sealed for G2.

Output: data/listing_prices.sqlite3 (tables `pools`, `hourly`, `sol_usd`).
"""

from __future__ import annotations

import argparse
import calendar
import gzip
import json
import os
import sqlite3
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_DB = ROOT / "data" / "announcements.sqlite3"
OUT_DB = ROOT / "data" / "listing_prices.sqlite3"
HOLDOUT_CUTOFF = datetime(2025, 7, 1, tzinfo=timezone.utc)
BEFORE, AFTER = timedelta(days=7), timedelta(days=21)
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
QUOTES = {WSOL: "SOL", USDC: "USDC"}
WORKERS = 6
TXS_PER_HOUR = 50  # first 50 successful transactions of each UTC hour (bandwidth: ~0.3 MB/hour gzipped vs 1.2 MB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pools (
    mint TEXT PRIMARY KEY, pool TEXT NOT NULL, dex TEXT, quote_mint TEXT NOT NULL, pool_created_at TEXT,
    reserve_usd_today REAL, chosen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hourly (
    mint TEXT NOT NULL, pool TEXT NOT NULL, hour TEXT NOT NULL,
    n_txs INTEGER NOT NULL, n_swaps INTEGER NOT NULL,
    price_quote REAL, p25 REAL, p75 REAL, quote_volume_sample REAL,
    PRIMARY KEY (mint, pool, hour)
);
CREATE TABLE IF NOT EXISTS sol_usd (hour TEXT PRIMARY KEY, close REAL NOT NULL);
"""


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def http_json(url: str, data: dict | None = None, retries: int = 5):
    for k in range(retries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                         headers={"User-Agent": "deskbot-research/1", "content-type": "application/json",
                                                  "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and k < retries - 1:
                time.sleep((20 if e.code == 429 else 2) * (k + 1))  # GeckoTerminal's window is a minute
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if k < retries - 1:
                time.sleep(2 * (k + 1))
                continue
            raise


def ts(dt: datetime) -> int:
    return calendar.timegm(dt.utctimetuple())


def hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


# --- inputs -----------------------------------------------------------------------

def research_events() -> list[dict]:
    db = sqlite3.connect(EVENTS_DB)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM listing_events WHERE announced_at < ? ORDER BY announced_at", (HOLDOUT_CUTOFF.isoformat(),))]
    return [r for r in rows if datetime.fromisoformat(r["announced_at"]) < HOLDOUT_CUTOFF]


def choose_pool(mint: str, window_start: datetime, anchor_hour: datetime | None = None, rpc: str | None = None) -> dict | None:
    """Among SOL/USDC-quoted pools that existed at the window start (GeckoTerminal's top pools), the one with the most
    swaps in the anchor hour (the announcement hour), so the pool is the one actually trading at the time.
    Falls back to the largest by today's reserve, then to the earliest-created pool."""
    pools = http_json(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/pools?page=1")["data"]
    time.sleep(2.1)  # GeckoTerminal public limit is about 30 calls/min
    cands = []
    for p in pools:
        a, rel = p["attributes"], p["relationships"]
        base = rel["base_token"]["data"]["id"].split("_", 1)[1]
        quote = rel["quote_token"]["data"]["id"].split("_", 1)[1]
        if base != mint or quote not in QUOTES:
            continue
        created = datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")) if a.get("pool_created_at") else None
        cands.append({"pool": a["address"], "dex": rel["dex"]["data"]["id"], "quote_mint": quote,
                      "created": created, "reserve": float(a.get("reserve_in_usd") or 0)})
    if not cands:
        return None
    existing = [c for c in cands if c["created"] and c["created"] <= window_start]
    if not existing:
        return min(cands, key=lambda c: c["created"] or datetime.max.replace(tzinfo=timezone.utc))
    if anchor_hour is not None and rpc:
        for c in sorted(existing, key=lambda c: -c["reserve"])[:6]:
            try:
                c["anchor_swaps"] = sample_hour(rpc, c["pool"], mint, c["quote_mint"], anchor_hour)["n_swaps"]
            except Exception:
                c["anchor_swaps"] = -1
        return max(existing, key=lambda c: (c.get("anchor_swaps", -1), c["reserve"]))
    return max(existing, key=lambda c: c["reserve"])


# --- one hour of swaps --------------------------------------------------------------

def sample_hour(rpc: str, pool: str, mint: str, quote: str, hour: datetime) -> dict:
    if hour >= HOLDOUT_CUTOFF or hour + timedelta(hours=1) > HOLDOUT_CUTOFF:
        raise ValueError("Refusing to fetch sealed holdout prices")
    res = http_json(rpc, {"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [pool, {
        "transactionDetails": "full", "sortOrder": "asc", "limit": TXS_PER_HOUR, "encoding": "json",
        "maxSupportedTransactionVersion": 0,
        "filters": {"blockTime": {"gte": ts(hour), "lt": ts(hour + timedelta(hours=1))}, "status": "succeeded"}}]})
    if "error" in res:
        if "did not produce a valid range" in str(res["error"].get("message", "")):
            # no blocks in this hour (e.g. the Solana mainnet outage of 6 Feb 2024): record it as an empty hour
            return {"n_txs": 0, "n_swaps": 0, "price_quote": None, "p25": None, "p75": None, "quote_volume_sample": 0.0}
        raise RuntimeError(res["error"])
    txs = res["result"]["data"]
    prices, volume = [], 0.0
    for tx in txs:
        meta = tx["meta"]
        owners: dict[str, dict[str, float]] = {}
        for side, entries in (("pre", meta["preTokenBalances"]), ("post", meta["postTokenBalances"])):
            for e in entries:
                if e["mint"] in (mint, quote) and e.get("owner"):
                    amt = float(e["uiTokenAmount"]["uiAmount"] or 0)
                    key = (e["owner"], e["mint"])
                    owners.setdefault(key, {"pre": 0.0, "post": 0.0})[side] += amt
        holders = {o for (o, m) in owners if m == mint} & {o for (o, m) in owners if m == quote}
        if not holders:
            continue
        vault_owner = pool if pool in holders else max(holders, key=lambda o: owners[(o, mint)]["post"])
        dx = owners[(vault_owner, mint)]["post"] - owners[(vault_owner, mint)]["pre"]
        dq = owners[(vault_owner, quote)]["post"] - owners[(vault_owner, quote)]["pre"]
        if dx and dq and (dx > 0) != (dq > 0):
            prices.append(abs(dq) / abs(dx))
            volume += abs(dq)
    out = {"n_txs": len(txs), "n_swaps": len(prices), "price_quote": None, "p25": None, "p75": None, "quote_volume_sample": volume}
    if prices:
        out["price_quote"] = statistics.median(prices)
        if len(prices) >= 4:
            q = statistics.quantiles(prices, n=4)
            out["p25"], out["p75"] = q[0], q[2]
    return out


def sol_usd_hours(db: sqlite3.Connection, start: datetime, end: datetime) -> None:
    end = min(end, HOLDOUT_CUTOFF)
    if start >= end:
        return
    have = {r[0] for r in db.execute("SELECT hour FROM sol_usd WHERE hour >= ? AND hour < ?", (start.isoformat(), end.isoformat()))}
    if len(have) >= int((end - start).total_seconds() // 3600):
        return
    cur = ts(start) * 1000
    while cur < ts(end) * 1000:
        rows = http_json(f"https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1h&startTime={cur}&endTime={ts(end) * 1000 - 1}&limit=1000")
        rows = [k for k in rows if cur <= k[0] < ts(end) * 1000]
        if not rows:
            break
        db.executemany("INSERT OR REPLACE INTO sol_usd VALUES (?,?)",
                       [(datetime.fromtimestamp(k[0] / 1000, timezone.utc).isoformat(), float(k[4])) for k in rows])
        cur = rows[-1][0] + 3_600_000
        time.sleep(0.2)
    db.commit()


# --- driver -----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="show the work and credit estimate without fetching swaps")
    ap.add_argument("--repick", action="store_true", help="re-run pool selection for every token (busiest pool in the announcement hour)")
    args = ap.parse_args()
    load_env()
    rpc = os.environ["SOLANA_RPC_URL"]
    db = sqlite3.connect(OUT_DB, check_same_thread=False)
    db.executescript(SCHEMA)

    events = research_events()
    windows: dict[str, tuple[datetime, datetime, str, set[datetime]]] = {}
    anchors: dict[str, datetime] = {}
    for e in events:  # per token: the union of its events' windows (not one span bridging months between events)
        a = datetime.fromisoformat(e["announced_at"])
        s, t = hour_floor(a - BEFORE), min(hour_floor(a + AFTER), HOLDOUT_CUTOFF)
        span = {s + timedelta(hours=i) for i in range(int((t - s).total_seconds() // 3600))}
        if e["mint"] in windows:
            s0, t0, _label, hs = windows[e["mint"]]
            s, t, span = min(s, s0), max(t, t0), span | hs
        windows[e["mint"]] = (s, t, e["ticker"], span)
        anchors.setdefault(e["mint"], hour_floor(a))

    plan, total_calls = [], 0
    for mint, (start, end, ticker, span) in windows.items():
        row = db.execute("SELECT pool, dex, quote_mint, pool_created_at FROM pools WHERE mint=?", (mint,)).fetchone()
        if args.repick and row:
            c = choose_pool(mint, start, anchors[mint], rpc)
            if c and c["pool"] != row[0]:
                print(f"  {ticker}: pool {row[0][:8]}… -> {c['pool'][:8]}… ({c.get('anchor_swaps')} swaps in the announcement hour)")
                db.execute("DELETE FROM hourly WHERE mint=?", (mint,))
                db.execute("DELETE FROM pools WHERE mint=?", (mint,))
                db.commit()
                row = None
        if not row:
            c = choose_pool(mint, start, anchors[mint], rpc)
            if not c:
                print(f"  {ticker}: no SOL/USDC pool found, skipped")
                continue
            db.execute("INSERT OR REPLACE INTO pools VALUES (?,?,?,?,?,?,?)",
                       (mint, c["pool"], c["dex"], c["quote_mint"], c["created"].isoformat() if c["created"] else None,
                        c["reserve"], datetime.now(timezone.utc).isoformat(timespec="seconds")))
            db.commit()
            row = (c["pool"], c["dex"], c["quote_mint"], c["created"].isoformat() if c["created"] else None)
        pool, dex, quote, created = row
        first = max(start, hour_floor(datetime.fromisoformat(created))) if created else start
        hours = sorted(h for h in span if h >= first)
        done = {r[0] for r in db.execute("SELECT hour FROM hourly WHERE mint=? AND pool=?", (mint, pool))}
        todo = [h for h in hours if h.isoformat() not in done]
        total_calls += len(todo)
        plan.append((ticker, mint, pool, dex, QUOTES[quote], quote, first, end, todo))
        print(f"  {ticker:9} {dex:10} {QUOTES[quote]:4} pool {pool[:8]}… created {str(created)[:10]}  "
              f"{first:%Y-%m-%d} → {end:%Y-%m-%d}  {len(hours)} h, {len(todo)} to fetch")
    print(f"\n{len(plan)} tokens, {total_calls} hourly calls ≈ {total_calls * 10:,} Helius credits")
    if args.plan or not total_calls:
        return

    sol_usd_hours(db, min(p[6] for p in plan), max(p[7] for p in plan))
    jobs = [(t, m, p, q, h) for (t, m, p, _d, _ql, q, _f, _e, todo) in plan for h in todo]
    done_n = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool_exec:
        futures = {pool_exec.submit(sample_hour, rpc, p, m, q, h): (t, m, p, h) for (t, m, p, q, h) in jobs}
        for fut in as_completed(futures):
            t, m, p, h = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                print(f"  {t} {h:%Y-%m-%d %H}: {e}")
                continue
            db.execute("INSERT OR REPLACE INTO hourly VALUES (?,?,?,?,?,?,?,?,?)",
                       (m, p, h.isoformat(), r["n_txs"], r["n_swaps"], r["price_quote"], r["p25"], r["p75"], r["quote_volume_sample"]))
            done_n += 1
            if done_n % 200 == 0:
                db.commit()
                print(f"  {done_n}/{len(jobs)} hours", flush=True)
    db.commit()
    print(f"done: {done_n}/{len(jobs)} hours fetched")


if __name__ == "__main__":
    main()
