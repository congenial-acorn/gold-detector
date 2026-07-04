"""Tests for shared MarketDatabase instance wiring across gold.py + GoldRunner.

These tests pin the fix for the dual-instance desynchronization bug where
bot.py and gold.py each created their OWN MarketDatabase pointing at the same
file, causing dispatch to read stale in-memory data that never saw the
monitor's fresh writes (e.g. first-discovery stations like Akrata Beach).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold
from gold_detector.gold_runner import GoldRunner
from gold_detector.market_database import MarketDatabase


@pytest.fixture
def fake_monitor(monkeypatch):
    """Replace gold.monitor_metals with a capturing stub that returns immediately."""
    captured = {}

    def _fake(urls, metals, market_db):
        captured["market_db"] = market_db

    monkeypatch.setattr(gold, "monitor_metals", _fake)
    return captured


# ---------------------------------------------------------------------------
# gold.main(market_db=...) wiring
# ---------------------------------------------------------------------------


def test_gold_main_uses_external_market_db(fake_monitor, tmp_path):
    """gold.main(market_db=...) must forward the EXTERNAL instance to monitor_metals
    instead of constructing its own — so the monitor and messenger share one object."""
    external_db = MarketDatabase(tmp_path / "shared.json")

    gold.main(market_db=external_db)

    assert fake_monitor["market_db"] is external_db, (
        "gold.main(market_db=...) must pass the SAME instance to monitor_metals, "
        "not create a new one"
    )


def test_gold_main_creates_own_db_when_no_arg(fake_monitor, monkeypatch, tmp_path):
    """gold.main() with no arg (standalone `python gold.py` mode) still works —
    it creates its own MarketDatabase so the standalone entrypoint is unaffected."""
    monkeypatch.chdir(tmp_path)  # isolate market_database.json

    gold.main()

    assert fake_monitor["market_db"] is not None
    assert isinstance(fake_monitor["market_db"], MarketDatabase)


# ---------------------------------------------------------------------------
# GoldRunner(market_db=...) wiring
# ---------------------------------------------------------------------------


def test_gold_runner_stores_market_db(tmp_path):
    """GoldRunner constructed with market_db must retain it for later use in _run()."""
    external_db = MarketDatabase(tmp_path / "shared.json")

    runner = GoldRunner(
        emit=None, loop_done=None, market_db=external_db, logger=None
    )

    assert runner.market_db is external_db


def test_gold_runner_defaults_market_db_to_none():
    """Backward-compat: GoldRunner without market_db must store None so legacy
    callers (and standalone tests) still function."""
    runner = GoldRunner(emit=None, loop_done=None)

    assert runner.market_db is None


def test_gold_runner_passes_market_db_to_gold_main(monkeypatch, tmp_path):
    """GoldRunner._run() must forward self.market_db into gold.main(market_db=...),
    not call gold.main() with no args. This is the core fix: the single shared
    instance must reach the monitor."""

    captured = {}

    def fake_main(market_db=None):
        captured["market_db"] = market_db
        raise KeyboardInterrupt("test: break the retry loop")

    monkeypatch.setattr(gold, "main", fake_main)
    monkeypatch.setattr(gold, "set_loop_done_emitter", lambda cb: None)

    external_db = MarketDatabase(tmp_path / "shared.json")
    runner = GoldRunner(
        emit=None,
        loop_done=lambda: None,
        market_db=external_db,
        logger=None,
    )

    with pytest.raises(KeyboardInterrupt):
        runner._run()

    assert captured["market_db"] is external_db, (
        "GoldRunner._run must pass the shared market_db into gold.main(market_db=...)"
    )


def test_gold_runner_without_market_db_passes_none(monkeypatch):
    """Backward-compat: GoldRunner without market_db must call gold.main(market_db=None)
    so gold.main falls back to creating its own instance (standalone parity)."""

    captured = {}

    def fake_main(market_db=None):
        captured["market_db"] = market_db
        raise KeyboardInterrupt("test: break the retry loop")

    monkeypatch.setattr(gold, "main", fake_main)
    monkeypatch.setattr(gold, "set_loop_done_emitter", lambda cb: None)

    runner = GoldRunner(emit=None, loop_done=lambda: None, logger=None)

    with pytest.raises(KeyboardInterrupt):
        runner._run()

    assert captured["market_db"] is None


# ---------------------------------------------------------------------------
# End-to-end invariant: shared instance visibility
# ---------------------------------------------------------------------------


def test_shared_instance_monitor_write_visible_to_messenger_read(tmp_path):
    """End-to-end invariant: when the monitor and messenger share ONE
    MarketDatabase, a write_market_entry on the monitor side must be visible
    to read_all_entries on the messenger side.

    This is the exact scenario that was broken for Akrata Beach: the monitor
    wrote the entry but dispatch never saw it because the two sides held
    independent in-memory caches.
    """
    db_path = tmp_path / "market_database.json"
    shared = MarketDatabase(db_path)

    # Monitor side: discovers Akrata Beach for the first time
    shared.write_market_entry(
        system_name="HIP 10792",
        system_address="https://inara.cz/elite/system/123/",
        station_name="Akrata Beach",
        station_type="Starport (Dodec)",
        url="https://inara.cz/elite/station/1089378/",
        metal="Gold",
        stock=471460,
    )

    # Messenger side: dispatch reads entries
    snapshot = shared.read_all_entries()

    assert "HIP 10792" in snapshot
    station = snapshot["HIP 10792"]["stations"]["Akrata Beach"]
    assert station["station_type"] == "Starport (Dodec)"
    assert station["metals"]["Gold"]["stock"] == 471460
    assert station["metals"]["Gold"]["sent_to"] == {"guild": {}, "user": {}}
