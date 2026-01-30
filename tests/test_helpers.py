"""
Test helper utilities for gold detector project.

Provides reusable test utilities for mocking, counting, and common test scenarios.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from gold_detector.market_database import MarketDatabase


@contextmanager
def count_save_calls(db: MarketDatabase) -> Generator[None, None, None]:
    """
    Monkey-patch _save() method to count calls on a specific database instance.

    Works by attaching a counter attribute to the db instance.
    Every _save call increments this counter.

    Args:
        db: The MarketDatabase instance to count saves on

    Yields:
        None - use db.save_count property to read the count

    Example:
        db = MarketDatabase(path)
        with count_save_calls(db):
            db.write_market_entry(...)
            db.mark_sent(...)
            assert db.save_count == 2
    """
    setattr(db, "save_count", 0)

    original_save = db._save

    def counting_wrapper(data: dict[str, Any]) -> None:
        setattr(db, "save_count", getattr(db, "save_count", 0) + 1)
        return original_save(data)

    db._save = counting_wrapper

    try:
        yield
    finally:
        db._save = original_save
