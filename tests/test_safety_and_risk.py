"""Unit tests for honeypot safety screening, anti-sandwich checks, and risk engine rules."""

from datetime import datetime, timezone, timedelta
import pytest

from deskbot.config import RiskLimits, Token
from deskbot.ledger import Book, Ledger, Position
from deskbot.risk import (
    check_anti_sandwich,
    check_costs,
    check_position_exit,
    check_proposal,
    cost_bps,
    global_halt,
)
from deskbot.safety import (
    extract_token_2022_details,
    screen,
    verify_anti_sandwich,
)


def test_safety_rejects_live_freeze_authority():
    token = Token(symbol="SCAM", mint="Scam111111111111111111111111111111111111111", decimals=9)
    mint_info = {
        "mintAuthority": None,
        "freezeAuthority": "AttackerWallet1111111111111111111111111111",
        "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "extensions": [],
    }
    jup_info = {"liquidity": 100_000, "audit": {"topHoldersPercentage": 15.0, "lpBurned": True}}
    limits = RiskLimits()

    rep = screen(token, mint_info, jup_info, limits)
    assert not rep.ok
    assert any("freeze authority is live" in f for f in rep.failures)


def test_safety_rejects_live_mint_authority():
    token = Token(symbol="INFLATE", mint="Inflate111111111111111111111111111111111111", decimals=9)
    mint_info = {
        "mintAuthority": "DeployerWallet1111111111111111111111111111",
        "freezeAuthority": None,
        "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "extensions": [],
    }
    jup_info = {"liquidity": 100_000, "audit": {"topHoldersPercentage": 15.0, "lpBurned": True}}
    limits = RiskLimits()

    rep = screen(token, mint_info, jup_info, limits)
    assert not rep.ok
    assert any("mint authority is live" in f for f in rep.failures)


def test_safety_rejects_token_2022_honeypot_extensions():
    token = Token(symbol="HOOK", mint="Hook111111111111111111111111111111111111111", decimals=9)
    mint_info = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "program": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "extensions": [
            {"extension": "transferHook", "state": {}},
            {"extension": "permanentDelegate", "state": {}},
        ],
    }
    jup_info = {"liquidity": 100_000, "audit": {"topHoldersPercentage": 10.0, "lpBurned": True}}
    limits = RiskLimits()

    rep = screen(token, mint_info, jup_info, limits)
    assert not rep.ok
    assert any("dangerous Token-2022 honeypot extensions" in f for f in rep.failures)
    assert "transferHook" in str(rep.failures)


def test_safety_rejects_token_2022_transfer_fee():
    token = Token(symbol="TAX", mint="Tax1111111111111111111111111111111111111111", decimals=9)
    mint_info = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "program": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "extensions": [
            {
                "extension": "transferFeeConfig",
                "state": {"newerTransferFee": {"transferFeeBasisPoints": 500}},  # 5% transfer fee
            }
        ],
    }
    jup_info = {"liquidity": 100_000, "audit": {"topHoldersPercentage": 10.0, "lpBurned": True}}
    limits = RiskLimits()

    rep = screen(token, mint_info, jup_info, limits)
    assert not rep.ok
    assert any("hidden transfer fee active: 500 bps" in f for f in rep.failures)


def test_safety_rejects_unburned_lp_when_required():
    token = Token(symbol="RUG", mint="Rug1111111111111111111111111111111111111111", decimals=9)
    mint_info = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "extensions": [],
    }
    jup_info = {"liquidity": 100_000, "audit": {"topHoldersPercentage": 10.0, "lpBurned": False}}
    limits = RiskLimits(require_lp_burned=True)

    rep = screen(token, mint_info, jup_info, limits)
    assert not rep.ok
    assert any("LP tokens are not burned/locked" in f for f in rep.failures)


def test_safety_rejects_low_liquidity():
    token = Token(symbol="THIN", mint="Thin111111111111111111111111111111111111111", decimals=9)
    mint_info = {"mintAuthority": None, "freezeAuthority": None, "extensions": []}
    jup_info = {"liquidity": 5_000, "audit": {"topHoldersPercentage": 10.0}}
    limits = RiskLimits(min_liquidity_usd=25_000.0)

    rep = screen(token, mint_info, jup_info, limits)
    assert not rep.ok
    assert any("below required $25,000" in f for f in rep.failures)


def test_safety_passes_clean_token():
    token = Token(symbol="SAFE", mint="Safe111111111111111111111111111111111111111", decimals=9)
    mint_info = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "extensions": [],
    }
    jup_info = {"liquidity": 150_000, "audit": {"topHoldersPercentage": 15.0, "lpBurned": True}}
    limits = RiskLimits(min_liquidity_usd=25_000.0, require_lp_burned=True)

    rep = screen(token, mint_info, jup_info, limits)
    assert rep.ok
    assert len(rep.failures) == 0


def test_anti_sandwich_checks():
    limits = RiskLimits(slippage_bps=50, max_price_impact_bps=200.0)

    # 1. High slippage invites sandwich
    assert check_anti_sandwich(price_impact_bps=50.0, slippage_bps=100, limits=limits) is not None

    # 2. High price impact invites sandwich
    assert check_anti_sandwich(price_impact_bps=250.0, slippage_bps=30, limits=limits) is not None

    # 3. Clean tight trade passes
    assert check_anti_sandwich(price_impact_bps=40.0, slippage_bps=30, limits=limits) is None


def test_protective_exits():
    limits = RiskLimits(take_profit_pct=15.0, stop_loss_pct=7.0, max_hold_hours=4.0)
    now = datetime.now(timezone.utc)
    entry_time = now - timedelta(hours=1)

    # 1. Take Profit trigger (+20%)
    exit_now, reason = check_position_exit(pos_qty=10.0, avg_price=10.0, current_price=12.0, entry_time=entry_time, now=now, limits=limits)
    assert exit_now
    assert "take-profit triggered" in reason

    # 2. Stop Loss trigger (-10%)
    exit_now, reason = check_position_exit(pos_qty=10.0, avg_price=10.0, current_price=9.0, entry_time=entry_time, now=now, limits=limits)
    assert exit_now
    assert "stop-loss triggered" in reason

    # 3. Normal fluctuation within bounds (+5%)
    exit_now, reason = check_position_exit(pos_qty=10.0, avg_price=10.0, current_price=10.5, entry_time=entry_time, now=now, limits=limits)
    assert not exit_now

    # 4. Time stop trigger (held 5 hours)
    old_entry = now - timedelta(hours=5)
    exit_now, reason = check_position_exit(pos_qty=10.0, avg_price=10.0, current_price=10.2, entry_time=old_entry, now=now, limits=limits)
    assert exit_now
    assert "max holding time exceeded" in reason


def test_ledger_accounting(tmp_path):
    db_file = tmp_path / "test_ledger.sqlite3"
    ledger = Ledger(str(db_file), starting_cash_usd=100.0)

    # Initially empty
    book = ledger.book()
    assert book.cash_usd == 100.0
    assert len(book.positions) == 0

    # Buy 2.0 SOL equivalent of TOKEN at $10 each
    ledger.record_fill(proposal_id=1, mint="TokenA", symbol="TKA", side="buy", qty=10.0, usd=20.0, fee_usd=0.01, price_impact_bps=10.0)

    book = ledger.book()
    assert round(book.cash_usd, 2) == 79.99
    assert book.positions["TokenA"].qty == 10.0
    assert book.positions["TokenA"].cost_usd == 20.0
    assert book.positions["TokenA"].avg_price == 2.0

    # Sell 5.0 of TOKEN at $3 each ($15 total, basis $10, realized pnl +$5)
    ledger.record_fill(proposal_id=2, mint="TokenA", symbol="TKA", side="sell", qty=5.0, usd=15.0, fee_usd=0.01, price_impact_bps=10.0)

    book = ledger.book()
    assert round(book.cash_usd, 2) == 94.98
    assert book.positions["TokenA"].qty == 5.0
    assert round(book.realized_pnl_usd, 2) == 5.0
