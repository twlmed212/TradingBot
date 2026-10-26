"""Deterministic token safety and anti-honeypot screener.

Protects against:
1. Selling blocks: freeze authority, transfer hooks, pausable configs, non-transferable extensions.
2. Supply dilution: live mint authority.
3. Hidden taxes / clawbacks: transfer fee configs (>0 bps), permanent delegate.
4. Liquidity pool rug pulls: unburned/unlocked LP, low liquidity pool thresholds.
5. Sandwich exploitation: wide slippage tolerance or excessive price impact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None

from .config import RiskLimits, Token

TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# Token-2022 extensions that can block selling, tax transfers, or seize balances.
CRITICAL_HONEYPOT_EXTENSIONS = {
    "transferHook",          # Smart contract hook executed on transfer: can silently revert all sells
    "permanentDelegate",     # Issuer can transfer/burn tokens directly from your wallet
    "nonTransferable",       # Pure honeypot: tokens cannot be transferred or sold
    "defaultAccountState",   # Can initialize user token accounts in a frozen state
    "pausableConfig",        # Trading/transfers can be paused at the creator's discretion
}


@dataclass
class SafetyReport:
    mint: str
    ok: bool
    facts: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


class SolanaRpc:
    def __init__(self, url: str, client: Any = None):
        self.url = url
        if client is None:
            if httpx is None:
                raise RuntimeError("httpx is required for live RPC calls: pip install httpx")
            self.http = httpx.Client(timeout=10.0)
        else:
            self.http = client

    def _call(self, method: str, params: list[Any]) -> Any:
        r = self.http.post(
            self.url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"RPC {method} failed: {body['error']}")
        return body["result"]

    def mint_info(self, mint: str) -> dict:
        result = self._call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        value = result.get("value")
        if value is None:
            raise RuntimeError(f"Mint account {mint} not found")
        parsed = value["data"]["parsed"]
        if parsed.get("type") != "mint":
            raise RuntimeError(f"{mint} is not a mint account")
        info = dict(parsed["info"])
        info["program"] = value["owner"]
        return info

    def token_largest_accounts(self, mint: str) -> list[dict]:
        """Fetch the 20 largest token accounts on-chain."""
        result = self._call("getTokenLargestAccounts", [mint])
        return result.get("value", [])

    def token_supply(self, mint: str) -> float:
        """Fetch current total token supply."""
        result = self._call("getTokenSupply", [mint])
        amount = result.get("value", {}).get("uiAmount")
        return float(amount) if amount is not None else 0.0

    def simulate_transaction(self, tx_base64: str) -> dict:
        """Simulate a transaction prior to broadcast to ensure it does not revert."""
        result = self._call(
            "simulateTransaction",
            [tx_base64, {"sigVerify": False, "replaceRecentBlockhash": True}],
        )
        return result.get("value", {})


def extract_token_2022_details(extensions_raw: list[dict]) -> tuple[set[str], float]:
    """Parse Token-2022 extensions and return detected extension names plus any transfer fee bps."""
    names: set[str] = set()
    transfer_fee_bps = 0.0

    for ext in extensions_raw:
        ext_type = ext.get("extension")
        if not ext_type:
            continue
        names.add(ext_type)
        if ext_type == "transferFeeConfig":
            state = ext.get("state", {})
            newer_fee = state.get("newerTransferFee", {}).get("transferFeeBasisPoints")
            older_fee = state.get("olderTransferFee", {}).get("transferFeeBasisPoints")
            fee = newer_fee if newer_fee is not None else older_fee
            if fee is not None:
                transfer_fee_bps = float(fee)

    return names, transfer_fee_bps


def screen(token: Token, mint_info: dict, jup_info: dict, limits: RiskLimits) -> SafetyReport:
    """Rigorous honeypot, freeze authority, Token-2022, LP lock, and pool screener."""
    raw_extensions = mint_info.get("extensions", [])
    ext_names, transfer_fee_bps = extract_token_2022_details(raw_extensions)
    audit = jup_info.get("audit") or {}

    lp_burned = audit.get("lpBurned")
    if lp_burned is None:
        # Fallback to boolean flags if present in metadata
        lp_burned = jup_info.get("isLpBurned", False)

    facts = {
        "mint_authority": mint_info.get("mintAuthority"),
        "freeze_authority": mint_info.get("freezeAuthority"),
        "token_2022": mint_info.get("program") == TOKEN_2022_PROGRAM_ID,
        "extensions": sorted(ext_names),
        "transfer_fee_bps": transfer_fee_bps,
        "top_holders_pct": audit.get("topHoldersPercentage"),
        "liquidity_usd": jup_info.get("liquidity"),
        "lp_burned": bool(lp_burned),
        "trusted_authorities": token.trusted_authorities,
    }

    failures: list[str] = []

    # 1. Block selling prevention: Freeze Authority must be revoked
    if not token.trusted_authorities:
        if facts["freeze_authority"]:
            failures.append("freeze authority is live (deployer can freeze your token account and block selling)")
        if facts["mint_authority"]:
            failures.append("mint authority is live (deployer can inflate supply and dump)")

    # 2. Token-2022 honeypot extension check
    honeypot_triggers = sorted(CRITICAL_HONEYPOT_EXTENSIONS.intersection(ext_names))
    if honeypot_triggers:
        failures.append(f"dangerous Token-2022 honeypot extensions: {', '.join(honeypot_triggers)}")

    # 3. Transfer tax / fee check
    if transfer_fee_bps > 0:
        failures.append(f"hidden transfer fee active: {transfer_fee_bps:.0f} bps ({transfer_fee_bps / 100:.2f}%)")

    # 4. Token pool & liquidity risk: LP burn check
    if limits.require_lp_burned and not token.trusted_authorities:
        if not facts["lp_burned"]:
            failures.append("liquidity pool LP tokens are not burned/locked (rug pull risk)")

    # 5. Top-holder concentration check
    top = facts["top_holders_pct"]
    if top is None:
        failures.append("top-holder concentration unknown")
    elif top > limits.max_top_holders_pct:
        failures.append(f"top holders own {top:.1f}% (> max {limits.max_top_holders_pct:.0f}%)")

    # 6. Minimum pool liquidity floor
    liq = facts["liquidity_usd"]
    if liq is None or liq < limits.min_liquidity_usd:
        failures.append(f"liquidity ${liq if liq is not None else 0:,.0f} below required ${limits.min_liquidity_usd:,.0f}")

    return SafetyReport(mint=token.mint, ok=not failures, facts=facts, failures=failures)


def verify_anti_sandwich(slippage_bps: int, price_impact_bps: float, max_slippage_bps: int = 50, max_impact_bps: float = 200.0) -> list[str]:
    """Anti-sandwich check: ensure trade does not use wide slippage or excessive impact that invites MEV attackers."""
    reasons: list[str] = []
    if slippage_bps > max_slippage_bps:
        reasons.append(f"slippage {slippage_bps} bps > max allowed {max_slippage_bps} bps (anti-sandwich threshold)")
    if price_impact_bps > max_impact_bps:
        reasons.append(f"price impact {price_impact_bps:.1f} bps > max allowed {max_impact_bps:.0f} bps")
    return reasons
