"""SOL/USDC dual-horizon trend kill test. Rules are frozen in research/registry/2026-10-25-trend-killtest.md.

    python3 research/trend_killtest.py

Downloads Binance SOLUSDT 15m klines for the research window only (cached under data/), runs the registered
walk-forward, and prints the pass/fail verdict for each criterion. Never loads bars on or after the holdout cutoff.
"""

from __future__ import annotations

import json
import math
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "binance_SOLUSDT_15m_research.json"

BAR_MS = 15 * 60 * 1000
BARS_PER_DAY = 96
BARS_PER_YEAR = BARS_PER_DAY * 365
RESEARCH_START = datetime(2023, 6, 1, tzinfo=timezone.utc)
HOLDOUT_CUTOFF = datetime(2025, 7, 1, tzinfo=timezone.utc)  # sealed: never load bars at or after this

FAST_HOURS = (4, 12, 24)
SLOW_DAYS = (3, 7, 14)
VOL_TARGET = 0.50
VOL_DAYS = 7
BAND = 0.10
BASE_COST = 0.0005
STRESS_COST = 0.0010
CASH_APR = 0.06
TRAIN_MONTHS, TEST_MONTHS = 6, 3
N_FOLDS = 6


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def add_months(dt: datetime, n: int) -> datetime:
    m = dt.month - 1 + n
    return dt.replace(year=dt.year + m // 12, month=m % 12 + 1)


def load_bars() -> list[tuple[int, float]]:
    """[(open_time_ms, open_price)] for the research window."""
    if CACHE.exists():
        bars = json.loads(CACHE.read_text())
    else:
        bars, start, end = [], ms(RESEARCH_START), ms(HOLDOUT_CUTOFF) - 1
        while start <= end:
            url = (f"https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=15m"
                   f"&startTime={start}&endTime={end}&limit=1000")
            with urllib.request.urlopen(url, timeout=30) as r:
                chunk = json.loads(r.read())
            if not chunk:
                break
            bars += [(k[0], float(k[1])) for k in chunk]
            start = chunk[-1][0] + BAR_MS
            time.sleep(0.2)
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(bars))
    if bars[-1][0] >= ms(HOLDOUT_CUTOFF):
        raise SystemExit("refusing to run: data reaches into the sealed holdout")
    gaps = sum(1 for a, b in zip(bars, bars[1:]) if b[0] - a[0] != BAR_MS)
    print(f"{len(bars)} bars {iso(bars[0][0])} -> {iso(bars[-1][0])}, {gaps} timestamp gaps")
    return bars


def iso(t: int) -> str:
    return datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")


def target_weights(px: list[float], fast_h: int, slow_d: int) -> list[float]:
    """w[i] is decided from prices up to bar i-1's close (= bar i's open) and held over bar i."""
    f, s, v = fast_h * 4, slow_d * BARS_PER_DAY, VOL_DAYS * BARS_PER_DAY
    logr = [0.0] + [math.log(px[i] / px[i - 1]) for i in range(1, len(px))]
    # rolling sums for realized vol
    w = [0.0] * len(px)
    s1 = s2 = 0.0
    for i in range(1, len(px)):
        s1 += logr[i]
        s2 += logr[i] ** 2
        if i > v:
            s1 -= logr[i - v]
            s2 -= logr[i - v] ** 2
        # decision for bar i+1 uses px[..i]
        if i + 1 < len(px) and i >= max(s, v):
            var = max(s2 / v - (s1 / v) ** 2, 1e-12)
            vol = math.sqrt(var * BARS_PER_YEAR)
            signal = px[i] > px[i - f] and px[i] > px[i - s]
            w[i + 1] = min(1.0, VOL_TARGET / vol) if signal else 0.0
    return w


def simulate(px, target, i0, i1, cost, cash_apr, band=BAND, w0=0.0):
    """Equity path over bars [i0, i1). Returns (equity list per bar, turnover)."""
    cash_r = cash_apr / BARS_PER_YEAR
    eq, w, out, turnover = 1.0, w0, [], 0.0
    for i in range(i0, i1):
        tgt = target[i]
        if abs(tgt - w) >= band or (tgt == 0.0 and w > 0.0):
            eq *= 1 - cost * abs(tgt - w)
            turnover += abs(tgt - w)
            w = tgt
        r = px[i + 1] / px[i] - 1 if i + 1 < len(px) else 0.0
        eq *= 1 + w * r + (1 - w) * cash_r
        out.append(eq)
    return out, turnover


def metrics(eq: list[float], cash_apr: float) -> dict:
    daily = [eq[i] for i in range(BARS_PER_DAY - 1, len(eq), BARS_PER_DAY)]
    rets = [b / a - 1 for a, b in zip([1.0] + daily, daily)]
    excess = [r - cash_apr / 365 for r in rets]
    sd = statistics.pstdev(excess) if len(excess) > 1 else 0.0
    sharpe = statistics.mean(excess) / sd * math.sqrt(365) if sd > 0 else 0.0
    peak, mdd = 1.0, 0.0
    for x in eq:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak)
    return {"ret": eq[-1] - 1, "sharpe": sharpe, "mdd": mdd}


def main() -> None:
    bars = load_bars()
    t = [b[0] for b in bars]
    px = [b[1] for b in bars]
    idx = lambda dt: next(i for i, x in enumerate(t) if x >= ms(dt))  # noqa: E731

    variants = {(fh, sd): target_weights(px, fh, sd) for fh in FAST_HOURS for sd in SLOW_DAYS}
    hold = [1.0] * len(px)
    half = [0.5] * len(px)

    first_test = add_months(RESEARCH_START, TRAIN_MONTHS)
    folds = []
    for k in range(N_FOLDS):
        ts = add_months(first_test, k * TEST_MONTHS)
        folds.append((idx(add_months(ts, -TRAIN_MONTHS)), idx(ts), idx(add_months(ts, TEST_MONTHS))))
    outer0, outer1 = folds[0][1], folds[-1][2]

    print(f"\nOuter test period {iso(t[outer0])} -> {iso(t[outer1 - 1])}; holdout from {HOLDOUT_CUTOFF.date()} stays sealed\n")
    print("fold  test window              chosen(F,S)  train Sharpe   strat    USDC6%   hold SOL  beat USDC")
    chosen_target = [0.0] * len(px)
    fold_wins = 0
    for k, (tr0, te0, te1) in enumerate(folds):
        scores = {v: metrics(simulate(px, w, tr0, te0, BASE_COST, CASH_APR)[0], CASH_APR)["sharpe"] for v, w in variants.items()}
        best = max(scores, key=scores.get)
        chosen_target[te0:te1] = variants[best][te0:te1]
        s = metrics(simulate(px, variants[best], te0, te1, BASE_COST, CASH_APR)[0], CASH_APR)
        cash = (1 + CASH_APR / BARS_PER_YEAR) ** (te1 - te0) - 1
        h = metrics(simulate(px, hold, te0, te1, BASE_COST, CASH_APR)[0], CASH_APR)
        win = s["ret"] > cash
        fold_wins += win
        print(f"{k + 1:4}  {iso(t[te0])} -> {iso(t[te1 - 1])}   {best[0]:>2}h,{best[1]:>2}d     {scores[best]:6.2f}     "
              f"{s['ret'] * 100:+6.1f}%  {cash * 100:+6.1f}%  {h['ret'] * 100:+7.1f}%   {'yes' if win else 'no'}")

    cash_outer = (1 + CASH_APR / BARS_PER_YEAR) ** (outer1 - outer0) - 1
    rows = {}
    for label, target in (("walk-forward", chosen_target), ("buy & hold SOL", hold)):
        for cost_label, cost in (("base", BASE_COST), ("stress", STRESS_COST)):
            for cash_label, cash_apr in (("6%", CASH_APR), ("0%", 0.0)):
                eq, turn = simulate(px, target, outer0, outer1, cost, cash_apr)
                rows[(label, cost_label, cash_label)] = (metrics(eq, cash_apr), turn)
    # 50/50 daily rebalance: target 0.5 with the band disabled once per day
    eq, w, cash_r = 1.0, 0.0, CASH_APR / BARS_PER_YEAR
    fifty = []
    for i in range(outer0, outer1):
        if (i - outer0) % BARS_PER_DAY == 0:
            eq *= 1 - BASE_COST * abs(0.5 - w)
            w = 0.5
        r = px[i + 1] / px[i] - 1 if i + 1 < len(px) else 0.0
        eq_before = eq
        eq *= 1 + w * r + (1 - w) * cash_r
        sol_val = w * eq_before * (1 + r)
        w = sol_val / eq
        fifty.append(eq)
    m50 = metrics(fifty, CASH_APR)

    years = (outer1 - outer0) / BARS_PER_YEAR
    print(f"\nWhole outer period ({years:.2f} years). USDC at 6%: {cash_outer * 100:+.1f}%")
    print("strategy          cost    cash   return   Sharpe(xs)   maxDD   turnover")
    for (label, c, cash), (m, turn) in rows.items():
        print(f"{label:16}  {c:6}  {cash:>4}  {m['ret'] * 100:+7.1f}%   {m['sharpe']:6.2f}    {m['mdd'] * 100:5.1f}%   {turn:6.1f}x")
    print(f"{'50/50 daily':16}  base      6%  {m50['ret'] * 100:+7.1f}%   {m50['sharpe']:6.2f}    {m50['mdd'] * 100:5.1f}%")

    print("\nFixed variants over the whole outer period (base cost, 6% cash):")
    variant_wins = 0
    for v, w in variants.items():
        m = metrics(simulate(px, w, outer0, outer1, BASE_COST, CASH_APR)[0], CASH_APR)
        win = m["ret"] > cash_outer
        variant_wins += win
        print(f"  F={v[0]:>2}h S={v[1]:>2}d  {m['ret'] * 100:+7.1f}%  Sharpe {m['sharpe']:5.2f}  maxDD {m['mdd'] * 100:5.1f}%  {'beats USDC' if win else ''}")

    wf_base = rows[("walk-forward", "base", "6%")][0]
    wf_stress = rows[("walk-forward", "stress", "6%")][0]
    bh = rows[("buy & hold SOL", "base", "6%")][0]
    checks = [
        (f"beats USDC in >=5 of 6 folds ({fold_wins}/6)", fold_wins >= 5),
        (f"beats USDC under stress costs ({wf_stress['ret'] * 100:+.1f}% vs {cash_outer * 100:+.1f}%)", wf_stress["ret"] > cash_outer),
        (f"Sharpe above buy & hold ({wf_base['sharpe']:.2f} vs {bh['sharpe']:.2f})", wf_base["sharpe"] > bh["sharpe"]),
        (f"max drawdown <= 25% ({wf_base['mdd'] * 100:.1f}%)", wf_base["mdd"] <= 0.25),
        (f">=6 of 9 fixed variants beat USDC ({variant_wins}/9)", variant_wins >= 6),
    ]
    print("\nPre-registered criteria:")
    for text, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")


if __name__ == "__main__":
    main()
