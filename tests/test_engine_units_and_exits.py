"""Regression tests for the two Milestone 0 bugs:

1. With SOL as the quote token, USD sizes must be converted to lamports (a "$150" buy is 1.5 SOL at $100, not 150 SOL)
   and the ledger must keep cash in SOL.
2. Protective exits must run even when the model is down or a halt is active; the kill switch flattens to SOL.
"""

from pathlib import Path

import pytest

from deskbot.config import RiskLimits, Settings, Token
from deskbot.engine import Desk
from deskbot.jupiter import Quote
from deskbot.ledger import Ledger
from deskbot.risk import check_proposal

SOL = "So11111111111111111111111111111111111111112"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
TOKENKEG = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


class FakeJupiter:
    """Quotes at fair value from `prices` (USD) with 1 bp impact; records every quote request."""

    def __init__(self, prices: dict[str, float], decimals: dict[str, int]):
        self.prices = prices
        self.decimals = decimals
        self.calls: list[tuple[str, str, int]] = []

    def token_info(self, mints):
        return {m: {"id": m, "usdPrice": self.prices[m], "liquidity": 10_000_000.0,
                    "audit": {"topHoldersPercentage": 10.0}} for m in mints if m in self.prices}

    def quote(self, input_mint, output_mint, amount, slippage_bps):
        self.calls.append((input_mint, output_mint, amount))
        usd = amount / 10 ** self.decimals[input_mint] * self.prices[input_mint]
        out = int(usd / self.prices[output_mint] * 10 ** self.decimals[output_mint])
        return Quote(input_mint, output_mint, amount, out, price_impact_bps=1.0, slippage_bps=slippage_bps)


class FakeRpc:
    def mint_info(self, mint):
        return {"mintAuthority": None, "freezeAuthority": None, "program": TOKENKEG, "extensions": []}


class FixedProposer:
    model = "fake"

    def __init__(self, proposals=None, fail=False):
        self.proposals = proposals or []
        self.fail = fail

    def propose(self, packet):
        if self.fail:
            raise RuntimeError("model unavailable")
        return {"market_view": "test", "proposals": self.proposals}, {}


def make_desk(tmp_path: Path, proposer, sol_px=100.0, jup_px=0.5) -> tuple[Desk, FakeJupiter]:
    settings = Settings(
        quote=Token("SOL", SOL, 9),
        tokens=(Token("JUP", JUP, 6),),
        risk=RiskLimits(max_position_usd=150.0, max_gross_exposure_usd=500.0, take_profit_pct=15.0,
                        stop_loss_pct=7.0, max_hold_hours=4.0, min_liquidity_usd=25_000.0),
        starting_cash_usd=1000.0,
        approve="auto",
    )
    jup = FakeJupiter({SOL: sol_px, JUP: jup_px}, {SOL: 9, JUP: 6})
    ledger = Ledger(str(tmp_path / "paper.sqlite3"), settings.starting_cash_usd)
    desk = Desk(settings, ledger, jup, FakeRpc(), proposer, lambda t: (True, "auto"), tmp_path)
    return desk, jup


def buy(usd=150.0):
    return {"mint": JUP, "side": "buy", "size_usd": usd, "confidence": 0.9, "expected_edge_bps": 500.0,
            "horizon_hours": 4.0, "thesis": "t", "invalidation": "i"}


def seed_position(desk: Desk, qty=300.0, sol_spent=1.5, sol_px=100.0):
    """A JUP position bought at 0.005 SOL per JUP."""
    desk.ledger.ensure_starting_cash_quote(sol_px)
    desk.ledger.record_fill(1, JUP, "JUP", "buy", qty, sol_spent * sol_px, 0.02, 1.0,
                            quote_amount=sol_spent, quote_price_usd=sol_px, fee_quote=0.02 / sol_px)


# --- bug 1: units ------------------------------------------------------------

def test_sol_quote_buy_is_sized_in_lamports(tmp_path):
    desk, jup = make_desk(tmp_path, FixedProposer([buy(150.0)]))
    result = desk.cycle()
    assert result.status == "ok", result
    sol_in = [amount for i, o, amount in jup.calls if i == SOL and o == JUP]
    assert sol_in == [1_500_000_000]  # $150 at $100/SOL = 1.5 SOL, not 150 SOL


def test_ledger_keeps_cash_in_sol(tmp_path):
    desk, _ = make_desk(tmp_path, FixedProposer([buy(150.0)]))
    desk.cycle()
    book = desk.ledger.book(100.0)
    fee_sol = 0.02 / 100.0
    assert book.cash_quote == pytest.approx(10.0 - 1.5 - fee_sol)   # started with $1000 = 10 SOL
    assert book.cash_usd == pytest.approx((10.0 - 1.5 - fee_sol) * 100.0)
    pos = book.positions[JUP]
    assert pos.cost_quote == pytest.approx(1.5)
    assert pos.qty == pytest.approx(300.0 * (1 - 0.0025))           # fair 300 JUP minus the half-slippage haircut
    # If SOL doubles, cash in SOL is unchanged and its USD value doubles.
    assert desk.ledger.book(200.0).cash_usd == pytest.approx(book.cash_usd * 2)


def test_take_profit_is_measured_in_sol_terms(tmp_path):
    # SOL and JUP both rise 20% in USD: JUP/SOL is flat, so no take-profit (a USD-based check would fire).
    desk, _ = make_desk(tmp_path, FixedProposer(), sol_px=120.0, jup_px=0.6)
    seed_position(desk)
    result = desk.cycle()
    assert not any("PROTECTIVE EXIT" in line for line in result.log)
    assert JUP in desk.ledger.book(120.0).positions


# --- bug 2: exits are independent of halts and the model -----------------------

def test_take_profit_exit_runs_when_model_is_down(tmp_path):
    desk, _ = make_desk(tmp_path, FixedProposer(fail=True), sol_px=100.0, jup_px=0.6)  # +20% in SOL terms
    seed_position(desk)
    result = desk.cycle()
    assert result.status == "error"
    assert any("PROTECTIVE EXIT JUP: take-profit" in line for line in result.log)
    assert JUP not in desk.ledger.book(100.0).positions


def test_kill_switch_flattens_to_sol(tmp_path):
    desk, _ = make_desk(tmp_path, FixedProposer([buy(150.0)]))
    seed_position(desk)
    (tmp_path / "STOP").write_text("")
    result = desk.cycle()
    assert result.status == "halted"
    assert any("kill switch" in line for line in result.log)
    assert desk.ledger.book(100.0).positions == {}


def test_kill_switch_flattens_even_without_fresh_prices(tmp_path):
    desk, jup = make_desk(tmp_path, FixedProposer())
    seed_position(desk)
    desk.ledger.set_state("last_quote_price_usd", "100.0")
    (tmp_path / "STOP").write_text("")
    jup.token_info = lambda mints: (_ for _ in ()).throw(RuntimeError("price API down"))
    result = desk.cycle()
    assert result.status == "error"
    assert desk.ledger.book(100.0).positions == {}


def test_model_sell_bypasses_entry_throttles(tmp_path):
    desk, _ = make_desk(tmp_path, FixedProposer())
    seed_position(desk)
    book = desk.ledger.book(100.0)
    sell = {"mint": JUP, "side": "sell", "size_usd": 150.0, "confidence": 0.1, "expected_edge_bps": 0.0}
    verdict = check_proposal(sell, desk.s.risk, book, {JUP: 0.5}, {JUP: True},
                             trades_used_today=99, last_fill_at=None)
    assert verdict.ok, verdict.reasons
