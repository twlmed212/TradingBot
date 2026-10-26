"""H9 forward paper test: risk-controlled short basket of Solana tokens vs long SOL on Hyperliquid prices.

Rules: research/registry/2026-10-25-h9-short-basket-forward.md. PAPER ONLY: reads public Hyperliquid data, places no
orders, needs no keys. Run once per hour (systemd timer on the server):

    python3 research/h9_paper.py            # one hourly step (idempotent within an hour)
    python3 research/h9_paper.py --status   # print equity, positions and criteria so far

State: data/h9_paper.sqlite3.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("H9_DB", ROOT / "data" / "h9_paper.sqlite3"))
API = "https://api.hyperliquid.xyz/info"
UNIVERSE = ["PUMP", "FARTCOIN", "GRASS", "USELESS", "PYTH", "TRUMP", "PENGU", "kBONK", "JUP", "JTO", "WIF", "W", "RENDER",
            "POPCAT", "GOAT", "MOODENG", "PNUT", "ME", "GRIFFAIN", "MELANIA", "LAYER", "BOME", "TNSR", "IO", "SKR"]
LONG = "SOL"
START_EQUITY = 10_000.0
COST = 0.0010
SHORT_SIDE = 0.5
MAX_PER_TOKEN = 0.1
MIN_NAMES = 5
MIN_MEDIAN_VOL = 1_000_000
MIN_AGE_DAYS = 30
MAX_24H_UP = 0.40
MIN_FUNDING_APR = -0.50
STOP_UP = 0.30
BLACKLIST = timedelta(days=14)
BRAKE_DD, BRAKE_DAYS = 0.15, 7
USDC_APR = 0.05
END = datetime(2027, 1, 31, 23, 59, tzinfo=timezone.utc)

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS positions (coin TEXT PRIMARY KEY, qty REAL, entry REAL, opened_at TEXT);
CREATE TABLE IF NOT EXISTS blacklist (coin TEXT PRIMARY KEY, until TEXT);
CREATE TABLE IF NOT EXISTS trades (ts TEXT, coin TEXT, qty_change REAL, px REAL, cost REAL, realized REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS contrib (coin TEXT PRIMARY KEY, pnl REAL);
CREATE TABLE IF NOT EXISTS runs (hour TEXT PRIMARY KEY, ts TEXT, equity REAL, cash REAL, gross REAL, n_short INTEGER, note TEXT);
"""


def post(body: dict):
    for k in range(5):
        try:
            req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if k == 4:
                raise
            time.sleep(3 * (k + 1))


class Book:
    def __init__(self, db: sqlite3.Connection, now: datetime):
        self.db, self.now = db, now

    def get(self, key, default=None):
        r = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, str(value)))

    def positions(self) -> dict[str, tuple[float, float]]:
        return {c: (q, e) for c, q, e, _ in self.db.execute("SELECT * FROM positions")}

    def add_contrib(self, coin, pnl):
        self.db.execute("INSERT INTO contrib VALUES (?, ?) ON CONFLICT(coin) DO UPDATE SET pnl = pnl + excluded.pnl", (coin, pnl))

    def trade(self, coin: str, new_qty: float, px: float, reason: str):
        q, e = self.positions().get(coin, (0.0, 0.0))
        if abs(new_qty - q) * px < 0.01:
            return
        q0 = q
        cost = abs(new_qty - q0) * px * COST
        realized = 0.0
        if q and (new_qty == 0 or (q > 0) != (new_qty > 0)):        # close (or flip)
            realized = q * (px - e)
            q, e = 0.0, 0.0
        if q and abs(new_qty) < abs(q):                               # reduce
            realized = (q - new_qty) * (px - e)
            e_new = e
        elif q:                                                       # add
            e_new = (abs(q) * e + (abs(new_qty) - abs(q)) * px) / abs(new_qty)
        else:                                                         # open
            e_new = px
        cash = float(self.get("cash")) + realized - cost
        self.set("cash", cash)
        self.add_contrib(coin, realized - cost)
        if new_qty == 0:
            self.db.execute("DELETE FROM positions WHERE coin=?", (coin,))
        else:
            self.db.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?,?)", (coin, new_qty, e_new, self.now.isoformat()))
        self.db.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?)", (self.now.isoformat(), coin, new_qty - q0, px, cost, realized, reason))

    def equity(self, marks: dict[str, float]) -> float:
        return float(self.get("cash")) + sum(q * (marks.get(c, e) - e) for c, (q, e) in self.positions().items())


def eligible(coin: str, ctx: dict, now: datetime) -> tuple[bool, str]:
    start = int((now - timedelta(days=60)).timestamp() * 1000)
    candles = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": start, "endTime": int(now.timestamp() * 1000)}})
    if len(candles) < MIN_AGE_DAYS:
        return False, "younger than 30 days"
    vols = [float(c["v"]) * float(c["c"]) for c in candles[-31:-1]]
    if statistics.median(vols) < MIN_MEDIAN_VOL:
        return False, f"median volume ${statistics.median(vols) / 1e6:.2f}M"
    mark, prev = float(ctx["markPx"]), float(ctx.get("prevDayPx") or ctx["markPx"])
    if prev and mark / prev - 1 > MAX_24H_UP:
        return False, "24h rise > 40%"
    if float(ctx.get("funding") or 0) * 24 * 365 < MIN_FUNDING_APR:
        return False, "funding below -50% APR"
    return True, "ok"


def step(force: bool = False) -> str:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if now > END:  # after the window nothing may change the state the verdict reads (registry operations log, 26 Oct)
        return "evaluation window over (last counted run 31 Jan 2027 23:00 UTC); state frozen for the verdict"
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    book = Book(db, now)
    if db.execute("SELECT 1 FROM runs WHERE hour=?", (now.isoformat(),)).fetchone() and not force:
        return "already ran this hour"
    if book.get("cash") is None:
        book.set("cash", START_EQUITY)
        book.set("peak", START_EQUITY)
        book.set("start", now.isoformat())
    meta, ctxs = post({"type": "metaAndAssetCtxs"})
    info = {a["name"]: (a, c) for a, c in zip(meta["universe"], ctxs)}
    marks = {n: float(c["markPx"]) for n, (a, c) in info.items() if c.get("markPx")}
    notes = []

    # 1) hourly funding on open positions (shorts receive positive funding; the long pays it)
    for coin, (q, _e) in book.positions().items():
        if coin in info and coin in marks:
            pay = -q * marks[coin] * float(info[coin][1].get("funding") or 0)
            book.set("cash", float(book.get("cash")) + pay)
            book.add_contrib(coin, pay)

    # 2) delistings and per-token stops
    for coin, (q, e) in book.positions().items():
        if coin == LONG:
            continue
        delisted = coin not in info or info[coin][0].get("isDelisted")
        px = marks.get(coin, e)
        if delisted:
            book.trade(coin, 0.0, px, "delisted")
            notes.append(f"{coin} delisted")
        elif q < 0 and px >= e * (1 + STOP_UP):
            book.trade(coin, 0.0, px, "stop +30%")
            db.execute("INSERT OR REPLACE INTO blacklist VALUES (?,?)", (coin, (now + BLACKLIST).isoformat()))
            notes.append(f"{coin} stopped")

    # 3) drawdown brake
    eq = book.equity(marks)
    peak = max(float(book.get("peak")), eq)
    book.set("peak", peak)
    brake_until = book.get("brake_until")
    braking = brake_until is not None and now < datetime.fromisoformat(brake_until)
    if not braking and eq <= peak * (1 - BRAKE_DD):
        for coin, (q, _e) in book.positions().items():
            book.trade(coin, q / 2, marks.get(coin, _e), "drawdown brake")
        book.set("brake_until", (now + timedelta(days=BRAKE_DAYS)).isoformat())
        braking = True
        notes.append("drawdown brake on")

    # 4) weekly rebalance (first run after Monday 00:00 UTC, and on the first run)
    week = (now - timedelta(days=now.weekday())).date().isoformat()
    if book.get("week") != week and now <= END:
        blocked = {c for c, u in db.execute("SELECT coin, until FROM blacklist") if now < datetime.fromisoformat(u)}
        chosen = []
        for coin in UNIVERSE:
            if coin in blocked or coin not in info or info[coin][0].get("isDelisted"):
                continue
            ok, why = eligible(coin, info[coin][1], now)
            if ok:
                chosen.append(coin)
            time.sleep(0.2)
        eq = book.equity(marks)
        side = SHORT_SIDE * eq * min(1.0, len(chosen) / MIN_NAMES) * (0.5 if braking else 1.0)
        per = min(side / len(chosen), MAX_PER_TOKEN * eq) if chosen else 0.0
        for coin in [c for c in book.positions() if c != LONG and c not in chosen]:
            book.trade(coin, 0.0, marks.get(coin, book.positions()[coin][1]), "rebalance out")
        for coin in chosen:
            book.trade(coin, -per / marks[coin], marks[coin], "rebalance")
        book.set("week", week)
        notes.append(f"rebalance: {len(chosen)} shorts ({', '.join(chosen)})")

    # 5) keep the SOL long equal to the short notional
    short_notional = sum(-q * marks.get(c, e) for c, (q, e) in book.positions().items() if c != LONG and q < 0)
    target_sol = short_notional / marks[LONG]
    cur = book.positions().get(LONG, (0.0, 0.0))[0]
    if abs(target_sol - cur) * marks[LONG] > 0.02 * max(short_notional, 1):
        book.trade(LONG, target_sol, marks[LONG], "hedge")

    eq = book.equity(marks)
    gross = sum(abs(q) * marks.get(c, e) for c, (q, e) in book.positions().items())
    n_short = sum(1 for c, (q, _e) in book.positions().items() if c != LONG and q < 0)
    db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?)",
               (now.isoformat(), datetime.now(timezone.utc).isoformat(timespec="seconds"), eq, float(book.get("cash")), gross, n_short, "; ".join(notes)))
    db.commit()
    return f"{now:%Y-%m-%d %H:%M} equity ${eq:,.2f} gross ${gross:,.0f} shorts {n_short} {'; '.join(notes)}"


def status() -> None:
    db = sqlite3.connect(DB)
    runs = db.execute("SELECT hour, equity FROM runs ORDER BY hour").fetchall()
    if not runs:
        print("no runs yet")
        return
    start = datetime.fromisoformat(runs[0][0])
    last = datetime.fromisoformat(runs[-1][0])
    eqs = [e for _, e in runs]
    peak, mdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak)
    hours = (last - start).total_seconds() / 3600 + 1
    usdc = START_EQUITY * ((1 + USDC_APR) ** ((last - start).days / 365) - 1)
    print(f"since {start:%Y-%m-%d %H:%M}: equity ${eqs[-1]:,.2f} ({(eqs[-1] / START_EQUITY - 1) * 100:+.2f}%), USDC 5% would be +${usdc:,.2f}; "
          f"max DD {mdd * 100:.1f}%; runs {len(runs)}/{int(hours)} ({len(runs) / hours * 100:.0f}%)")
    for c, q, e, _ in db.execute("SELECT * FROM positions ORDER BY coin"):
        print(f"  {c:9} qty {q:+,.2f} entry {e:.6g}")
    print("  contribution:", {c: round(p, 2) for c, p in db.execute("SELECT coin, pnl FROM contrib ORDER BY pnl DESC")})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-run this hour (testing only)")
    args = ap.parse_args()
    if args.status:
        status()
    else:
        print(step(args.force))


if __name__ == "__main__":
    main()
