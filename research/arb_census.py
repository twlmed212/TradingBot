"""Solana DEX arbitrage measurement. Rules: research/registry/2026-10-26-arb-market-measurement.md

    python3 research/arb_census.py fetch      # Stage A data: 2,000 random blocks from the last 7 days (gzip, resumable)
    python3 research/arb_census.py analyze    # detector, size, concentration, competition -> data/arb_census.sqlite3
    python3 research/arb_census.py reach      # Stage B: how long each of 300 random arbitrages' price gap stayed open

Reads the Helius RPC URL from .env (never printed). Read-only: no transactions are sent.
"""

from __future__ import annotations

import gzip
import json
import os
import random
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "data" / "arb_blocks"
MANIFEST = BLOCKS / "manifest.json"
OUT_DB = ROOT / "data" / "arb_census.sqlite3"
N_BLOCKS = 2_000
N_REACH = 300
DAYS = 7
SEED = 20261026
REACH_SLOTS = 3                       # registry: "open for >= 3 slots (~1.2 s)"
TOL = 1e-4                            # registry: |net| > 0.01% of the counterparties' gross flow
FEE_RECEIVER_MIN = 20                 # registry: single-mint receiver in >= 20 user swaps
PUBLIC_PROGRAM_MIN = 20               # a top-level program seen in >= 20 user swaps is public (DEX, aggregator)

WSOL = "So11111111111111111111111111111111111111112"
USD_MINTS = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 6, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 6}
JITO_TIPS = {"96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
             "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
             "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
             "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"}
PLUMBING = {"ComputeBudget111111111111111111111111111111", "11111111111111111111111111111111",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL", "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
            "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"}
SYSVAR_PREFIX = "Sysvar"


# --- RPC -------------------------------------------------------------------------

def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def rpc(method: str, params: list, retries: int = 6):
    url = os.environ["SOLANA_RPC_URL"]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for k in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers={"content-type": "application/json", "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and k < retries - 1:
                time.sleep(2 * (k + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if k < retries - 1:
                time.sleep(2 * (k + 1))
                continue
            raise


BLOCK_OPTS = {"encoding": "json", "transactionDetails": "full", "rewards": False,
              "maxSupportedTransactionVersion": 1, "commitment": "finalized"}
SKIPPED_CODES = {-32007, -32009}      # slot skipped / missing in long-term storage


def block_time(slot: int) -> tuple[int, int]:
    """Block time of `slot`, or of the next produced slot after it."""
    for s in range(slot, slot + 50):
        res = rpc("getBlockTime", [s])
        if res.get("result"):
            return s, res["result"]
    raise RuntimeError(f"no block time near slot {slot}")


# --- Stage A: fetch ---------------------------------------------------------------

def fetch() -> None:
    load_env()
    BLOCKS.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists():
        man = json.loads(MANIFEST.read_text())
    else:
        hi, t_hi = block_time(rpc("getSlot", [{"commitment": "finalized"}])["result"] - 100)
        guess, t_guess = block_time(hi - int(DAYS * 86400 / 0.4))
        rate = (hi - guess) / (t_hi - t_guess)                     # slots per second over the window
        lo, t_lo = block_time(hi - int(DAYS * 86400 * rate))
        man = {"drawn_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lo": lo, "hi": hi,
               "t_lo": t_lo, "t_hi": t_hi, "seed": SEED, "draws": [], "skipped": []}
        MANIFEST.write_text(json.dumps(man))

    def get(slot):
        if (BLOCKS / f"{slot}.json.gz").exists():
            return slot, "ok"
        res = rpc("getBlock", [slot, BLOCK_OPTS])
        if "error" in res:
            if res["error"].get("code") in SKIPPED_CODES:
                return slot, "skipped"
            raise RuntimeError(f"slot {slot}: {res['error']}")
        tmp = BLOCKS / f"{slot}.json.gz.tmp"
        with gzip.open(tmp, "wt") as f:
            json.dump(res["result"], f)
        tmp.replace(BLOCKS / f"{slot}.json.gz")
        return slot, "ok"

    # one deterministic stream of random slots; a skipped slot (no block) is replaced by the next draw
    rng = random.Random(man["seed"])
    draws, skipped, ok = [], set(man["skipped"]), 0
    with ThreadPoolExecutor(6) as ex:
        while ok < N_BLOCKS:
            batch = []
            while len(batch) < N_BLOCKS - ok:
                slot = rng.randint(man["lo"], man["hi"])
                if slot not in batch and slot not in draws:      # sample without replacement
                    batch.append(slot)
            draws += batch
            for slot, status in ex.map(get, batch):
                if status == "skipped":
                    skipped.add(slot)
                else:
                    ok += 1
            print(f"  {ok}/{N_BLOCKS} blocks, {len(skipped)} skipped slots", flush=True)
    man["draws"], man["skipped"] = draws, sorted(skipped)
    MANIFEST.write_text(json.dumps(man))
    print(f"window {man['lo']}..{man['hi']} ({(man['t_hi'] - man['t_lo']) / 86400:.2f} days); "
          f"{ok} blocks, {len(skipped)} of {len(draws)} draws were skipped slots")


# --- ed25519: pool vault owners are program addresses (off the curve); user wallets are signing keys (on it) ---------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_on_curve_cache: dict[str, bool] = {}


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def on_curve(addr: str) -> bool:
    """True for a valid ed25519 public key (a wallet that can sign); False for a program-derived address."""
    hit = _on_curve_cache.get(addr)
    if hit is not None:
        return hit
    b = b58decode(addr)
    ok = False
    if len(b) == 32:
        y = int.from_bytes(b, "little") & ((1 << 255) - 1)
        if y < _P:
            y2 = y * y % _P
            x2 = (y2 - 1) * pow(_D * y2 + 1, _P - 2, _P) % _P
            x = pow(x2, (_P + 3) // 8, _P)
            if (x * x - x2) % _P:
                x = x * pow(2, (_P - 1) // 4, _P) % _P
            ok = (x * x - x2) % _P == 0
    _on_curve_cache[addr] = ok
    return ok


# --- detector ---------------------------------------------------------------------

def keys(tx) -> list[str]:
    la = tx["meta"].get("loadedAddresses") or {}
    return list(tx["transaction"]["message"]["accountKeys"]) + la.get("writable", []) + la.get("readonly", [])


def writable(tx) -> set[str]:
    m = tx["transaction"]["message"]
    h, static = m["header"], m["accountKeys"]
    nsig = h["numRequiredSignatures"]
    w = set(static[:nsig - h["numReadonlySignedAccounts"]]) | set(static[nsig:len(static) - h["numReadonlyUnsignedAccounts"]])
    return w | set((tx["meta"].get("loadedAddresses") or {}).get("writable", []))


def top_programs(tx, ks) -> list[str]:
    return [p for p in dict.fromkeys(ks[ix["programIdIndex"]] for ix in tx["transaction"]["message"]["instructions"]) if p not in PLUMBING]


def owner_nets(tx) -> tuple[dict, dict]:
    """Per owner, per mint net change in raw units (WSOL kept as its own mint); decimals by mint."""
    m = tx["meta"]
    pre = {b["accountIndex"]: b for b in m["preTokenBalances"]}
    post = {b["accountIndex"]: b for b in m["postTokenBalances"]}
    nets: dict[str, Counter] = defaultdict(Counter)
    dec = {}
    for i in set(pre) | set(post):
        b = post.get(i) or pre.get(i)
        a0 = int(pre[i]["uiTokenAmount"]["amount"]) if i in pre else 0
        a1 = int(post[i]["uiTokenAmount"]["amount"]) if i in post else 0
        dec[b["mint"]] = b["uiTokenAmount"]["decimals"]
        if a1 != a0:
            nets[b.get("owner") or f"?{i}"][b["mint"]] += a1 - a0
    return nets, dec


def is_pool(c: Counter) -> bool:
    vals = [v for v in c.values() if v]
    return len(vals) >= 2 and any(v > 0 for v in vals) and any(v < 0 for v in vals)


def tips_in(tx, ks) -> int:
    m = tx["meta"]
    return sum(m["postBalances"][i] - m["preBalances"][i] for i, k in enumerate(ks[:len(m["postBalances"])]) if k in JITO_TIPS)


def user_swap(tx, nets, ks) -> bool:
    """A user swap: the fee payer's own token mix changed (one mint up, another down)."""
    return is_pool(nets.get(ks[0], Counter()))


def detect(tx, fee_receivers: set[str]) -> dict | None:
    """Registry detector. Returns the loop's mint and the searcher's take (raw units, before tx fee and tips)."""
    if tx["meta"]["err"] is not None:
        return None
    nets, dec = owner_nets(tx)
    if user_swap(tx, nets, keys(tx)):      # the signer's own token mix changed: a user swap, not a loop
        return None
    # pools are program-owned vaults: never a signer of the transaction and never a signing key (fix 4)
    signers = set(tx["transaction"]["message"]["accountKeys"][:tx["transaction"]["message"]["header"]["numRequiredSignatures"]])
    pools = [o for o, c in nets.items() if is_pool(c) and o not in signers and not on_curve(o)]
    if len(pools) < 2:
        return None
    # fee receivers count on the pools' side only where they receive (fix 2, 26 Oct, after the first run)
    side = set(pools) | {o for o in fee_receivers & set(nets) if all(v >= 0 for v in nets[o].values())}
    total, flow = Counter(), Counter()
    for o in side:
        for mint, v in nets[o].items():
            total[mint] += v
            flow[mint] += abs(v)
    off = {mint: v for mint, v in total.items() if abs(v) > TOL * flow[mint] and v != 0}
    if len(off) != 1:
        return None
    (mint, v), = off.items()
    if v >= 0:
        return None
    # nobody outside the pools paid in: otherwise it is a user's swap from a separate account (fix 1)
    for o, c in nets.items():
        if o not in side and any(x < 0 and -x > TOL * flow[m] for m, x in c.items()):
            return None
    # a loop at sane prices: the take is at most the pools' inflow of that mint, i.e. output <= 2x input (fix 3)
    if -v > sum(max(nets[o][mint], 0) for o in side):
        return None
    return {"mint": mint, "take_raw": -v, "decimals": dec.get(mint, 9), "pools": sorted(pools)}


# --- Stage A: analyze -------------------------------------------------------------

def sol_usd_hourly(t_lo: int, t_hi: int) -> dict[int, float]:
    out, start = {}, (t_lo // 3600 - 1) * 3600 * 1000
    while start < t_hi * 1000:
        url = f"https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1h&startTime={start}&limit=1000"
        with urllib.request.urlopen(url, timeout=30) as r:
            rows = json.loads(r.read())
        if not rows:
            break
        for k in rows:
            out[k[0] // 1000] = float(k[4])
        start = rows[-1][0] + 3_600_000
    return out


def iter_blocks():
    for p in sorted(BLOCKS.glob("*.json.gz")):
        with gzip.open(p, "rt") as f:
            yield int(p.name.split(".")[0]), json.load(f)


SCHEMA = """
DROP TABLE IF EXISTS arbs; DROP TABLE IF EXISTS blocks;
CREATE TABLE blocks (slot INTEGER PRIMARY KEY, block_time INTEGER, n_tx INTEGER, n_failed INTEGER, n_arb_failed INTEGER);
CREATE TABLE arbs (slot INTEGER, idx INTEGER, sig TEXT, payer TEXT, grp TEXT, mint TEXT, take REAL, fee_sol REAL,
                   tips_sol REAL, sol_usd REAL, net_usd REAL, gross_usd REAL, pools TEXT, accounts TEXT,
                   PRIMARY KEY (slot, idx));
"""


def analyze() -> None:
    man = json.loads(MANIFEST.read_text())
    # pass 1: fee receivers and public programs, from user swaps only
    recv, public = Counter(), Counter()
    for _slot, b in iter_blocks():
        for tx in b["transactions"]:
            if tx["meta"]["err"] is not None:
                continue
            ks = keys(tx)
            nets, _ = owner_nets(tx)
            if not user_swap(tx, nets, ks):
                continue
            public.update(top_programs(tx, ks))
            for o, c in nets.items():
                vals = [v for v in c.values() if v]
                if o != ks[0] and len(vals) == 1 and vals[0] > 0:
                    recv[o] += 1
    fee_receivers = {o for o, n in recv.items() if n >= FEE_RECEIVER_MIN}
    public_programs = {p for p, n in public.items() if n >= PUBLIC_PROGRAM_MIN}
    print(f"pass 1: {len(fee_receivers)} fee receivers, {len(public_programs)} public programs")

    prices = sol_usd_hourly(man["t_lo"], man["t_hi"])
    db = sqlite3.connect(OUT_DB)
    db.executescript(SCHEMA)
    group_programs: set[str] = set()
    failed_progs: list[tuple[int, list[str]]] = []
    for slot, b in iter_blocks():
        txs = b["transactions"]
        bt = b.get("blockTime") or 0
        px = prices.get(bt // 3600 * 3600) or prices.get(bt // 3600 * 3600 - 3600)
        # tip-only transactions in this block, by fee payer
        side_tips = Counter()
        for tx in txs:
            if tx["meta"]["err"] is None and not tx["meta"]["preTokenBalances"] and not tx["meta"]["postTokenBalances"]:
                ks = keys(tx)
                t = tips_in(tx, ks)
                if t > 0 and not top_programs(tx, ks):
                    side_tips[ks[0]] += t
        found = []
        n_failed = 0
        for idx, tx in enumerate(txs):
            ks = keys(tx)
            if tx["meta"]["err"] is not None:
                n_failed += 1
                failed_progs.append((slot, top_programs(tx, ks)))
                continue
            d = detect(tx, fee_receivers)
            if not d:
                continue
            progs = top_programs(tx, ks)
            custom = next((p for p in progs if p not in public_programs), None)
            if custom:
                group_programs.add(custom)
            found.append((idx, tx, ks, d, custom))
        per_payer = Counter(ks[0] for _i, _t, ks, _d, _c in found)
        for idx, tx, ks, d, custom in found:
            payer = ks[0]
            fee = tx["meta"]["fee"] / 1e9
            tips = (tips_in(tx, ks) + side_tips.get(payer, 0) / per_payer[payer]) / 1e9
            take = d["take_raw"] / 10 ** d["decimals"]
            if d["mint"] == WSOL and px:
                gross, net = take * px, (take - fee - tips) * px
            elif d["mint"] in USD_MINTS and px:
                gross, net = take, take - (fee + tips) * px
            else:
                gross = net = None
            accts = sorted(writable(tx) - {payer} - JITO_TIPS)
            db.execute("INSERT INTO arbs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (slot, idx, tx["transaction"]["signatures"][0], payer, custom or f"payer:{payer}", d["mint"], take,
                        fee, tips, px, net, gross, json.dumps(d["pools"]), json.dumps(accts)))
        db.execute("INSERT INTO blocks VALUES (?,?,?,?,?)", (slot, bt, len(txs), n_failed, 0))
    # failed arbitrage attempts: failed transactions calling a searcher program seen in successful arbitrage
    arb_failed = Counter(slot for slot, progs in failed_progs if any(p in group_programs for p in progs))
    for slot, n in arb_failed.items():
        db.execute("UPDATE blocks SET n_arb_failed=? WHERE slot=?", (n, slot))
    db.commit()
    report(db, man)


def report(db: sqlite3.Connection, man: dict) -> None:
    n_blocks, n_tx, n_failed, n_arb_failed = db.execute("SELECT COUNT(*), SUM(n_tx), SUM(n_failed), SUM(n_arb_failed) FROM blocks").fetchone()
    days = (man["t_hi"] - man["t_lo"]) / 86400
    produced = (man["hi"] - man["lo"] + 1) * (1 - len(man["skipped"]) / max(len(man["draws"]), 1))
    scale = produced / n_blocks / days            # sample block -> per day
    rows = db.execute("SELECT slot, grp, mint, net_usd, gross_usd, fee_sol, tips_sol FROM arbs").fetchall()
    valued = [r for r in rows if r[3] is not None]
    print(f"\nsample: {n_blocks} blocks over {days:.2f} days ({produced:,.0f} produced blocks); {n_tx:,} txs, "
          f"{n_failed / n_tx:.0%} failed")
    print(f"arbitrage txs: {len(rows):,} ({len(rows) * scale:,.0f}/day); valued (SOL/USDC/USDT loops): {len(valued) / max(len(rows), 1):.0%}")
    net = [r[3] for r in valued]
    by_block = defaultdict(float)
    for r in valued:
        by_block[r[0]] += r[3]
    slots = [s for (s,) in db.execute("SELECT slot FROM blocks")]
    daily = sum(net) * scale
    boots = []
    rng = random.Random(1)
    for _ in range(1000):
        boots.append(sum(by_block.get(rng.choice(slots), 0.0) for _ in slots) * scale)
    boots.sort()
    print(f"net profit: ${daily:,.0f}/day (95% CI ${boots[25]:,.0f}..${boots[974]:,.0f}); gross ${sum(r[4] for r in valued) * scale:,.0f}/day; "
          f"fees {sum(r[5] for r in valued) * scale:,.1f} SOL/day; visible tips {sum(r[6] for r in valued) * scale:,.1f} SOL/day")
    if net:
        q = statistics.quantiles(net, n=100)
        print(f"per arbitrage (USD): median {statistics.median(net):.3f}, p90 {q[89]:.3f}, p99 {q[98]:.2f}, "
              f"max {max(net):.2f}; net <= 0: {sum(1 for x in net if x <= 0) / len(net):.0%}")
    grp = Counter()
    for r in valued:
        grp[r[1]] += max(r[3], 0.0)
    tot = sum(grp.values()) or 1
    top = grp.most_common(10)
    print(f"searcher groups: {len(grp)}; top 1 {top[0][1] / tot:.0%}, top 5 {sum(v for _, v in top[:5]) / tot:.0%}, "
          f"top 10 {sum(v for _, v in top) / tot:.0%} of positive net profit" if top else "no groups")
    for g, v in top:
        print(f"   {g[:52]:52} ${v * scale:,.0f}/day")
    print(f"competition: {n_arb_failed:,} failed attempts by arbitrage programs vs {len(rows):,} successes "
          f"({n_arb_failed / max(len(rows), 1):.1f} failures per success)")
    mints = Counter(r[2] for r in rows)
    print("loop mints:", {("SOL" if m == WSOL else "USDC/USDT" if m in USD_MINTS else m[:8]): n for m, n in mints.most_common(6)})


# --- Stage B: reachability -----------------------------------------------------------

def reach() -> None:
    load_env()
    db = sqlite3.connect(OUT_DB)
    db.execute("CREATE TABLE IF NOT EXISTS reach (slot INTEGER, idx INTEGER, age_slots INTEGER, age_vaults INTEGER, "
               "min_account TEXT, n_accounts INTEGER, PRIMARY KEY (slot, idx))")
    rows = db.execute("SELECT slot, idx, grp, accounts FROM arbs ORDER BY slot, idx").fetchall()
    sample = random.Random(SEED + 1).sample(rows, min(N_REACH, len(rows)))
    done = {(s, i) for s, i in db.execute("SELECT slot, idx FROM reach")}

    def last_touch(acct: str, slot: int) -> int | None:
        res = rpc("getTransactionsForAddress", [acct, {"transactionDetails": "signatures", "sortOrder": "desc", "limit": 1,
                                                       "filters": {"slot": {"lt": slot}, "status": "succeeded"}}])
        data = (res.get("result") or {}).get("data") or []
        return data[0]["slot"] if data else None

    def one(item):
        slot, idx, grp, accounts = item
        with gzip.open(BLOCKS / f"{slot}.json.gz", "rt") as f:
            b = json.load(f)
        tx = b["transactions"][idx]
        nets, _ = owner_nets(tx)
        ks = keys(tx)
        m = tx["meta"]
        pools = {o for o, c in nets.items() if is_pool(c) and not on_curve(o)}
        tok_owner = {ks[bb["accountIndex"]]: bb.get("owner") for bb in m["preTokenBalances"] + m["postTokenBalances"]}
        cand = sorted(a for a in json.loads(accounts)
                      if not a.startswith(SYSVAR_PREFIX) and (a not in tok_owner or tok_owner[a] in pools))
        info = rpc("getMultipleAccounts", [cand, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])["result"]["value"]
        prog = None if grp.startswith("payer:") else grp
        cand = [a for a, v in zip(cand, info) if v and v["owner"] not in (prog, "11111111111111111111111111111111")]
        vaults = {a for a in cand if tok_owner.get(a) in pools}
        # last successful write before the arbitrage: earlier in the same block, else the account's history
        age = {}
        for j in range(idx - 1, -1, -1):
            t2 = b["transactions"][j]
            if t2["meta"]["err"] is None:
                for a in writable(t2) & set(cand):
                    age.setdefault(a, 0)
        for a in cand:
            if a not in age:
                prev = last_touch(a, slot)
                if prev is not None:
                    age[a] = slot - prev
        if not age:
            return slot, idx, None, None, None, len(cand)
        a_min = min(age, key=age.get)
        v_ages = [age[a] for a in vaults if a in age]
        return slot, idx, age[a_min], (min(v_ages) if v_ages else None), a_min, len(cand)

    todo = [it for it in sample if (it[0], it[1]) not in done]
    with ThreadPoolExecutor(6) as ex:
        for n, res in enumerate(ex.map(one, todo)):
            db.execute("INSERT OR REPLACE INTO reach VALUES (?,?,?,?,?,?)", res)
            if n % 25 == 0:
                db.commit()
                print(f"  {n}/{len(todo)}", flush=True)
    db.commit()
    report_reach(db)


def report_reach(db: sqlite3.Connection) -> None:
    man = json.loads(MANIFEST.read_text())
    n_blocks = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    n_arbs = db.execute("SELECT COUNT(*) FROM arbs").fetchone()[0]
    days = (man["t_hi"] - man["t_lo"]) / 86400
    produced = (man["hi"] - man["lo"] + 1) * (1 - len(man["skipped"]) / max(len(man["draws"]), 1))
    scale = produced / n_blocks / days
    common = db.execute("SELECT min_account, COUNT(*) FROM reach WHERE age_slots = 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall()
    print("accounts that most often set a same-slot age:", [(a[:8], n) for a, n in common])
    vrows = db.execute("SELECT r.age_vaults, a.net_usd FROM reach r JOIN arbs a USING (slot, idx) WHERE r.age_vaults IS NOT NULL").fetchall()
    if vrows:
        far_v = [v for a, v in vrows if a >= REACH_SLOTS and v is not None]
        print(f"sensitivity (pool vaults only): {len(far_v) / len(vrows):.0%} of arbitrages are >= {REACH_SLOTS} slots old, "
              f"net ${sum(far_v):,.2f} in sample")
    rows = db.execute("SELECT r.age_slots, a.net_usd, a.grp FROM reach r JOIN arbs a USING (slot, idx)").fetchall()
    known = [r for r in rows if r[0] is not None]
    print(f"\nreachability sample: {len(rows)} arbitrages ({len(known)} with a known age)")
    for lo, hi, label in ((0, 0, "same slot"), (1, 2, "1-2 slots"), (REACH_SLOTS, 10**12, f">= {REACH_SLOTS} slots")):
        part = [r for r in known if lo <= r[0] <= hi]
        val = [r[1] for r in part if r[1] is not None]
        print(f"  {label:12} {len(part) / max(len(known), 1):5.0%} of arbitrages, net ${sum(val):,.2f} in sample")
    far = [r for r in known if r[0] >= REACH_SLOTS and r[1] is not None]
    # sample -> all arbitrages -> per day
    daily_far = sum(r[1] for r in far) * (n_arbs / max(len(rows), 1)) * scale
    grp = Counter()
    for r in far:
        grp[r[2]] += max(r[1], 0.0)
    tot = sum(grp.values()) or 1
    top = grp.most_common(10)
    med = statistics.median([r[1] for r in far]) if far else None
    checks = [
        (f"net profit from >= {REACH_SLOTS}-slot gaps ${daily_far:,.0f}/day >= $1,000", daily_far >= 1000),
        (f"top group {top[0][1] / tot:.0%} <= 50% and top 10 {sum(v for _, v in top) / tot:.0%} < 90%" if top else "no groups",
         bool(top) and top[0][1] / tot <= 0.5 and sum(v for _, v in top) / tot < 0.9),
        (f"median net per >= {REACH_SLOTS}-slot arbitrage ${med if med is not None else float('nan'):.3f} >= $0.50", med is not None and med >= 0.5),
    ]
    print("\nGo / no-go (registry):")
    for t, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {t}")
    print(f"DECISION: {'GO (shadow-mode prototype)' if all(ok for _, ok in checks) else 'NO-GO'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        fetch()
    elif cmd == "analyze":
        analyze()
    elif cmd == "reach":
        reach()
    else:
        print(__doc__)
