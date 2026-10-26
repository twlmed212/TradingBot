"""Forward Jupiter quote recorder (PLAN.md Milestone 1).

Every interval it probes Jupiter Swap API V2 `/order` (quote only: no taker, so no transaction is built) for
SOL->USDC and USDC->SOL at fixed USD notionals, plus Jupiter Price V3 and Binance spot as reference prices.
It also probes ecosystem tokens against SOL (both directions) from a universe file, a round-robin slice per cycle
so every token is covered every `--universe-slices` cycles without bursting the keyless rate limit.
Everything goes into an append-only SQLite file. Each cycle row records whether every expected snapshot
arrived, so gaps (laptop sleep, network loss, rate limits) are explicit rather than silently missing.

Standard library only, so it can run unattended without a virtualenv:

    python3 recorder/quote_recorder.py --db data/quotes.sqlite3 --universe recorder/universe.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DECIMALS = {SOL: 9, USDC: 6}
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    expected INTEGER NOT NULL,
    recorded INTEGER NOT NULL,
    errors TEXT
);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES cycles(cycle_id),
    observed_at TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    schema_version INTEGER NOT NULL,
    source TEXT NOT NULL,
    input_mint TEXT NOT NULL,
    output_mint TEXT NOT NULL,
    notional_usd REAL NOT NULL,
    in_amount INTEGER NOT NULL,
    out_amount INTEGER NOT NULL,
    fee_bps REAL,
    price_impact_pct REAL,
    router TEXT,
    route_labels TEXT,
    request_id TEXT,
    in_usd REAL,
    out_usd REAL,
    payload_sha256 TEXT NOT NULL,
    payload_zlib BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_prices (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES cycles(cycle_id),
    observed_at TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price_usd REAL NOT NULL,
    payload_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS quotes_observed ON quotes(observed_at);
"""

_stop = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _get(url: str, headers: dict[str, str], timeout: float = 10.0) -> tuple[bytes, float]:
    req = urllib.request.Request(url, headers={"User-Agent": "deskbot-recorder/1", **headers})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body, (time.monotonic() - t0) * 1000


class Recorder:
    def __init__(self, db_path: str, base_url: str, api_key: str, notionals: list[float],
                 universe: list[dict] | None = None, universe_notionals: list[float] | None = None,
                 universe_slices: int = 5, pause: float = 1.0):
        self.db = sqlite3.connect(db_path)
        self.db.executescript(SCHEMA)
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.notionals = notionals
        self.universe = universe or []
        self.universe_notionals = universe_notionals or []
        self.universe_slices = max(1, universe_slices)
        self.n_cycles = 0
        self.pause = pause  # seconds between API requests; spreads a cycle across the minute

    def _ref_prices(self, cycle_id: int, errors: list[str]) -> float | None:
        """Returns the Jupiter SOL price (used to size SOL->USDC probes); records both references."""
        jup_price = None
        sources = [
            ("jupiter_price_v3", f"{self.base_url}/price/v3?ids={SOL}", self.headers,
             lambda d: float(d[SOL]["usdPrice"])),
            ("binance_spot", "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", {},
             lambda d: float(d["price"])),
        ]
        for source, url, headers, parse in sources:
            observed_at = _now()
            try:
                body, ms = _get(url, headers)
                price = parse(json.loads(body))
            except Exception as e:
                errors.append(f"{source}: {e}")
                continue
            self.db.execute(
                "INSERT INTO ref_prices (cycle_id, observed_at, latency_ms, source, symbol, price_usd, payload_sha256) VALUES (?,?,?,?,?,?,?)",
                (cycle_id, observed_at, ms, source, "SOL", price, hashlib.sha256(body).hexdigest()),
            )
            if source == "jupiter_price_v3":
                jup_price = price
        return jup_price

    def _universe_prices(self, cycle_id: int, tokens: list[dict], errors: list[str]) -> dict[str, float]:
        """One batched Jupiter Price V3 call for this cycle's slice; returns {mint: usd_price}."""
        observed_at = _now()
        try:
            body, ms = _get(f"{self.base_url}/price/v3?ids={','.join(t['mint'] for t in tokens)}", self.headers)
            data = json.loads(body)
        except Exception as e:
            errors.append(f"universe prices: {e}")
            return {}
        digest = hashlib.sha256(body).hexdigest()
        prices = {}
        for t in tokens:
            if t["mint"] in data and data[t["mint"]].get("usdPrice"):
                prices[t["mint"]] = float(data[t["mint"]]["usdPrice"])
                self.db.execute(
                    "INSERT INTO ref_prices (cycle_id, observed_at, latency_ms, source, symbol, price_usd, payload_sha256) VALUES (?,?,?,?,?,?,?)",
                    (cycle_id, observed_at, ms, "jupiter_price_v3", t["symbol"], prices[t["mint"]], digest),
                )
        return prices

    def _quote(self, cycle_id: int, input_mint: str, output_mint: str, notional: float, in_price_usd: float,
               in_decimals: int) -> None:
        amount = int(notional / in_price_usd * 10 ** in_decimals)
        query = urllib.parse.urlencode({"inputMint": input_mint, "outputMint": output_mint, "amount": amount})
        observed_at = _now()
        body, ms = _get(f"{self.base_url}/swap/v2/order?{query}", self.headers)
        d = json.loads(body)
        if "outAmount" not in d:
            raise RuntimeError(d.get("error") or d.get("errorMessage") or "no outAmount")
        labels = [step.get("swapInfo", {}).get("label") for step in d.get("routePlan", [])]
        self.db.execute(
            """INSERT INTO quotes (cycle_id, observed_at, latency_ms, schema_version, source, input_mint, output_mint,
                   notional_usd, in_amount, out_amount, fee_bps, price_impact_pct, router, route_labels, request_id,
                   in_usd, out_usd, payload_sha256, payload_zlib)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cycle_id, observed_at, ms, SCHEMA_VERSION, "jupiter_swap_v2_order", input_mint, output_mint, notional,
                int(d["inAmount"]), int(d["outAmount"]), d.get("feeBps"),
                float(d["priceImpactPct"]) if d.get("priceImpactPct") is not None else None,
                d.get("router"), json.dumps(labels), d.get("requestId"),
                d.get("inUsdValue"), d.get("outUsdValue"),
                hashlib.sha256(body).hexdigest(), zlib.compress(body, 6),
            ),
        )

    def cycle(self) -> tuple[int, int, list[str]]:
        started_at = _now()
        slice_tokens = self.universe[self.n_cycles % self.universe_slices::self.universe_slices]
        self.n_cycles += 1
        expected = 2 + 2 * len(self.notionals)
        if slice_tokens:
            expected += 1 + 2 * len(self.universe_notionals) * len(slice_tokens)
        cur = self.db.execute(
            "INSERT INTO cycles (started_at, finished_at, expected, recorded) VALUES (?,?,?,0)",
            (started_at, started_at, expected),
        )
        cycle_id = cur.lastrowid
        errors: list[str] = []
        sol_price = self._ref_prices(cycle_id, errors)
        recorded = 2 - len(errors)
        if sol_price is None:
            errors.append("no Jupiter SOL price; skipped quote probes")
        else:
            for notional in self.notionals:
                for pair in ((USDC, SOL), (SOL, USDC)):
                    in_price, in_dec = (1.0, DECIMALS[USDC]) if pair[0] == USDC else (sol_price, DECIMALS[SOL])
                    try:
                        self._quote(cycle_id, *pair, notional, in_price, in_dec)
                        recorded += 1
                    except Exception as e:
                        errors.append(f"{'buy' if pair[0] == USDC else 'sell'} ${notional:g}: {e}")
                    time.sleep(self.pause)  # stay under keyless rate limits
            if slice_tokens:
                prices = self._universe_prices(cycle_id, slice_tokens, errors)
                recorded += 1 if prices else 0
                for t in slice_tokens:
                    px = prices.get(t["mint"])
                    if px is None:
                        errors.append(f"{t['symbol']}: no price; skipped")
                        continue
                    for notional in self.universe_notionals:
                        for side, pair, in_px, in_dec in (("buy", (SOL, t["mint"]), sol_price, DECIMALS[SOL]),
                                                          ("sell", (t["mint"], SOL), px, t["decimals"])):
                            try:
                                self._quote(cycle_id, *pair, notional, in_px, in_dec)
                                recorded += 1
                            except Exception as e:
                                errors.append(f"{t['symbol']} {side} ${notional:g}: {e}")
                            time.sleep(self.pause)
        self.db.execute(
            "UPDATE cycles SET finished_at=?, recorded=?, errors=? WHERE cycle_id=?",
            (_now(), recorded, json.dumps(errors) if errors else None, cycle_id),
        )
        self.db.commit()
        return recorded, expected, errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/quotes.sqlite3")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between cycle starts")
    ap.add_argument("--notionals", default="100,1000,10000,100000", help="comma-separated USD probe sizes")
    ap.add_argument("--base-url", default="https://api.jup.ag")
    ap.add_argument("--api-key", default="", help="Jupiter API key (optional; raises rate limits)")
    ap.add_argument("--universe", default="", help="JSON file with {'tokens': [{symbol, mint, decimals}]} to probe vs SOL")
    ap.add_argument("--universe-notionals", default="1000,10000", help="USD probe sizes for universe tokens")
    ap.add_argument("--universe-slices", type=int, default=5, help="cycles needed to cover the whole universe once")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between API requests (keyless Jupiter rate limit)")
    ap.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = ap.parse_args()

    universe = json.loads(open(args.universe).read())["tokens"] if args.universe else []
    rec = Recorder(args.db, args.base_url, args.api_key, [float(x) for x in args.notionals.split(",")],
                   universe, [float(x) for x in args.universe_notionals.split(",")], args.universe_slices, args.pause)

    def handle(signum, frame):  # finish the current cycle, then exit
        global _stop
        _stop = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    while True:
        t0 = time.monotonic()
        recorded, expected, errors = rec.cycle()
        status = "ok" if recorded == expected else f"GAP {recorded}/{expected}: {'; '.join(errors)[:300]}"
        print(f"{_now()} {status}", flush=True)
        if args.once or _stop:
            break
        while not _stop and time.monotonic() - t0 < args.interval:
            time.sleep(0.5)
        if _stop:
            break


if __name__ == "__main__":
    main()
