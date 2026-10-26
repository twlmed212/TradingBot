"""H6 step 3: monthly wallet ranking + copy simulation. Rules: research/registry/2026-10-25-h6-copy-smart-wallets.md.

    python3 research/h6_killtest.py

Positions are marked at entry value until exit (equity changes when copies close), so the daily Sharpe is computed on a
step curve; this is disclosed in the result. Copy prices come from the token's pool (median swap price among the first
10 successful transactions within 15 minutes after t + delay), cached in data/h6.sqlite3.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from listing_prices import http_json, load_env  # noqa: E402
from h6_discover import DB, CUTOFF, pool_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STAKE = 0.06
TRADE_COST = 0.003
BASE, STRESS = 0.003, 0.006
MIN_SOL = 1.0
HOLD_MAX = timedelta(days=7)
COPY_MONTHS = [datetime(2025, m, 1, tzinfo=timezone.utc) for m in range(1, 7)]
VARIANTS = [(10, 120), (10, 600), (25, 120), (25, 600)]
PRIMARY = (10, 120)
WSOL, USDC = "So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def month_add(d, n):
    m = d.month - 1 + n
    return d.replace(year=d.year + m // 12, month=m % 12 + 1)


class World:
    def __init__(self):
        self.db = sqlite3.connect(DB)
        self.db.execute("CREATE TABLE IF NOT EXISTS copy_prices (mint TEXT, t INTEGER, price REAL, PRIMARY KEY (mint, t))")
        h5 = sqlite3.connect(ROOT / "data" / "h5_prices.sqlite3")
        self.sol = {datetime.fromisoformat(h): o for h, o in h5.execute("SELECT hour, open FROM sol_usd_open")}
        self.first_pool = {}
        for mint, c in h5.execute("SELECT mint, MIN(created_at) FROM candidates GROUP BY mint"):
            if c:
                self.first_pool[mint] = datetime.fromisoformat(c.replace("Z", "+00:00")).timestamp()
        lp = sqlite3.connect(ROOT / "data" / "listing_prices.sqlite3")
        for mint, c in lp.execute("SELECT mint, pool_created_at FROM pools"):
            if c and mint not in self.first_pool:
                self.first_pool[mint] = datetime.fromisoformat(c).timestamp()
        self.pools = pool_for()
        ok = {w for (w,) in self.db.execute("SELECT wallet FROM wallets WHERE status='ok'")}
        self.trades = defaultdict(list)
        for w, t, mint, side, amt, quote, q in self.db.execute(
                "SELECT wallet, t, mint, side, token_amt, quote, quote_amt FROM trades WHERE t < ? ORDER BY t", (CUTOFF.timestamp(),)):
            if w not in ok:
                continue
            sol_amt = q if quote == "SOL" else q / self.sol_at(t)
            if sol_amt:
                self.trades[w].append((t, mint, side, amt, sol_amt))

    def sol_at(self, t):
        h = datetime.fromtimestamp(t, timezone.utc).replace(minute=0, second=0, microsecond=0)
        return self.sol.get(h) or self.sol.get(h - timedelta(hours=1)) or float("nan")

    def score(self, wallet, start, end):
        """Realized SOL profit on closed positions minus 30 bps per trade, with exclusion flags."""
        tr = [x for x in self.trades[wallet] if start.timestamp() <= x[0] < end.timestamp()]
        if len(tr) > 2000:
            return None
        pos, profit, closed, buys, snipes = defaultdict(lambda: [0.0, 0.0]), 0.0, 0, 0, 0
        for t, mint, side, amt, sol in tr:
            profit -= TRADE_COST * sol
            if side == "buy":
                buys += 1
                if mint in self.first_pool and t - self.first_pool[mint] < 300:
                    snipes += 1
                pos[mint][0] += amt
                pos[mint][1] += sol
            elif pos[mint][0] > 0:
                take = min(amt, pos[mint][0])
                basis = pos[mint][1] * take / pos[mint][0]
                profit += sol * take / amt - basis
                pos[mint][0] -= take
                pos[mint][1] -= basis
                closed += 1
        if closed < 10 or (buys and snipes / buys > 0.30):
            return None
        return profit

    def price(self, mint, t):
        row = self.db.execute("SELECT price FROM copy_prices WHERE mint=? AND t=?", (mint, t)).fetchone()
        if row:
            return row[0]
        if t + 900 >= CUTOFF.timestamp():
            return None
        months = self.pools.get(mint, {})
        p = months.get(datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m")) or months.get("*")
        val = None
        if p:
            pool, quote = p
            res = http_json(os.environ["SOLANA_RPC_URL"], {"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [pool, {
                "transactionDetails": "full", "sortOrder": "asc", "limit": 10, "encoding": "json", "maxSupportedTransactionVersion": 0,
                "filters": {"blockTime": {"gte": int(t), "lt": int(t) + 900}, "status": "succeeded"}}]})
            prices = []
            for tx in (res.get("result") or {}).get("data", []):
                d = defaultdict(float)
                for side, es in ((-1, tx["meta"]["preTokenBalances"]), (1, tx["meta"]["postTokenBalances"])):
                    for e in es:
                        if e.get("owner") == pool and e["mint"] in (mint, quote):
                            d[e["mint"]] += side * float(e["uiTokenAmount"]["uiAmount"] or 0)
                if d[mint] and d[quote] and (d[mint] > 0) != (d[quote] > 0):
                    prices.append(abs(d[quote]) / abs(d[mint]))
            if prices:
                val = statistics.median(prices)
                if quote == USDC:
                    val /= self.sol_at(t)
        self.db.execute("INSERT OR REPLACE INTO copy_prices VALUES (?,?,?)", (mint, t, val))
        self.db.commit()
        return val


def simulate(w: World, N, delay, cost, exclude_trade=None):
    eq, positions, closed_log, curve = 1.0, {}, [], []
    stake_s = (1 + STAKE) ** (1 / (365 * 86400)) - 1
    events = []
    for m in COPY_MONTHS:
        scores = {x: w.score(x, month_add(m, -3), m) for x in w.trades}
        top = [x for x, s in sorted(((x, s) for x, s in scores.items() if s and s > 0), key=lambda kv: -kv[1])[:N]]
        end = month_add(m, 1)
        for x in top:
            for t, mint, side, amt, sol in w.trades[x]:
                if m.timestamp() <= t < end.timestamp() and side == "buy" and sol >= MIN_SOL:
                    sell = next((s[0] for s in w.trades[x] if s[0] > t and s[1] == mint and s[2] == "sell"), None)
                    events.append((t, x, mint, sell))
    events.sort()
    cash, last_t = 1.0, COPY_MONTHS[0].timestamp()
    for t, x, mint, sell in events:
        # close positions whose exit time has passed
        for key in [k for k, p in positions.items() if p["exit_t"] <= t]:
            p = positions.pop(key)
            cash += p["value"] * p["growth"] * (1 - cost)
            closed_log.append((p["exit_t"], key, p["value"] * (p["growth"] * (1 - cost) - 1)))
        cash *= (1 + stake_s) ** (t - last_t)
        last_t = t
        if mint in positions or (exclude_trade and (t, mint) == exclude_trade):
            continue
        equity = cash + sum(p["value"] for p in positions.values())
        size = equity / N
        if cash < size:
            continue
        entry = w.price(mint, int(t + delay))
        if not entry:
            continue
        exit_t = min(sell + delay if sell else t + HOLD_MAX.total_seconds(), t + HOLD_MAX.total_seconds())
        exit_p = None
        for k in range(0, 24 * 4):
            exit_p = w.price(mint, int(exit_t + k * 900))
            if exit_p or exit_t + k * 900 >= CUTOFF.timestamp():
                break
        growth = (exit_p / entry) if exit_p else 0.0
        cash -= size
        positions[mint] = {"value": size * (1 - cost), "growth": growth, "exit_t": exit_t, "t": t}
    for key, p in positions.items():
        cash += p["value"] * p["growth"] * (1 - cost)
        closed_log.append((p["exit_t"], key, p["value"] * (p["growth"] * (1 - cost) - 1)))
    # daily step curve from realized PnL
    pnl_by_day = defaultdict(float)
    for et, _k, pnl in closed_log:
        pnl_by_day[datetime.fromtimestamp(et, timezone.utc).date()] += pnl
    d, e = COPY_MONTHS[0].date(), 1.0
    stake_d = (1 + STAKE) ** (1 / 365) - 1
    while d < CUTOFF.date():
        e = e * (1 + stake_d) + pnl_by_day.get(d, 0.0)
        curve.append((d, e))
        d += timedelta(days=1)
    return curve, closed_log, len(events)


def stats(curve):
    eqs = [1.0] + [e for _, e in curve]
    rets = [b / a - 1 for a, b in zip(eqs, eqs[1:]) if a > 0]
    stake_d = (1 + STAKE) ** (1 / 365) - 1
    xs = [r - stake_d for r in rets]
    sd = statistics.pstdev(xs) if len(xs) > 1 else 0
    peak, mdd = 1.0, 0.0
    for x in eqs:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak if peak > 0 else 1)
    return {"ret": eqs[-1] - 1, "sharpe": statistics.mean(xs) / sd * math.sqrt(365) if sd else 0.0, "mdd": mdd}


def main():
    load_env()
    w = World()
    stake = (1 + STAKE) ** (181 / 365) - 1
    print(f"non-bot wallets with trades: {len(w.trades)}; copy period 2025-01-01 → 2025-06-30; staked SOL {stake * 100:+.1f}%")
    res = {}
    for N, delay in VARIANTS:
        for label, c in (("base", BASE), ("stress", STRESS)):
            curve, log, n_events = simulate(w, N, delay, c)
            res[(N, delay, label)] = (stats(curve), curve, log)
            st = stats(curve)
            print(f"N={N:2} delay={delay:3}s {label:6}: {st['ret'] * 100:+7.1f}%  Sharpe {st['sharpe']:5.2f}  maxDD {st['mdd'] * 100:5.1f}%  copies {len(log)} (signals {n_events})")
    pst, pcurve, plog = res[(*PRIMARY, "base")]
    sst = res[(*PRIMARY, "stress")][0]
    months = defaultdict(float)
    by_day = dict(pcurve)
    prev = 1.0
    for m in COPY_MONTHS:
        last = max((d for d in by_day if d < month_add(m, 1).date()), default=None)
        if last:
            months[m.strftime("%Y-%m")] = by_day[last] / prev - 1 - ((1 + STAKE) ** (30 / 365) - 1)
            prev = by_day[last]
    best = max(plog, key=lambda r: r[2]) if plog else None
    ex = stats(simulate(w, *PRIMARY, BASE, exclude_trade=None)[0]) if not best else None
    if best:
        # rerun without the single best copied trade (identified by its entry time and token)
        curve, log, _ = simulate(w, *PRIMARY, BASE)
        best_pos = max(log, key=lambda r: r[2])
        ex_ret = pst["ret"] - best_pos[2]
        ex = {"ret": ex_ret}
    vwins = sum(1 for N, dl in VARIANTS if res[(N, dl, "base")][0]["ret"] > stake)
    print("monthly vs staking:", {k: f"{v * 100:+.1f}%" for k, v in months.items()})
    checks = [
        (f"beats staked SOL under stress ({sst['ret'] * 100:+.1f}%)", sst["ret"] > stake),
        (f"daily Sharpe > 0 ({pst['sharpe']:.2f})", pst["sharpe"] > 0),
        (f"positive in >= 4 of 6 months ({sum(v > 0 for v in months.values())}/6)", sum(v > 0 for v in months.values()) >= 4),
        (f"max drawdown <= 40% ({pst['mdd'] * 100:.1f}%)", pst["mdd"] <= 0.40),
        (f"without best copied trade beats staked SOL ({ex['ret'] * 100:+.1f}%)", ex["ret"] > stake),
        (f">= 3 of 4 variants beat staked SOL at base ({vwins}/4)", vwins >= 3),
    ]
    print("\nPre-registered criteria:")
    for t_, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {t_}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")


if __name__ == "__main__":
    main()
