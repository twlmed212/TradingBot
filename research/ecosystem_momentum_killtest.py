"""Solana ecosystem cross-sectional momentum vs SOL — kill test.

Rules are frozen in research/registry/2026-10-25-ecosystem-momentum-killtest.md.

    python3 research/ecosystem_momentum_killtest.py

Downloads Binance daily klines for the research window only (cached under data/), prices every token in SOL,
runs the registered weekly walk-forward and prints the verdict. Never loads bars on or after the holdout cutoff.
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
CACHE = ROOT / "data" / "binance_ecosystem_daily_research.json"

RESEARCH_START = date(2023, 6, 1)
HOLDOUT_CUTOFF = date(2025, 7, 1)  # sealed: never load bars on or after this date
# token -> Binance symbols in chronological order (RENDER was RNDR until 2024-07-22)
UNIVERSE = {
    "RAY": ["RAYUSDT"], "GMT": ["GMTUSDT"], "FIDA": ["FIDAUSDT"], "BONK": ["BONKUSDT"], "JTO": ["JTOUSDT"],
    "JUP": ["JUPUSDT"], "PYTH": ["PYTHUSDT"], "WIF": ["WIFUSDT"], "BOME": ["BOMEUSDT"], "W": ["WUSDT"],
    "TNSR": ["TNSRUSDT"], "IO": ["IOUSDT"], "RENDER": ["RNDRUSDT", "RENDERUSDT"], "PNUT": ["PNUTUSDT"],
    "ACT": ["ACTUSDT"], "ORCA": ["ORCAUSDT"], "ME": ["MEUSDT"], "PENGU": ["PENGUUSDT"], "TRUMP": ["TRUMPUSDT"],
    "LAYER": ["LAYERUSDT"], "KMNO": ["KMNOUSDT"],
}
LOOKBACKS = (7, 14, 28)
TOP_K = (1, 3, 5)
MIN_HISTORY_DAYS = 30
MIN_MEDIAN_QUOTE_VOL = 5_000_000
BASE_COST, STRESS_COST = 0.0015, 0.0030
STAKE_APR = 0.06
TRAIN_START = date(2024, 1, 1)
TRAIN_MONTHS, TEST_MONTHS, N_FOLDS = 4, 2, 7


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return d.replace(year=d.year + m // 12, month=m % 12 + 1)


def fetch(symbol: str) -> list[list]:
    start = int(datetime(RESEARCH_START.year, RESEARCH_START.month, RESEARCH_START.day, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(HOLDOUT_CUTOFF.year, HOLDOUT_CUTOFF.month, HOLDOUT_CUTOFF.day, tzinfo=timezone.utc).timestamp() * 1000) - 1
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime={start}&endTime={end}&limit=1000"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def load() -> dict:
    """{token: {date_iso: (open_usd, close_usd, quote_vol_usd)}} including SOL."""
    if CACHE.exists():
        raw = json.loads(CACHE.read_text())
    else:
        raw = {}
        for token, symbols in {"SOL": ["SOLUSDT"], **UNIVERSE}.items():
            rows = {}
            for s in symbols:
                for k in fetch(s):
                    d = datetime.fromtimestamp(k[0] / 1000, timezone.utc).date().isoformat()
                    rows[d] = (float(k[1]), float(k[4]), float(k[7]))
                time.sleep(0.2)
            raw[token] = rows
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(raw))
    last = max(d for rows in raw.values() for d in rows)
    if date.fromisoformat(last) >= HOLDOUT_CUTOFF:
        raise SystemExit("refusing to run: data reaches into the sealed holdout")
    return raw


class Market:
    def __init__(self, raw: dict):
        self.sol = raw["SOL"]
        self.tok = {t: rows for t, rows in raw.items() if t != "SOL"}
        self.first = {t: min(rows) for t, rows in self.tok.items() if rows}

    def px_sol(self, token: str, d: date, field: int) -> float | None:
        """Price in SOL on day d (field 0=open, 1=close), carrying the last close across short gaps."""
        rows = self.tok[token]
        for back in range(0, 5):
            k = (d - timedelta(days=back)).isoformat()
            if k in rows and k in self.sol:
                f = field if back == 0 else 1
                return rows[k][f] / self.sol[k][f]
        return None

    def eligible(self, token: str, monday: date) -> bool:
        first = self.first.get(token)
        if first is None or date.fromisoformat(first) > monday - timedelta(days=MIN_HISTORY_DAYS):
            return False
        vols = [self.tok[token][k][2] for k in ((monday - timedelta(days=i)).isoformat() for i in range(1, 31)) if k in self.tok[token]]
        return len(vols) >= 20 and statistics.median(vols) >= MIN_MEDIAN_QUOTE_VOL

    def score(self, token: str, monday: date, lookback: int) -> float | None:
        a = self.px_sol(token, monday - timedelta(days=1 + lookback), 1)
        b = self.px_sol(token, monday - timedelta(days=1), 1)
        return b / a - 1 if a and b else None

    def week_return(self, token: str, monday: date) -> float:
        a = self.px_sol(token, monday, 0)
        b = self.px_sol(token, monday + timedelta(days=7), 0)
        return b / a if a and b else 1.0


def mondays(a: date, b: date, purge: bool = False) -> list[date]:
    """Rebalance Mondays in [a, b). With purge=True a week must also end by b (training windows: no label overlap
    into the following test window). A week must always end before the holdout cutoff."""
    d = a + timedelta(days=(7 - a.weekday()) % 7)
    out = []
    while d < b and d + timedelta(days=7) < HOLDOUT_CUTOFF:
        if not purge or d + timedelta(days=7) <= b:
            out.append(d)
        d += timedelta(days=7)
    return out


def momentum_targets(m: Market, monday: date, lookback: int, k: int) -> dict[str, float]:
    scored = []
    for t in m.tok:
        if m.eligible(t, monday):
            s = m.score(t, monday, lookback)
            if s is not None and s > 0:
                scored.append((s, t))
    scored.sort(reverse=True)
    return {t: 1.0 / k for _, t in scored[:k]}


def basket_targets(m: Market, monday: date) -> dict[str, float]:
    el = [t for t in m.tok if m.eligible(t, monday)]
    return {t: 1.0 / len(el) for t in el} if el else {}


def simulate(m: Market, weeks: list[date], targets_for, cost: float, stake_apr: float):
    """Returns (weekly returns, equity curve, turnover). Weights are token->fraction; the rest is SOL."""
    stake_w = (1 + stake_apr) ** (7 / 365) - 1
    eq, w, rets, curve, turnover = 1.0, {}, [], [], 0.0
    for monday in weeks:
        tgt = targets_for(monday)
        traded = sum(abs(tgt.get(t, 0) - w.get(t, 0)) for t in set(tgt) | set(w))
        turnover += traded
        eq_before = eq
        eq *= 1 - cost * traded
        w = dict(tgt)
        growth = {t: m.week_return(t, monday) for t in w}
        sol_w = 1 - sum(w.values())
        port = sum(wt * growth[t] for t, wt in w.items()) + sol_w * (1 + stake_w)
        eq *= port
        w = {t: wt * growth[t] / port for t, wt in w.items()}
        rets.append(eq / eq_before - 1)
        curve.append(eq)
    return rets, curve, turnover


def metrics(rets: list[float], curve: list[float], stake_apr: float) -> dict:
    stake_w = (1 + stake_apr) ** (7 / 365) - 1
    xs = [r - stake_w for r in rets]
    sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
    peak, mdd = 1.0, 0.0
    for x in curve:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak)
    return {"ret": curve[-1] - 1 if curve else 0.0, "sharpe": statistics.mean(xs) / sd * math.sqrt(52) if sd else 0.0, "mdd": mdd}


def main() -> None:
    m = Market(load())
    print("History per token (SOL terms):", ", ".join(f"{t} from {m.first[t]}" for t in sorted(m.first, key=m.first.get)))

    variants = {(lb, k): (lambda d, lb=lb, k=k: momentum_targets(m, d, lb, k)) for lb in LOOKBACKS for k in TOP_K}
    folds = []
    for i in range(N_FOLDS):
        tr0 = add_months(TRAIN_START, i * TEST_MONTHS)
        te0 = add_months(tr0, TRAIN_MONTHS)
        te1 = min(add_months(te0, TEST_MONTHS), HOLDOUT_CUTOFF)
        folds.append((mondays(tr0, te0, purge=True), mondays(te0, te1), te0, te1))

    stake = lambda weeks: (1 + STAKE_APR) ** (7 * len(weeks) / 365) - 1  # noqa: E731
    print("\nfold  test window              chosen(L,K)  train Sharpe   strat   stakedSOL  EW basket  SOL/USD  beat")
    chosen: dict[date, tuple] = {}
    wins = 0
    for i, (train_w, test_w, te0, te1) in enumerate(folds):
        scores = {v: metrics(*simulate(m, train_w, f, BASE_COST, STAKE_APR)[:2], STAKE_APR)["sharpe"] for v, f in variants.items()}
        best = max(scores, key=scores.get)
        for d in test_w:
            chosen[d] = best
        s = metrics(*simulate(m, test_w, variants[best], BASE_COST, STAKE_APR)[:2], STAKE_APR)
        b = metrics(*simulate(m, test_w, lambda d: basket_targets(m, d), BASE_COST, STAKE_APR)[:2], STAKE_APR)
        sol_usd = m.sol[(test_w[-1] + timedelta(days=7)).isoformat()][0] / m.sol[test_w[0].isoformat()][0] - 1
        win = s["ret"] > stake(test_w)
        wins += win
        print(f"{i + 1:4}  {te0} -> {te1}   L={best[0]:>2} K={best[1]}    {scores[best]:6.2f}     {s['ret'] * 100:+6.1f}%   "
              f"{stake(test_w) * 100:+5.1f}%   {b['ret'] * 100:+7.1f}%  {sol_usd * 100:+6.1f}%   {'yes' if win else 'no'}")

    outer = [d for _, test_w, _, _ in folds for d in test_w]
    wf = lambda d: variants[chosen[d]](d)  # noqa: E731
    stake_outer = stake(outer)
    print(f"\nOuter period {outer[0]} -> {outer[-1] + timedelta(days=7)} ({len(outer)} weeks). Staked SOL: {stake_outer * 100:+.1f}% (SOL terms)")
    print("strategy             cost    stake  return(SOL)  Sharpe(xs)   maxDD   turnover")
    res = {}
    for label, f in (("walk-forward", wf), ("equal-weight basket", lambda d: basket_targets(m, d))):
        for cl, c in (("base", BASE_COST), ("stress", STRESS_COST)):
            for sl, sa in (("6%", STAKE_APR), ("0%", 0.0)):
                rets, curve, turn = simulate(m, outer, f, c, sa)
                res[(label, cl, sl)] = metrics(rets, curve, sa)
                r = res[(label, cl, sl)]
                print(f"{label:19}  {cl:6}  {sl:>4}   {r['ret'] * 100:+8.1f}%    {r['sharpe']:6.2f}    {r['mdd'] * 100:5.1f}%   {turn:6.1f}x")

    print("\nFixed variants over the outer period (base cost, 6% staking, SOL terms):")
    vwins = 0
    for v, f in variants.items():
        r = metrics(*simulate(m, outer, f, BASE_COST, STAKE_APR)[:2], STAKE_APR)
        ok = r["ret"] > stake_outer
        vwins += ok
        print(f"  L={v[0]:>2}d K={v[1]}  {r['ret'] * 100:+8.1f}%  Sharpe {r['sharpe']:5.2f}  maxDD {r['mdd'] * 100:5.1f}%  {'beats staked SOL' if ok else ''}")

    wb, ws, eb = res[("walk-forward", "base", "6%")], res[("walk-forward", "stress", "6%")], res[("equal-weight basket", "base", "6%")]
    checks = [
        (f"beats staked SOL in >=5 of 7 folds ({wins}/7)", wins >= 5),
        (f"beats staked SOL under stress costs ({ws['ret'] * 100:+.1f}% vs {stake_outer * 100:+.1f}%)", ws["ret"] > stake_outer),
        (f"Sharpe > 0 and above equal-weight basket ({wb['sharpe']:.2f} vs {eb['sharpe']:.2f})", wb["sharpe"] > 0 and wb["sharpe"] > eb["sharpe"]),
        (f"max drawdown in SOL terms <= 40% ({wb['mdd'] * 100:.1f}%)", wb["mdd"] <= 0.40),
        (f">=6 of 9 fixed variants beat staked SOL ({vwins}/9)", vwins >= 6),
    ]
    print("\nPre-registered criteria:")
    for text, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    print(f"\nVERDICT: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")


if __name__ == "__main__":
    main()
