"""Command line interface for deskbot: cycle, status, screen, audit, loop."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import Token, load_settings
from .engine import Desk
from .grok import Grok
from .jupiter import Jupiter
from .ledger import Ledger
from .safety import SafetyReport, SolanaRpc, screen


def terminal_approver(ticket) -> tuple[bool, str]:
    print("\n" + "=" * 60)
    print(f"TRADE TICKET #{ticket.proposal_id}")
    print(f"Side: {ticket.side.upper()} {ticket.token.symbol} (${ticket.size_usd:,.2f})")
    print(f"Confidence: {ticket.confidence:.2f} | Expected Edge: {ticket.edge_bps:.0f} bps | Costs: {ticket.costs_bps:.0f} bps")
    print(f"Thesis: {ticket.thesis}")
    if ticket.invalidation:
        print(f"Invalidation: {ticket.invalidation}")
    if ticket.notes:
        print(f"Risk Adjustments: {'; '.join(ticket.notes)}")
    print(f"Quote Impact: {ticket.quote.price_impact_bps:.1f} bps | Slippage: {ticket.quote.slippage_bps} bps")
    print("=" * 60)
    try:
        ans = input("Approve trade? [y/N]: ").strip().lower()
        return ans in ("y", "yes"), "user approved" if ans in ("y", "yes") else "user rejected"
    except (EOFError, KeyboardInterrupt):
        return False, "cancelled by user"


def auto_approver(ticket) -> tuple[bool, str]:
    return True, "auto approved by risk engine"


def build_desk(config_path: Path, workdir: Path) -> Desk:
    settings = load_settings(config_path)
    ledger = Ledger(str(workdir / settings.db_path), settings.starting_cash_usd)
    jupiter = Jupiter(settings.jupiter_base_url, settings.jupiter_api_key)
    rpc = SolanaRpc(settings.rpc_url)
    proposer = None
    if settings.xai_api_key:
        proposer = Grok(
            api_key=settings.xai_api_key,
            model=settings.xai_model,
            temperature=settings.temperature,
            x_search=settings.x_search,
            x_handles=settings.x_handles,
        )
    approver = terminal_approver if settings.approve == "manual" else auto_approver
    return Desk(settings, ledger, jupiter, rpc, proposer, approver, workdir)


def cmd_status(desk: Desk) -> int:
    book = desk.ledger.book()
    print("=" * 60)
    print("DESKBOT PORTFOLIO STATUS")
    print(f"Quote Currency: {desk.s.quote.symbol}")
    print(f"Cash Available: {book.cash_usd:,.2f} {desk.s.quote.symbol}")
    print(f"Realized PnL:   {book.realized_pnl_usd:+,.2f} {desk.s.quote.symbol}")
    print(f"Total Fees:     {book.fees_usd:,.2f} {desk.s.quote.symbol}")
    print(f"Fills Today:    {desk.ledger.fills_today()} / {desk.s.risk.max_trades_per_day}")
    print("-" * 60)
    if not book.positions:
        print("Open Positions: None")
    else:
        print("Open Positions:")
        for mint, pos in book.positions.items():
            print(f"  • {pos.symbol}: {pos.qty:,.4g} tokens (cost basis {pos.cost_usd:,.2f})")
    print("=" * 60)
    return 0


def cmd_screen(desk: Desk, mint: str) -> int:
    print(f"\nScreening token mint: {mint} ...")
    token = desk.s.token(mint) or Token(symbol="SCAN", mint=mint, decimals=9, trusted_authorities=False)
    try:
        mint_info = desk.rpc.mint_info(mint)
    except Exception as e:
        print(f"❌ RPC error querying mint: {e}")
        return 1

    try:
        jup_info_map = desk.jupiter.token_info([mint])
        jup_info = jup_info_map.get(mint, {})
    except Exception as e:
        print(f"⚠️ Jupiter info error: {e}")
        jup_info = {}

    rep = screen(token, mint_info, jup_info, desk.s.risk)
    print("=" * 60)
    print(f"SAFETY REPORT FOR {token.symbol} ({mint})")
    print(f"Status: {'✅ PASSED (Safe to Trade)' if rep.ok else '❌ REJECTED (High Risk / Honeypot)'}")
    print("\nVerified Facts:")
    for k, v in rep.facts.items():
        print(f"  • {k}: {v}")

    if rep.failures:
        print("\nIdentified Hazards / Failures:")
        for f in rep.failures:
            print(f"  ⚠️  {f}")
    print("=" * 60)
    return 0 if rep.ok else 2


def cmd_cycle(desk: Desk) -> int:
    print("\nStarting trading cycle...")
    res = desk.cycle()
    print(f"Cycle Status: {res.status.upper()}")
    if res.message:
        print(f"Message: {res.message}")
    if res.market_view:
        print(f"Market View: {res.market_view}")
    if res.log:
        print("Activity Log:")
        for entry in res.log:
            print(f"  → {entry}")
    return 0 if res.status == "ok" else 1


def cmd_audit(desk: Desk) -> int:
    counts = desk.ledger.counts()
    print("=" * 60)
    print("DESKBOT AUDIT COUNTS")
    for k, v in counts.items():
        print(f"  {k:20s}: {v}")
    print("-" * 60)
    proposals = desk.ledger.recent_proposals(limit=10)
    if proposals:
        print("Recent Proposals:")
        for p in proposals:
            status = "APPROVED" if p.get("approved") else ("RISK_OK" if p.get("risk_ok") else "REJECTED")
            print(f"  [{p.get('ts')[:19]}] {p.get('side', '').upper():4s} {p.get('symbol', ''):6s} ${p.get('size_usd', 0):6.2f} -> {status}")
    print("=" * 60)
    return 0


def cmd_loop(desk: Desk) -> int:
    interval = desk.s.interval_minutes * 60
    print(f"Starting deskbot loop (every {desk.s.interval_minutes} minutes). Press Ctrl+C to stop.")
    while True:
        try:
            cmd_cycle(desk)
        except Exception as e:
            print(f"Cycle exception: {e}", file=sys.stderr)
        try:
            print(f"Sleeping for {desk.s.interval_minutes} minutes...")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nLoop stopped by user.")
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deskbot", description="Solana DEX Trading Bot & Screener")
    parser.add_argument("--config", default="deskbot.toml", help="Path to deskbot.toml config file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show current portfolio, positions, and day stats")
    subparsers.add_parser("cycle", help="Execute one decision cycle")
    subparsers.add_parser("loop", help="Run cycles continuously on a timer")
    subparsers.add_parser("audit", help="Inspect decision and fill ledger statistics")

    screen_parser = subparsers.add_parser("screen", help="Inspect a token mint for honeypots and pool risks")
    screen_parser.add_argument("mint", help="Token mint address to screen")

    args = parser.parse_args(argv)
    workdir = Path.cwd()
    config_path = workdir / args.config

    if not config_path.exists():
        # Fallback to local script directory
        script_dir = Path(__file__).resolve().parent.parent
        if (script_dir / args.config).exists():
            config_path = script_dir / args.config
            workdir = script_dir

    try:
        desk = build_desk(config_path, workdir)
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    if args.command == "status":
        return cmd_status(desk)
    elif args.command == "cycle":
        return cmd_cycle(desk)
    elif args.command == "loop":
        return cmd_loop(desk)
    elif args.command == "audit":
        return cmd_audit(desk)
    elif args.command == "screen":
        return cmd_screen(desk, args.mint)

    return 0


if __name__ == "__main__":
    sys.exit(main())
