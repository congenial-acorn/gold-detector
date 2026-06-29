"""
Tests for mark_market_alerts_sent_batch() atomic batch marking in MarketDatabase.

Verifies that batch marking:
- Performs a SINGLE save for all entries (not one per entry)
- Is a no-op for an empty list
- Marks every entry in the batch
- Skips missing system/station/metal paths gracefully
- Handles mixed recipient types (guild + user) in one call
- Is idempotent when the same entry repeats
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.market_database import MarketDatabase
from tests.test_helpers import count_save_calls


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "market_alerts_batch.json"


@pytest.fixture
def db(db_path):
    return MarketDatabase(db_path)


def _seed(db, system="Sol", station="Abraham Lincoln", metal="Gold"):
    """Write a market entry so the system/station/metal path exists."""
    db.write_market_entry(
        system_name=system,
        system_address="10477373803",
        station_name=station,
        station_type="Coriolis Starport",
        url="https://inara.cz/station/-1/",
        metal=metal,
        stock=25000,
    )


def test_empty_batch_skips_save(db):
    """An empty entries list must not trigger a save."""
    with count_save_calls(db):
        db.mark_market_alerts_sent_batch([])

    assert db.save_count == 0


def test_single_entry_batch_marks_sent(db):
    """A degenerate single-entry batch marks that recipient."""
    _seed(db)
    db.mark_market_alerts_sent_batch(
        [("Sol", "Abraham Lincoln", "Gold", "guild", "123")]
    )

    assert db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "123"
    )
    assert not db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "999"
    )


def test_multiple_entries_all_marked_in_single_save(db):
    """Multiple entries are all marked with exactly one save call."""
    _seed(db)
    entries = [("Sol", "Abraham Lincoln", "Gold", "guild", str(i)) for i in range(10)]

    with count_save_calls(db):
        db.mark_market_alerts_sent_batch(entries)

    assert db.save_count == 1
    for i in range(10):
        assert db.has_market_alert_been_sent(
            "Sol", "Abraham Lincoln", "Gold", "guild", str(i)
        )


def test_missing_paths_skipped_gracefully(db):
    """Missing system/station/metal paths are skipped without error."""
    _seed(db)
    db.mark_market_alerts_sent_batch(
        [
            ("Sol", "Abraham Lincoln", "Gold", "guild", "123"),
            ("MissingSystem", "Abraham Lincoln", "Gold", "guild", "456"),
            ("Sol", "MissingStation", "Gold", "guild", "789"),
            ("Sol", "Abraham Lincoln", "MissingMetal", "guild", "012"),
            ("Sol", "Abraham Lincoln", "Gold", "guild", "345"),
        ]
    )

    assert db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "123"
    )
    assert db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "345"
    )
    assert not db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "456"
    )
    assert not db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "789"
    )
    assert not db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "012"
    )


def test_mixed_recipient_types_in_batch(db):
    """Guild and user recipients are marked in the same batch call."""
    _seed(db)
    db.mark_market_alerts_sent_batch(
        [
            ("Sol", "Abraham Lincoln", "Gold", "guild", "123"),
            ("Sol", "Abraham Lincoln", "Gold", "user", "456"),
        ]
    )

    assert db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "123"
    )
    assert db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "user", "456"
    )
    # Per-recipient independence: marking guild doesn't mark user, and vice versa.
    assert not db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "456"
    )
    assert not db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "user", "123"
    )


def test_duplicate_entries_idempotent_single_save(db):
    """The same entry repeated in the batch is idempotent and still one save."""
    _seed(db)
    entries = [("Sol", "Abraham Lincoln", "Gold", "guild", "123")] * 5

    with count_save_calls(db):
        db.mark_market_alerts_sent_batch(entries)

    assert db.save_count == 1
    assert db.has_market_alert_been_sent(
        "Sol", "Abraham Lincoln", "Gold", "guild", "123"
    )
