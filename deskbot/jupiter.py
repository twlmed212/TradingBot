"""Read-only Jupiter client: token stats and swap quotes. Never builds or sends a transaction."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import httpx
except ImportError:
    httpx = None


@dataclass(frozen=True)
class Quote:
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    price_impact_bps: float
    slippage_bps: int


class Jupiter:
    def __init__(self, base_url: str, api_key: str = "", client: object = None):
        headers = {"x-api-key": api_key} if api_key else {}
        self.base_url = base_url
        if client is None:
            if httpx is None:
                raise RuntimeError("httpx is required for live Jupiter calls: pip install httpx")
            self.http = httpx.Client(timeout=10.0, headers=headers)
        else:
            self.http = client

    def token_info(self, mints: list[str]) -> dict[str, dict]:
        """Price, liquidity, flow stats and Jupiter's audit fields, keyed by mint."""
        out: dict[str, dict] = {}
        for mint in mints:
            r = self.http.get(f"{self.base_url}/tokens/v2/search", params={"query": mint})
            r.raise_for_status()
            for item in r.json():
                if item.get("id") == mint:
                    out[mint] = item
                    break
        return out

    def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> Quote:
        r = self.http.get(
            f"{self.base_url}/swap/v1/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": slippage_bps,
                "swapMode": "ExactIn",
            },
        )
        data = r.json()
        if r.status_code != 200 or "outAmount" not in data:
            raise RuntimeError(f"Jupiter quote failed: {data.get('error') or r.status_code}")
        return Quote(
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=int(data["inAmount"]),
            out_amount=int(data["outAmount"]),
            price_impact_bps=abs(float(data.get("priceImpactPct") or 0.0)) * 10_000,
            slippage_bps=slippage_bps,
        )
