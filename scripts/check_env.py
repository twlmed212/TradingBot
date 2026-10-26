"""Check that the keys in .env work, without ever printing them.

    python3 scripts/check_env.py

For each configured service it makes one cheap read-only call and prints OK/FAIL, the host, and the latency.
Key values are masked in all output.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def masked(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" + ("?api-key=***" if "api-key" in parts.query else "")


def rpc(url: str, method: str, params: list | None = None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode()
    req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return data, (time.monotonic() - t0) * 1000


def check_solana_rpc(env: dict) -> None:
    url = env.get("SOLANA_RPC_URL", "")
    if not url:
        print("SOLANA_RPC_URL   : not set")
        return
    try:
        health, ms = rpc(url, "getHealth")
        slot, _ = rpc(url, "getSlot")
        ok = health.get("result") == "ok" and isinstance(slot.get("result"), int)
        print(f"SOLANA_RPC_URL   : {'OK' if ok else 'FAIL'}  {masked(url)}  slot {slot.get('result')}  {ms:.0f} ms"
              + ("" if ok else f"  {health.get('error') or slot.get('error')}"))
        if "helius" not in url:
            print("                   (not Helius yet: still the public RPC)")
    except urllib.error.HTTPError as e:
        print(f"SOLANA_RPC_URL   : FAIL  {masked(url)}  HTTP {e.code} (wrong or missing key?)")
    except Exception as e:
        print(f"SOLANA_RPC_URL   : FAIL  {masked(url)}  {e}")


def check_helius_key(env: dict) -> None:
    key = env.get("HELIUS_API_KEY", "")
    if not key:
        print("HELIUS_API_KEY   : not set")
        return
    url = f"https://mainnet.helius-rpc.com/?api-key={key}"
    try:
        data, ms = rpc(url, "getHealth")
        ok = data.get("result") == "ok"
        print(f"HELIUS_API_KEY   : {'OK' if ok else 'FAIL'}  key ****{key[-4:]}  {ms:.0f} ms")
        rpc_url = env.get("SOLANA_RPC_URL", "")
        if ok and key not in rpc_url:
            print("                   SOLANA_RPC_URL does not use this key yet")
    except urllib.error.HTTPError as e:
        print(f"HELIUS_API_KEY   : FAIL  key ****{key[-4:]}  HTTP {e.code} (wrong key?)")
    except Exception as e:
        print(f"HELIUS_API_KEY   : FAIL  {e}")


def main() -> None:
    env = {**load_env(ROOT / ".env")}
    check_helius_key(env)
    check_solana_rpc(env)


if __name__ == "__main__":
    main()
