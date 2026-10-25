"""One desk cycle: gather data -> screen -> ask Grok -> risk gate -> human/rule approval -> paper fill via Jupiter quote."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import risk
from .config import Settings, Token
from .jupiter import Jupiter, Quote
from .ledger import Ledger, utcnow
from .safety import SafetyReport, SolanaRpc, screen

STAT_KEYS = ("priceChange", "liquidityChange", "holderChange", "buyVolume", "sellVolume", "numBuys", "numSells", "numTraders")
NOTES_MAX_CHARS = 4000


class Proposer(Protocol):
    model: str

    def propose(self, packet: dict) -> tuple[dict, dict]: ...


@dataclass
class TradeTicket:
    proposal_id: int
    token: Token
    side: str
    size_usd: float
    confidence: float
    edge_bps: float
    costs_bps: float
    thesis: str
    invalidation: str
    notes: list[str]
    quote: Quote


# Returns (approved, note). Manual mode asks the human; auto mode approves anything that passed risk.
Approver = Callable[[TradeTicket], tuple[bool, str]]


@dataclass
class MarketData:
    info: dict[str, dict]
    prices: dict[str, float]
    safety: dict[str, SafetyReport]


@dataclass
class CycleResult:
    status: str  # "ok" | "halted" | "error"
    message: str = ""
    market_view: str = ""
    log: list[str] = field(default_factory=list)


def _round(v):
    return round(v, 4) if isinstance(v, float) else v


class Desk:
    def __init__(self, settings: Settings, ledger: Ledger, jupiter: Jupiter, rpc: SolanaRpc,
                 proposer: Proposer | None, approver: Approver, workdir: Path):
        self.s = settings
        self.ledger = ledger
        self.jupiter = jupiter
        self.rpc = rpc
        self.proposer = proposer
        self.approver = approver
        self.workdir = workdir

    # --- data ---------------------------------------------------------------

    def gather(self) -> MarketData:
        mints = [t.mint for t in self.s.tokens]
        info = self.jupiter.token_info(mints)
        missing = [t.symbol for t in self.s.tokens if t.mint not in info]
        if missing:
            raise RuntimeError(f"Jupiter returned no data for {', '.join(missing)}")
        prices = {m: float(i["usdPrice"]) for m, i in info.items() if i.get("usdPrice")}
        safety = {t.mint: screen(t, self.rpc.mint_info(t.mint), info[t.mint], self.s.risk) for t in self.s.tokens}
        return MarketData(info=info, prices=prices, safety=safety)

    def build_packet(self, md: MarketData) -> dict:
        book = self.ledger.book()
        lim = self.s.risk
        tokens = []
        for t in self.s.tokens:
            i = md.info[t.mint]
            stats = {}
            for window in ("5m", "1h", "6h", "24h"):
                w = i.get(f"stats{window}") or {}
                stats[window] = {k: _round(w[k]) for k in STAT_KEYS if k in w}
            sr = md.safety[t.mint]
            tokens.append({
                "symbol": t.symbol,
                "mint": t.mint,
                "price_usd": md.prices.get(t.mint),
                "liquidity_usd": _round(i.get("liquidity")),
                "mcap_usd": _round(i.get("mcap")),
                "holder_count": i.get("holderCount"),
                "organic_score": _round(i.get("organicScore")),
                "stats": stats,
                "safety": {"ok": sr.ok, "failures": sr.failures, "facts": sr.facts},
            })
        positions = []
        for m, p in book.positions.items():
            px = md.prices.get(m, 0.0)
            positions.append({
                "symbol": p.symbol, "mint": m, "qty": _round(p.qty), "avg_price_usd": p.avg_price, "price_usd": px,
                "value_usd": round(p.qty * px, 2), "unrealized_pnl_usd": round(p.qty * px - p.cost_usd, 2),
            })
        notes = ""
        notes_file = self.workdir / self.s.notes_path
        if notes_file.exists():
            notes = notes_file.read_text()[:NOTES_MAX_CHARS]
        return {
            "now_utc": utcnow().isoformat(timespec="seconds"),
            "mode": "paper",
            "quote_asset": self.s.quote.symbol,
            "tokens": tokens,
            "portfolio": {
                "cash_usd": round(book.cash_usd, 2),
                "equity_usd": round(book.equity(md.prices), 2),
                "realized_pnl_usd": round(book.realized_pnl_usd, 2),
                "positions": positions,
            },
            "limits": {
                "trades_left_today": max(lim.max_trades_per_day - self.ledger.fills_today(), 0),
                "max_position_usd": lim.max_position_usd,
                "max_gross_exposure_usd": lim.max_gross_exposure_usd,
                "min_trade_usd": lim.min_trade_usd,
                "min_confidence": lim.min_confidence,
                "slippage_bps": lim.slippage_bps,
                "network_fee_usd": self.s.network_fee_usd,
                "edge_cost_multiple": lim.edge_cost_multiple,
                "mint_cooldown_minutes": lim.mint_cooldown_minutes,
            },
            "recent_proposals": self.ledger.recent_proposals(),
            "trader_notes": notes,
        }

    # --- execution (paper) --------------------------------------------------

    def _quote(self, token: Token, side: str, size_usd: float, price: float) -> Quote:
        q = self.s.quote
        slip = self.s.risk.slippage_bps
        if side == "buy":
            return self.jupiter.quote(q.mint, token.mint, int(size_usd * 10**q.decimals), slip)
        pos = self.ledger.book().positions[token.mint]
        qty = min(size_usd / price, pos.qty)
        return self.jupiter.quote(token.mint, q.mint, int(qty * 10**token.decimals), slip)

    def _paper_fill(self, ticket: TradeTicket) -> str:
        """Fill at the quoted output, haircut by half the slippage tolerance to stay on the conservative side."""
        qt, tk, quote = self.s.quote, ticket.token, ticket.quote
        haircut = 1 - (self.s.risk.slippage_bps / 2) / 10_000
        if ticket.side == "buy":
            usd = quote.in_amount / 10**qt.decimals
            qty = quote.out_amount / 10**tk.decimals * haircut
        else:
            qty = quote.in_amount / 10**tk.decimals
            usd = quote.out_amount / 10**qt.decimals * haircut
        self.ledger.record_fill(ticket.proposal_id, tk.mint, tk.symbol, ticket.side, qty, usd,
                                self.s.network_fee_usd, quote.price_impact_bps)
        return f"PAPER {ticket.side.upper()} {qty:,.6g} {tk.symbol} for ${usd:,.2f} (impact {quote.price_impact_bps:.1f} bps)"

    # --- cycle --------------------------------------------------------------

    def _error(self, msg: str) -> CycleResult:
        n = int(self.ledger.get_state("consecutive_errors", "0")) + 1
        self.ledger.set_state("consecutive_errors", str(n))
        return CycleResult(status="error", message=f"{msg} (consecutive errors: {n})")

    def cycle(self) -> CycleResult:
        try:
            md = self.gather()
        except Exception as e:  # network, RPC, Jupiter
            return self._error(f"market data failed: {e}")

        book = self.ledger.book()
        equity = book.equity(md.prices)
        day_open = self.ledger.day_open_equity()
        self.ledger.snapshot_equity(equity, book.cash_usd)
        halt = risk.global_halt(self.s.risk, self.workdir, equity, day_open,
                                int(self.ledger.get_state("consecutive_errors", "0")))
        if halt:
            return CycleResult(status="halted", message=halt)
        if self.proposer is None:
            return CycleResult(status="error", message="no proposer configured")

        packet = self.build_packet(md)
        started = time.monotonic()
        try:
            opinion, raw = self.proposer.propose(packet)
        except Exception as e:
            self.ledger.record_decision(self.proposer.model, packet, None, str(e), time.monotonic() - started)
            return self._error(f"model call failed: {e}")
        decision_id = self.ledger.record_decision(self.proposer.model, packet, raw, None, time.monotonic() - started)
        self.ledger.set_state("consecutive_errors", "0")

        result = CycleResult(status="ok", market_view=opinion["market_view"])

        # 1. Automated Protective Exits (Bypasses entry throttles and halts)
        now_dt = utcnow()
        for mint, pos in list(book.positions.items()):
            price = md.prices.get(mint, 0.0)
            token = self.s.token(mint)
            if not token or price <= 0 or pos.qty <= 0:
                continue
            entry_ts = self.ledger.last_fill_ts(mint)
            should_exit, exit_reason = risk.check_position_exit(
                pos.qty, pos.avg_price, price, entry_ts, now_dt, self.s.risk
            )
            safety_rep = md.safety.get(mint)
            if not should_exit and safety_rep and not safety_rep.ok:
                should_exit = True
                exit_reason = f"safety screen breached: {'; '.join(safety_rep.failures)}"

            if should_exit:
                try:
                    exit_size_usd = pos.qty * price
                    quote = self._quote(token, "sell", exit_size_usd, price)
                    ticket = TradeTicket(
                        proposal_id=0,
                        token=token,
                        side="sell",
                        size_usd=exit_size_usd,
                        confidence=1.0,
                        edge_bps=0.0,
                        costs_bps=0.0,
                        thesis=f"Protective Exit: {exit_reason}",
                        invalidation="",
                        notes=[exit_reason],
                        quote=quote,
                    )
                    result.log.append(f"PROTECTIVE EXIT {token.symbol}: {exit_reason}")
                    result.log.append(self._paper_fill(ticket))
                except Exception as e:
                    result.log.append(f"PROTECTIVE EXIT ERROR for {token.symbol}: {e}")

        # 2. Evaluate New Proposals
        if not opinion["proposals"]:
            result.log.append("No proposals (hold).")
        safety_ok = {m: r.ok for m, r in md.safety.items()}
        for p in opinion["proposals"]:
            token = self.s.token(p["mint"])
            price = md.prices.get(p["mint"])
            verdict = risk.check_proposal(
                p, self.s.risk, self.ledger.book(), md.prices, safety_ok,
                trades_used_today=self.ledger.fills_today(), last_fill_at=self.ledger.last_fill_ts(p["mint"]),
            )
            quote = None
            costs = 0.0
            if verdict.ok:
                try:
                    quote = self._quote(token, p["side"], verdict.size_usd, price)
                    # Anti-sandwich verification
                    sw_err = risk.check_anti_sandwich(quote.price_impact_bps, self.s.risk.slippage_bps, self.s.risk)
                    if sw_err:
                        verdict.reasons.append(sw_err)
                    costs = risk.cost_bps(quote.price_impact_bps, self.s.risk.slippage_bps, self.s.network_fee_usd, verdict.size_usd)
                    reason = risk.check_costs(p["expected_edge_bps"], costs, self.s.risk.edge_cost_multiple)
                    if reason:
                        verdict.reasons.append(reason)
                except Exception as e:
                    verdict.reasons.append(f"quote failed: {e}")
                verdict.ok = not verdict.reasons
            pid = self.ledger.record_proposal(decision_id, p, token.symbol, price, verdict.ok, verdict.reasons + verdict.notes)
            label = f"{p['side'].upper()} {token.symbol} ${p['size_usd']:.2f} (conf {p['confidence']:.2f}, edge {p['expected_edge_bps']:.0f} bps)"
            if not verdict.ok:
                result.log.append(f"REJECTED {label}: {'; '.join(verdict.reasons)}")
                continue
            ticket = TradeTicket(pid, token, p["side"], verdict.size_usd, p["confidence"], p["expected_edge_bps"], costs,
                                 p["thesis"], p["invalidation"], verdict.notes, quote)
            approved, note = self.approver(ticket)
            self.ledger.set_approval(pid, approved, note)
            if not approved:
                result.log.append(f"DECLINED {label}" + (f": {note}" if note else ""))
                continue
            result.log.append(self._paper_fill(ticket))
        return result
