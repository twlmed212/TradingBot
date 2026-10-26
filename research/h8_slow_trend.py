"""H8: slow trend filter on SOL vs USDC — kill test. Rules: research/registry/2026-10-25-h8-slow-trend-sol.md.

    python3 research/h8_slow_trend.py

Binance daily klines (cached in data/), nothing on or after 2025-07-01.
"""

from __future__ import annotations

import json
import math
import statistics
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = date(2025, 7, 1)
WIN_A = (date(2021, 3, 1), date(2023, 5, 31))
WIN_B = (date(2023, 6, 1), date(2025, 6, 30))
USDC_APR = 0.05
BASE, STRESS = 0.0010, 0.0020
VARIANTS = [("sma", 50), ("sma", 100), ("sma", 200), ("mom", 28), ("mom", 56), ("mom", 112)]
PRIMARY = ("sma", 100)


def closes(symbol: str) -> dict[date, float]:
    cache = ROOT / "data" / f"binance_{symbol}_1d_to_2025-06-30.json"
    if not cache.exists():
        rows, start = [], int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        end = int(datetime(2025, 7, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1
        while start < end:
            with urllib.request.urlopen(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime={start}&endTime={end}&limit=1000", timeout=30) as r:
                chunk = json.loads(r.read())
            if not chunk:
                break
            rows += [(k[0], float(k[4])) for k in chunk]
            start = chunk[-1][0] + 86_400_000
            time.sleep(0.2)
        cache.write_text(json.dumps(rows))
    out = {datetime.fromtimestamp(t / 1000, timezone.utc).date(): c for t, c in json.loads(cache.read_text())}
    assert max(out) < CUTOFF, "holdout leak"
    return out


def signals(px: dict[date, float], kind: str, n: int) -> dict[date, int]:
    days = sorted(px)
    out = {}
    for i, d in enumerate(days):
        if i < n:
            continue
        if kind == "sma":
            out[d] = int(px[d] > sum(px[days[j]] for j in range(i - n + 1, i + 1)) / n)
        else:
            out[d] = int(px[d] > px[days[i - n]])
    return out


def run(px, sig, win, cost):
    days = [d for d in sorted(px) if win[0] <= d <= win[1]]
    cash_d = (1 + USDC_APR) ** (1 / 365) - 1
    eq, pos, curve, trades = 1.0, None, [], 0
    for prev, d in zip(days, days[1:]):
        # position held over (prev, d] was decided from the signal two closes back (one full day of delay)
        decided = sig.get(prev - timedelta(days=1))
        target = decided if decided is not None else 0
        if pos is None:
            pos = target
        elif target != pos:
            eq *= 1 - cost
            trades += 1
            pos = target
        eq *= (px[d] / px[prev]) if pos else (1 + cash_d)
        curve.append((d, eq))
    return curve, trades


def stats(curve):
    eqs = [1.0] + [e for _, e in curve]
    rets = [b / a - 1 for a, b in zip(eqs, eqs[1:])]
    cash_d = (1 + USDC_APR) ** (1 / 365) - 1
    xs = [r - cash_d for r in rets]
    sd = statistics.pstdev(xs)
    peak, mdd = 1.0, 0.0
    for x in eqs:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak)
    return {"ret": eqs[-1] - 1, "sharpe": statistics.mean(xs) / sd * math.sqrt(365) if sd else 0.0, "mdd": mdd}


def hold(px, win):
    days = [d for d in sorted(px) if win[0] <= d <= win[1]]
    return [(d, px[d] / px[days[0]]) for d in days[1:]]


def main():
    sol = closes("SOLUSDT")
    out, primary = {}, {}
    for label, win in (("A", WIN_A), ("B", WIN_B)):
        years = (win[1] - win[0]).days / 365
        usdc = (1 + USDC_APR) ** years - 1
        h = stats(hold(sol, win))
        print(f"\nWindow {label} {win[0]} → {win[1]}: hold SOL {h['ret'] * 100:+.0f}% (Sharpe {h['sharpe']:.2f}, maxDD {h['mdd'] * 100:.0f}%), USDC 5% {usdc * 100:+.1f}%")
        for kind, n in VARIANTS:
            sig = signals(sol, kind, n)
            for cl, c in (("base", BASE), ("stress", STRESS)):
                curve, trades = run(sol, sig, win, c)
                st = stats(curve)
                out[(label, kind, n, cl)] = (st, curve, trades)
                if cl == "base" or (kind, n) == PRIMARY:
                    print(f"  {kind}{n:<4}{' (primary)' if (kind, n) == PRIMARY else '          '} {cl:6} {st['ret'] * 100:+8.0f}%  Sharpe {st['sharpe']:5.2f}  maxDD {st['mdd'] * 100:4.0f}%  trades {trades}")
        primary[label] = (out[(label, *PRIMARY, "base")][0], out[(label, *PRIMARY, "stress")][0], h, usdc)

    # robustness on BTC / ETH, window A
    robust = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        px = closes(sym)
        st = stats(run(px, signals(px, *PRIMARY), WIN_A, BASE)[0])
        h = stats(hold(px, WIN_A))
        robust.append(st["sharpe"] > h["sharpe"])
        print(f"\n{sym[:3]} window A: primary {st['ret'] * 100:+.0f}% Sharpe {st['sharpe']:.2f} maxDD {st['mdd'] * 100:.0f}% | hold {h['ret'] * 100:+.0f}% Sharpe {h['sharpe']:.2f} maxDD {h['mdd'] * 100:.0f}%")

    # best-month removal (window A, primary, base): drop that month's daily returns
    st_a, curve_a, _ = out[("A", *PRIMARY, "base")]
    eqs = [1.0] + [e for _, e in curve_a]
    rets = [(d, eqs[i + 1] / eqs[i] - 1) for i, (d, _) in enumerate(curve_a)]
    monthly = {}
    for d, r in rets:
        monthly[(d.year, d.month)] = monthly.get((d.year, d.month), 1.0) * (1 + r)
    best = max(monthly, key=monthly.get)
    cash_d = (1 + USDC_APR) ** (1 / 365) - 1
    xs = [r - cash_d for d, r in rets if (d.year, d.month) != best]
    sharpe_ex = statistics.mean(xs) / statistics.pstdev(xs) * math.sqrt(365)
    vwins = sum(1 for kind, n in VARIANTS if out[("A", kind, n, "base")][0]["sharpe"] > primary["A"][2]["sharpe"])

    pa, pb = primary["A"], primary["B"]
    checks = [
        (f"Sharpe above holding SOL: A {pa[0]['sharpe']:.2f} vs {pa[2]['sharpe']:.2f}, B {pb[0]['sharpe']:.2f} vs {pb[2]['sharpe']:.2f}",
         pa[0]["sharpe"] > pa[2]["sharpe"] and pb[0]["sharpe"] > pb[2]["sharpe"]),
        (f"max drawdown <= 60% of SOL's: A {pa[0]['mdd'] * 100:.0f}% vs {pa[2]['mdd'] * 100:.0f}%, B {pb[0]['mdd'] * 100:.0f}% vs {pb[2]['mdd'] * 100:.0f}%",
         pa[0]["mdd"] <= 0.6 * pa[2]["mdd"] and pb[0]["mdd"] <= 0.6 * pb[2]["mdd"]),
        (f"beats USDC 5% under stress: A {pa[1]['ret'] * 100:+.0f}% vs {pa[3] * 100:+.0f}%, B {pb[1]['ret'] * 100:+.0f}% vs {pb[3] * 100:+.0f}%",
         pa[1]["ret"] > pa[3] and pb[1]["ret"] > pb[3]),
        (f">= 4 of 6 variants beat SOL's Sharpe in A ({vwins}/6)", vwins >= 4),
        (f"beats buy-and-hold Sharpe on BTC or ETH in A (BTC {robust[0]}, ETH {robust[1]})", any(robust)),
        (f"without best month {best[0]}-{best[1]:02d}: Sharpe {sharpe_ex:.2f} vs SOL {pa[2]['sharpe']:.2f}", sharpe_ex > pa[2]["sharpe"]),
    ]
    print("\nPre-registered criteria:")
    for t, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {t}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")


if __name__ == "__main__":
    main()
