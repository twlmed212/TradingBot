"""Build the H3 listing-event list: which exchange listings were genuine Solana-native tokens, with exact times.

    python3 research/listing_events.py            # fetch missing bodies, rebuild events, print a summary
    python3 research/listing_events.py --offline  # rebuild from cached bodies only

Input: data/announcements.sqlite3 (research/announcements.py). Bodies are cached in the same file, table
`announcement_bodies`, so each announcement is fetched once. Run from a home connection: Upbit blocks cloud IPs.

A listing counts only on first-party evidence, never on ticker alone (tickers collide with wrapped tokens and
tokenized stocks):
- **address**: the announcement prints a contract address that Helius confirms is an SPL / Token-2022 mint
  (Upbit notices always do).
- **text**: a Binance announcement's own description says the token is on Solana, and the ticker and project name
  match a Jupiter-verified Solana token.
- **corroborated**: a futures-only announcement whose ticker has an address- or text-confirmed Solana mint from
  another first-party announcement.

Stablecoin tickers (USD...) are skipped.

Output: table `listing_events` in data/announcements.sqlite3 and research/data/listing_events.csv.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "announcements.sqlite3"
CSV_OUT = ROOT / "research" / "data" / "listing_events.csv"
SINCE = "2021-01-01"
EVENT_TYPES = ("binance_spot_listing", "binance_futures_listing", "upbit_new_listing", "upbit_market_added")
TOKEN_PROGRAMS = {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}
NOT_LISTINGS = re.compile(r"Equity|TradFi|bStocks|Tokenized|Stock", re.I)
BASE58 = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcement_bodies (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    text TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS listing_events (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ticker TEXT NOT NULL,
    mint TEXT NOT NULL,
    token_name TEXT,
    announced_at TEXT NOT NULL,
    trading_start_at TEXT,
    evidence TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    PRIMARY KEY (source, source_id, ticker)
);
"""


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_json(url: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "deskbot-research/1", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# --- bodies ------------------------------------------------------------------

def _binance_text(body: str) -> str:
    def walk(node, out):
        if isinstance(node, dict):
            if node.get("node") == "text" and "text" in node:
                out.append(node["text"])
            for v in node.values():
                walk(v, out)
        elif isinstance(node, list):
            for v in node:
                walk(v, out)
        return out
    try:
        text = " ".join(walk(json.loads(body), []))
    except (json.JSONDecodeError, TypeError):
        text = re.sub(r"<[^>]+>", " ", body or "")
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " "))


def fetch_body(source: str, source_id: str) -> tuple[str, str]:
    if source == "binance":
        d = get_json(f"https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={source_id}")
        raw = (d.get("data") or {}).get("body") or ""
        return _binance_text(raw), hashlib.sha256(raw.encode()).hexdigest()
    d = get_json(f"https://api-manager.upbit.com/api/v1/announcements/{source_id}")
    raw = (d.get("data") or {}).get("body") or ""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))
    return text, hashlib.sha256(raw.encode()).hexdigest()


def ensure_bodies(db: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    have = {(r[0], r[1]) for r in db.execute("SELECT source, source_id FROM announcement_bodies")}
    todo = [r for r in rows if (r["source"], r["source_id"]) not in have]
    print(f"bodies cached: {len(rows) - len(todo)}, to fetch: {len(todo)}", flush=True)
    for i, r in enumerate(todo, 1):
        text = None
        for attempt in range(6):  # back off on rate limits instead of skipping
            try:
                text, digest = fetch_body(r["source"], r["source_id"])
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 5:
                    print(f"  skip {r['source']} {r['source_id']}: {e}", flush=True)
                    break
                time.sleep(15 * (attempt + 1))
            except Exception as e:
                print(f"  skip {r['source']} {r['source_id']}: {e}", flush=True)
                break
        if text is None:
            continue
        db.execute("INSERT OR REPLACE INTO announcement_bodies VALUES (?,?,?,?,?)",
                   (r["source"], r["source_id"], datetime.now(timezone.utc).isoformat(timespec="seconds"), text, digest))
        if i % 25 == 0:
            db.commit()
            print(f"  fetched {i}/{len(todo)}", flush=True)
        time.sleep(1.0 if r["source"] == "binance" else 0.4)
    db.commit()


# --- evidence ------------------------------------------------------------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def is_pubkey(s: str) -> bool:
    """True if `s` is base58 that decodes to exactly 32 bytes (a Solana public key)."""
    n = 0
    for ch in s:
        if ch not in _B58:
            return False
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    raw = b"\x00" * (len(s) - len(s.lstrip("1"))) + raw
    return len(raw) == 32


def verify_mints(addresses: set[str]) -> dict[str, str]:
    """Return {address: token_program} for addresses that are SPL / Token-2022 mints (checked via Helius RPC)."""
    url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    out: dict[str, str] = {}
    addrs = sorted(a for a in addresses if is_pubkey(a))
    for i in range(0, len(addrs), 100):
        chunk = addrs[i:i + 100]
        res = get_json(url, {"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                             "params": [chunk, {"encoding": "jsonParsed"}]})
        if "result" not in res:
            raise RuntimeError(f"getMultipleAccounts failed: {res.get('error')}")
        for addr, acc in zip(chunk, res["result"]["value"]):
            if acc and acc.get("owner") in TOKEN_PROGRAMS and (acc["data"].get("parsed") or {}).get("type") == "mint":
                out[addr] = acc["owner"]
    return out


_jup_cache: dict[str, list[dict]] = {}


def jupiter_search(query: str) -> list[dict]:
    """Jupiter Tokens V2 search. Rate limits are retried; a lookup that still fails raises instead of
    silently counting as 'no token' (that once dropped JUP, WIF and others from the event list)."""
    if query in _jup_cache:
        return _jup_cache[query]
    for attempt in range(6):
        try:
            res = get_json("https://api.jup.ag/tokens/v2/search?query=" + urllib.parse.quote(query))
            _jup_cache[query] = res
            time.sleep(0.6)
            return res
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def project_names(title: str) -> dict[str, str]:
    """'Binance Will List Jupiter (JUP) and Wormhole (W)' -> {'JUP': 'Jupiter', 'W': 'Wormhole'}."""
    names = {}
    prefix = re.compile(r"^(?:Binance\s+)?(?:Exchange\s+)?(?:Will\s+)?(?:List|Lists|Add|Adds|Launch)\s+|^(?:and|,)\s+", re.I)
    for chunk in re.split(r"\)\s*(?:,|and)?\s*", title):
        m = re.search(r"(.+?)\s*\(([A-Z0-9]{1,15})$", chunk.strip())
        if m:
            names[m.group(2)] = prefix.sub("", prefix.sub("", m.group(1).strip())).strip(" ,")
    return names


def upbit_names(title: str) -> dict[str, str]:
    """Korean titles only give the ticker; the project name comes from Jupiter later."""
    return {t: "" for t in re.findall(r"\(([A-Z0-9]{1,15})\)", title)}


def says_solana(text: str, ticker: str) -> bool:
    """Per-token network evidence in a Binance announcement (never another token's line in the same post):
    a '<TICKER> Smart Contract : ...' line whose first network is Solana, or, without such a line,
    this token's own 'What Is ... (<TICKER>)' paragraph mentioning Solana."""
    t = re.escape(ticker)
    line = re.search(rf"\b{t} Smart Contracts? ?: ?(.+?)(?=\s+[0-9]*[A-Z][A-Z0-9]* Smart Contract|\s+Note|$)", text)
    if line:
        return line.group(1).strip().lower().startswith("solana")
    desc = re.search(rf"What Is [^()]*\({t}\)(.*?)(?=What Is |Reminder|$)", text)
    return bool(desc and re.search(r"\bSolana\b", desc.group(1)))


def trading_start(source: str, text: str, published: datetime) -> str | None:
    if source == "binance":
        m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) \(UTC\)", text)
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:00+00:00").isoformat() if m else None
    seg = text.split("거래지원 개시 시점", 1)[-1][:600]
    m = re.search(r"(\d{1,2})월 (\d{1,2})일 (\d{1,2})시(?:\s*(\d{1,2})분)?", seg)
    if not m:
        return None
    month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
    year = published.year + (1 if month < published.month - 6 else 0)
    try:
        return datetime(year, month, day, hour, minute, tzinfo=KST).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def build(db: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    bodies = {(r[0], r[1]): r[2] for r in db.execute("SELECT source, source_id, text FROM announcement_bodies")}
    # 1) every base58 string in every body, verified on-chain in one pass
    addr_by_row = {}
    for r in rows:
        text = bodies.get((r["source"], r["source_id"]), "")
        addr_by_row[(r["source"], r["source_id"])] = set(BASE58.findall(text))
    mints = verify_mints(set().union(*addr_by_row.values())) if addr_by_row else {}
    print(f"verified on-chain mints found in announcement text: {len(mints)}")

    events, confirmed = [], {}  # confirmed: ticker -> (mint, name)
    deferred = []
    for r in rows:
        key = (r["source"], r["source_id"])
        text = bodies.get(key)
        if text is None or NOT_LISTINGS.search(r["title"]):
            continue
        published = datetime.fromisoformat(r["published_at"])
        tickers = json.loads(r["tickers"])
        names = project_names(r["title"]) if r["source"] == "binance" else upbit_names(r["title"])
        start = trading_start(r["source"], text, published)
        row_mints = [a for a in addr_by_row[key] if a in mints]
        for ticker in tickers:
            if re.match(r"^USD|USD$", ticker):
                continue  # stablecoins cannot drift; not listing-drift events
            mint, name, evidence = None, names.get(ticker, ""), None
            # address evidence: a verified mint whose Jupiter symbol is this ticker
            for a in row_mints:
                hit = next((t for t in jupiter_search(a) if t.get("id") == a), None)
                if hit and norm(hit.get("symbol", "")) == norm(ticker):
                    mint, name, evidence = a, hit.get("name", name), "address"
                    break
            if not mint and len(tickers) == 1 and len(row_mints) == 1:
                mint, evidence = row_mints[0], "address"
            # text evidence (Binance spot): this token's own network line or description says Solana
            if not mint and r["source"] == "binance" and r["event_type"] == "binance_spot_listing" and says_solana(text, ticker):
                cands = [t for t in jupiter_search(ticker) if t.get("isVerified") and norm(t.get("symbol", "")) == norm(ticker)]
                if name:
                    cands = [t for t in cands if norm(name) in norm(t.get("name", "")) or norm(t.get("name", "")) in norm(name)]
                if cands:
                    best = max(cands, key=lambda t: t.get("liquidity") or 0)
                    mint, name, evidence = best["id"], best.get("name", name), "text"
            if mint and re.search(r"staked|wrapped", name or "", re.I):
                continue  # liquid-staking / wrapped tokens track their underlying; not listing-drift events
            if mint:
                confirmed.setdefault(ticker, (mint, name))
                events.append(dict(source=r["source"], source_id=r["source_id"], event_type=r["event_type"], ticker=ticker,
                                   mint=mint, token_name=name, announced_at=r["published_at"], trading_start_at=start,
                                   evidence=evidence, title=r["title"], url=r["url"]))
            elif r["event_type"] == "binance_futures_listing":
                deferred.append((r, ticker, start))
    # corroborated futures listings
    for r, ticker, start in deferred:
        if ticker in confirmed:
            mint, name = confirmed[ticker]
            events.append(dict(source=r["source"], source_id=r["source_id"], event_type=r["event_type"], ticker=ticker,
                               mint=mint, token_name=name, announced_at=r["published_at"], trading_start_at=start,
                               evidence="corroborated", title=r["title"], url=r["url"]))
    events.sort(key=lambda e: e["announced_at"])
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use cached bodies only")
    args = ap.parse_args()
    load_env()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    rows = db.execute(f"SELECT * FROM announcements WHERE event_type IN ({','.join('?' * len(EVENT_TYPES))}) "
                      "AND published_at >= ? AND source_id NOT LIKE 'mkt:%' ORDER BY published_at",
                      (*EVENT_TYPES, SINCE)).fetchall()
    if not args.offline:
        # Futures announcements carry no network or address; fetch them only for tickers that spot/Upbit
        # announcements already confirmed as Solana tokens.
        primary = [r for r in rows if r["event_type"] != "binance_futures_listing"]
        ensure_bodies(db, primary)
        confirmed = {e["ticker"] for e in build(db, primary)}
        futures = [r for r in rows if r["event_type"] == "binance_futures_listing" and set(json.loads(r["tickers"])) & confirmed]
        ensure_bodies(db, futures)
    events = build(db, rows)
    db.execute("DELETE FROM listing_events")
    db.executemany("INSERT OR REPLACE INTO listing_events VALUES (:source,:source_id,:event_type,:ticker,:mint,:token_name,"
                   ":announced_at,:trading_start_at,:evidence,:title,:url)", events)
    db.commit()
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0].keys()) if events else ["ticker"])
        w.writeheader()
        w.writerows(events)
    print(f"\n{len(events)} Solana listing events ({len({e['mint'] for e in events})} distinct tokens) -> {CSV_OUT.relative_to(ROOT)}")
    by = {}
    for e in events:
        by.setdefault((e["source"], e["event_type"], e["evidence"]), 0)
        by[(e["source"], e["event_type"], e["evidence"])] += 1
    for k, v in sorted(by.items()):
        print(f"  {k[0]:8} {k[1]:24} {k[2]:12} {v}")


if __name__ == "__main__":
    main()
