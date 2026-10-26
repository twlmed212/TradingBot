"""H4 data readiness: which tokens have unlock schedules that are provable on-chain at the time? Metadata only.

    python3 research/unlock_onchain.py            # scan, store contracts, print the coverage report
    python3 research/unlock_onchain.py --report   # report from stored contracts only

Reads vesting contracts of two Solana lockers through Helius `getProgramAccounts`, filtered by token mint:
- Streamflow (strmRqUCoQUgGUan5YhzUZa6KqdzwX5L6FpUxfmKg5m): mint at byte 177; `created_at` is stored in the account.
- Jupiter Lock (LocpQgucEQHbqNABEYvBvwoxCPsSbG91A1QaQhQQqjn): mint at byte 40; creation time is taken from the
  account's first transaction (Helius `getTransactionsForAddress`, ascending), only for large contracts.

A schedule written into a contract is public from the contract's creation onward, so "known at time t" is provable
for t >= creation. Limitations reported, not hidden: custodial or multisig vesting is invisible here; contracts that
were closed after vesting are not returned by getProgramAccounts (survivorship); supply shares use today's total
supply because historical circulating supply is not available from this source.

No prices, no returns, no keys printed. Output: data/unlock_onchain.sqlite3 and
reports/h4-onchain-coverage-2026-10-25.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "unlock_onchain.sqlite3"
REPORT = ROOT / "reports" / "h4-onchain-coverage-2026-10-25.md"
STREAMFLOW = "strmRqUCoQUgGUan5YhzUZa6KqdzwX5L6FpUxfmKg5m"
JUP_LOCK = "LocpQgucEQHbqNABEYvBvwoxCPsSbG91A1QaQhQQqjn"
RESEARCH_START = datetime(2023, 6, 1, tzinfo=timezone.utc)
HOLDOUT_CUTOFF = datetime(2025, 7, 1, tzinfo=timezone.utc)
LARGE_SHARE = 0.001        # contracts holding >= 0.1% of total supply get a creation-time lookup and count as "large"
UNLOCK_SHARE = 0.02        # PLAN.md H4 idea: >= 2% of supply within 14 days
WINDOW = timedelta(days=14)
# H2's Binance-listed Solana universe (tickers resolved to mints through Jupiter-verified search)
H2_TICKERS = ["RAY", "GMT", "FIDA", "BONK", "JTO", "JUP", "PYTH", "WIF", "BOME", "W", "TNSR", "IO", "RENDER", "PNUT",
              "ACT", "ORCA", "ME", "PENGU", "TRUMP", "LAYER", "KMNO"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (mint TEXT PRIMARY KEY, symbol TEXT, decimals INTEGER, supply_raw TEXT, observed_at TEXT);
CREATE TABLE IF NOT EXISTS contracts (
    program TEXT NOT NULL, address TEXT NOT NULL, mint TEXT NOT NULL,
    created_at INTEGER, created_source TEXT,
    start_time INTEGER, cliff_time INTEGER, cliff_amount REAL, period_s INTEGER, amount_per_period REAL,
    periods INTEGER, total_amount REAL, end_time INTEGER, withdrawn REAL, canceled_at INTEGER,
    observed_at TEXT NOT NULL, raw_b64 TEXT NOT NULL,
    PRIMARY KEY (program, address)
);
"""


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def http_json(url: str, data: dict | None = None):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                         headers={"User-Agent": "deskbot-research/1", "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def rpc(method: str, params: list):
    res = http_json(os.environ["SOLANA_RPC_URL"], {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in res:
        raise RuntimeError(f"{method}: {res['error']}")
    return res["result"]


def universe() -> dict[str, str]:
    """mint -> symbol: recorder universe + all listing-event tokens + H2's tickers."""
    out = {t["mint"]: t["symbol"] for t in json.loads((ROOT / "recorder" / "universe.json").read_text())["tokens"]}
    ev = sqlite3.connect(ROOT / "data" / "announcements.sqlite3")
    for mint, ticker in ev.execute("SELECT DISTINCT mint, ticker FROM listing_events"):
        out.setdefault(mint, ticker)
    have = {s.upper() for s in out.values()}
    for t in H2_TICKERS:
        if t in have:
            continue
        res = http_json("https://api.jup.ag/tokens/v2/search?query=" + urllib.parse.quote(t))
        cands = [x for x in res if x.get("isVerified") and x.get("symbol", "").upper().lstrip("$") == t]
        if cands:
            best = max(cands, key=lambda x: x.get("liquidity") or 0)
            out[best["id"]] = t
        time.sleep(0.8)
    return out


# --- decoders ---------------------------------------------------------------------

def decode_streamflow(d: bytes, scale: float) -> dict:
    u = lambda o: struct.unpack_from("<Q", d, o)[0]  # noqa: E731
    start, deposited, period, per, cliff, cliff_amt = (u(409), u(417), u(425), u(433), u(441), u(449))
    periods = int(max(deposited - cliff_amt, 0) // per) if per else 0
    return {"created_at": u(9), "created_source": "account.created_at", "withdrawn": u(17) / scale,
            "canceled_at": u(25) or None, "end_time": u(33), "start_time": start, "cliff_time": cliff or start,
            "cliff_amount": cliff_amt / scale, "period_s": period, "amount_per_period": per / scale,
            "periods": periods, "total_amount": deposited / scale}


def decode_jup_lock(d: bytes, scale: float) -> dict:
    cliff, freq, cliff_amt, per, n, claimed, start, cancelled = struct.unpack_from("<8Q", d, 8 + 32 * 4 + 8)
    total = cliff_amt + per * n
    return {"created_at": None, "created_source": None, "withdrawn": claimed / scale, "canceled_at": cancelled or None,
            "end_time": cliff + freq * n, "start_time": start, "cliff_time": cliff, "cliff_amount": cliff_amt / scale,
            "period_s": freq, "amount_per_period": per / scale, "periods": n, "total_amount": total / scale}


def first_tx_time(address: str) -> int | None:
    res = rpc("getTransactionsForAddress", [address, {"transactionDetails": "signatures", "sortOrder": "asc", "limit": 1}])
    data = res.get("data") or []
    return data[0].get("blockTime") if data else None


# --- unlock schedule ----------------------------------------------------------------

def releases(c: dict) -> list[tuple[int, float]]:
    """(unix time, amount) releases implied by the schedule, bucketed per UTC day for fast streams.
    Cancelled contracts stop releasing at cancellation."""
    out: list[tuple[int, float]] = []
    stop = c["canceled_at"] or 1 << 62
    if c["cliff_amount"] and c["cliff_time"] < stop:
        out.append((c["cliff_time"], c["cliff_amount"]))
    per, period, n = c["amount_per_period"], c["period_s"], c["periods"] or 0
    if not (per and period and n):
        return out
    first = max(c["cliff_time"], c["start_time"])
    last = min(first + n * period, stop)
    if period >= 86_400:
        t = first + period
        while t <= last:
            out.append((t, per))
            t += period
    else:  # many releases per day: sum each UTC day's releases
        day = first - first % 86_400
        while day < last:
            lo, hi = max(day, first), min(day + 86_400, last)
            count = (hi - first) // period - (lo - first) // period
            if count > 0:
                out.append((day, count * per))
            day += 86_400
    return out


def big_unlock_windows(contracts: list[dict], supply: float) -> list[tuple[datetime, float, bool]]:
    """Daily aggregation; for each day, unlocked share over the next 14 days. Returns window starts where the share
    is >= UNLOCK_SHARE, with whether every contributing contract existed (was created) before that day."""
    daily: dict[datetime, float] = defaultdict(float)
    created_by_day: dict[datetime, list[int | None]] = defaultdict(list)
    for c in contracts:
        for t, amt in releases(c):
            day = datetime.fromtimestamp(t, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            daily[day] += amt
            created_by_day[day].append(c["created_at"])
    if not daily or not supply:
        return []
    days = sorted(daily)
    out, d = [], days[0] - WINDOW
    last = days[-1]
    while d <= last:
        window_days = [x for x in days if d <= x < d + WINDOW]
        share = sum(daily[x] for x in window_days) / supply
        if share >= UNLOCK_SHARE:
            provable = all(ca is not None and ca <= d.timestamp() for x in window_days for ca in created_by_day[x])
            out.append((d, share, provable))
            d += WINDOW  # count non-overlapping windows
        else:
            d += timedelta(days=1)
    return out


# --- driver ---------------------------------------------------------------------

def scan(db: sqlite3.Connection) -> None:
    mints = universe()
    print(f"universe: {len(mints)} tokens")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for mint, sym in sorted(mints.items(), key=lambda kv: kv[1]):
        sup = rpc("getTokenSupply", [mint])["value"]
        dec, supply_raw = sup["decimals"], sup["amount"]
        db.execute("INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?)", (mint, sym, dec, supply_raw, now))
        scale = 10 ** dec
        supply = int(supply_raw) / scale
        counts = {}
        for program, offset, decode in ((STREAMFLOW, 177, decode_streamflow), (JUP_LOCK, 40, decode_jup_lock)):
            accs = rpc("getProgramAccounts", [program, {"encoding": "base64", "filters": [{"memcmp": {"offset": offset, "bytes": mint}}]}])
            counts[program] = len(accs)
            for a in accs:
                raw = base64.b64decode(a["account"]["data"][0])
                try:
                    c = decode(raw, scale)
                except struct.error:
                    continue
                if program == JUP_LOCK and supply and c["total_amount"] / supply >= LARGE_SHARE:
                    c["created_at"], c["created_source"] = first_tx_time(a["pubkey"]), "first transaction"
                    time.sleep(0.1)
                db.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (program, a["pubkey"], mint, c["created_at"], c["created_source"], c["start_time"], c["cliff_time"],
                            c["cliff_amount"], c["period_s"], c["amount_per_period"], c["periods"], c["total_amount"],
                            c["end_time"], c["withdrawn"], c["canceled_at"], now, a["account"]["data"][0]))
            time.sleep(0.3)
        db.commit()
        print(f"  {sym:9} streamflow {counts[STREAMFLOW]:5}  jupiter-lock {counts[JUP_LOCK]:5}", flush=True)


def fmt_day(ts: int | None) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else "—"


def report(db: sqlite3.Connection) -> str:
    db.row_factory = sqlite3.Row
    toks = {r["mint"]: r for r in db.execute("SELECT * FROM tokens")}
    by_mint: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute("SELECT * FROM contracts"):
        by_mint[r["mint"]].append(dict(r))
    rows, usable = [], []
    for mint, t in sorted(toks.items(), key=lambda kv: kv[1]["symbol"]):
        supply = int(t["supply_raw"]) / 10 ** t["decimals"]
        cs = by_mint.get(mint, [])
        large = [c for c in cs if supply and c["total_amount"] / supply >= LARGE_SHARE]
        locked_share = sum(c["total_amount"] for c in cs) / supply if supply else 0
        wins = big_unlock_windows(large, supply)
        research = [w for w in wins if RESEARCH_START <= w[0] < HOLDOUT_CUTOFF]
        provable = [w for w in research if w[2]]
        first_large = min((c["created_at"] for c in large if c["created_at"]), default=None)
        rows.append((t["symbol"], len(cs), len(large), locked_share, first_large, len(wins), len(research), len(provable)))
        if provable:
            usable.append((t["symbol"], provable))

    lines = [
        "# H4 on-chain unlock coverage (data readiness, metadata only)",
        "",
        f"Generated by `research/unlock_onchain.py` on {datetime.now(timezone.utc):%d %B %Y %H:%M} UTC. No prices or returns were fetched or computed. "
        "H4 is still unregistered and has not used a hypothesis trial.",
        "",
        "## Method",
        "",
        "- Lockers scanned: **Streamflow** and **Jupiter Lock**, via Helius `getProgramAccounts` filtered by mint. Field offsets were validated on KMNO "
        "(100M KMNO over 2 years hourly = 5,708 per hour, as decoded) and JTO.",
        "- A schedule written into a contract is public from the contract's creation, so unlocks are \"known at time t\" only if the contract existed before t. "
        "Streamflow stores `created_at`; for Jupiter Lock the first transaction time is used (looked up for large contracts only).",
        f"- Large contract: ≥ {LARGE_SHARE:.1%} of today's total supply. Big-unlock window: releases from large contracts totalling ≥ {UNLOCK_SHARE:.0%} "
        "of today's total supply within 14 days (non-overlapping windows). Research window: 1 Jun 2023 – 30 Jun 2025. *Provable* = every contributing contract existed before the window started.",
        "",
        "## Coverage by token",
        "",
        "| Token | Contracts | Large | Locked share of supply | First large contract | Big-unlock windows (all) | In research window | Provable in research window |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sym, n, nl, share, first, w_all, w_res, w_prov in rows:
        lines.append(f"| {sym} | {n:,} | {nl} | {share:.1%} | {fmt_day(first)} | {w_all} | {w_res} | {w_prov} |")
    total_prov = sum(len(p) for _, p in usable)
    lines += [
        "",
        "## What this means for H4",
        "",
        f"- Tokens with at least one provable big-unlock window in the research window: **{len(usable)}** "
        f"({', '.join(s for s, _ in usable) or 'none'}), {total_prov} windows in total.",
        "- Tokens with no large on-chain contracts are not 'no unlock' tokens: their team/investor vesting is likely held by custodians or multisigs, which this scan cannot see. "
        "They must be treated as *unknown*, never as zero unlocks.",
        "- Survivorship: contracts closed after vesting are not returned by `getProgramAccounts`, so older unlocks can be missing. Supply shares use today's total supply, "
        "not historical circulating supply, which understates shares for tokens whose supply grew and overstates them where supply was burned.",
        "",
        "## Decision input",
        "",
        "A historical H4 test is only meaningful if the provable sample above is broad enough (the registration must set a minimum, e.g. several tokens and tens of windows). "
        "If it is not, the honest options are forward-only collection (archive schedules as they are published and evaluate later) or a paid unlock feed that can prove "
        "publication dates. Either way, unknown coverage stays unknown.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="only rebuild the report from stored contracts")
    args = ap.parse_args()
    load_env()
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    if not args.report:
        scan(db)
    text = report(db)
    REPORT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
