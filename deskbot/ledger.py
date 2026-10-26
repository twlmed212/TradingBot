"""SQLite paper ledger. Every model output, risk verdict, approval and fill is kept so you can audit the copilot."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    model TEXT,
    packet_json TEXT,
    response_json TEXT,
    error TEXT,
    latency_s REAL
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    decision_id INTEGER NOT NULL REFERENCES decisions(id),
    ts TEXT NOT NULL,
    mint TEXT NOT NULL,
    symbol TEXT,
    side TEXT NOT NULL,
    size_usd REAL,
    confidence REAL,
    edge_bps REAL,
    horizon_hours REAL,
    thesis TEXT,
    invalidation TEXT,
    price_usd REAL,
    risk_ok INTEGER NOT NULL,
    risk_reasons TEXT,
    approved INTEGER,
    approval_note TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER REFERENCES proposals(id),
    ts TEXT NOT NULL,
    mint TEXT NOT NULL,
    symbol TEXT,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    usd REAL NOT NULL,
    fee_usd REAL NOT NULL,
    price_impact_bps REAL
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    equity_usd REAL NOT NULL,
    cash_usd REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Columns added after the first schema; existing databases are migrated in place.
MIGRATIONS = {
    "fills": {"quote_amount": "REAL", "quote_price_usd": "REAL", "fee_quote": "REAL"},
    "equity": {"equity_quote": "REAL"},
}


@dataclass
class Position:
    mint: str
    symbol: str
    qty: float = 0.0
    cost_usd: float = 0.0    # average-cost basis of the open quantity, in USD at fill time
    cost_quote: float = 0.0  # same basis in quote-token units (SOL when SOL is the quote)

    @property
    def avg_price(self) -> float:
        return self.cost_usd / self.qty if self.qty else 0.0

    @property
    def avg_price_quote(self) -> float:
        return self.cost_quote / self.qty if self.qty else 0.0


@dataclass
class Book:
    """Cash is held in the quote token. `quote_price_usd` converts it; 1.0 for a USD stablecoin quote."""
    cash_quote: float
    positions: dict[str, Position]
    realized_pnl_usd: float
    realized_pnl_quote: float
    fees_usd: float
    quote_price_usd: float = 1.0

    @property
    def cash_usd(self) -> float:
        return self.cash_quote * self.quote_price_usd

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(p.qty * prices.get(m, 0.0) for m, p in self.positions.items())

    def equity(self, prices: dict[str, float]) -> float:
        """Total equity in USD at current prices."""
        return self.cash_usd + self.market_value(prices)

    def equity_quote(self, prices: dict[str, float]) -> float:
        """Total equity in quote-token units (the plan's numeraire)."""
        return self.equity(prices) / self.quote_price_usd


class Ledger:
    def __init__(self, path: str, starting_cash_usd: float):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.db.commit()
        self.starting_cash_usd = starting_cash_usd

    def starting_cash_quote(self) -> float:
        """Starting cash in quote units. Fixed once (see ensure_starting_cash_quote); defaults to the USD amount."""
        v = self.get_state("starting_cash_quote")
        return float(v) if v else self.starting_cash_usd

    def ensure_starting_cash_quote(self, quote_price_usd: float) -> None:
        """Convert the configured USD starting cash into quote units at the first price seen, then never again."""
        if not self.get_state("starting_cash_quote"):
            self.set_state("starting_cash_quote", repr(self.starting_cash_usd / quote_price_usd))

    # --- writes -------------------------------------------------------------

    def record_decision(self, model: str, packet: dict, response: dict | None, error: str | None, latency_s: float) -> int:
        cur = self.db.execute(
            "INSERT INTO decisions (ts, model, packet_json, response_json, error, latency_s) VALUES (?,?,?,?,?,?)",
            (utcnow().isoformat(), model, json.dumps(packet), json.dumps(response) if response is not None else None, error, latency_s),
        )
        self.db.commit()
        return cur.lastrowid

    def record_proposal(self, decision_id: int, p: dict, symbol: str, price_usd: float | None, risk_ok: bool, reasons: list[str]) -> int:
        cur = self.db.execute(
            """INSERT INTO proposals (decision_id, ts, mint, symbol, side, size_usd, confidence, edge_bps, horizon_hours,
                                      thesis, invalidation, price_usd, risk_ok, risk_reasons)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                decision_id, utcnow().isoformat(), p["mint"], symbol, p["side"], p.get("size_usd"), p.get("confidence"),
                p.get("expected_edge_bps"), p.get("horizon_hours"), p.get("thesis"), p.get("invalidation"), price_usd,
                int(risk_ok), json.dumps(reasons),
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def set_approval(self, proposal_id: int, approved: bool, note: str = "") -> None:
        self.db.execute("UPDATE proposals SET approved=?, approval_note=? WHERE id=?", (int(approved), note, proposal_id))
        self.db.commit()

    def record_fill(self, proposal_id: int | None, mint: str, symbol: str, side: str, qty: float, usd: float,
                    fee_usd: float, price_impact_bps: float, quote_amount: float | None = None,
                    quote_price_usd: float | None = None, fee_quote: float | None = None) -> None:
        """`usd` is the trade's USD value at fill time. `quote_amount` is what actually moved in quote-token units;
        when omitted (USD stablecoin quote) it equals `usd`."""
        qp = quote_price_usd or 1.0
        self.db.execute(
            """INSERT INTO fills (proposal_id, ts, mint, symbol, side, qty, usd, fee_usd, price_impact_bps,
                                  quote_amount, quote_price_usd, fee_quote) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (proposal_id, utcnow().isoformat(), mint, symbol, side, qty, usd, fee_usd, price_impact_bps,
             quote_amount if quote_amount is not None else usd / qp, qp,
             fee_quote if fee_quote is not None else fee_usd / qp),
        )
        self.db.commit()

    def snapshot_equity(self, equity_usd: float, cash_usd: float, equity_quote: float | None = None) -> None:
        now = utcnow()
        self.db.execute("INSERT INTO equity (ts, day, equity_usd, cash_usd, equity_quote) VALUES (?,?,?,?,?)",
                        (now.isoformat(), now.date().isoformat(), equity_usd, cash_usd, equity_quote))
        self.db.commit()

    def get_state(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO state (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    # --- reads --------------------------------------------------------------

    def book(self, quote_price_usd: float = 1.0) -> Book:
        """Replay all fills. Cash moves in quote units; pass the live quote price to value it in USD."""
        cash = self.starting_cash_quote()
        realized_usd = realized_quote = fees = 0.0
        positions: dict[str, Position] = {}
        for f in self.db.execute("SELECT * FROM fills ORDER BY id"):
            pos = positions.setdefault(f["mint"], Position(f["mint"], f["symbol"]))
            qp = f["quote_price_usd"] or 1.0
            q_amt = f["quote_amount"] if f["quote_amount"] is not None else f["usd"] / qp
            fee_q = f["fee_quote"] if f["fee_quote"] is not None else f["fee_usd"] / qp
            fees += f["fee_usd"]
            cash -= fee_q
            if f["side"] == "buy":
                cash -= q_amt
                pos.qty += f["qty"]
                pos.cost_usd += f["usd"]
                pos.cost_quote += q_amt
            else:
                cash += q_amt
                share = f["qty"] / pos.qty if pos.qty else 1.0
                basis_usd, basis_quote = pos.cost_usd * share, pos.cost_quote * share
                realized_usd += f["usd"] - basis_usd
                realized_quote += q_amt - basis_quote
                pos.qty -= f["qty"]
                pos.cost_usd -= basis_usd
                pos.cost_quote -= basis_quote
                if pos.qty <= 1e-12:
                    pos.qty, pos.cost_usd, pos.cost_quote = 0.0, 0.0, 0.0
        positions = {m: p for m, p in positions.items() if p.qty > 0}
        return Book(cash_quote=cash, positions=positions, realized_pnl_usd=realized_usd,
                    realized_pnl_quote=realized_quote, fees_usd=fees, quote_price_usd=quote_price_usd)

    def fills_today(self) -> int:
        day = utcnow().date().isoformat()
        return self.db.execute("SELECT COUNT(*) FROM fills WHERE substr(ts,1,10)=?", (day,)).fetchone()[0]

    def last_fill_ts(self, mint: str) -> datetime | None:
        row = self.db.execute("SELECT ts FROM fills WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,)).fetchone()
        return datetime.fromisoformat(row["ts"]) if row else None

    def day_open_equity(self) -> float | None:
        """Equity at the first snapshot of the UTC day, in quote units (USD for snapshots taken before the migration)."""
        day = utcnow().date().isoformat()
        row = self.db.execute("SELECT equity_usd, equity_quote FROM equity WHERE day=? ORDER BY ts LIMIT 1", (day,)).fetchone()
        if not row:
            return None
        return row["equity_quote"] if row["equity_quote"] is not None else row["equity_usd"]

    def recent_proposals(self, limit: int = 8) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts, symbol, side, size_usd, confidence, thesis, risk_ok, approved FROM proposals ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def all_proposals(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM proposals ORDER BY id").fetchall()

    def counts(self) -> dict:
        q = lambda sql: self.db.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "decisions": q("SELECT COUNT(*) FROM decisions"),
            "decision_errors": q("SELECT COUNT(*) FROM decisions WHERE error IS NOT NULL"),
            "proposals": q("SELECT COUNT(*) FROM proposals"),
            "risk_passed": q("SELECT COUNT(*) FROM proposals WHERE risk_ok=1"),
            "approved": q("SELECT COUNT(*) FROM proposals WHERE approved=1"),
            "fills": q("SELECT COUNT(*) FROM fills"),
        }
