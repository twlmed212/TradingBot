"""Daily consistent copies of the small, irreplaceable SQLite files on the server.

Runs at 03:15 UTC (deskbot-backup.timer), just before the 03:30 UTC EBS snapshot (Data Lifecycle Manager policy,
7 kept), so every snapshot also holds a clean copy taken with SQLite's online backup API. Copies live in
/opt/deskbot/backups and are kept for 30 days. quotes.sqlite3 is not copied here: it is large and grows daily,
and the snapshot already captures it (SQLite's journal makes a crash-consistent snapshot recoverable).

    python3 /opt/deskbot/ops/backup_sqlite.py
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(os.environ.get("DESKBOT_DATA", "/opt/deskbot/data"))
OUT = Path(os.environ.get("DESKBOT_BACKUPS", "/opt/deskbot/backups"))
FILES = ["h9_paper.sqlite3", "announcements.sqlite3"]
KEEP_DAYS = 30


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for name in FILES:
        src_path = DATA / name
        if not src_path.exists():
            print(f"skip {name}: not found")
            continue
        dst_path = OUT / f"{src_path.stem}-{day}.sqlite3"
        tmp = dst_path.with_suffix(".tmp")
        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=60)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        src.close()
        dst.close()
        if ok != "ok":
            tmp.unlink()
            raise SystemExit(f"{name}: integrity check failed on the copy ({ok})")
        tmp.replace(dst_path)
        print(f"{name} -> {dst_path.name} ({dst_path.stat().st_size / 1e6:.2f} MB)")
    cutoff = time.time() - KEEP_DAYS * 86400
    for old in OUT.glob("*.sqlite3"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            print(f"removed {old.name}")


if __name__ == "__main__":
    main()
