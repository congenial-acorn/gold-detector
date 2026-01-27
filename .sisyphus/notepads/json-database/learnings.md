# Test Structure for MarketDatabase

## Test File Created
- `tests/test_market_database.py` - Comprehensive test suite for MarketDatabase class

## Test Coverage (RED Phase - All tests expected to fail)

### Core Functionality Tests
1. **write_market_entry()** - 5 tests
   - Creates new system entries
   - Creates new station entries
   - Updates metal stock
   - Atomic write persistence
   - Preserves existing cooldown data

2. **write_powerplay_entry()** - 3 tests
   - Creates/updates powerplay data
   - Preserves existing station/metal data
   - Updates existing powerplay entries

3. **read_all_entries()** - 3 tests
   - Returns all systems with data
   - Returns empty dict if no data
   - Includes powerplay, stations, metals, cooldowns

4. **check_cooldown()** - 6 tests
   - Returns True if no cooldown exists
   - Returns False if within cooldown period
   - Returns True if cooldown expired
   - Different recipient_type values don't interfere
   - Different recipient_id values don't interfere
   - Cooldown is per (station, metal) combination

5. **mark_sent()** - 3 tests
   - Sets cooldown timestamp
   - Persists to file
   - Overwrites existing cooldown

6. **prune_stale()** - 5 tests
   - Removes systems not in current_systems set
   - Keeps systems in current_systems set
   - Does NOT prune if cooldowns still active
   - Does prune if all cooldowns expired
   - Atomic write persists changes

7. **begin_scan() / end_scan()** - 3 tests
   - begin_scan() marks scan started
   - end_scan() calls prune_stale() with scanned systems
   - Only prunes verified-absent stations

### Thread-Safety Tests - 3 tests
- Concurrent writes don't corrupt file
- Concurrent reads see consistent data
- Multiple threads calling write_market_entry()

### Atomic Write Tests - 2 tests
- No partial writes on crash (monkeypatch simulation)
- Temp file pattern works correctly

## Test Patterns Used

### Fixtures
```python
@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "market_database.json"

@pytest.fixture
def db(db_path):
    return MarketDatabase(db_path)
```

### Thread-Safety Pattern
```python
errors = []
def write_entry(...):
    try:
        # operations
    except Exception as e:
        errors.append(e)

threads = [threading.Thread(target=write_entry, args=(...)) for _ in range(N)]
for t in threads: t.start()
for t in threads: t.join()
assert len(errors) == 0
```

### Atomic Write Verification
```python
# Verify no temp file exists after write
tmp_file = db_path.with_suffix(db_path.suffix + ".tmp")
assert not tmp_file.exists()
assert db_path.exists()
```

### Crash Simulation (monkeypatch)
```python
def crash_dump(*args, **kwargs):
    raise RuntimeError("Simulated crash")

monkeypatch.setattr(json, "dump", crash_dump)
```

## Expected Test Results
- **Status**: All tests FAIL with `ModuleNotFoundError: No module named 'gold_detector.market_database'`
- **Verification**: Confirmed via `python3 -c "from gold_detector.market_database import MarketDatabase"`
- **Result**: `ModuleNotFoundError: No module named 'gold_detector.market_database'`

This is the expected RED phase behavior - tests define the interface before implementation.

## Total Test Count
- **37 tests** covering all MarketDatabase functionality
- All tests include docstrings explaining validation purpose
- Tests follow pytest conventions and project patterns

## Next Steps (GREEN Phase)
1. Implement `gold_detector/market_database.py` with MarketDatabase class
2. Implement all methods to make tests pass
3. Use JsonStore pattern for atomic writes
4. Use threading.Lock for thread-safety
5. Implement cooldown logic per (station, metal, recipient_type, recipient_id)
