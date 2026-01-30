import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_helpers import count_save_calls
from gold_detector.market_database import MarketDatabase


def test_save_call_counter_single_save():
    """Test that count_save_calls correctly counts a single _save() call."""
    db = MarketDatabase(Path("test_single_save.json"))

    with count_save_calls(db):
        db.write_market_entry("System", "1", "Station", "Coriolis", "url", "Gold", 100)
        assert db.save_count == 1

    os.remove("test_single_save.json")


def test_save_call_counter_multiple_saves():
    """Test that count_save_calls correctly counts multiple _save() calls."""
    db = MarketDatabase(Path("test_multiple_saves.json"))

    with count_save_calls(db):
        db.write_market_entry("System", "1", "Station", "Coriolis", "url", "Gold", 100)
        db.write_market_entry("System", "1", "Station", "Coriolis", "url", "Palladium", 50)
        db.mark_sent("System", "Station", "Gold", "guild", "123")
        db.mark_sent("System", "Station", "Palladium", "guild", "123")
        assert db.save_count == 4

    os.remove("test_multiple_saves.json")


def test_save_call_counter_no_saves():
    """Test that count_save_calls returns 0 when no saves occur."""
    db = MarketDatabase(Path("test_no_saves.json"))

    with count_save_calls(db):
        assert db.save_count == 0

    if os.path.exists("test_no_saves.json"):
        os.remove("test_no_saves.json")


def test_save_call_counter_preserves_original_behavior():
    """Test that count_save_calls preserves original _save() behavior."""
    db = MarketDatabase(Path("test_preserves_behavior.json"))

    with count_save_calls(db):
        db.write_market_entry("System", "1", "Station", "Coriolis", "url", "Gold", 100)

    assert db.save_count == 1

    data = db.read_all_entries()
    assert "System" in data
    assert "Station" in data["System"]["stations"]
    assert "Gold" in data["System"]["stations"]["Station"]["metals"]

    os.remove("test_preserves_behavior.json")


if __name__ == "__main__":
    test_save_call_counter_single_save()
    test_save_call_counter_multiple_saves()
    test_save_call_counter_no_saves()
    test_save_call_counter_preserves_original_behavior()
    print("✓ All tests passed")
