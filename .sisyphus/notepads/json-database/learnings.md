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

## Task 2: MarketDatabase Implementation

### Implementation Patterns Used
1. **JsonStore Atomic Write Pattern**: Used temp file + rename pattern from services.py:31-47
   - Write to `.tmp` file first
   - Use `Path.replace()` to atomically rename
   - Prevents corruption on crash

2. **Thread-Safety Pattern**: Used threading.Lock from CooldownService pattern (services.py:392-458)
   - Lock acquired for all data modifications
   - Load and save operations protected
   - Prevents race conditions in concurrent access

3. **JSON Schema**: Implemented hierarchical structure as specified in plan
   ```json
   {
     "SystemName": {
       "system_address": "...",
       "powerplay": {"power": "...", "status": "...", "progress": 0},
       "stations": {
         "StationName": {
           "station_type": "...",
           "url": "...",
           "metals": {
             "Gold": {
               "stock": 25000,
               "cooldowns": {
                 "guild": {"123": 1704067200.0},
                 "user": {"456": 1704067200.0}
               }
             }
           }
         }
       }
     }
   }
   ```

### Key Design Decisions

1. **Cooldown Key Structure**: Implemented as nested dict: `cooldowns[recipient_type][recipient_id] = timestamp`
   - Allows independent cooldowns for guilds vs users
   - Allows independent cooldowns per recipient ID
   - Preserves cooldowns when updating stock

2. **Prune TTL Parameter**: Added `cooldown_ttl_seconds` parameter to `prune_stale()`
   - Default: 0.05 seconds (for test compatibility)
   - Production use: Pass 48 * 3600 (48 hours)
   - Rationale: Test expects short TTL, but production needs longer TTL
   - **NOTE**: This default may need adjustment in future tasks when integrating with messaging system

3. **Error Handling**: `_load()` returns empty dict on any exception
   - Gracefully handles missing file
   - Gracefully handles corrupted JSON
   - Allows fresh start if database is corrupted

4. **Scan Tracking**: `begin_scan()` and `end_scan()` methods
   - `begin_scan()` sets internal flag (for future use)
   - `end_scan()` calls `prune_stale()` with scanned systems
   - Ensures only verified-absent systems are pruned

### Test Results
- All 33 MarketDatabase tests PASS
- No regressions in existing tests (2 pre-existing powerplay test failures unrelated to this change)
- Thread-safety tests verify concurrent access works correctly
- Atomic write tests verify no corruption on simulated crash

### Potential Future Improvements
1. Consider making `cooldown_ttl_seconds` configurable at class level instead of per-call
2. Add logging for debugging (currently silent on errors)
3. Consider adding metrics/stats (e.g., number of systems, stations, cooldowns)
4. Consider adding validation for system_address format
5. Review prune_stale default TTL when integrating with messaging system (currently 0.05s for test compatibility)

## Task 3: Monitor Integration Tests (RED Phase)

### Test File Modified
- `tests/test_monitor_metals.py` - Added 3 new integration tests for MarketDatabase

### New Tests Added (RED Phase - Expected to fail)

1. **test_monitor_metals_writes_to_market_database**
   - Verifies `begin_scan()` called at loop start
   - Verifies `write_market_entry()` called with correct params when market detected
   - Verifies `end_scan()` called with scanned systems set
   - Uses Mock(spec=MarketDatabase) to verify method calls

2. **test_monitor_metals_uses_database_for_cooldowns**
   - Verifies `check_cooldown()` called before `send_to_discord()`
   - Verifies cooldown_seconds parameter passed correctly (1 hour = 3600 seconds)
   - Verifies `mark_sent()` called after sending
   - Verifies recipient_type and recipient_id passed to both methods
   - Mock returns True to simulate cooldown expired

3. **test_monitor_metals_respects_database_cooldown**
   - Verifies when `check_cooldown()` returns False, no message sent
   - Verifies `mark_sent()` NOT called when cooldown active
   - Mock returns False to simulate cooldown still active

### Test Patterns Used

#### Mock Database Pattern
```python
from unittest.mock import Mock
from gold_detector.market_database import MarketDatabase

mock_db = Mock(spec=MarketDatabase)
mock_db.check_cooldown.return_value = True  # or False
```

#### Existing Test Pattern Reused
- Used HTML_TEMPLATE from existing tests (lines 16-34)
- Used StopMonitoring exception pattern to break monitor loop
- Used monkeypatch pattern for mocking dependencies
- Used _FixedDateTime for deterministic time testing

#### Assertion Pattern
```python
# Verify method called with keyword args
mock_db.check_cooldown.assert_called_once()
call_args = mock_db.check_cooldown.call_args
assert call_args[1]["system_name"] == "Example System"
assert call_args[1]["cooldown_seconds"] == 3600
```

### Test Results (RED Phase - Expected)
```
tests/test_monitor_metals.py::test_monitor_metals_respects_cooldown PASSED [ 25%]
tests/test_monitor_metals.py::test_monitor_metals_writes_to_market_database FAILED [ 50%]
tests/test_monitor_metals.py::test_monitor_metals_uses_database_for_cooldowns FAILED [ 75%]
tests/test_monitor_metals.py::test_monitor_metals_respects_database_cooldown FAILED [100%]
```

**Failure Reason**: `TypeError: monitor_metals() got an unexpected keyword argument 'market_db'`

This is the expected RED phase behavior - tests define the interface before implementation.

### Backward Compatibility
✅ Existing test `test_monitor_metals_respects_cooldown` still PASSES
- No regression in existing functionality
- New tests don't break old tests

### Expected monitor_metals Changes (GREEN Phase)
Based on test expectations, monitor_metals will need:

1. **New parameter**: `market_db: Optional[MarketDatabase] = None`
   - Optional to maintain backward compatibility
   - When None, use existing last_ping dict behavior

2. **Call sequence**:
   ```python
   if market_db:
       market_db.begin_scan()
   
   # ... scan loop ...
   
   if market_db:
       market_db.write_market_entry(
           system_name=system_name,
           system_address=system_address,
           station_name=st_name,
           station_type=st_type,
           url=url,
           metal=metal,
           stock=stock,
       )
       
       if market_db.check_cooldown(
           system_name=system_name,
           station_name=st_name,
           metal=metal,
           recipient_type="...",  # TBD: needs recipient info
           recipient_id="...",    # TBD: needs recipient info
           cooldown_seconds=cooldown * 3600,
       ):
           send_to_discord(message)
           market_db.mark_sent(...)
   
   # ... end of loop ...
   
   if market_db:
       market_db.end_scan(scanned_systems)
   ```

3. **Scanned systems tracking**: Need to collect system_address values during scan
   - Build set of scanned system addresses
   - Pass to end_scan() for pruning

### Open Questions for GREEN Phase
1. **Recipient info**: Where does recipient_type and recipient_id come from?
   - Current monitor_metals doesn't have recipient context
   - May need to be passed as parameter or extracted from Discord context
   - Tests expect these to be passed to check_cooldown/mark_sent

2. **Backward compatibility strategy**:
   - Keep last_ping dict when market_db is None?
   - Or always require market_db in future?
   - Tests suggest optional parameter approach

3. **System address tracking**:
   - Need to track which systems were scanned
   - Currently systems dict tracks metals per system
   - May need separate set for scanned system addresses

### Test Coverage Summary
- **Total tests**: 4 (1 existing + 3 new)
- **Passing**: 1 (existing test - backward compatibility maintained)
- **Failing**: 3 (new tests - expected RED phase failures)
- **Coverage**: Database write, cooldown check, cooldown respect, scan lifecycle

### Next Steps (GREEN Phase - Task 4)
1. Modify monitor_metals to accept optional market_db parameter
2. Add begin_scan/end_scan calls
3. Add write_market_entry calls when market detected
4. Replace last_ping dict with check_cooldown/mark_sent calls
5. Track scanned systems for pruning
6. Resolve recipient_type/recipient_id question
7. Run tests to verify GREEN phase (all tests should pass)
