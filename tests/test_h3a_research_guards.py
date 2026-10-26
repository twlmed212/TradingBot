"""Offline H3a rule/holdout regression tests using only synthetic observations."""

from datetime import datetime, timedelta, timezone
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from research import h3a_killtest as h3a
from research import listing_prices as fetch


UTC = timezone.utc
CUTOFF = datetime(2025, 7, 1, tzinfo=UTC)
ANNOUNCED = datetime(2024, 2, 1, 10, 15, tzinfo=UTC)
MINT = "synthetic-mint"


def event(announced=ANNOUNCED, trading_start=None):
    return {
        "mint": MINT,
        "announced_at": announced.isoformat(),
        "trading_start_at": trading_start.isoformat() if trading_start else None,
        "ticker": "SYNTHETIC",
        "event_type": "spot_listing",
        "evidence": "synthetic",
    }


class FakePrices:
    def __init__(self, observations=None):
        self.observations = observations or {}
        self.calls = []

    def at(self, mint, hour):
        self.calls.append((mint, hour))
        return self.observations.get(hour, (1.0, 20))


class NoPrices:
    def at(self, mint, hour):
        pytest.fail("An excluded holdout event must not query prices")


def test_registered_six_variants_and_primary_are_frozen():
    assert h3a.DELAYS == {"1h": timedelta(hours=1), "3h": timedelta(hours=3)}
    assert h3a.EXITS == ("trading_start", "24h", "72h")
    assert h3a.PRIMARY == ("1h", "trading_start")
    assert len(h3a.DELAYS) * len(h3a.EXITS) == 6
    assert h3a.MIN_SWAPS == 20
    assert h3a.DEFAULT_COST_BPS == 40.0
    assert h3a.HOLDOUT_CUTOFF == fetch.HOLDOUT_CUTOFF == CUTOFF


@pytest.mark.parametrize("delay", ("1h", "3h"))
@pytest.mark.parametrize("exit_key", ("trading_start", "24h", "72h"))
def test_each_registered_variant_uses_rounded_entry_and_frozen_exit(delay, exit_key):
    prices = FakePrices()
    trading_start = datetime(2024, 2, 2, 11, 1, tzinfo=UTC)
    rows, excluded = h3a.evaluate([event(trading_start=trading_start)], prices, {}, delay, exit_key, "base")
    entry = datetime(2024, 2, 1, 12 if delay == "1h" else 14, tzinfo=UTC)
    expected_exit = (
        datetime(2024, 2, 2, 12, tzinfo=UTC)
        if exit_key == "trading_start"
        else entry + timedelta(hours=int(exit_key[:-1]))
    )
    assert excluded == []
    assert rows[0]["entry_h"] == entry
    assert rows[0]["exit_h"] == expected_exit
    assert prices.calls == [(MINT, entry), (MINT, expected_exit)]


@pytest.mark.parametrize("trading_start", (None, datetime(2024, 2, 1, 11, tzinfo=UTC), datetime(2024, 2, 1, 12, tzinfo=UTC)))
def test_primary_uses_24h_fallback_when_trading_start_is_missing_or_not_later(trading_start):
    rows, excluded = h3a.evaluate([event(trading_start=trading_start)], FakePrices(), {}, *h3a.PRIMARY, "base")
    assert excluded == []
    assert rows[0]["exit_h"] == rows[0]["entry_h"] + timedelta(hours=24)


def test_exact_full_hour_is_not_rounded_to_the_following_hour():
    full_hour = datetime(2024, 2, 1, 12, tzinfo=UTC)
    assert h3a.ceil_hour(full_hour) == full_hour
    assert h3a.ceil_hour(full_hour + timedelta(microseconds=1)) == full_hour + timedelta(hours=1)


@pytest.mark.parametrize("entry_swaps,exit_swaps,priced", ((19, 20, False), (20, 19, False), (20, 20, True)))
def test_twenty_swaps_required_at_both_entry_and_exit(entry_swaps, exit_swaps, priced):
    entry = datetime(2024, 2, 1, 12, tzinfo=UTC)
    exit_at = entry + timedelta(hours=24)
    prices = FakePrices({entry: (1.0, entry_swaps), exit_at: (1.0, exit_swaps)})
    rows, excluded = h3a.evaluate([event()], prices, {}, *h3a.PRIMARY, "base")
    assert len(rows) == int(priced)
    assert len(excluded) == int(not priced)


@pytest.mark.parametrize("cost_bps,expected_base", ((None, 40), (-5, 20), (0, 20), (19, 20), (20, 20), (70, 70)))
@pytest.mark.parametrize("mode", ("base", "stress"))
def test_cost_default_floor_and_two_times_plus_fifty_bps_stress(cost_bps, expected_base, mode):
    costs = {} if cost_bps is None else {MINT: cost_bps}
    rows, excluded = h3a.evaluate([event()], FakePrices(), costs, *h3a.PRIMARY, mode)
    expected_bps = expected_base if mode == "base" else 2 * expected_base + 50
    assert excluded == []
    assert rows[0]["gross"] == 0
    assert rows[0]["net"] == pytest.approx(-expected_bps / 10_000)


@pytest.mark.parametrize(
    "announced,trading_start,exit_key",
    (
        (CUTOFF, None, "24h"),
        (CUTOFF - timedelta(hours=1), None, "24h"),
        (CUTOFF - timedelta(hours=25), None, "24h"),
        (CUTOFF - timedelta(hours=73), None, "72h"),
        (CUTOFF - timedelta(days=2), CUTOFF, "trading_start"),
        (CUTOFF - timedelta(days=2), CUTOFF - timedelta(minutes=1), "trading_start"),
    ),
)
def test_entry_or_exit_at_cutoff_is_excluded_before_price_access(announced, trading_start, exit_key):
    rows, excluded = h3a.evaluate([event(announced, trading_start)], NoPrices(), {}, "1h", exit_key, "base")
    assert rows == []
    assert len(excluded) == 1


@pytest.mark.parametrize(
    "trading_start,expected",
    (
        (None, None),
        (datetime(2024, 2, 1, 9, 15, tzinfo=UTC), datetime(2024, 2, 1, 10, tzinfo=UTC)),
        (datetime(2024, 2, 2, 12, tzinfo=UTC), datetime(2024, 2, 2, 12, tzinfo=UTC)),
        (CUTOFF - timedelta(minutes=1), None),
        (CUTOFF, None),
    ),
)
def test_secondary_anchor_is_actual_trading_start_not_primary_fallback(trading_start, expected):
    synthetic = event(trading_start=trading_start)
    synthetic["exit_h"] = datetime(2024, 2, 2, 12, tzinfo=UTC)
    assert h3a.secondary_anchor(synthetic) == expected


def test_prices_load_only_pre_holdout_observations_for_selected_pool(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-prices.sqlite3"
    before = CUTOFF - timedelta(hours=1)
    stale_only_hour = before - timedelta(hours=1)
    with sqlite3.connect(path) as db:
        db.executescript(fetch.SCHEMA)
        db.executemany(
            "INSERT INTO pools VALUES (?,?,?,?,?,?,?)",
            [
                (MINT, "selected", "synthetic", fetch.WSOL, None, None, ANNOUNCED.isoformat()),
                ("usd-mint", "usd-pool", "synthetic", fetch.USDC, None, None, ANNOUNCED.isoformat()),
            ],
        )
        db.executemany(
            "INSERT INTO hourly VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (MINT, "selected", before.isoformat(), 50, 20, 2.0, None, None, 0),
                (MINT, "old-pool", before.isoformat(), 50, 20, 99.0, None, None, 0),
                (MINT, "old-pool", stale_only_hour.isoformat(), 50, 20, 98.0, None, None, 0),
                (MINT, "selected", CUTOFF.isoformat(), 50, 20, 999.0, None, None, 0),
                ("usd-mint", "usd-pool", before.isoformat(), 50, 20, 10.0, None, None, 0),
                ("unselected-mint", "other-pool", before.isoformat(), 50, 20, 97.0, None, None, 0),
            ],
        )
        db.executemany("INSERT INTO sol_usd VALUES (?,?)", [(before.isoformat(), 100.0), (CUTOFF.isoformat(), 999.0)])
    monkeypatch.setattr(h3a, "PRICES_DB", path)

    prices = h3a.Prices()

    assert prices.hours[MINT] == {before.isoformat(): (2.0, 20)}
    assert "unselected-mint" not in prices.hours
    assert prices.sol == {before.isoformat(): 100.0}
    assert prices.at(MINT, before) == (2.0, 20)
    assert prices.at("usd-mint", before) == (0.1, 20)
    assert prices.at(MINT, stale_only_hour) == (None, 0)
    assert prices.at(MINT, CUTOFF) == (None, 0)
    assert prices.at(MINT, CUTOFF + timedelta(hours=1)) == (None, 0)
    prices.created[MINT] = before + timedelta(minutes=21)
    assert prices.at(MINT, before) == (None, 0)


@pytest.mark.parametrize("hour", (CUTOFF, CUTOFF + timedelta(hours=1)))
def test_sample_hour_rejects_holdout_before_http(monkeypatch, hour):
    def forbidden_http(*args, **kwargs):
        pytest.fail("Holdout sample must be rejected before HTTP")

    monkeypatch.setattr(fetch, "http_json", forbidden_http)
    with pytest.raises(ValueError):
        fetch.sample_hour("https://synthetic.invalid", "pool", MINT, fetch.WSOL, hour)


def test_sol_usd_fetch_clamps_request_and_ignores_server_overshoot(monkeypatch):
    start = CUTOFF - timedelta(hours=2)
    start_ms = fetch.ts(start) * 1000
    cutoff_ms = fetch.ts(CUTOFF) * 1000
    requests = []

    def fake_http(url):
        query = parse_qs(urlsplit(url).query)
        requests.append(query)
        assert int(query["startTime"][0]) == start_ms
        assert int(query["endTime"][0]) == cutoff_ms - 1
        # A bad upstream response must not allow a sealed or out-of-window row into the DB.
        return [[ms, "0", "0", "0", "100"] for ms in (start_ms - 3_600_000, start_ms, cutoff_ms - 3_600_000, cutoff_ms, cutoff_ms + 3_600_000)]

    monkeypatch.setattr(fetch, "http_json", fake_http)
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    with sqlite3.connect(":memory:") as db:
        db.executescript(fetch.SCHEMA)
        fetch.sol_usd_hours(db, start, CUTOFF + timedelta(days=7))
        rows = db.execute("SELECT hour, close FROM sol_usd ORDER BY hour").fetchall()
    assert len(requests) == 1
    assert rows == [(start.isoformat(), 100.0), ((CUTOFF - timedelta(hours=1)).isoformat(), 100.0)]


@pytest.mark.parametrize("start", (CUTOFF, CUTOFF + timedelta(hours=1)))
def test_sol_usd_fetch_does_not_request_holdout_only_window(monkeypatch, start):
    def forbidden_http(*args, **kwargs):
        pytest.fail("A holdout-only SOL/USD range must not issue an HTTP request")

    monkeypatch.setattr(fetch, "http_json", forbidden_http)
    with sqlite3.connect(":memory:") as db:
        db.executescript(fetch.SCHEMA)
        fetch.sol_usd_hours(db, start, start + timedelta(hours=2))
        assert db.execute("SELECT COUNT(*) FROM sol_usd").fetchone()[0] == 0
