"""Archive public unlock documents, not prices or trading signals.

python3 research/unlock_sources.py --plan
python3 research/unlock_sources.py --fetch

Capture time is never backdated to a page's claimed publication date. Historical
availability requires separately verified archived versions. This collector does
not qualify any event for H4, evaluate returns, or contact a wallet/RPC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research/data/unlock_sources.json"
DATABASE = ROOT / "data/unlock_sources.sqlite3"
MAX_BYTES = 5_000_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 sha256 TEXT PRIMARY KEY, body BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, requested_url TEXT NOT NULL,
 final_url TEXT NOT NULL, observed_at TEXT NOT NULL, sha256 TEXT NOT NULL,
 content_type TEXT NOT NULL, last_modified_claim TEXT,
 FOREIGN KEY(sha256) REFERENCES documents(sha256)
);
CREATE TRIGGER IF NOT EXISTS immutable_documents_update BEFORE UPDATE ON documents
 BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_documents_delete BEFORE DELETE ON documents
 BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_observations_update BEFORE UPDATE ON observations
 BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_observations_delete BEFORE DELETE ON observations
 BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END;
"""


def checked_url(url: str, allowed_hosts: list[str]) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in allowed_hosts or p.username
            or p.password or p.port not in (None, 443) or p.query or p.fragment):
        raise ValueError("Source URL must be a credential-free approved HTTPS document")
    return url


def save(db, source, final_url, body, content_type, last_modified=None):
    checked_url(final_url, source["allowed_hosts"])
    if not body or len(body) > MAX_BYTES:
        raise ValueError("Empty or oversized source document")
    if not any(t in content_type.lower() for t in ("text/", "application/json", "application/pdf")):
        raise ValueError("Unsupported document content type")
    digest = hashlib.sha256(body).hexdigest()
    # UTC receipt time, not HTTP Last-Modified or a date found inside the page.
    observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with db:
        db.execute("INSERT OR IGNORE INTO documents VALUES (?,?)", (digest, body))
        db.execute("INSERT INTO observations (source_id,requested_url,final_url,observed_at,sha256,"
                   "content_type,last_modified_claim) VALUES (?,?,?,?,?,?,?)",
                   (source["id"], source["url"], final_url, observed_at, digest, content_type, last_modified))
    return digest


class ApprovedRedirects(HTTPRedirectHandler):
    def __init__(self, allowed_hosts):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    sources = json.loads(MANIFEST.read_text())["sources"]
    for source in sources:
        checked_url(source["url"], source["allowed_hosts"])
    if args.plan:
        for source in sources:
            print(f"{source['id']}: {source['url']}")
        print("Documents only; no historical-availability claim, prices, keys, or trading.")
        return
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with sqlite3.connect(DATABASE) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        for source in sources:
            try:
                req = Request(source["url"], headers={"User-Agent": "deskbot-research/1", "Accept-Encoding": "identity"})
                opener = build_opener(ApprovedRedirects(source["allowed_hosts"]))
                with opener.open(req, timeout=30) as response:
                    digest = save(db, source, response.url, response.read(MAX_BYTES + 1),
                                  response.headers.get("Content-Type", ""), response.headers.get("Last-Modified"))
                print(f"{source['id']}: archived {digest[:12]} (not historical proof)")
            except Exception as exc:
                failed += 1
                # No response bodies or arbitrary upstream error text in logs.
                print(f"{source['id']}: failed ({type(exc).__name__}); no observation saved")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
