"""H7: short an equal-weight basket of Solana tokens vs long SOL on Hyperliquid perps — research-only kill test.

Rules are frozen in research/registry/2026-10-25-h7-short-basket-vs-sol.md.

    python3 research/h7_short_basket_killtest.py

Downloads Hyperliquid daily candles and hourly funding for the research window only (cached under data/),
simulates the registered variants with daily marks, and prints the verdict. Never loads data on or after the
holdout cutoff.
"""

from __future__ import annotations

import json
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "hyperliquid_h7_research.json"

UNIVERSE = ["POPCAT", "MEW", "GOAT", "FARTCOIN", "MOODENG", "CHILLGUY", "AI16Z", "GRIFFAIN", "ZEREBRO",
            "MELANIA", "GRASS", "VINE", "JELLY", "MYRO", "LAUNCHCOIN"]
LONG = "SOL"
RESEARCH_START = date(2023, 6, 1)
HOLDOUT_CUTOFF = date(2025, 7, 1)
MIN_HISTORY_DAYS = 30
MIN_MEDIAN_NOTIONAL = 2_000_000
MIN_NAMES = 3
BASE_COST, STRESS_COST = 0.0010, 0.0020
USDC_APR = 0.06


def ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def day(t_ms: int) -> date:
    return datetime.fromtimestamp(t_ms / 1000, timezone.utc).date()


def post(body: dict):
    for k in range(6):
        try:
            req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(body).encode(),
                                         headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (k + 1))
                continue
            raise
    raise RuntimeError("rate limited")


def load() -> dict:
    if CACHE.exists():
        raw = json.loads(CACHE.read_text())
    else:
        raw = {}
        end = ms(HOLDOUT_CUTOFF) - 1
        for coin in UNIVERSE + [LONG]:
            candles = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d",
                                                              "startTime": ms(RESEARCH_START), "endTime": end}})
            funding, start = [], candles[0]["t"]
            while start < end:
                chunk = post({"type": "fundingHistory", "coin": coin, "startTime": start, "endTime": end})
                if not chunk:
                    break
                funding += [(x["time"], float(x["fundingRate"])) for x in chunk]
                start = chunk[-1]["time"] + 1
                if len(chunk) < 500:
                    break
                time.sleep(0.4)
            raw[coin] = {
                "candles": {day(c["t"]).isoformat(): [float(c["o"]), float(c["c"]), float(c["v"]) * float(c["c"])] for c in candles},
                "funding": funding,
            }
            print(f"  loaded {coin}: {len(candles)} days, {len(funding)} funding hours", flush=True)
            time.sleep(0.4)
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(raw))
    last = max(d for v in raw.values() for d in v["candles"])
    if date.fromisoformat(last) >= HOLDOUT_CUTOFF or any(t >= ms(HOLDOUT_CUTOFF) for v in raw.values() for t, _ in v["funding"]):
        raise SystemExit("refusing to run: data reaches into the sealed holdout")
    return raw


class Data:
    def __init__(self, raw: dict):
        self.c = {k: v["candles"] for k, v in raw.items()}
        self.first = {k: date.fromisoformat(min(v)) for k, v in self.c.items()}
        self.last = {k: date.fromisoformat(max(v)) for k, v in self.c.items()}
        self.fund_by_day: dict[str, dict[str, float]] = {}
        for k, v in raw.items():
            agg: dict[str, float] = {}
            for t, r in v["funding"]:
                d = day(t).isoformat()
                agg[d] = agg.get(d, 0.0) + r
            self.fund_by_day[k] = agg

    def o(self, k, d):
        return self.c[k].get(d.isoformat(), [None])[0]

    def cl(self, k, d):
        row = self.c[k].get(d.isoformat())
        return row[1] if row else None

    def eligible(self, k: str, monday: date) -> bool:
        if self.first[k] > monday - timedelta(days=MIN_HISTORY_DAYS) or self.o(k, monday) is None:
            return False
        vols = [self.c[k][d.isoformat()][2] for d in (monday - timedelta(days=i) for i in range(1, 31)) if d.isoformat() in self.c[k]]
        return len(vols) >= 20 and statistics.median(vols) >= MIN_MEDIAN_NOTIONAL

    def rel_28d(self, k: str, monday: date) -> float | None:
        a, b = monday - timedelta(days=29), monday - timedelta(days=1)
        xa, xb, sa, sb = self.cl(k, a), self.cl(k, b), self.cl(LONG, a), self.cl(LONG, b)
        return (xb / xa) / (sb / sa) - 1 if all((xa, xb, sa, sb)) else None


def select(dt: Data, monday: date, mode: str, universe: list[str]) -> list[str]:
    el = [k for k in universe if dt.eligible(k, monday)]
    if len(el) < MIN_NAMES:
        return []
    if mode == "all":
        return el
    scored = sorted((s, k) for k in el if (s := dt.rel_28d(k, monday)) is not None)
    n = max(MIN_NAMES, math.ceil(len(scored) / 2))
    return [k for _, k in scored[:n]] if len(scored) >= MIN_NAMES else []


def simulate(dt: Data, mondays: list[date], end: date, mode: str, every: int, cost: float, universe: list[str]):
    """Returns (daily equity [(date, eq)], per-token contribution, worst week)."""
    eq = 1.0
    q: dict[str, float] = {}           # coin quantities (+ long, - short)
    entry: dict[str, float] = {}       # entry price of current period
    curve, contrib = [], {}
    rebal = mondays[::every]
    for idx, r in enumerate(rebal):
        nxt = rebal[idx + 1] if idx + 1 < len(rebal) else end
        # mark old positions at r's open and rebalance
        names = select(dt, r, mode, universe)
        target = {}
        if names:
            target[LONG] = eq / dt.o(LONG, r)
            for k in names:
                target[k] = -(eq / len(names)) / dt.o(k, r)
        traded = 0.0
        for k in set(q) | set(target):
            px = dt.o(k, r)
            if px is None:
                continue
            traded += abs(target.get(k, 0.0) - q.get(k, 0.0)) * px
            if k != LONG:
                contrib[k] = contrib.get(k, 0.0) - cost * abs(target.get(k, 0.0) - q.get(k, 0.0)) * px
        eq -= cost * traded
        q = target
        entry = {k: dt.o(k, r) for k in q}
        base = eq
        closed: dict[str, float] = {}  # token -> realized PnL for delisted-mid-period closes
        mark = dict(entry)             # last known close, carried across missing days (no look-ahead)
        fund_acc = 0.0
        d = r
        while d < nxt:
            pnl = 0.0
            for k, qty in q.items():
                if k in closed:
                    pnl += closed[k]
                    continue
                f = dt.fund_by_day[k].get(d.isoformat(), 0.0)
                fp = -qty * entry[k] * f
                fund_acc += fp
                contrib[k] = contrib.get(k, 0.0) + fp if k != LONG else contrib.get(k, 0.0)
                px = dt.cl(k, d)
                if px is not None:
                    mark[k] = px
                if d >= dt.last[k] and dt.last[k] < nxt - timedelta(days=1):
                    # delisted mid-period: settle at its final daily close
                    realized = qty * (mark[k] - entry[k]) - cost * abs(qty) * mark[k]
                    closed[k] = realized
                    if k != LONG:
                        contrib[k] = contrib.get(k, 0.0) - cost * abs(qty) * mark[k] - qty * (mark[k] - entry[k])
                    pnl += realized
                    continue
                pnl += qty * (mark[k] - entry[k])
            curve.append((d, base + pnl + fund_acc))
            d += timedelta(days=1)
        # close the period at next rebalance open
        period = 0.0
        for k, qty in q.items():
            if k in closed:
                gain = closed[k]
            else:
                px = dt.o(k, nxt) or mark[k]
                gain = qty * (px - entry[k])
            period += gain
            if k != LONG:
                contrib[k] = contrib.get(k, 0.0) + gain
        eq = base + period + fund_acc
        q = {k: v for k, v in q.items() if k not in closed}
        entry = {k: dt.o(k, nxt) for k in q if dt.o(k, nxt)}
        q = {k: v for k, v in q.items() if k in entry}
    return curve, contrib


def stats(curve, start_eq=1.0):
    eqs = [e for _, e in curve]
    peak, mdd = start_eq, 0.0
    for x in eqs:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak)
    rets = [b / a - 1 for a, b in zip([start_eq] + eqs, eqs)]
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0
    sharpe = (statistics.mean(rets) - USDC_APR / 365) / sd * math.sqrt(365) if sd else 0.0
    return {"ret": eqs[-1] / start_eq - 1, "mdd": mdd, "sharpe": sharpe}


def main() -> None:
    dt = Data(load())
    print("History:", ", ".join(f"{k} {dt.first[k]}→{dt.last[k]}" for k in UNIVERSE))
    all_mondays, d = [], date(2024, 1, 1)
    while d + timedelta(days=7) < HOLDOUT_CUTOFF:
        all_mondays.append(d)
        d += timedelta(days=7)
    start = next(m for m in all_mondays if len([k for k in UNIVERSE if dt.eligible(k, m)]) >= MIN_NAMES)
    mondays = [m for m in all_mondays if m >= start]
    end = mondays[-1] + timedelta(days=7)
    years = (end - start).days / 365
    usdc = (1 + USDC_APR) ** years - 1
    print(f"\nWindow {start} → {end} ({years:.2f} years, {len(mondays)} weeks). USDC at 6%: {usdc * 100:+.1f}%")
    print("Eligible names per month:", " ".join(f"{m:%y-%m}:{len([k for k in UNIVERSE if dt.eligible(k, m)])}" for m in mondays[::4]))

    variants = [("all", 1), ("all", 4), ("weakest", 1), ("weakest", 4)]
    results = {}
    print("\nvariant              cost    return   Sharpe(xs 6%)  maxDD   SOL leg vs basket")
    for mode, every in variants:
        for cl, c in (("base", BASE_COST), ("stress", STRESS_COST)):
            curve, contrib = simulate(dt, mondays, end, mode, every, c, UNIVERSE)
            st = stats(curve)
            results[(mode, every, cl)] = (st, curve, contrib)
            print(f"{mode:8} every {every}w     {cl:6}  {st['ret'] * 100:+7.1f}%    {st['sharpe']:6.2f}     {st['mdd'] * 100:5.1f}%")

    st, curve, contrib = results[("all", 1, "base")]
    print("\nPrimary (all, weekly, base): per-token contribution (fraction of starting equity, shorts incl. funding)")
    for k, v in sorted(contrib.items(), key=lambda kv: -kv[1]):
        if k != LONG:
            print(f"  {k:11} {v * 100:+7.1f}%")

    # 8-week blocks on the primary at stress cost
    st_s, curve_s, _ = results[("all", 1, "stress")]
    eq_by_day = dict(curve_s)
    blocks, b0, prev = [], start, 1.0
    while b0 + timedelta(days=56) <= end:
        b1 = b0 + timedelta(days=55)
        e1 = eq_by_day.get(b1)
        if e1 is not None:
            blocks.append(e1 / prev - 1)
            prev = e1
        b0 += timedelta(days=56)
    pos_blocks = sum(1 for x in blocks if x > 0)
    print(f"\n8-week blocks (primary, stress): {' '.join(f'{x * 100:+.0f}%' for x in blocks)}")

    top = max((k for k in contrib if k != LONG), key=lambda k: contrib[k])
    ex_curve, _ = simulate(dt, mondays, end, "all", 1, BASE_COST, [k for k in UNIVERSE if k != top])
    ex = stats(ex_curve)
    var_wins = sum(1 for mode, every in variants if results[(mode, every, "base")][0]["ret"] > usdc)

    checks = [
        (f"primary beats USDC 6% under stress ({st_s['ret'] * 100:+.1f}% vs {usdc * 100:+.1f}%)", st_s["ret"] > usdc),
        (f"positive in >=70% of 8-week blocks ({pos_blocks}/{len(blocks)})", len(blocks) > 0 and pos_blocks / len(blocks) >= 0.70),
        (f"max drawdown <= 30% ({st['mdd'] * 100:.1f}%)", st["mdd"] <= 0.30),
        (f"without top contributor {top}: beats USDC 6% ({ex['ret'] * 100:+.1f}%)", ex["ret"] > usdc),
        (f">=3 of 4 variants beat USDC 6% at base ({var_wins}/4)", var_wins >= 3),
    ]
    print("\nPre-registered criteria:")
    for text, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")


if __name__ == "__main__":
    main()
