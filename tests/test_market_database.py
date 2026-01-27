"""
Tests for MarketDatabase class following TDD RED phase.

These tests define the expected behavior of the MarketDatabase class
which manages market data, powerplay status, and cooldown tracking
for Elite Dangerous stations.

Expected to FAIL with ImportError until MarketDatabase is implemented.
"""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

# Ensure the repository root is on the import path for the tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# This import will fail - expected in RED phase
from gold_detector.market_database import MarketDatabase


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary path for test database files."""
    return tmp_path / "market_database.json"


@pytest.fixture
def db(db_path):
    """Provide a MarketDatabase instance for testing."""
    return MarketDatabase(db_path)


# ============================================================================
# write_market_entry() tests
# ============================================================================


def test_write_market_entry_creates_new_system(db, db_path):
    """Test that write_market_entry creates a new system entry if it doesn't exist."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Verify data was written to file
    assert db_path.exists()
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "Sol" in data
    assert data["Sol"]["system_address"] == "10477373803"
    assert "Abraham Lincoln" in data["Sol"]["stations"]


def test_write_market_entry_creates_new_station(db, db_path):
    """Test that write_market_entry creates a new station if it doesn't exist."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Daedalus",
        station_type="Orbis Starport",
        url="https://inara.cz/station/456",
        metal="Palladium",
        stock=15000,
    )

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["Sol"]["stations"]) == 2
    assert "Abraham Lincoln" in data["Sol"]["stations"]
    assert "Daedalus" in data["Sol"]["stations"]


def test_write_market_entry_updates_metal_stock(db, db_path):
    """Test that write_market_entry updates metal stock for existing entries."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=30000,
    )

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 30000


def test_write_market_entry_persists_atomically(db, db_path):
    """Test that write_market_entry uses atomic writes (no .tmp file left behind)."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Verify no temp file exists
    tmp_file = db_path.with_suffix(db_path.suffix + ".tmp")
    assert not tmp_file.exists()
    assert db_path.exists()


def test_write_market_entry_preserves_cooldowns(db, db_path):
    """Test that write_market_entry preserves existing cooldown data."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Manually add cooldown
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Update stock
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=30000,
    )

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Cooldown should still exist
    assert "cooldowns" in data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]
    assert "guild" in data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["cooldowns"]


# ============================================================================
# write_powerplay_entry() tests
# ============================================================================


def test_write_powerplay_entry_creates_powerplay_data(db, db_path):
    """Test that write_powerplay_entry creates/updates powerplay data for a system."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Acquisition",
        progress=75,
    )

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "Sol" in data
    assert data["Sol"]["system_address"] == "10477373803"
    assert data["Sol"]["powerplay"]["power"] == "Zachary Hudson"
    assert data["Sol"]["powerplay"]["status"] == "Acquisition"
    assert data["Sol"]["powerplay"]["progress"] == 75


def test_write_powerplay_entry_preserves_station_data(db, db_path):
    """Test that write_powerplay_entry preserves existing station/metal data."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Acquisition",
        progress=75,
    )

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Station data should still exist
    assert "Abraham Lincoln" in data["Sol"]["stations"]
    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 25000


def test_write_powerplay_entry_updates_existing_powerplay(db, db_path):
    """Test that write_powerplay_entry updates existing powerplay data."""
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Acquisition",
        progress=75,
    )

    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Acquisition",
        progress=90,
    )

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["Sol"]["powerplay"]["progress"] == 90


# ============================================================================
# read_all_entries() tests
# ============================================================================


def test_read_all_entries_returns_all_systems(db):
    """Test that read_all_entries returns all systems with their data."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_market_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        station_name="Hutton Orbital",
        station_type="Outpost",
        url="https://inara.cz/station/789",
        metal="Palladium",
        stock=10000,
    )

    entries = db.read_all_entries()

    assert len(entries) == 2
    assert "Sol" in entries
    assert "Alpha Centauri" in entries
    assert entries["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 25000


def test_read_all_entries_returns_empty_dict_if_no_data(db):
    """Test that read_all_entries returns empty dict if no data exists."""
    entries = db.read_all_entries()
    assert entries == {}


def test_read_all_entries_includes_powerplay_and_cooldowns(db):
    """Test that read_all_entries includes powerplay, stations, metals, and cooldowns."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Acquisition",
        progress=75,
    )

    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    entries = db.read_all_entries()

    assert "powerplay" in entries["Sol"]
    assert entries["Sol"]["powerplay"]["power"] == "Zachary Hudson"
    assert "cooldowns" in entries["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]


# ============================================================================
# check_cooldown() tests
# ============================================================================


def test_check_cooldown_returns_true_if_no_cooldown_exists(db):
    """Test that check_cooldown returns True if no cooldown exists for the key."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    can_send = db.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Gold",
        recipient_type="guild",
        recipient_id="123456",
        cooldown_seconds=48 * 3600,
    )

    assert can_send is True


def test_check_cooldown_returns_false_if_within_cooldown_period(db):
    """Test that check_cooldown returns False if within cooldown period."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    can_send = db.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Gold",
        recipient_type="guild",
        recipient_id="123456",
        cooldown_seconds=48 * 3600,
    )

    assert can_send is False


def test_check_cooldown_returns_true_if_cooldown_expired(db):
    """Test that check_cooldown returns True if cooldown has expired."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Wait for cooldown to expire (use very short cooldown for testing)
    time.sleep(0.1)

    can_send = db.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Gold",
        recipient_type="guild",
        recipient_id="123456",
        cooldown_seconds=0.05,  # 50ms cooldown
    )

    assert can_send is True


def test_check_cooldown_different_recipient_types_dont_interfere(db):
    """Test that different recipient_type values don't interfere with each other."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Mark sent for guild
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Check cooldown for user - should be True (no cooldown for user)
    can_send = db.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Gold",
        recipient_type="user",
        recipient_id="123456",
        cooldown_seconds=48 * 3600,
    )

    assert can_send is True


def test_check_cooldown_different_recipient_ids_dont_interfere(db):
    """Test that different recipient_id values don't interfere with each other."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Mark sent for guild 123456
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Check cooldown for guild 789012 - should be True (different guild)
    can_send = db.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Gold",
        recipient_type="guild",
        recipient_id="789012",
        cooldown_seconds=48 * 3600,
    )

    assert can_send is True


def test_check_cooldown_per_station_metal_combination(db):
    """Test that cooldown is per (station, metal) combination."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Palladium",
        stock=15000,
    )

    # Mark sent for Gold
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Check cooldown for Palladium - should be True (different metal)
    can_send = db.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Palladium",
        recipient_type="guild",
        recipient_id="123456",
        cooldown_seconds=48 * 3600,
    )

    assert can_send is True


# ============================================================================
# mark_sent() tests
# ============================================================================


def test_mark_sent_sets_cooldown_timestamp(db, db_path):
    """Test that mark_sent sets cooldown timestamp for the key."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    before = time.time()
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")
    after = time.time()

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cooldown_ts = data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["cooldowns"]["guild"]["123456"]
    assert before <= cooldown_ts <= after


def test_mark_sent_persists_to_file(db, db_path):
    """Test that mark_sent persists cooldown to file."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Create new instance to verify persistence
    db2 = MarketDatabase(db_path)
    can_send = db2.check_cooldown(
        system_name="Sol",
        station_name="Abraham Lincoln",
        metal="Gold",
        recipient_type="guild",
        recipient_id="123456",
        cooldown_seconds=48 * 3600,
    )

    assert can_send is False


def test_mark_sent_overwrites_existing_cooldown(db, db_path):
    """Test that mark_sent overwrites existing cooldown timestamp."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")
    time.sleep(0.01)
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Should only have one cooldown entry
    cooldowns = data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["cooldowns"]["guild"]
    assert len(cooldowns) == 1
    assert "123456" in cooldowns


# ============================================================================
# prune_stale() tests
# ============================================================================


def test_prune_stale_removes_systems_not_in_current_set(db, db_path):
    """Test that prune_stale removes systems not in current_systems set."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_market_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        station_name="Hutton Orbital",
        station_type="Outpost",
        url="https://inara.cz/station/789",
        metal="Palladium",
        stock=10000,
    )

    # Prune - only keep Sol
    db.prune_stale({"Sol"})

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "Sol" in data
    assert "Alpha Centauri" not in data


def test_prune_stale_keeps_systems_in_current_set(db, db_path):
    """Test that prune_stale keeps systems in current_systems set."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.prune_stale({"Sol"})

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "Sol" in data


def test_prune_stale_does_not_prune_if_cooldowns_active(db, db_path):
    """Test that prune_stale does NOT prune if any cooldowns still active."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Mark sent (creates active cooldown)
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Try to prune (should not remove because cooldown is active)
    db.prune_stale(set())

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Sol should still exist because it has active cooldown
    assert "Sol" in data


def test_prune_stale_does_prune_if_all_cooldowns_expired(db, db_path):
    """Test that prune_stale DOES prune if all cooldowns expired AND system not in current_systems."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Mark sent with very short cooldown
    db.mark_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123456")

    # Wait for cooldown to expire
    time.sleep(0.1)

    # Prune (cooldown expired, system not in current set)
    # Note: prune_stale should check if cooldowns are expired based on some TTL
    # For this test, we assume prune_stale takes a cooldown_seconds parameter
    # or uses a default TTL to determine if cooldowns are expired
    db.prune_stale(set())

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Sol should be removed (cooldown expired and not in current_systems)
    # This test may need adjustment based on actual prune_stale implementation
    # For now, we'll assume it checks cooldowns against a TTL
    assert "Sol" not in data


def test_prune_stale_atomic_write_persists_changes(db, db_path):
    """Test that prune_stale uses atomic write to persist changes."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.prune_stale(set())

    # Verify no temp file exists
    tmp_file = db_path.with_suffix(db_path.suffix + ".tmp")
    assert not tmp_file.exists()


# ============================================================================
# begin_scan() / end_scan() tests
# ============================================================================


def test_begin_scan_marks_scan_started(db):
    """Test that begin_scan marks scan as started."""
    db.begin_scan()
    # This test verifies that begin_scan() can be called without error
    # Actual state tracking will be verified in end_scan tests


def test_end_scan_calls_prune_stale_with_scanned_systems(db, db_path):
    """Test that end_scan calls prune_stale with scanned systems."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.write_market_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        station_name="Hutton Orbital",
        station_type="Outpost",
        url="https://inara.cz/station/789",
        metal="Palladium",
        stock=10000,
    )

    db.begin_scan()
    db.end_scan({"Sol"})

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Alpha Centauri should be pruned
    assert "Sol" in data
    assert "Alpha Centauri" not in data


def test_end_scan_only_prunes_verified_absent_stations(db, db_path):
    """Test that end_scan only prunes stations verified absent from last complete scan."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.begin_scan()
    # Scan completes without seeing Sol
    db.end_scan(set())

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Sol should be pruned (verified absent from complete scan)
    assert "Sol" not in data


# ============================================================================
# Thread-safety tests
# ============================================================================


def test_concurrent_writes_dont_corrupt_file(db, db_path):
    """Test that concurrent writes don't corrupt the database file."""
    errors = []

    def write_entry(system_name, station_name, metal):
        try:
            for i in range(10):
                db.write_market_entry(
                    system_name=system_name,
                    system_address=f"addr_{system_name}",
                    station_name=station_name,
                    station_type="Starport",
                    url=f"https://inara.cz/station/{station_name}",
                    metal=metal,
                    stock=1000 + i,
                )
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=write_entry, args=("Sol", "Station1", "Gold")),
        threading.Thread(target=write_entry, args=("Sol", "Station2", "Palladium")),
        threading.Thread(target=write_entry, args=("Alpha Centauri", "Station3", "Gold")),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # No errors should occur
    assert len(errors) == 0

    # File should be valid JSON
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # All systems should exist
    assert "Sol" in data
    assert "Alpha Centauri" in data


def test_concurrent_reads_see_consistent_data(db):
    """Test that concurrent reads see consistent data."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    results = []
    errors = []

    def read_entries():
        try:
            for _ in range(10):
                entries = db.read_all_entries()
                results.append(entries)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=read_entries) for _ in range(5)]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # No errors should occur
    assert len(errors) == 0

    # All reads should return consistent data
    for entries in results:
        assert "Sol" in entries
        assert entries["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 25000


def test_concurrent_write_market_entry_calls(db, db_path):
    """Test multiple threads calling write_market_entry concurrently."""
    errors = []

    def write_many():
        try:
            for i in range(20):
                db.write_market_entry(
                    system_name=f"System{i % 3}",
                    system_address=f"addr{i % 3}",
                    station_name=f"Station{i % 5}",
                    station_type="Starport",
                    url=f"https://inara.cz/station/{i}",
                    metal="Gold" if i % 2 == 0 else "Palladium",
                    stock=1000 + i,
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_many) for _ in range(10)]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # No errors should occur
    assert len(errors) == 0

    # File should be valid JSON
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Should have 3 systems (System0, System1, System2)
    assert len(data) == 3


# ============================================================================
# Atomic write tests
# ============================================================================


def test_no_partial_writes_on_crash(db, db_path, monkeypatch):
    """Test that no partial writes occur on simulated crash."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Read original data
    with open(db_path, "r", encoding="utf-8") as f:
        original_data = f.read()

    # Simulate crash during write by making json.dump raise an exception
    original_dump = json.dump

    def crash_dump(*args, **kwargs):
        raise RuntimeError("Simulated crash")

    monkeypatch.setattr(json, "dump", crash_dump)

    # Try to write (should fail)
    try:
        db.write_market_entry(
            system_name="Sol",
            system_address="10477373803",
            station_name="Abraham Lincoln",
            station_type="Coriolis Starport",
            url="https://inara.cz/station/123",
            metal="Gold",
            stock=30000,
        )
    except RuntimeError:
        pass

    # Restore original json.dump
    monkeypatch.setattr(json, "dump", original_dump)

    # Original file should be unchanged
    with open(db_path, "r", encoding="utf-8") as f:
        current_data = f.read()

    assert current_data == original_data


def test_temp_file_pattern_works_correctly(db, db_path):
    """Test that temp file pattern (write to .tmp, then rename) works correctly."""
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    # Verify final file exists and temp file doesn't
    assert db_path.exists()
    tmp_file = db_path.with_suffix(db_path.suffix + ".tmp")
    assert not tmp_file.exists()

    # Verify data is correct
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 25000
