"""Load deskbot.toml plus secrets from the environment (.env is read if present)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Token:
    symbol: str
    mint: str
    decimals: int
    trusted_authorities: bool = False


@dataclass(frozen=True)
class RiskLimits:
    max_trades_per_day: int = 6
    max_position_usd: float = 150.0
    max_gross_exposure_usd: float = 500.0
    min_trade_usd: float = 10.0
    min_confidence: float = 0.6
    slippage_bps: int = 50  # 50 bps (0.5%) anti-sandwich ceiling
    max_price_impact_bps: float = 200.0  # 2% max impact
    edge_cost_multiple: float = 2.0
    mint_cooldown_minutes: int = 60
    daily_loss_limit_usd: float = 50.0
    max_consecutive_errors: int = 3
    max_top_holders_pct: float = 40.0
    min_liquidity_usd: float = 25_000.0
    require_lp_burned: bool = False
    take_profit_pct: float = 15.0
    stop_loss_pct: float = 7.0
    max_hold_hours: float = 4.0
    kill_switch_file: str = "STOP"


@dataclass(frozen=True)
class Settings:
    quote: Token
    tokens: tuple[Token, ...]
    risk: RiskLimits
    starting_cash_usd: float = 1000.0
    db_path: str = "deskbot.sqlite3"
    network_fee_usd: float = 0.02
    interval_minutes: int = 15
    approve: str = "manual"
    notes_path: str = "notes.md"
    temperature: float = 0.2
    x_search: bool = False
    x_handles: tuple[str, ...] = ()
    xai_api_key: str = field(default="", repr=False)
    xai_model: str = "grok-4.7"
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    jupiter_base_url: str = "https://lite-api.jup.ag"
    jupiter_api_key: str = field(default="", repr=False)

    def token(self, mint: str) -> Token | None:
        for t in self.tokens:
            if t.mint == mint:
                return t
        return None


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings(config_path: str | Path = "deskbot.toml") -> Settings:
    config_path = Path(config_path)
    load_dotenv(config_path.parent / ".env")
    raw = tomllib.loads(config_path.read_text())

    paper = raw.get("paper", {})
    loop = raw.get("loop", {})
    grok = raw.get("grok", {})
    tokens = tuple(Token(**t) for t in raw.get("tokens", []))
    quote = Token(**raw["quote"])
    if any(t.mint == quote.mint for t in tokens):
        raise ValueError("The quote token must not also appear in [[tokens]].")
    approve = loop.get("approve", "manual")
    if approve not in ("manual", "auto"):
        raise ValueError(f"loop.approve must be 'manual' or 'auto', got {approve!r}")

    return Settings(
        quote=quote,
        tokens=tokens,
        risk=RiskLimits(**raw.get("risk", {})),
        starting_cash_usd=paper.get("starting_cash_usd", 1000.0),
        db_path=paper.get("db_path", "deskbot.sqlite3"),
        network_fee_usd=paper.get("network_fee_usd", 0.02),
        interval_minutes=loop.get("interval_minutes", 15),
        approve=approve,
        notes_path=loop.get("notes_path", "notes.md"),
        temperature=grok.get("temperature", 0.2),
        x_search=grok.get("x_search", False),
        x_handles=tuple(grok.get("x_handles", [])),
        xai_api_key=os.environ.get("XAI_API_KEY", ""),
        xai_model=os.environ.get("XAI_MODEL", "grok-4.7"),
        rpc_url=os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        jupiter_base_url=os.environ.get("JUPITER_BASE_URL", "https://lite-api.jup.ag").rstrip("/"),
        jupiter_api_key=os.environ.get("JUPITER_API_KEY", ""),
    )
