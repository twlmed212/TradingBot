"""H9 verdict counting (registry Clarifications) and the engine's freeze after the window."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from research import h9_paper, h9_verdict as v

UTC = timezone.utc
START = datetime(2026, 10, 25, 23, tzinfo=UTC)  # Sunday, the real opening run


def make_db(path, equity_at, until, skip=(), positions=None, booked=None):
    db = sqlite3.connect(path)
    db.executescript(h9_paper.SCHEMA)
    h = START
    while h <= until:
        if h not in skip:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (h.isoformat(), h.isoformat(), equity_at(h), 0, 0, 0, ""))
        h += timedelta(hours=1)
    for coin, (q, e) in (positions or {}).items():
        db.execute("INSERT INTO positions VALUES (?,?,?,?)", (coin, q, e, START.isoformat()))
    for coin, pnl in (booked or {}).items():
        db.execute("INSERT INTO contrib VALUES (?,?)", (coin, pnl))
    db.commit()
    db.close()
    return path


def test_weeks_run_monday_to_monday_and_skip_the_opening_hour(tmp_path):
    # equity steps: 9,990 at the opening hour, 10,100 through week 1, 10,050 through week 2, 10,200 after
    def eq(h):
        if h == START:
            return 9_990.0
        if h < datetime(2026, 11, 2, tzinfo=UTC):
            return 10_100.0
        if h < datetime(2026, 11, 9, tzinfo=UTC):
            return 10_050.0
        return 10_200.0
    now = datetime(2026, 11, 9, 5, 30, tzinfo=UTC)
    data = v.load(make_db(tmp_path / "h9.sqlite3", eq, datetime(2026, 11, 9, 5, tzinfo=UTC)))
    res = v.evaluate(data, {}, now)
    assert [w["week"] for w in res["weeks"]] == ["2026-10-26", "2026-11-02", "2026-11-09"]
    assert [w["complete"] for w in res["weeks"]] == [True, True, False]
    assert res["weeks"][0]["return"] == pytest.approx(10_100 / 9_990 - 1, abs=1e-6)
    assert res["weeks"][1]["return"] == pytest.approx(10_050 / 10_100 - 1, abs=1e-6)
    assert (res["weeks_up"], res["weeks_done"]) == (1, 2)
    assert res["checks"][2]["pass"] is False          # 50% < 55%
    assert res["verdict"] == "not on track" and res["final"] is False


def test_runs_due_and_missed_runs(tmp_path):
    skip = {START + timedelta(hours=3)}
    data = v.load(make_db(tmp_path / "h9.sqlite3", lambda h: 10_000.0, START + timedelta(hours=9), skip=skip))
    res = v.evaluate(data, {}, START + timedelta(hours=10, minutes=5))   # the 10:00 hour is not due until :10
    assert res["runs_due"] == 10 and res["runs"] == 9
    res = v.evaluate(data, {}, START + timedelta(hours=10, minutes=15))
    assert res["runs_due"] == 11 and res["runs"] == 9
    # a run that finished early (at :02) counts as due at once, so the ratio never exceeds 100%
    data = v.load(make_db(tmp_path / "h9b.sqlite3", lambda h: 10_000.0, START + timedelta(hours=10), skip=skip))
    res = v.evaluate(data, {}, START + timedelta(hours=10, minutes=3))
    assert res["runs_due"] == 11 and res["runs"] == 10
    assert res["runs_total"] == 2353                                         # registry: every hour through 31 Jan 23:00
    assert res["checks"][4]["pass"] is False                                 # 10/11 < 95%


def test_drawdown_peak_starts_at_start_equity(tmp_path):
    data = v.load(make_db(tmp_path / "h9.sqlite3", lambda h: 9_000.0 if h > START else 9_990.0, START + timedelta(hours=5)))
    res = v.evaluate(data, {}, START + timedelta(hours=6))
    assert res["max_dd"] == pytest.approx(0.10)
    assert res["checks"][1]["pass"] is True


def test_token_share_uses_booked_plus_unrealized_and_counts_sol(tmp_path):
    pos = {"SOL": (50.0, 100.0), "PUMP": (-1_000.0, 1.0)}
    booked = {"SOL": -5.0, "PUMP": 10.0, "GOAT": -20.0}
    data = v.load(make_db(tmp_path / "h9.sqlite3", lambda h: 10_000.0, START + timedelta(hours=2), positions=pos, booked=booked))
    res = v.evaluate(data, {"SOL": 104.0, "PUMP": 0.9}, START + timedelta(hours=3))
    totals = {t["coin"]: t["total"] for t in res["tokens"]}
    assert totals == {"SOL": 195.0, "PUMP": 110.0, "GOAT": -20.0}
    assert res["profit"] == pytest.approx(285.0)
    assert res["top_token"] == "SOL" and res["top_share"] == pytest.approx(195 / 285)
    assert res["checks"][3]["pass"] is False                                 # 68% > 50%


def test_no_profit_makes_token_share_not_applicable_and_never_passes(tmp_path):
    data = v.load(make_db(tmp_path / "h9.sqlite3", lambda h: 9_900.0, START + timedelta(hours=2),
                          positions={"PUMP": (-100.0, 1.0)}, booked={"PUMP": -100.0}))
    res = v.evaluate(data, {"PUMP": 1.0}, START + timedelta(hours=3))
    assert res["top_share"] is None and res["checks"][3]["pass"] is None
    assert res["verdict"] == "not on track"


def test_final_verdict_after_the_window_ignores_later_runs(tmp_path):
    end = v.END
    data = v.load(make_db(tmp_path / "h9.sqlite3", lambda h: 10_500.0, end + timedelta(hours=3)))
    assert data["hours"][-1] == end
    res = v.evaluate(data, {}, end + timedelta(minutes=30))
    assert res["final"] is True and res["runs"] == res["runs_due"] == res["runs_total"] == 2353
    assert res["verdict"] in ("PASS", "FAIL")


def test_engine_does_nothing_after_the_window(tmp_path, monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 2, 1, 0, 2, tzinfo=UTC)
    monkeypatch.setattr(h9_paper, "datetime", Frozen)
    monkeypatch.setattr(h9_paper, "DB", tmp_path / "h9.sqlite3")
    monkeypatch.setattr(h9_paper, "post", lambda body: pytest.fail("no network after the window"))
    assert h9_paper.step().startswith("evaluation window over")
    assert not (tmp_path / "h9.sqlite3").exists()


def test_console_card_matches_the_verdict(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from console.api import main

    pos = {"SOL": (50.0, 100.0), "PUMP": (-1_000.0, 1.0)}
    path = make_db(tmp_path / "h9.sqlite3", lambda h: 10_000.0, START + timedelta(hours=4), positions=pos, booked={"SOL": -5.0, "PUMP": 10.0})
    monkeypatch.setattr(main, "H9_DB", path)
    monkeypatch.setattr(main, "hyperliquid_mids", lambda: {"SOL": 104.0, "PUMP": 0.9})
    main._cache.clear()
    d = TestClient(main.app).get("/api/h9").json()
    res = v.evaluate(v.load(path), {"SOL": 104.0, "PUMP": 0.9}, datetime.now(UTC))
    assert d["criteria"]["runs"] == res["runs"] and d["criteria"]["top_token"] == res["top_token"] == "SOL"
    assert {t["coin"]: t["total"] for t in d["tokens"]} == {t["coin"]: t["total"] for t in res["tokens"]}
    assert d["live_equity"] == pytest.approx(10_000 + res["profit"])
    pump = next(t for t in d["tokens"] if t["coin"] == "PUMP")
    assert pump["side"] == "short" and pump["stop"] == pytest.approx(1.3) and pump["to_stop"] == pytest.approx(1.3 / 0.9 - 1)
