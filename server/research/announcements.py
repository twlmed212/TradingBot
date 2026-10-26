"""Exchange announcement archive for H3 (listing events). Free first-party sources only.

    python3 research/announcements.py            # backfill / refresh, then print a summary
    python3 research/announcements.py --summary  # summary only

Sources:
- Binance CMS "New Cryptocurrency Listing" catalog (id 48)
- Upbit trading notices (category "trade"); this site blocks cloud IPs, so it only works from a home connection
- Upbit's official market list (api.upbit.com), diffed run to run: a market that appears, disappears, or gets a
  warning flag becomes an event. Works from the AWS server. Event time = when we first saw it.

Each row keeps the source's own publish time, our first-seen time, the raw payload hash, and a deterministic
parse (event type + tickers). Parsing clean first-party titles is rule-based on purpose (PLAN.md: parser first);
an LLM is only considered for messy text where it measurably beats this parser.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "announcements.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    event_type TEXT NOT NULL,
    tickers TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS upbit_markets (
    market TEXT PRIMARY KEY,
    english_name TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    warning INTEGER NOT NULL DEFAULT 0,
    removed_at TEXT
);
"""


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "deskbot-research/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- deterministic parsers -------------------------------------------------

TICKER_PAREN = re.compile(r"\(([A-Z0-9]{1,15})\)")
PERP = re.compile(r"\b([A-Z0-9]{2,20})USDT?C? Perpetual")
PERP_LIST = re.compile(r"\b([0-9]*[A-Z][A-Z0-9]{1,19})USD[TC]\b")
PERP_WORDS = re.compile(r"(?:USD[ⓈT]-M(?:argined)?|USDC-Margined)\s+((?:[0-9]*[A-Z][A-Z0-9]{1,14})(?:\s*(?:,|and)\s*[0-9]*[A-Z][A-Z0-9]{1,14})*)\s+Perpetual")
MULTIPLIER = re.compile(r"^(?:1000000|10000|1000|1M)(?=[A-Z])")


def _perp_tickers(t: str) -> list[str]:
    found = PERP_LIST.findall(t)
    for group in PERP_WORDS.findall(t):
        found += re.split(r"\s*(?:,|and)\s*", group)
    cleaned = {MULTIPLIER.sub("", re.sub(r"USD[TC]$", "", x)) for x in found}
    return sorted(x for x in cleaned if x and x not in ("USD", "USDT", "USDC"))


def parse_binance(title: str) -> tuple[str, list[str]]:
    t = title
    tickers = TICKER_PAREN.findall(t)
    if "bStocks" in t or "Tokenized Securities" in t or "Cash Dividend" in t:
        return "binance_bstocks", tickers
    if "Futures Will Launch" in t or "Perpetual" in t:
        perps = _perp_tickers(t)
        return ("binance_futures_listing" if "Pre-Market" not in t else "binance_futures_premarket"), sorted(set(perps or tickers))
    if re.search(r"\bWill List\b", t):
        return "binance_spot_listing", tickers
    if "Binance Alpha" in t or "Alpha" in t.split()[:3]:
        return "binance_alpha", tickers
    if "HODLer Airdrops" in t or "Launchpool" in t or "Megadrop" in t:
        return "binance_launch_program", tickers
    if re.search(r"Will Add .* on (Earn|Margin|Convert|Buy Crypto|VIP Loan)", t):
        return "binance_product_add", tickers
    if re.search(r"Adds .+ on (Earn|Simple Earn|Convert|Margin|Futures|Buy Crypto|VIP Loan)", t):
        return "binance_product_add", tickers
    if re.search(r"Binance (Exchange )?Adds", t):
        return "binance_spot_listing" if tickers else "binance_other", tickers
    return "binance_other", tickers


def parse_upbit(title: str) -> tuple[str, list[str]]:
    tickers = TICKER_PAREN.findall(title)
    if "신규 거래지원" in title:
        return "upbit_new_listing", tickers
    if "마켓 디지털 자산 추가" in title:
        return "upbit_market_added", tickers
    if "거래지원 종료" in title:
        return "upbit_delisting", tickers
    if "유의" in title:
        return "upbit_warning", tickers
    return "upbit_other", tickers


# --- collectors ------------------------------------------------------------

def store(db, source, source_id, published_at, title, url, event_type, tickers, payload) -> bool:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    cur = db.execute(
        """INSERT OR IGNORE INTO announcements (source, source_id, published_at, first_seen_at, title, url, event_type,
               tickers, payload_sha256, payload) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (source, str(source_id), published_at, _now(), title, url, event_type, json.dumps(tickers),
         hashlib.sha256(body.encode()).hexdigest(), body),
    )
    return cur.rowcount == 1


def collect_binance(db, max_pages: int = 100, full: bool = False) -> int:
    new = 0
    for page in range(1, max_pages + 1):
        d = _get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
                 f"?type=1&catalogId=48&pageNo={page}&pageSize=50")
        catalogs = (d.get("data") or {}).get("catalogs") or []
        articles = catalogs[0]["articles"] if catalogs else []
        if not articles:
            break
        added = 0
        for a in articles:
            et, tk = parse_binance(a["title"])
            published = datetime.fromtimestamp(a["releaseDate"] / 1000, timezone.utc).isoformat(timespec="seconds")
            url = f"https://www.binance.com/en/support/announcement/{a['code']}"
            added += store(db, "binance", a["code"], published, a["title"], url, et, tk, a)
        db.commit()
        new += added
        if added == 0 and not full:
            break  # reached announcements we already have
        time.sleep(0.5)
    return new


def collect_upbit(db, max_pages: int = 200, full: bool = False) -> int:
    new = 0
    for page in range(1, max_pages + 1):
        d = _get(f"https://api-manager.upbit.com/api/v1/announcements?os=web&page={page}&per_page=20&category=trade")
        notices = d["data"]["notices"]
        if not notices:
            break
        added = 0
        for n in notices:
            et, tk = parse_upbit(n["title"])
            published = datetime.fromisoformat(n.get("first_listed_at") or n["listed_at"]).astimezone(timezone.utc).isoformat(timespec="seconds")
            url = f"https://upbit.com/service_center/notice?id={n['id']}"
            added += store(db, "upbit", n["id"], published, n["title"], url, et, tk, n)
        db.commit()
        new += added
        if added == 0 and not full:
            break  # reached notices we already have
        if page >= d["data"].get("total_pages", page):
            break
        time.sleep(0.4)
    return new


def reparse(db) -> None:
    """Parsers are deterministic, so stored rows are re-derived from their titles after any parser change."""
    rows = db.execute("SELECT source, source_id, title FROM announcements WHERE source_id NOT LIKE 'mkt:%'").fetchall()
    for source, sid, title in rows:
        et, tk = (parse_binance if source == "binance" else parse_upbit)(title)
        db.execute("UPDATE announcements SET event_type=?, tickers=? WHERE source=? AND source_id=?",
                   (et, json.dumps(tk), source, sid))
    db.commit()


def collect_upbit_markets(db) -> int:
    """Diff Upbit's market list against the last snapshot. The first run only records a baseline."""
    markets = _get("https://api.upbit.com/v1/market/all?is_details=true")
    now = _now()
    baseline = db.execute("SELECT COUNT(*) FROM upbit_markets").fetchone()[0] == 0
    known = {r[0]: (r[1], r[2]) for r in db.execute("SELECT market, warning, removed_at FROM upbit_markets")}
    seen, events = set(), 0
    for m in markets:
        code, name = m["market"], m.get("english_name", "")
        warning = int(bool((m.get("market_event") or {}).get("warning")))
        base = code.split("-", 1)[1]
        seen.add(code)
        url = f"https://upbit.com/exchange?code=CRIX.UPBIT.{code}"
        if code not in known or known[code][1] is not None:
            db.execute("INSERT OR REPLACE INTO upbit_markets (market, english_name, first_seen_at, last_seen_at, warning) VALUES (?,?,?,?,?)",
                       (code, name, now, now, warning))
            if not baseline:
                events += store(db, "upbit", f"mkt:{code}:opened:{now[:16]}", now, f"Upbit opened {code} market ({name})",
                                url, "upbit_market_opened", [base], m)
            continue
        db.execute("UPDATE upbit_markets SET last_seen_at=?, warning=? WHERE market=?", (now, warning, code))
        if warning and not known[code][0] and not baseline:
            events += store(db, "upbit", f"mkt:{code}:warning:{now[:16]}", now, f"Upbit flagged {code} ({name}) with a trading warning",
                            url, "upbit_warning", [base], m)
    for code, (_, removed) in known.items():
        if code not in seen and removed is None:
            db.execute("UPDATE upbit_markets SET removed_at=? WHERE market=?", (now, code))
            events += store(db, "upbit", f"mkt:{code}:removed:{now[:16]}", now, f"Upbit removed {code} market",
                            None, "upbit_market_removed", [code.split("-", 1)[1]], {"market": code})
    db.commit()
    return events


def summary(db) -> None:
    print("\nEvents by type and year (published_at, UTC):")
    rows = db.execute("""SELECT event_type, substr(published_at,1,4) y, COUNT(*) FROM announcements
                         GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    by_type: dict[str, list[str]] = {}
    for et, y, n in rows:
        by_type.setdefault(et, []).append(f"{y}:{n}")
    for et, ys in sorted(by_type.items()):
        print(f"  {et:28} {' '.join(ys)}")
    span = db.execute("SELECT source, MIN(published_at), MAX(published_at), COUNT(*) FROM announcements GROUP BY 1").fetchall()
    for s, a, b, n in span:
        print(f"  {s}: {n} announcements, {a[:10]} → {b[:10]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--full", action="store_true", help="page through the whole history instead of stopping at known items")
    ap.add_argument("--quiet", action="store_true", help="skip the summary (for the timer)")
    args = ap.parse_args()
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    if not args.summary:
        sources = [("binance", lambda: collect_binance(db, full=args.full)),
                   ("upbit", lambda: collect_upbit(db, full=args.full)),
                   ("upbit-markets", lambda: collect_upbit_markets(db))]
        failures = 0
        for name, fn in sources:
            try:
                print(f"{name}: {fn()} new")
            except Exception as e:  # one blocked source must not stop the others
                failures += 1
                print(f"{name}: FAILED ({e})")
        if failures == len(sources):
            raise SystemExit(1)
    reparse(db)
    if not args.quiet:
        summary(db)


if __name__ == "__main__":
    main()
