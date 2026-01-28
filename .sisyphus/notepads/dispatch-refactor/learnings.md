# Learnings - dispatch-refactor

## [2026-01-28T00:03:18Z] Task: Plan Analysis

### Task Flow
- 6 tasks total, all sequential
- Task 1: Write data-level filter tests (RED)
- Task 2: Implement data-level filter (GREEN)
- Task 3: Write refactored dispatch tests (RED)
- Task 4: Refactor dispatch implementation (GREEN)
- Task 5: Remove monitor cooldown
- Task 6: Remove legacy code & cleanup

### Key Files
- `gold_detector/messaging.py` - Current dispatch implementation (lines 362-450)
- `gold_detector/message_filters.py` - String-based filters (adapt to data level)
- `gold_detector/services.py:11-15` - PREFERENCE_OPTIONS structure
- `tests/test_message_filters.py` - Test patterns for string-based filters
- `tests/test_messaging.py` - Existing dispatch tests (needs update for refactored behavior)
- `gold_detector/alert_helpers.py:63-84` - `assemble_hidden_market_messages()` to be removed
- `gold_detector/market_database.py` - MarketDatabase API (no schema changes)

## [2026-01-28T00:15:00Z] Task: Write failing tests for filter_entries_for_preferences()

### Entry Structure from MarketDatabase
MarketDatabase `read_all_entries()` returns nested dict structure:
```python
{
    "Sol": {
        "system_address": "1234",
        "powerplay": {"power": "Zachary Hudson", "status": "Acquisition", "progress": 75},
        "stations": {
            "Abraham Lincoln": {
                "station_type": "Coriolis Starport",
                "url": "https://inara.cz/station/1234/",
                "metals": {
                    "Gold": {"stock": 25000, "cooldowns": {}}
                }
            }
        }
    }
}
```

### Test Data Format for filter_entries_for_preferences()
Tests need simplified entry format (not full MarketDatabase structure):
```python
# Market entry
{
    "system_name": "Sol",
    "system_address": "1234",
    "station_name": "Abraham Lincoln",
    "station_type": "Coriolis Starport",
    "url": "https://inara.cz/station/1234/",
    "metals": [("Gold", 25000), ("Palladium", 18000)],  # List of tuples
}

# Powerplay entry
{
    "system_name": "Sol",
    "power": "Zachary Hudson",
    "status": "Acquisition",
    "progress": 75,
    "is_powerplay": True,
}
```

### Test Coverage
Written 10 comprehensive tests:
1. `test_filter_entries_by_station_type()` - Filters by station_type (case-insensitive)
2. `test_filter_entries_by_commodity()` - Filters by commodity in metals list
3. `test_filter_entries_by_powerplay()` - Filters by power name
4. `test_filter_entries_no_preferences_returns_all()` - Empty dict returns all entries
5. `test_filter_entries_empty_preferences_returns_all()` - Empty lists return all entries
6. `test_filter_entries_non_matching_filtered_out()` - Entries without matches filtered out
7. `test_filter_entries_mixed_some_pass_some_filtered()` - Mixed entries with multiple filters
8. `test_filter_entries_case_insensitive()` - Case-insensitive matching
9. `test_filter_entries_all_filters_must_pass()` - AND logic: all filters must pass

### Existing Filter Patterns (from message_filters.py)
- Uses lowercase comparison: `{p.lower() for p in station_type_prefs or []}`
- Filters use exact match OR prefix match: `lowered == opt or lowered.startswith(f"{opt} ")`
- Powerplay filters: `any(name in lowered for name in allowed)`
- Returns None to suppress message, returns content to allow

### PREFERENCE_OPTIONS (from services.py)
```python
PREFERENCE_OPTIONS = {
    "station_type": ("Starport", "Outpost", "Surface Port"),
    "commodity": ("Gold", "Palladium"),
    "powerplay": ("Aisling Duval", "Archon Delaine", "Arissa Lavigny-Duval", 
                 "Denton Patreus", "Edmund Mahon", "Felicia Winters", 
                 "Jerome Archer", "Li Yong-Rui", "Nakato Kaine", 
                 "Pranav Antal", "Yuri Grom", "Zemina Torval"),
}
```

### Test Organization
Tests added to `tests/test_messaging.py` (existing test file for dispatch/messaging)
- Each test function has docstring explaining purpose
- Inline comments explain test data, filter parameters, assertions
- Section header marks TDD RED phase: "Tests for filter_entries_for_preferences() - TDD RED phase"

### Expected RED Phase Behavior
Tests will fail with ImportError because:
- Function `filter_entries_for_preferences()` doesn't exist in `gold_detector.message_filters`
- Import statement: `from gold_detector.message_filters import filter_entries_for_preferences`
- When pytest runs, it will fail at import time

### Test Design Decisions
1. **Separate market and powerplay entries**: Different structure, filtered differently
2. **Metals as list of tuples**: `[("Gold", 25000)]` format (simplified from MarketDatabase)
3. **AND logic for filters**: Entry must pass ALL applicable filters
4. **Case-insensitive matching**: Consistent with existing `message_filters.py`
5. **Return filtered list**: Unlike string filters (return content or None), data filters return list

### Success Criteria Verification
- [x] Tests added to `tests/test_messaging.py`
- [x] Tests cover: station_type, commodity, powerplay filtering
- [x] Test syntax valid (verified with `python3 -m py_compile`)
- [x] Tests will fail (import from non-existent function)
- [x] Test data structures match expected format

