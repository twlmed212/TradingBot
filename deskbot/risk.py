"""Deterministic risk engine. The model proposes; this code decides. No LLM output can widen a limit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import RiskLimits
from .ledger import Book, utcnow


@dataclass
class Verdict:
    ok: bool
    size_usd: float
    reasons: list[str] = field(default_factory=list)  # why it was rejected
    notes: list[str] = field(default_factory=list)  # adjustments made (e.g. size clipped)


def global_halt(limits: RiskLimits, workdir: Path, equity_usd: float, day_open_equity: float | None,
                consecutive_errors: int) -> str | None:
    """Reasons to stop before asking the model anything. Returns a reason string, or None to proceed."""
    if (workdir / limits.kill_switch_file).exists():
        return f"kill switch file '{limits.kill_switch_file}' present"
    if day_open_equity is not None and day_open_equity - equity_usd >= limits.daily_loss_limit_usd:
        return f"daily loss limit hit (down ${day_open_equity - equity_usd:.2f} since UTC day open)"
    if consecutive_errors >= limits.max_consecutive_errors:
        return f"{consecutive_errors} consecutive data/model errors"
    return None


def check_proposal(
    p: dict,
    limits: RiskLimits,
    book: Book,
    prices: dict[str, float],
    safety_ok: dict[str, bool],
    trades_used_today: int,
    last_fill_at: datetime | None,
    now: datetime | None = None,
) -> Verdict:
    """Pre-quote checks. Buys are clipped to the tightest headroom; sells to the open position."""
    now = now or utcnow()
    reasons: list[str] = []
    notes: list[str] = []
    mint, side = p["mint"], p["side"]
    size = float(p["size_usd"])
    price = prices.get(mint)

    if price is None or price <= 0:
        reasons.append("no live price")
    if trades_used_today >= limits.max_trades_per_day:
        reasons.append(f"daily trade cap {limits.max_trades_per_day} reached")
    if p["confidence"] < limits.min_confidence:
        reasons.append(f"confidence {p['confidence']:.2f} < {limits.min_confidence:.2f}")
    if last_fill_at is not None and now - last_fill_at < timedelta(minutes=limits.mint_cooldown_minutes):
        reasons.append(f"mint cooldown ({limits.mint_cooldown_minutes} min) active")
    if size <= 0:
        reasons.append("non-positive size")

    pos = book.positions.get(mint)
    if side == "buy":
        if not safety_ok.get(mint, False):
            reasons.append("token failed safety screen")
        held_usd = pos.qty * price if (pos and price) else 0.0
        gross = book.market_value(prices)
        headroom = min(
            limits.max_position_usd - held_usd,
            limits.max_gross_exposure_usd - gross,
            book.cash_usd - 1.0,  # keep a dollar for fees
        )
        if size > headroom:
            notes.append(f"size clipped ${size:.2f} -> ${max(headroom, 0):.2f} by position/exposure/cash limits")
            size = max(headroom, 0.0)
    else:
        # Exits are allowed even if the token now fails safety; that is when you most want out.
        held_usd = pos.qty * price if (pos and price) else 0.0
        if held_usd <= 0:
            reasons.append("no open position to sell")
        elif size > held_usd:
            notes.append(f"size clipped ${size:.2f} -> ${held_usd:.2f} (whole position)")
            size = held_usd

    if size < limits.min_trade_usd and "non-positive size" not in reasons:
        reasons.append(f"size ${size:.2f} below minimum ${limits.min_trade_usd:.2f}")

    return Verdict(ok=not reasons, size_usd=round(size, 2), reasons=reasons, notes=notes)


def cost_bps(price_impact_bps: float, slippage_bps: int, fee_usd: float, size_usd: float) -> float:
    return price_impact_bps + slippage_bps + (fee_usd / size_usd) * 10_000


def check_costs(edge_bps: float, costs_bps: float, multiple: float) -> str | None:
    """Post-quote check: the claimed edge must clear real costs by `multiple`. Returns a rejection reason or None."""
    if edge_bps < costs_bps * multiple:
        return f"edge {edge_bps:.0f} bps < {multiple:g}x costs ({costs_bps:.0f} bps)"
    return None


def check_anti_sandwich(price_impact_bps: float, slippage_bps: int, limits: RiskLimits) -> str | None:
    """Anti-sandwich check: reject orders whose slippage or impact would expose the trade to MEV sandwichers."""
    if slippage_bps > limits.slippage_bps:
        return f"slippage {slippage_bps} bps > max allowed {limits.slippage_bps} bps (sandwich defense)"
    if price_impact_bps > limits.max_price_impact_bps:
        return f"price impact {price_impact_bps:.1f} bps > max allowed {limits.max_price_impact_bps:.0f} bps"
    return None


def check_position_exit(
    pos_qty: float,
    avg_price: float,
    current_price: float,
    entry_time: datetime | None,
    now: datetime | None,
    limits: RiskLimits,
) -> tuple[bool, str]:
    """Automated risk exit rules for volatile token positions:
    1. Take-Profit hit (e.g. +15%)
    2. Stop-Loss hit (e.g. -7%)
    3. Maximum hold horizon expired (time stop)
    Returns (should_exit, reason).
    """
    if pos_qty <= 0 or avg_price <= 0 or current_price <= 0:
        return False, ""

    pnl_pct = ((current_price - avg_price) / avg_price) * 100.0

    if pnl_pct >= limits.take_profit_pct:
        return True, f"take-profit triggered (+{pnl_pct:.1f}% >= +{limits.take_profit_pct:.1f}%)"

    if pnl_pct <= -limits.stop_loss_pct:
        return True, f"stop-loss triggered ({pnl_pct:.1f}% <= -{limits.stop_loss_pct:.1f}%)"

    if entry_time is not None and now is not None:
        if now - entry_time >= timedelta(hours=limits.max_hold_hours):
            elapsed_h = (now - entry_time).total_seconds() / 3600.0
            return True, f"max holding time exceeded ({elapsed_h:.1f}h >= {limits.max_hold_hours:.1f}h)"

    return False, ""

