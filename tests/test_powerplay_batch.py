"""
Tests for mark_powerplay_sent_batch() method in MarketDatabase class.

Tests verify that batch operations correctly:
- Set cooldowns for multiple entries in a single database save
- Handle missing systems and powerplay data gracefully
- Use a single save for all entries
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.market_database import MarketDatabase
from tests.test_helpers import count_save_calls


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary path for test database files."""
    return tmp_path / "powerplay_batch_database.json"


@pytest.fixture
def db(db_path):
    """Provide a MarketDatabase instance for testing."""
    return MarketDatabase(db_path)


def test_mark_powerplay_sent_batch_sets_multiple_cooldowns(db, db_path):
    """Test that mark_powerplay_sent_batch sets cooldowns for multiple entries."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
    )
    db.write_powerplay_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        power="Zachary Hudson",
        status="Stronghold",
        progress=80,
    )

    cooldowns = [
        ("Sol", "guild", "123"),
        ("Sol", "guild", "456"),
        ("Alpha Centauri", "user", "789"),
    ]
    db.mark_powerplay_sent_batch(cooldowns)

    # Verify all cooldowns are set
    assert db.check_powerplay_cooldown("Sol", "guild", "123", 3600) is False
    assert db.check_powerplay_cooldown("Sol", "guild", "456", 3600) is False
    assert db.check_powerplay_cooldown("Alpha Centauri", "user", "789", 3600) is False

    # Verify unmarked recipient is not on cooldown
    assert db.check_powerplay_cooldown("Sol", "user", "999", 3600) is True


def test_mark_powerplay_sent_batch_single_save(db):
    """Test that mark_powerplay_sent_batch performs only one save for all entries."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
    )

    cooldowns = [
        ("Sol", "guild", "123"),
        ("Sol", "guild", "456"),
        ("Sol", "user", "789"),
    ]

    with count_save_calls(db):
        db.mark_powerplay_sent_batch(cooldowns)

    # Should have exactly one save call
    assert db.save_count == 1


def test_mark_powerplay_sent_batch_handles_missing_system(db, db_path):
    """Test that mark_powerplay_sent_batch gracefully skips missing systems."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
    )

    cooldowns = [
        ("Sol", "guild", "123"),
        ("NonExistent", "guild", "456"),
        ("Sol", "user", "789"),
    ]
    db.mark_powerplay_sent_batch(cooldowns)

    # Verify only valid system entries are set
    assert db.check_powerplay_cooldown("Sol", "guild", "123", 3600) is False
    assert db.check_powerplay_cooldown("Sol", "user", "789", 3600) is False

    # Verify NonExistent system did not cause errors


def test_mark_powerplay_sent_batch_handles_missing_powerplay(db, db_path):
    """Test that mark_powerplay_sent_batch gracefully skips systems without powerplay data."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Sol exists but has no powerplay data
    cooldowns = [("Sol", "guild", "123")]
    with count_save_calls(db):
        db.mark_powerplay_sent_batch(cooldowns)

    assert db.save_count == 1

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "Sol" in data
    assert "powerplay" in data["Sol"]
    assert "cooldowns" in data["Sol"]["powerplay"]
    assert "guild" in data["Sol"]["powerplay"]["cooldowns"]
    assert "123" in data["Sol"]["powerplay"]["cooldowns"]["guild"]


def test_mark_powerplay_sent_batch_empty_list(db):
    """Test that mark_powerplay_sent_batch handles empty cooldowns list."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
    )

    with count_save_calls(db):
        db.mark_powerplay_sent_batch([])

    # Should still perform one save (load + save with no changes)
    assert db.save_count == 1


def test_mark_powerplay_sent_batch_mixed_recipient_types(db, db_path):
    """Test that mark_powerplay_sent_batch handles mixed guild and user recipients."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
    )

    cooldowns = [
        ("Sol", "guild", "123"),
        ("Sol", "user", "456"),
        ("Sol", "guild", "789"),
    ]
    db.mark_powerplay_sent_batch(cooldowns)

    # Verify all recipient types are handled correctly
    assert db.check_powerplay_cooldown("Sol", "guild", "123", 3600) is False
    assert db.check_powerplay_cooldown("Sol", "user", "456", 3600) is False
    assert db.check_powerplay_cooldown("Sol", "guild", "789", 3600) is False

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Verify both recipient types exist in cooldowns
    assert "guild" in data["Sol"]["powerplay"]["cooldowns"]
    assert "user" in data["Sol"]["powerplay"]["cooldowns"]
    assert data["Sol"]["powerplay"]["cooldowns"]["guild"]["123"] > 0
    assert data["Sol"]["powerplay"]["cooldowns"]["user"]["456"] > 0


def test_mark_powerplay_sent_batch_same_recipient_multiple_times(db, db_path):
    """Test that mark_powerplay_sent_batch updates timestamp if same recipient appears multiple times."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
    )

    cooldowns = [
        ("Sol", "guild", "123"),
        ("Sol", "guild", "123"),
        ("Sol", "guild", "123"),
    ]
    db.mark_powerplay_sent_batch(cooldowns)

    # Should still be on cooldown (timestamp should be from last occurrence)
    assert db.check_powerplay_cooldown("Sol", "guild", "123", 3600) is False

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Cooldown should exist with a timestamp
    assert "123" in data["Sol"]["powerplay"]["cooldowns"]["guild"]
