"""One desk cycle, in this order:

1. gather prices and safety facts
2. protective exits (take-profit, stop-loss, time stop, safety breach) — always, even when halted or the model is down
3. halts (kill switch flattens everything to the quote token; other halts only stop new entries)
4. ask the proposer, risk-gate its proposals, get approval, paper-fill via a Jupiter quote

All sizes are in USD; amounts sent to Jupiter and cash in the ledger are in quote-token units (SOL when SOL is the
quote), converted at the live quote price.
"""

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


STABLE_QUOTES = {"USDC", "USDT"}


@dataclass
class MarketData:
    info: dict[str, dict]
    prices: dict[str, float]
    safety: dict[str, SafetyReport]
    quote_px: float = 1.0  # USD price of the quote token


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
        q = self.s.quote
        mints = [t.mint for t in self.s.tokens] + [q.mint]
        info = self.jupiter.token_info(mints)
        missing = [t.symbol for t in self.s.tokens if t.mint not in info]
        if missing:
            raise RuntimeError(f"Jupiter returned no data for {', '.join(missing)}")
        prices = {m: float(i["usdPrice"]) for m, i in info.items() if i.get("usdPrice")}
        quote_px = prices.pop(q.mint, None)
        if quote_px is None:
            if q.symbol not in STABLE_QUOTES:
                raise RuntimeError(f"no USD price for quote token {q.symbol}")
            quote_px = 1.0
        self.ledger.ensure_starting_cash_quote(quote_px)
        self.ledger.set_state("last_quote_price_usd", repr(quote_px))
        safety = {t.mint: screen(t, self.rpc.mint_info(t.mint), info[t.mint], self.s.risk) for t in self.s.tokens}
        return MarketData(info=info, prices=prices, safety=safety, quote_px=quote_px)

    def build_packet(self, md: MarketData) -> dict:
        book = self.ledger.book(md.quote_px)
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
            "quote_price_usd": md.quote_px,
            "tokens": tokens,
            "portfolio": {
                "cash_quote": round(book.cash_quote, 6),
                "cash_usd": round(book.cash_usd, 2),
                "equity_usd": round(book.equity(md.prices), 2),
                "equity_quote": round(book.equity_quote(md.prices), 6),
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

    def _quote(self, token: Token, side: str, size_usd: float, price: float, quote_px: float) -> Quote:
        """Buy: spend `size_usd` worth of the quote token. Sell: `size_usd` worth of the token, capped at the position."""
        q = self.s.quote
        slip = self.s.risk.slippage_bps
        if side == "buy":
            return self.jupiter.quote(q.mint, token.mint, int(size_usd / quote_px * 10**q.decimals), slip)
        pos = self.ledger.book(quote_px).positions[token.mint]
        qty = min(size_usd / price, pos.qty)
        return self._quote_sell_qty(token, qty)

    def _quote_sell_qty(self, token: Token, qty: float) -> Quote:
        return self.jupiter.quote(token.mint, self.s.quote.mint, int(qty * 10**token.decimals), self.s.risk.slippage_bps)

    def _paper_fill(self, ticket: TradeTicket, quote_px: float) -> str:
        """Fill at the quoted output, haircut by half the slippage tolerance to stay on the conservative side.
        Records the quote-token amount that moved and its USD value at the live quote price."""
        qt, tk, quote = self.s.quote, ticket.token, ticket.quote
        haircut = 1 - (self.s.risk.slippage_bps / 2) / 10_000
        if ticket.side == "buy":
            quote_amount = quote.in_amount / 10**qt.decimals
            qty = quote.out_amount / 10**tk.decimals * haircut
        else:
            qty = quote.in_amount / 10**tk.decimals
            quote_amount = quote.out_amount / 10**qt.decimals * haircut
        usd = quote_amount * quote_px
        self.ledger.record_fill(ticket.proposal_id, tk.mint, tk.symbol, ticket.side, qty, usd,
                                self.s.network_fee_usd, quote.price_impact_bps, quote_amount=quote_amount,
                                quote_price_usd=quote_px, fee_quote=self.s.network_fee_usd / quote_px)
        return (f"PAPER {ticket.side.upper()} {qty:,.6g} {tk.symbol} for {quote_amount:,.6g} {qt.symbol} "
                f"(${usd:,.2f}, impact {quote.price_impact_bps:.1f} bps)")

    def _exit_ticket(self, token: Token, qty: float, usd: float, reason: str, quote: Quote) -> TradeTicket:
        return TradeTicket(proposal_id=0, token=token, side="sell", size_usd=usd, confidence=1.0, edge_bps=0.0,
                           costs_bps=0.0, thesis=f"Protective exit: {reason}", invalidation="", notes=[reason], quote=quote)

    def _protective_exits(self, md: MarketData, flatten_reason: str | None = None) -> list[str]:
        """Sell positions that hit take-profit / stop-loss / time stop or now fail the safety screen.
        With `flatten_reason` (kill switch), sell everything. Measured in quote-token terms (the plan's numeraire)."""
        log: list[str] = []
        now_dt = utcnow()
        for mint, pos in list(self.ledger.book(md.quote_px).positions.items()):
            token = self.s.token(mint)
            if not token or pos.qty <= 0:
                continue
            price = md.prices.get(mint, 0.0)
            reason = flatten_reason
            if reason is None:
                if price <= 0:
                    continue
                should_exit, reason = risk.check_position_exit(
                    pos.qty, pos.avg_price_quote, price / md.quote_px, self.ledger.last_fill_ts(mint), now_dt, self.s.risk)
                safety_rep = md.safety.get(mint)
                if not should_exit and safety_rep and not safety_rep.ok:
                    should_exit, reason = True, f"safety screen breached: {'; '.join(safety_rep.failures)}"
                if not should_exit:
                    continue
            try:
                quote = self._quote_sell_qty(token, pos.qty)
                log.append(f"PROTECTIVE EXIT {token.symbol}: {reason}")
                log.append(self._paper_fill(self._exit_ticket(token, pos.qty, pos.qty * price, reason, quote), md.quote_px))
            except Exception as e:
                log.append(f"PROTECTIVE EXIT ERROR for {token.symbol}: {e}")
        return log

    def _kill_switch_on(self) -> bool:
        return (self.workdir / self.s.risk.kill_switch_file).exists()

    # --- cycle --------------------------------------------------------------

    def _error(self, msg: str) -> CycleResult:
        n = int(self.ledger.get_state("consecutive_errors", "0")) + 1
        self.ledger.set_state("consecutive_errors", str(n))
        return CycleResult(status="error", message=f"{msg} (consecutive errors: {n})")

    def cycle(self) -> CycleResult:
        try:
            md = self.gather()
        except Exception as e:  # network, RPC, Jupiter
            result = self._error(f"market data failed: {e}")
            if self._kill_switch_on():
                # No fresh prices, but the kill switch must still flatten: sell by quantity, value at the last quote price.
                last_px = float(self.ledger.get_state("last_quote_price_usd", "0") or 0) or 1.0
                result.log += self._protective_exits(MarketData({}, {}, {}, last_px), flatten_reason="kill switch (no fresh prices)")
            return result

        result = CycleResult(status="ok")
        # 1. Protective exits always run first: no halt, model outage or entry throttle may block risk reduction.
        result.log += self._protective_exits(md)

        book = self.ledger.book(md.quote_px)
        equity_q = book.equity_quote(md.prices)
        self.ledger.snapshot_equity(book.equity(md.prices), book.cash_usd, equity_q)

        # 2. Halts. Losses are measured in quote terms (vs holding the quote token), valued at the live quote price.
        day_open_q = self.ledger.day_open_equity()
        halt = risk.global_halt(self.s.risk, self.workdir, equity_q * md.quote_px,
                                day_open_q * md.quote_px if day_open_q is not None else None,
                                int(self.ledger.get_state("consecutive_errors", "0")))
        if halt:
            if self._kill_switch_on():
                result.log += self._protective_exits(md, flatten_reason="kill switch")
            return CycleResult(status="halted", message=halt, log=result.log)
        if self.proposer is None:
            return CycleResult(status="error", message="no proposer configured", log=result.log)

        # 3. Ask the proposer.
        packet = self.build_packet(md)
        started = time.monotonic()
        try:
            opinion, raw = self.proposer.propose(packet)
        except Exception as e:
            self.ledger.record_decision(self.proposer.model, packet, None, str(e), time.monotonic() - started)
            err = self._error(f"model call failed: {e}")
            err.log = result.log + err.log
            return err
        decision_id = self.ledger.record_decision(self.proposer.model, packet, raw, None, time.monotonic() - started)
        self.ledger.set_state("consecutive_errors", "0")
        result.market_view = opinion["market_view"]

        # 4. Evaluate new proposals.
        if not opinion["proposals"]:
            result.log.append("No proposals (hold).")
        safety_ok = {m: r.ok for m, r in md.safety.items()}
        for p in opinion["proposals"]:
            token = self.s.token(p["mint"])
            price = md.prices.get(p["mint"])
            verdict = risk.check_proposal(
                p, self.s.risk, self.ledger.book(md.quote_px), md.prices, safety_ok,
                trades_used_today=self.ledger.fills_today(), last_fill_at=self.ledger.last_fill_ts(p["mint"]),
            )
            quote = None
            costs = 0.0
            if verdict.ok:
                try:
                    quote = self._quote(token, p["side"], verdict.size_usd, price, md.quote_px)
                    sw_err = risk.check_anti_sandwich(quote.price_impact_bps, self.s.risk.slippage_bps, self.s.risk)
                    if sw_err:
                        verdict.reasons.append(sw_err)
                    costs = risk.cost_bps(quote.price_impact_bps, self.s.risk.slippage_bps, self.s.network_fee_usd, verdict.size_usd)
                    reason = risk.check_costs(p["expected_edge_bps"], costs, self.s.risk.edge_cost_multiple)
                    if reason and p["side"] == "buy":  # never refuse an exit for being "too expensive"
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
            result.log.append(self._paper_fill(ticket, md.quote_px))
        return result
