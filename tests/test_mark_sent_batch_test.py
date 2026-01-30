"""
Tests for mark_sent_batch() batch save optimization in MarketDatabase.

Tests follow the Verification Strategy from batch-save-optimization plan.
"""

from pathlib import Path
from gold_detector.market_database import MarketDatabase
import sys
sys.path.insert(0, '/mnt/data/Code/gold-detector')
from tests.test_helpers import count_save_calls
import inspect
import os


def test_method_exists_with_correct_signature():
    """Test 1: Verify mark_sent_batch method exists with correct signature"""
    assert hasattr(MarketDatabase, 'mark_sent_batch')

    sig_batch = inspect.signature(MarketDatabase.mark_sent_batch)
    assert 'cooldowns' in sig_batch.parameters
    assert len(sig_batch.parameters) == 2


def test_empty_batch_skips_save():
    """Test 2: Empty list should not trigger save"""
    db = MarketDatabase(Path("test_empty_batch.json"))

    with count_save_calls(db):
        db.mark_sent_batch([])

    assert db.save_count == 0

    if os.path.exists("test_empty_batch.json"):
        os.remove("test_empty_batch.json")


def test_single_entry_batch_works():
    """Test 3: Degenerate case with one entry"""
    db = MarketDatabase(Path("test_single_batch.json"))
    db.write_market_entry("TestSystem", "1", "TestStation", "Coriolis", "url", "Gold", 100)

    db.mark_sent_batch([("TestSystem", "TestStation", "Gold", "guild", "123")])

    data = db.read_all_entries()
    cooldown = data["TestSystem"]["stations"]["TestStation"]["metals"]["Gold"]["cooldowns"]["guild"]["123"]
    assert cooldown > 0

    os.remove("test_single_batch.json")


def test_duplicate_entries_in_batch():
    """Test 4: Same entry appears twice in batch"""
    import time

    db = MarketDatabase(Path("test_dup_batch.json"))
    db.write_market_entry("DupSystem", "1", "DupStation", "Coriolis", "url", "Gold", 100)

    now = time.time()
    db.mark_sent_batch([
        ("DupSystem", "DupStation", "Gold", "guild", "123"),
        ("DupSystem", "DupStation", "Gold", "guild", "123")
    ])

    data = db.read_all_entries()
    cooldown = data["DupSystem"]["stations"]["DupStation"]["metals"]["Gold"]["cooldowns"]["guild"]["123"]
    assert cooldown >= now

    os.remove("test_dup_batch.json")


def test_mixed_recipient_types_in_batch():
    """Test 5: Guild and user cooldowns in same batch"""
    db = MarketDatabase(Path("test_mix_batch.json"))
    db.write_market_entry("MixSystem", "1", "MixStation", "Coriolis", "url", "Gold", 100)

    db.mark_sent_batch([
        ("MixSystem", "MixStation", "Gold", "guild", "123"),
        ("MixSystem", "MixStation", "Gold", "user", "456"),
    ])

    data = db.read_all_entries()
    assert "guild" in data["MixSystem"]["stations"]["MixStation"]["metals"]["Gold"]["cooldowns"]
    assert "123" in data["MixSystem"]["stations"]["MixStation"]["metals"]["Gold"]["cooldowns"]["guild"]
    assert "user" in data["MixSystem"]["stations"]["MixStation"]["metals"]["Gold"]["cooldowns"]
    assert "456" in data["MixSystem"]["stations"]["MixStation"]["metals"]["Gold"]["cooldowns"]["user"]

    os.remove("test_mix_batch.json")


def test_batch_produces_identical_state_to_sequential():
    """Test 7: Compare batch vs sequential behavior"""
    db_batch = MarketDatabase(Path("test_batch_state.json"))
    db_seq = MarketDatabase(Path("test_seq_state.json"))

    db_batch.write_market_entry("System1", "1", "Station1", "Coriolis", "url", "Gold", 100)
    db_seq.write_market_entry("System1", "1", "Station1", "Coriolis", "url", "Gold", 100)

    db_batch.mark_sent_batch([("System1", "Station1", "Gold", "guild", "123")])
    db_seq.mark_sent("System1", "Station1", "Gold", "guild", "123")

    batch_data = db_batch.read_all_entries()
    seq_data = db_seq.read_all_entries()

    assert "System1" in batch_data
    assert "System1" in seq_data

    batch_station = batch_data["System1"]["stations"]["Station1"]
    seq_station = seq_data["System1"]["stations"]["Station1"]
    assert batch_station["station_type"] == seq_station["station_type"]
    assert batch_station["url"] == seq_station["url"]

    batch_metal = batch_station["metals"]["Gold"]
    seq_metal = seq_station["metals"]["Gold"]
    assert batch_metal["stock"] == seq_metal["stock"]

    assert "guild" in batch_metal["cooldowns"]
    assert "guild" in seq_metal["cooldowns"]
    assert "123" in batch_metal["cooldowns"]["guild"]
    assert "123" in seq_metal["cooldowns"]["guild"]

    # Timestamps may differ due to timing, just verify they're set
    assert batch_metal["cooldowns"]["guild"]["123"] > 0
    assert seq_metal["cooldowns"]["guild"]["123"] > 0

    os.remove("test_batch_state.json")
    os.remove("test_seq_state.json")


def test_save_count_reduction():
    """Test 8: Measure actual save count during dispatch"""
    db_seq = MarketDatabase(Path("test_seq_count.json"))

    with count_save_calls(db_seq):
        db_seq.write_market_entry("Test", "1", "Station", "Coriolis", "url", "Gold", 100)
        for i in range(10):
            db_seq.mark_sent("Test", "Station", "Gold", "guild", str(i))

    sequential_saves = db_seq.save_count

    db_batch = MarketDatabase(Path("test_batch_count.json"))

    with count_save_calls(db_batch):
        db_batch.write_market_entry("Test", "1", "Station", "Coriolis", "url", "Gold", 100)
        cooldowns = [("Test", "Station", "Gold", "guild", str(i)) for i in range(10)]
        db_batch.mark_sent_batch(cooldowns)

    batch_saves = db_batch.save_count

    assert batch_saves == 2
    assert batch_saves < sequential_saves

    os.remove("test_seq_count.json")
    os.remove("test_batch_count.json")


def test_missing_paths_handled_gracefully():
    """Test: Missing system/station/metal paths should be skipped without error"""
    db = MarketDatabase(Path("test_missing_paths.json"))
    db.write_market_entry("ValidSystem", "1", "ValidStation", "Coriolis", "url", "Gold", 100)

    db.mark_sent_batch([
        ("ValidSystem", "ValidStation", "Gold", "guild", "123"),
        ("MissingSystem", "ValidStation", "Gold", "guild", "456"),
        ("ValidSystem", "MissingStation", "Gold", "guild", "789"),
        ("ValidSystem", "ValidStation", "MissingMetal", "guild", "012"),
        ("ValidSystem", "ValidStation", "Gold", "guild", "345"),
    ])

    data = db.read_all_entries()
    cooldowns = data["ValidSystem"]["stations"]["ValidStation"]["metals"]["Gold"]["cooldowns"]["guild"]
    assert "123" in cooldowns
    assert "345" in cooldowns
    assert "456" not in cooldowns
    assert "789" not in cooldowns
    assert "012" not in cooldowns

    os.remove("test_missing_paths.json")


if __name__ == "__main__":
    test_method_exists_with_correct_signature()
    print("✓ test_method_exists_with_correct_signature")

    test_empty_batch_skips_save()
    print("✓ test_empty_batch_skips_save")

    test_single_entry_batch_works()
    print("✓ test_single_entry_batch_works")

    test_duplicate_entries_in_batch()
    print("✓ test_duplicate_entries_in_batch")

    test_mixed_recipient_types_in_batch()
    print("✓ test_mixed_recipient_types_in_batch")

    test_batch_produces_identical_state_to_sequential()
    print("✓ test_batch_produces_identical_state_to_sequential")

    test_save_count_reduction()
    print("✓ test_save_count_reduction")

    test_missing_paths_handled_gracefully()
    print("✓ test_missing_paths_handled_gracefully")

    print("\n✓ All tests passed")
