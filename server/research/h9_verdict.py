"""H9 verdict: the five pass criteria, counted exactly as the registry's Clarifications define them.

Rules: research/registry/2026-10-25-h9-short-basket-forward.md. Written 26 Oct 2026, before any weekly or per-token
result existed. The console's H9 card calls the same `evaluate()`, so the screen and the verdict cannot disagree.

    python3 research/h9_verdict.py               # provisional until 31 Jan 2027 23:10 UTC, final after
    H9_DB=path python3 research/h9_verdict.py    # evaluate another copy of the database

Per-token profit (criterion 4) needs each open position's price at the last counted hour. The engine stores equity,
not per-token marks, so this script takes the open of that hour's Hyperliquid 1-hour candle (the engine reads marks
at :02 of the same hour). Public API, no key.
"""

from __future__ import annotations

import bisect
import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("H9_DB", ROOT / "data" / "h9_paper.sqlite3"))
API = "https://api.hyperliquid.xyz/info"
START_EQUITY = 10_000.0
USDC_APR = 0.05
MAX_DD = 0.15
MIN_WEEKS_UP = 0.55
MAX_TOKEN_SHARE = 0.50
MIN_RUNS = 0.95
END = datetime(2027, 1, 31, 23, 0, tzinfo=timezone.utc)  # last hourly run that counts
DUE_AFTER = timedelta(minutes=10)                         # the timer fires at :02; an hour is due once 10 minutes old
HOUR = timedelta(hours=1)


def load(db_path: Path = DB) -> dict:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    runs = [(datetime.fromisoformat(h), e) for h, e in db.execute("SELECT hour, equity FROM runs ORDER BY hour")]
    runs = [(h, e) for h, e in runs if h <= END]
    data = {
        "hours": [h for h, _ in runs],
        "equity": [e for _, e in runs],
        "positions": {c: (q, e) for c, q, e in db.execute("SELECT coin, qty, entry FROM positions")},
        "booked": dict(db.execute("SELECT coin, pnl FROM contrib")),
    }
    db.close()
    return data


def weeks(hours: list[datetime], eqs: list[float], now: datetime) -> list[dict]:
    """Monday-to-Monday UTC weeks after the opening run; the opening hour belongs to no week."""
    def eq_before(t: datetime) -> float:
        i = bisect.bisect_left(hours, t) - 1
        return eqs[i] if i >= 0 else START_EQUITY
    start = hours[0]
    monday = (start - timedelta(days=start.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    if monday < start:
        monday += timedelta(days=7)
    out = []
    while monday <= min(now, END):
        end = monday + timedelta(days=7)
        ret = eq_before(min(end, now + timedelta(seconds=1))) / eq_before(monday) - 1
        out.append({"week": monday.date().isoformat(), "return": round(ret, 6), "complete": end <= now})
        monday = end
    return out


def evaluate(data: dict, marks: dict[str, float], now: datetime) -> dict:
    """Criteria so far (or final once the window is over). `marks`: prices for open positions at the evaluation hour."""
    hours, eqs = data["hours"], data["equity"]
    start, last = hours[0], hours[-1]
    peak, max_dd = START_EQUITY, 0.0
    for e in eqs:
        peak = max(peak, e)
        max_dd = max(max_dd, 1 - e / peak)
    years = (last - start).total_seconds() / (365 * 86400)
    net, usdc = eqs[-1] / START_EQUITY - 1, (1 + USDC_APR) ** years - 1
    # hours due by the clock, plus any hour whose run already finished early (the timer fires at :02)
    due = max((min(now, END + DUE_AFTER) - start - DUE_AFTER) // HOUR + 1, (last - start) // HOUR + 1)
    total_runs = (END - start) // HOUR + 1
    wk = weeks(hours, eqs, now)
    done = [w for w in wk if w["complete"]]
    up = sum(1 for w in done if w["return"] > 0)

    tokens = []
    for coin in sorted(set(data["positions"]) | set(data["booked"])):
        qty, entry = data["positions"].get(coin, (0.0, None))
        mark = marks.get(coin) if qty else None
        unreal = qty * (mark - entry) if qty and mark is not None else 0.0
        booked = data["booked"].get(coin, 0.0)
        tokens.append({"coin": coin, "qty": qty, "entry": entry, "mark": mark,
                       "unrealized": round(unreal, 2), "booked": round(booked, 2), "total": round(booked + unreal, 2)})
    marks_ok = all(c in marks for c in data["positions"])
    # cash = start + all booked P&L, so the token totals add up to equity at these marks
    profit = sum(t["total"] for t in tokens) if marks_ok else None
    top = max(tokens, key=lambda t: t["total"]) if tokens else None
    share = top["total"] / profit if (top and profit is not None and profit > 0) else None

    final = now >= END + DUE_AFTER
    checks = [
        {"n": 1, "label": f"net return {net:+.2%} above USDC at 5% {usdc:+.2%}", "pass": net > usdc},
        {"n": 2, "label": f"max drawdown {max_dd:.1%} <= {MAX_DD:.0%}", "pass": max_dd <= MAX_DD},
        {"n": 3, "label": f"positive weeks {up} of {len(done)} >= {MIN_WEEKS_UP:.0%}", "pass": bool(done) and up / len(done) >= MIN_WEEKS_UP},
        {"n": 4, "label": (f"largest token {top['coin']} {share:.0%} of profit <= {MAX_TOKEN_SHARE:.0%}" if share is not None
                           else "largest token share: not applicable (no profit)" if marks_ok else "largest token share: marks missing"),
         "pass": (share <= MAX_TOKEN_SHARE) if share is not None else None},
        {"n": 5, "label": f"hourly runs {len(eqs)} of {due} expected >= {MIN_RUNS:.0%}", "pass": len(eqs) / due >= MIN_RUNS},
    ]
    passed = all(c["pass"] is True for c in checks)
    return {
        "start": start, "last": last, "final": final,
        "net_return": net, "usdc_return": usdc, "max_dd": max_dd, "dd_now": 1 - eqs[-1] / peak,
        "weeks": wk, "weeks_up": up, "weeks_done": len(done),
        "tokens": tokens, "profit": profit, "top_token": top["coin"] if share is not None else None, "top_share": share,
        "runs": len(eqs), "runs_due": int(due), "runs_total": int(total_runs),
        "checks": checks, "verdict": ("PASS" if passed else "FAIL") if final else ("on track" if passed else "not on track"),
    }


def candle_marks(coins: list[str], hour: datetime) -> dict[str, float]:
    """Open of each coin's Hyperliquid 1-hour candle starting at `hour`."""
    out = {}
    t0 = int(hour.timestamp() * 1000)
    for coin in coins:
        body = {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": t0, "endTime": t0 + 3_600_000}}
        req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            candles = json.loads(r.read())
        hit = [c for c in candles if int(c["t"]) == t0]
        if hit:
            out[coin] = float(hit[0]["o"])
        time.sleep(0.2)
    return out


def main() -> None:
    data = load()
    if not data["hours"]:
        print("no runs yet")
        return
    now = datetime.now(timezone.utc)
    res = evaluate(data, candle_marks(list(data["positions"]), data["hours"][-1]), now)
    print(f"H9 {'FINAL' if res['final'] else 'PROVISIONAL'} as of {res['last']:%Y-%m-%d %H:%M} UTC "
          f"(window {res['start']:%Y-%m-%d %H:%M} -> {END:%Y-%m-%d %H:%M} UTC)")
    for c in res["checks"]:
        mark = "PASS" if c["pass"] is True else "n/a " if c["pass"] is None else "FAIL"
        print(f"  [{mark}] {c['n']}. {c['label']}")
    print("  per-token P&L (booked + unrealized at the hour's candle open):")
    for t in sorted(res["tokens"], key=lambda t: -t["total"]):
        print(f"    {t['coin']:9} {t['total']:+10.2f}")
    print(f"VERDICT: {res['verdict']}")


if __name__ == "__main__":
    main()
