"""Grok as a research copilot: it reads a market packet and returns a structured opinion. It never signs anything."""

from __future__ import annotations

import json
from datetime import timedelta

try:
    import httpx
except ImportError:
    httpx = None

from .ledger import utcnow

SYSTEM_PROMPT = """You are the research copilot on a small Solana spot desk. You do not execute trades.
You read a JSON packet (prices, flow stats, safety screen, the paper portfolio, hard risk limits, the trader's notes,
and your own recent proposals) and return at most a few trade proposals for a human and a deterministic risk engine to judge.

Rules:
- Doing nothing is the default. Return an empty "proposals" list unless you see a specific, time-bound edge.
- Only propose mints listed in packet.tokens. Never propose a token whose safety.ok is false.
- Every trade pays price impact + slippage + a network fee. expected_edge_bps is your honest estimate of the gross
  expected move in basis points, before costs; the engine subtracts costs itself and rejects thin edges.
- Respect packet.limits; proposals that break them are discarded. Sells must not exceed the open position.
- Do not flip-flop: if you proposed the opposite side on the same mint recently, explain what changed in the thesis.
- Separate facts from narrative. Treat social-media claims as unverified unless the packet's on-chain data supports them.
- invalidation must be a concrete, observable condition (price level, event, data point), not "if the thesis fails".
- confidence is your probability (0..1) that the trade is profitable after costs over horizon_hours."""


def response_schema(mints: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["market_view", "proposals"],
        "properties": {
            "market_view": {"type": "string", "description": "Two or three sentences on regime and what matters now."},
            "proposals": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["mint", "side", "size_usd", "confidence", "expected_edge_bps", "horizon_hours",
                                 "thesis", "invalidation"],
                    "properties": {
                        "mint": {"type": "string", "enum": mints},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "size_usd": {"type": "number"},
                        "confidence": {"type": "number"},
                        "expected_edge_bps": {"type": "number"},
                        "horizon_hours": {"type": "number"},
                        "thesis": {"type": "string"},
                        "invalidation": {"type": "string"},
                    },
                },
            },
        },
    }


def validate_response(data: object, mints: list[str]) -> dict:
    """Re-check the shape locally; structured output is a request, not a guarantee."""
    if not isinstance(data, dict) or not isinstance(data.get("proposals"), list):
        raise ValueError("model response missing 'proposals' list")
    clean = []
    for p in data["proposals"]:
        if not isinstance(p, dict):
            raise ValueError("proposal is not an object")
        if p.get("mint") not in mints:
            raise ValueError(f"proposal mint {p.get('mint')!r} not in allowlist")
        if p.get("side") not in ("buy", "sell"):
            raise ValueError(f"bad side {p.get('side')!r}")
        for k in ("size_usd", "confidence", "expected_edge_bps", "horizon_hours"):
            if not isinstance(p.get(k), (int, float)) or isinstance(p.get(k), bool):
                raise ValueError(f"proposal field {k} must be a number")
        for k in ("thesis", "invalidation"):
            if not isinstance(p.get(k), str):
                raise ValueError(f"proposal field {k} must be a string")
        clean.append({k: p[k] for k in ("mint", "side", "size_usd", "confidence", "expected_edge_bps",
                                         "horizon_hours", "thesis", "invalidation")})
    return {"market_view": str(data.get("market_view", "")), "proposals": clean}


def extract_output_text(body: dict) -> str:
    for item in body.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c["text"]
    raise ValueError("no output_text in Grok response")


class Grok:
    def __init__(self, api_key: str, model: str, temperature: float = 0.2, x_search: bool = False,
                 x_handles: tuple[str, ...] = (), client: object = None):
        if not api_key:
            raise ValueError("XAI_API_KEY is not set")
        self.model = model
        self.temperature = temperature
        self.x_search = x_search
        self.x_handles = x_handles
        if client is None:
            if httpx is None:
                raise RuntimeError("httpx is required for live Grok calls: pip install httpx")
            self.http = httpx.Client(
                base_url="https://api.x.ai/v1",
                timeout=180.0,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        else:
            self.http = client

    def _tools(self) -> list[dict]:
        if not self.x_search:
            return []
        tool: dict = {"type": "x_search", "from_date": (utcnow() - timedelta(days=2)).date().isoformat()}
        if self.x_handles:
            tool["allowed_x_handles"] = list(self.x_handles)[:20]
        return [tool]

    def propose(self, packet: dict) -> tuple[dict, dict]:
        """Returns (validated_opinion, raw_response_body)."""
        mints = [t["mint"] for t in packet["tokens"]]
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "store": False,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(packet, separators=(",", ":"))},
            ],
            "text": {"format": {"type": "json_schema", "name": "desk_opinion", "schema": response_schema(mints), "strict": True}},
        }
        tools = self._tools()
        if tools:
            body["tools"] = tools
        r = self.http.post("/responses", json=body)
        if r.status_code != 200:
            raise RuntimeError(f"xAI API {r.status_code}: {r.text[:300]}")
        raw = r.json()
        opinion = validate_response(json.loads(extract_output_text(raw)), mints)
        return opinion, raw
