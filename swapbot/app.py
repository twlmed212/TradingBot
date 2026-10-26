"""Swap API and signing page (AWS Lambda with a function URL). Plan: PRODUCT.md.

Non-custodial: the API builds Jupiter orders that carry our referral fee for the user's wallet, the user's wallet signs
in the browser, and the API forwards the signed transaction to Jupiter's /execute. It never sees a private key.

Routes
    GET  /                 signing page (static/index.html)
    GET  /app.js, /app.css page assets
    GET  /api/config       fee shown to the user
    GET  /api/tokens?q=    token search (symbol, name or mint)
    POST /api/order        {inputMint, outputMint, amount, taker?} -> Jupiter order (+ unsigned transaction when taker is set)
    POST /api/execute      {signedTransaction, requestId} -> Jupiter execute result

Config (environment): REFERRAL_ACCOUNT (public address, from referral.jup.ag), FEE_BPS (50-255, default 50),
PARAM_PREFIX (e.g. /swapbot/: read secrets from SSM Parameter Store; empty: read JUPITER_API_KEY from the environment).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

JUP = "https://api.jup.ag"
STATIC = Path(__file__).resolve().parent / "static"
WSOL = "So11111111111111111111111111111111111111112"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MAX_BODY = 8192
SECRETS_TTL = 300

ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8")}

SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self' https: data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "strict-transport-security": "max-age=31536000",
    "x-frame-options": "DENY",
}

_secrets: tuple[float, dict] | None = None


def fee_bps() -> int:
    return max(50, min(255, int(os.environ.get("FEE_BPS", "50"))))


def secrets() -> dict:
    """Jupiter API key (optional: keyless works at lower rate limits). Cached for 5 minutes."""
    global _secrets
    if _secrets and time.monotonic() - _secrets[0] < SECRETS_TTL:
        return _secrets[1]
    prefix = os.environ.get("PARAM_PREFIX", "")
    if prefix:
        import boto3  # available in the Lambda Python runtime
        res = boto3.client("ssm").get_parameters(Names=[prefix + "jupiter_api_key"], WithDecryption=True)
        got = {p["Name"][len(prefix):]: p["Value"] for p in res["Parameters"]}
    else:
        got = {"jupiter_api_key": os.environ.get("JUPITER_API_KEY", "")}
    _secrets = (time.monotonic(), got)
    return got


def is_pubkey(s) -> bool:
    if not isinstance(s, str) or not 32 <= len(s) <= 44 or any(c not in B58 for c in s):
        return False
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    return len(s) - len(s.lstrip("1")) + (n.bit_length() + 7) // 8 == 32


def jupiter(method: str, path: str, params: dict | None = None, body: dict | None = None) -> tuple[int, dict]:
    url = JUP + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"content-type": "application/json", "user-agent": "swapbot/1"}
    key = secrets().get("jupiter_api_key")
    if key:
        headers["x-api-key"] = key
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read())
        except ValueError:
            payload = {}
        return e.code, {"error": payload.get("error") or payload.get("errorMessage") or f"Jupiter returned HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError):
        return 502, {"error": "Jupiter did not respond"}


# --- API --------------------------------------------------------------------------

def api_config(_q, _b):
    return 200, {"feeBps": fee_bps(), "feeActive": bool(os.environ.get("REFERRAL_ACCOUNT"))}


def api_tokens(q, _b):
    query = (q.get("q") or "").strip()
    if not 1 <= len(query) <= 64:
        return 400, {"error": "search for a token symbol, name or mint address"}
    status, data = jupiter("GET", "/tokens/v2/search", {"query": query})
    if status != 200 or not isinstance(data, list):
        return 502, {"error": "token search failed"}
    keep = ("id", "symbol", "name", "decimals", "icon", "isVerified", "liquidity", "usdPrice", "mcap", "organicScore")
    return 200, {"tokens": [{k: t.get(k) for k in keep} for t in data[:10]]}


ORDER_FIELDS = ("transaction", "requestId", "inputMint", "outputMint", "inAmount", "outAmount", "otherAmountThreshold",
                "slippageBps", "priceImpact", "priceImpactPct", "feeBps", "feeMint", "platformFee", "router", "mode",
                "transactionVersion", "lastValidBlockHeight", "expireAt", "errorCode", "errorMessage", "inUsdValue", "outUsdValue")


def api_order(_q, body):
    inp, out, amount, taker = body.get("inputMint"), body.get("outputMint"), body.get("amount"), body.get("taker")
    if not (is_pubkey(inp) and is_pubkey(out)) or inp == out:
        return 400, {"error": "choose two different tokens"}
    if not (isinstance(amount, (int, str)) and str(amount).isdigit() and 0 < int(amount) < 10**20):
        return 400, {"error": "amount must be a positive whole number of the token's smallest unit"}
    if taker is not None and not is_pubkey(taker):
        return 400, {"error": "wallet address is not valid"}
    params = {"inputMint": inp, "outputMint": out, "amount": str(int(amount))}
    if taker:
        params["taker"] = taker
    referral = os.environ.get("REFERRAL_ACCOUNT", "")
    if referral:
        params["referralAccount"] = referral
        params["referralFee"] = str(fee_bps())
    status, data = jupiter("GET", "/swap/v2/order", params)
    if status != 200:
        return 502, {"error": data.get("error") or "no quote"}
    return 200, {k: data[k] for k in ORDER_FIELDS if k in data}


def api_execute(_q, body):
    signed, request_id = body.get("signedTransaction"), body.get("requestId")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        return 400, {"error": "missing requestId"}
    try:
        raw = base64.b64decode(signed, validate=True) if isinstance(signed, str) else b""
    except (binascii.Error, ValueError):
        raw = b""
    if not 64 < len(raw) <= 1232:  # a Solana transaction is at most 1,232 bytes
        return 400, {"error": "signed transaction is not valid"}
    status, data = jupiter("POST", "/swap/v2/execute", body={"signedTransaction": signed, "requestId": request_id})
    keep = ("status", "signature", "code", "error", "totalInputAmount", "totalOutputAmount", "inputAmountResult", "outputAmountResult")
    result = {k: data[k] for k in keep if k in data}
    print(json.dumps({"event": "execute", "status": result.get("status"), "code": result.get("code"),
                      "signature": result.get("signature"), "http": status}))
    return (200 if status == 200 else 502), result


ROUTES = {("GET", "/api/config"): api_config, ("GET", "/api/tokens"): api_tokens,
          ("POST", "/api/order"): api_order, ("POST", "/api/execute"): api_execute}


# --- Lambda entry point ---------------------------------------------------------------

def respond(status: int, body, content_type: str = "application/json", cache: str = "no-store") -> dict:
    headers = {"content-type": content_type, "cache-control": cache, **SECURITY_HEADERS}
    return {"statusCode": status, "headers": headers, "body": body if isinstance(body, str) else json.dumps(body)}


def handler(event, _context=None) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or "/"
    if method == "GET" and path in ASSETS:
        name, ctype = ASSETS[path]
        return respond(200, (STATIC / name).read_text(), ctype, "no-cache")
    route = ROUTES.get((method, path))
    if not route:
        return respond(404, {"error": "not found"})
    query = event.get("queryStringParameters") or {}
    body = {}
    if method == "POST":
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8", "replace")
        if len(raw) > MAX_BODY:
            return respond(413, {"error": "request too large"})
        try:
            body = json.loads(raw or "{}")
        except ValueError:
            return respond(400, {"error": "body must be JSON"})
        if not isinstance(body, dict):
            return respond(400, {"error": "body must be a JSON object"})
    try:
        status, payload = route(query, body)
    except Exception as e:  # never leak internals to the page
        print(json.dumps({"event": "error", "path": path, "error": repr(e)[:300]}))
        status, payload = 500, {"error": "internal error"}
    return respond(status, payload)
