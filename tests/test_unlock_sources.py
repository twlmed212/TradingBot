"""Synthetic document archive tests; no network or market data."""
import hashlib
import sqlite3
from datetime import datetime, timezone

import pytest

from research import unlock_sources as archive

SOURCE = {"id": "synthetic", "url": "https://example.org/document", "allowed_hosts": ["example.org"]}


@pytest.mark.parametrize("url", ["http://example.org/a", "https://evil.test/a", "https://user:secret@example.org/a", "https://example.org/a?api-key=x", "https://example.org:8080/a"])
def test_rejects_unapproved_or_credential_urls(url):
    with pytest.raises(ValueError):
        archive.checked_url(url, SOURCE["allowed_hosts"])


def test_redirect_is_checked_before_following():
    handler = archive.ApprovedRedirects(SOURCE["allowed_hosts"])
    with pytest.raises(ValueError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://unapproved.test/page")


def test_capture_preserves_versions_and_never_backdates():
    with sqlite3.connect(":memory:") as db:
        db.executescript(archive.SCHEMA)
        before = datetime.now(timezone.utc)
        for body in (b"original", b"original", b"revised"):
            archive.save(db, SOURCE, SOURCE["url"], body, "text/html", "Mon, 01 Jan 2024 00:00:00 GMT")
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 2
        for timestamp, digest in db.execute("SELECT observed_at,sha256 FROM observations"):
            assert datetime.fromisoformat(timestamp) >= before
            assert digest in {hashlib.sha256(x).hexdigest() for x in (b"original", b"revised")}
        for table in ("documents", "observations"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize("body,kind", [(b"", "text/html"), (b"x", "image/png")])
def test_invalid_document_leaves_no_observation(body, kind):
    with sqlite3.connect(":memory:") as db:
        db.executescript(archive.SCHEMA)
        with pytest.raises(ValueError):
            archive.save(db, SOURCE, SOURCE["url"], body, kind)
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
