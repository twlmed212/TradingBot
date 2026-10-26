"""deskbot console API — read-only, watch-only dashboard for the EC2 services.

Serves JSON under /api and the built React app under /. It never writes to any data file, never holds keys,
and is bound to 127.0.0.1 on the server; it is reached only through the Session Manager SSH tunnel.
Its only outbound call is Hyperliquid's public price endpoint (no key), for live estimates on the H9 card.

    DESKBOT_ROOT=/opt/deskbot uvicorn console.api.main:app --host 127.0.0.1 --port 8787
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from research import h9_paper, h9_verdict  # H9 rules and the verdict's own criteria code (one source of truth)

ROOT = Path(os.environ.get("DESKBOT_ROOT", Path(__file__).resolve().parents[2]))
DATA = ROOT / "data"
QUOTES_DB = DATA / "quotes.sqlite3"
ANNOUNCEMENTS_DB = DATA / "announcements.sqlite3"
REGISTRY = ROOT / "research" / "registry"
UNIVERSE = ROOT / "recorder" / "universe.json"
H9_DB = Path(os.environ.get("H9_DB", DATA / "h9_paper.sqlite3"))
WEB_DIST = Path(os.environ.get("DESKBOT_WEB_DIST", Path(__file__).resolve().parents[1] / "web" / "dist"))

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Research stop rule (archived plan): fixed in advance.
STOP_RULE_DEADLINE = date(2027, 1, 31)
STOP_RULE_MAX_HYPOTHESES = 6
BASELINE_HYPOTHESES = {"H1", "H2"}

HYPERLIQUID_INFO = "https://api.hyperliquid.xyz/info"

LISTING_TYPES = ("binance_spot_listing", "binance_futures_listing", "binance_futures_premarket", "binance_alpha",
                 "upbit_new_listing", "upbit_market_added", "upbit_market_opened", "upbit_market_removed",
                 "upbit_delisting", "upbit_warning")

app = FastAPI(title="deskbot console", docs_url=None, redoc_url=None, openapi_url=None)
_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.monotonic(), value)
    return value


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise HTTPException(503, f"{path.name} not found")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def service_state(name: str) -> str:
    try:
        out = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def symbols() -> dict[str, str]:
    m = {SOL: "SOL", USDC: "USDC"}
    if UNIVERSE.exists():
        for t in json.loads(UNIVERSE.read_text())["tokens"]:
            m[t["mint"]] = t["symbol"]
    return m


# --- overview --------------------------------------------------------------

def host_stats() -> dict:
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
    except OSError:
        pass
    disk = shutil.disk_usage(DATA if DATA.exists() else ROOT)
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except OSError:
        uptime = None
    return {
        "mem_total_mb": round(mem["MemTotal"] / 1024) if mem else None,
        "mem_available_mb": round(mem["MemAvailable"] / 1024) if mem else None,
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_used_gb": round(disk.used / 1e9, 1),
        "load_1m": round(os.getloadavg()[0], 2),
        "uptime_s": uptime,
        "data_mb": round(sum(f.stat().st_size for f in DATA.glob("*.sqlite3")) / 1e6, 1) if DATA.exists() else None,
    }


def recorder_stats() -> dict:
    db = connect(QUOTES_DB)
    now = now_utc()
    last = db.execute("SELECT started_at, expected, recorded, errors FROM cycles ORDER BY cycle_id DESC LIMIT 1").fetchone()
    first = db.execute("SELECT MIN(started_at) FROM cycles").fetchone()[0]
    out = {"service": service_state("deskbot-recorder"), "first_cycle_at": first}
    for label, hours in (("1h", 1), ("24h", 24)):
        since = now - timedelta(hours=hours)
        row = db.execute("SELECT COUNT(*), COALESCE(SUM(recorded),0), COALESCE(SUM(expected),0) FROM cycles WHERE started_at >= ?",
                         (iso(since),)).fetchone()
        span_min = min(hours * 60, max(math.ceil((now - parse_ts(first)).total_seconds() / 60), 1)) if first else hours * 60
        cycles, rec, exp = row
        out[f"cycles_{label}"] = cycles
        out[f"cycles_expected_{label}"] = int(span_min)
        out[f"readings_{label}"] = rec
        out[f"readings_expected_{label}"] = exp
        out[f"cycle_coverage_{label}"] = round(min(cycles / span_min, 1.0), 4) if span_min else None
        out[f"reading_coverage_{label}"] = round(rec / exp, 4) if exp else None
    if last:
        out["last_cycle_at"] = last["started_at"]
        out["last_cycle_age_s"] = round((now - parse_ts(last["started_at"])).total_seconds())
        out["last_cycle"] = {"expected": last["expected"], "recorded": last["recorded"],
                             "errors": json.loads(last["errors"]) if last["errors"] else []}
    return out


def announcements_stats() -> dict:
    if not ANNOUNCEMENTS_DB.exists():
        return {"service": service_state("deskbot-announcements.timer"), "count": 0, "last_seen_at": None}
    db = connect(ANNOUNCEMENTS_DB)
    count, last_seen, last_pub = db.execute(
        "SELECT COUNT(*), MAX(first_seen_at), MAX(published_at) FROM announcements").fetchone()
    return {"service": service_state("deskbot-announcements.timer"), "count": count,
            "last_seen_at": last_seen, "last_published_at": last_pub}


@app.get("/api/overview")
def overview():
    def build():
        return {
            "server_time": iso(now_utc()),
            "recorder": recorder_stats(),
            "announcements": announcements_stats(),
            "host": host_stats(),
            "bot": {
                "state": "not_running",
                "mode": "paper",
                "reason": "No strategy has passed its kill test, so the bot has nothing to trade. "
                          "H9 is being tested forward with paper money (see the H9 card); a pass would only extend paper testing.",
            },
        }
    return cached("overview", 5, build)


@app.get("/api/coverage")
def coverage(hours: int = 24):
    hours = max(1, min(hours, 24 * 7))

    def build():
        db = connect(QUOTES_DB)
        now = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        start = now - timedelta(hours=hours)
        rows = db.execute("SELECT substr(started_at,1,13) h, COUNT(*), SUM(recorded), SUM(expected) FROM cycles "
                          "WHERE started_at >= ? GROUP BY h", (iso(start),)).fetchall()
        by_hour = {r[0]: r for r in rows}
        first = db.execute("SELECT MIN(started_at) FROM cycles").fetchone()[0]
        first_dt = parse_ts(first) if first else now
        out = []
        for i in range(hours):
            h = start + timedelta(hours=i)
            key = h.strftime("%Y-%m-%dT%H")
            r = by_hour.get(key)
            # minutes this hour could have had a cycle (partial for the first and the current hour)
            lo, hi = max(h, first_dt), min(h + timedelta(hours=1), now_utc())
            possible = max(int((hi - lo).total_seconds() // 60), 0)
            out.append({"hour": iso(h), "cycles": r[1] if r else 0, "possible": possible,
                        "recorded": r[2] if r else 0, "expected": r[3] if r else 0})
        return out
    return cached(f"coverage:{hours}", 30, build)


# --- markets ---------------------------------------------------------------

def _bucketed(points: list[tuple[datetime, float]], start: datetime, hours: int, minutes: int = 30) -> list[dict]:
    """Median per fixed time bucket (default 30 min) over the window, skipping empty buckets."""
    n = hours * 60 // minutes
    buckets: dict[int, list[float]] = {}
    for t, v in points:
        i = int((t - start).total_seconds() // (minutes * 60))
        if 0 <= i < n:
            buckets.setdefault(i, []).append(v)
    return [{"t": iso(start + timedelta(minutes=i * minutes)), "v": round(statistics.median(buckets[i]), 6)}
            for i in range(n) if i in buckets]


@app.get("/api/markets")
def markets():
    def build():
        db = connect(QUOTES_DB)
        names = symbols()
        now = now_utc()
        start = (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
        rows = db.execute(
            "SELECT cycle_id, observed_at, input_mint, output_mint, notional_usd, in_amount, out_amount, fee_bps, router "
            "FROM quotes WHERE observed_at >= ? AND in_amount > 0 AND out_amount > 0", (iso(start),)).fetchall()
        # Pair every buy with the sell of the same cycle and size. Round-trip cost = 1 - (buy rate x sell rate) in raw
        # token units, so Jupiter's per-side USD valuations (which use slightly different reference prices) drop out.
        legs: dict[tuple, dict] = {}
        for r in rows:
            if r["input_mint"] == USDC and r["output_mint"] == SOL:
                token, side, quote = SOL, "buy", "USDC"
            elif r["input_mint"] == SOL and r["output_mint"] == USDC:
                token, side, quote = SOL, "sell", "USDC"
            elif r["input_mint"] == SOL:
                token, side, quote = r["output_mint"], "buy", "SOL"
            elif r["output_mint"] == SOL:
                token, side, quote = r["input_mint"], "sell", "SOL"
            else:
                continue
            key = (token, quote, r["cycle_id"], r["notional_usd"])
            leg = legs.setdefault(key, {"t": parse_ts(r["observed_at"]), "fee": r["fee_bps"], "router": r["router"]})
            leg[side] = r["out_amount"] / r["in_amount"]
        series: dict[tuple, list[tuple[datetime, float, dict]]] = {}
        for (token, quote, _cycle, notional), leg in legs.items():
            if "buy" in leg and "sell" in leg:
                series.setdefault((token, quote, notional), []).append((leg["t"], (1 - leg["buy"] * leg["sell"]) * 1e4, leg))

        prices: dict[str, list[tuple[datetime, float]]] = {}
        for r in db.execute("SELECT observed_at, symbol, price_usd FROM ref_prices WHERE source='jupiter_price_v3' "
                            "AND observed_at >= ?", (iso(start),)):
            prices.setdefault(r["symbol"], []).append((parse_ts(r["observed_at"]), r["price_usd"]))
        binance = db.execute("SELECT price_usd, observed_at FROM ref_prices WHERE source='binance_spot' "
                             "ORDER BY id DESC LIMIT 1").fetchone()

        out = []
        for mint, sym in names.items():
            if mint == USDC:
                continue
            quote = "USDC" if mint == SOL else "SOL"
            sizes = {}
            for (token, q, notional), pts in series.items():
                if token != mint or q != quote:
                    continue
                pts.sort(key=lambda p: p[0])
                t, _, leg = pts[-1]
                rt = statistics.median(p[1] for p in pts[-3:])  # last ~15 min; a single quote is noisy
                sizes[str(int(notional))] = {"roundtrip_bps": round(rt, 1), "at": iso(t), "fee_bps": leg["fee"],
                                             "router": leg["router"], "median_24h_bps": round(statistics.median(p[1] for p in pts), 1)}
            cost_series = series.get((mint, quote, 1000.0), [])
            p = sorted(prices.get(sym, []))
            change = (p[-1][1] / p[0][1] - 1) if len(p) >= 2 and p[0][1] else None
            out.append({
                "symbol": sym, "mint": mint, "pair": f"{sym}/{quote}",
                "price_usd": p[-1][1] if p else None, "price_at": iso(p[-1][0]) if p else None,
                "price_change_24h": round(change, 4) if change is not None else None,
                "price_series": _bucketed(p, start, 25),
                "cost_series_1k": _bucketed([(t, v) for t, v, _ in cost_series], start, 25),
                "sizes": sizes,
                "binance_price_usd": binance["price_usd"] if (mint == SOL and binance) else None,
            })
        out.sort(key=lambda m: (m["symbol"] != "SOL", m["symbol"]))
        return {"as_of": iso(now), "markets": out}
    return cached("markets", 20, build)


# --- announcements ---------------------------------------------------------

@app.get("/api/announcements")
def announcements(limit: int = 60, scope: str = "listings"):
    limit = max(1, min(limit, 300))

    def build():
        if not ANNOUNCEMENTS_DB.exists():
            return {"items": [], "counts_7d": {}}
        db = connect(ANNOUNCEMENTS_DB)
        where, args = ("WHERE event_type IN (%s)" % ",".join("?" * len(LISTING_TYPES)), LISTING_TYPES) if scope == "listings" else ("", ())
        items = [dict(r) for r in db.execute(
            f"SELECT source, published_at, first_seen_at, title, url, event_type, tickers FROM announcements {where} "
            f"ORDER BY published_at DESC LIMIT ?", (*args, limit))]
        for it in items:
            it["tickers"] = json.loads(it["tickers"])
        since = iso(now_utc() - timedelta(days=7))
        counts = {r[0]: r[1] for r in db.execute(
            "SELECT event_type, COUNT(*) FROM announcements WHERE published_at >= ? GROUP BY 1", (since,))}
        return {"items": items, "counts_7d": counts}
    return cached(f"ann:{limit}:{scope}", 30, build)


# --- research --------------------------------------------------------------

def parse_registry(path: Path) -> dict:
    text = path.read_text()
    title_line = next((l for l in text.splitlines() if l.startswith("# ")), path.stem)
    title = re.sub(r"^#\s*Pre-registration( H\d+)?:\s*", "", title_line).strip()
    hid = re.search(r"\*\*Hypothesis:\*\*\s*(H\d+[a-z]?)", text) or re.search(r"Pre-registration (H\d+[a-z]?)", text)
    registered = re.search(r"\*\*Registered:\*\*\s*([^,\n]+)", text)
    result = re.search(r"^## Result[^\n]*?—\s*\*\*(.+?)\*\*", text, re.M)
    verdict, detail = ("RUNNING" if "**Evaluation window:**" in text else "PENDING"), None
    bullets: list[str] = []
    if result:
        head = result.group(1)
        verdict = "PASS" if head.upper().startswith("PASS") else "FAIL" if head.upper().startswith("FAIL") else "PENDING"
        detail = head.split(",", 1)[1].strip() if "," in head else None
        section = text[result.end():]
        bullets = [re.sub(r"\*\*|`", "", b[2:]).strip() for b in section.splitlines() if b.startswith("- ")][:3]
    return {"id": hid.group(1) if hid else None, "file": path.name, "title": title,
            "registered": registered.group(1).strip() if registered else None,
            "verdict": verdict, "detail": detail, "notes": bullets}


@app.get("/api/research")
def research():
    def build():
        items = [parse_registry(p) for p in sorted(REGISTRY.glob("*.md"))] if REGISTRY.exists() else []
        used = len({i["id"] for i in items if i["id"] and i["id"] not in BASELINE_HYPOTHESES})
        passed = [i["id"] for i in items if i["verdict"] == "PASS"]
        return {
            "items": items,
            "stop_rule": {"deadline": STOP_RULE_DEADLINE.isoformat(),
                          "days_left": (STOP_RULE_DEADLINE - now_utc().date()).days,
                          "hypotheses_used": used, "hypotheses_max": STOP_RULE_MAX_HYPOTHESES,
                          "passed": passed},
        }
    return cached("research", 30, build)


# --- H9 forward paper test ---------------------------------------------------

def hyperliquid_mids() -> dict[str, float]:
    """Live perp mid prices for the between-runs estimate. Public endpoint, no key. Empty on failure (cached too)."""
    def fetch():
        try:
            req = urllib.request.Request(HYPERLIQUID_INFO, data=b'{"type":"allMids"}', headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                return {k: float(v) for k, v in json.loads(r.read()).items() if not k.startswith("@")}
        except (OSError, ValueError):
            return {}
    return cached("hl_mids", 60, fetch)


@app.get("/api/h9")
def h9():
    def build():
        timer = service_state("deskbot-h9.timer")
        if not H9_DB.exists():
            return {"started": False, "timer": timer}
        data = h9_verdict.load(H9_DB)
        if not data["hours"]:
            return {"started": False, "timer": timer}
        db = connect(H9_DB)
        runs = [r for r in db.execute("SELECT hour, ts, gross, n_short, note FROM runs ORDER BY hour")
                if parse_ts(r["hour"]) <= h9_verdict.END]
        state = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM state")}
        opened = {r["coin"]: r["opened_at"] for r in db.execute("SELECT coin, opened_at FROM positions")}
        blocked = [{"coin": r["coin"], "until": r["until"]} for r in db.execute("SELECT coin, until FROM blacklist")]
        now = now_utc()
        mids = hyperliquid_mids()
        res = h9_verdict.evaluate(data, mids, now)

        tokens = []
        for t in res["tokens"]:
            qty, entry, mark = t["qty"], t["entry"], t["mark"]
            short = qty < 0
            stop = entry * (1 + h9_paper.STOP_UP) if short else None
            tokens.append({**t, "side": "short" if short else "long" if qty > 0 else "closed", "opened_at": opened.get(t["coin"]),
                           "notional": abs(qty) * (mark if mark is not None else entry) if qty else 0.0,
                           "move": (mark / entry - 1) if qty and mark is not None else None,
                           "stop": stop, "to_stop": (stop / mark - 1) if stop and mark else None})
        tokens.sort(key=lambda t: (t["coin"] != h9_paper.LONG, t["side"] == "closed", -t["notional"], t["coin"]))
        cash = float(state.get("cash", h9_verdict.START_EQUITY))
        brake = state.get("brake_until")
        next_run = now.replace(minute=2, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(hours=1)
        next_rebalance = (now - timedelta(days=now.weekday())).replace(hour=0, minute=2, second=0, microsecond=0)
        if next_rebalance <= now:
            next_rebalance += timedelta(days=7)
        return {
            "started": True, "timer": timer, "start": iso(res["start"]), "end": iso(h9_verdict.END),
            "last_run": runs[-1]["hour"], "last_run_at": runs[-1]["ts"], "next_run": iso(next_run),
            "next_rebalance": iso(next_rebalance) if next_rebalance <= h9_verdict.END else None,
            "start_equity": h9_verdict.START_EQUITY, "usdc_apr": h9_verdict.USDC_APR,
            "equity": round(data["equity"][-1], 2),
            "live_equity": round(h9_verdict.START_EQUITY + res["profit"], 2) if res["profit"] is not None else None,
            "cash": round(cash, 2), "gross": round(runs[-1]["gross"], 2), "n_short": runs[-1]["n_short"],
            "series": [{"t": iso(h), "v": round(e, 2)} for h, e in zip(data["hours"], data["equity"])],
            "brake_until": brake if brake and parse_ts(brake) > now else None,
            "blacklist": [b for b in blocked if parse_ts(b["until"]) > now],
            "tokens": tokens,
            "events": [{"hour": r["hour"], "note": r["note"]} for r in reversed(runs) if r["note"]][:12],
            "weeks": res["weeks"],
            "verdict": res["verdict"], "final": res["final"],
            "criteria": {
                "net_return": round(res["net_return"], 6), "usdc_return": round(res["usdc_return"], 6),
                "max_dd": round(res["max_dd"], 6), "dd_now": round(res["dd_now"], 6), "max_dd_limit": h9_verdict.MAX_DD,
                "weeks_up": res["weeks_up"], "weeks_done": res["weeks_done"], "weeks_up_min": h9_verdict.MIN_WEEKS_UP,
                "top_token": res["top_token"], "top_share": round(res["top_share"], 4) if res["top_share"] is not None else None,
                "top_share_limit": h9_verdict.MAX_TOKEN_SHARE,
                "runs": res["runs"], "runs_due": res["runs_due"], "runs_min": h9_verdict.MIN_RUNS, "runs_total": res["runs_total"],
            },
        }
    return cached("h9", 20, build)

# --- static app ------------------------------------------------------------

if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    index = WEB_DIST / "index.html"
    if not index.exists():
        return {"detail": "web app not built; run npm run build in console/web"}
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
