# JSON Database Refactoring for Gold Detector

## Context

### Original Request
Update gold.py to write to a JSON "database" with hierarchical structure. Each entry is a system name containing powerplay status and stations. Discord messaging logic adds cooldowns and builds messages by reading from preferences and iterating through the database.

### Interview Summary
**Key Discussions**:
- Data flow: Write-then-read architecture (gold.py writes raw data, Discord bot reads and sends)
- Cooldown consolidation: Full - replace both monitor.py `last_ping` AND server/user cooldowns
- Cooldown scope: Per station-metal-guild/user (most granular)
- Cooldown semantics: Station-metal key (stock changes don't trigger new alerts)
- Message format: Keep current format, change how it's built
- Stale handling: Remove if not in current scan AND all cooldowns expired
- Powerplay: Include in database refactor

**Research Findings**:
- Existing `JsonStore` class (services.py:31-47) provides atomic writes
- Existing `CooldownService` pattern (services.py:392-458) for thread-safety
- `HiddenMarketEntry` dataclass captures current data structure
- Test infrastructure with pytest (tests/test_*.py)

### Metis Review
**Identified Gaps** (addressed):
- Cooldown semantics change: Confirmed new behavior (station-metal key)
- Powerplay scope: Confirmed inclusion
- Thread safety: Use JsonStore atomic write pattern
- Partial scan failure: Only prune verified-absent stations
- Empty scan results: Don't prune (safety)
- File corruption: Return default on error

---

## Work Objectives

### Core Objective
Decouple data collection from message emission by introducing a JSON database as the single source of truth for market state and cooldowns.

### Concrete Deliverables
- `gold_detector/market_database.py` - New MarketDatabase class
- Modified `gold_detector/monitor.py` - Write to DB instead of emitting
- Modified `gold_detector/powerplay.py` - Write powerplay to DB instead of emitting  
- Modified `gold_detector/messaging.py` - Read from DB, iterate, send
- `tests/test_market_database.py` - New test file
- Updated existing tests
- Removed: `server_cooldowns.json`, `user_cooldowns.json`, `last_ping` dict

### Definition of Done
- [ ] `pytest tests/` passes with all new and existing tests
- [ ] gold.py scan writes market data to `market_database.json`
- [ ] Discord bot reads from database and sends messages with cooldown checking
- [ ] Old cooldown files removed from codebase

### Must Have
- Atomic JSON writes (follow JsonStore pattern)
- Thread-safe concurrent access
- Per station-metal-guild/user cooldown granularity
- Preserve existing message format exactly
- Preserve existing preference filtering behavior
- TDD approach for all new code

### Must NOT Have (Guardrails)
- DO NOT change message format (use existing `assemble_hidden_market_messages()`)
- DO NOT change preference filtering logic (use existing `message_filters.py`)
- DO NOT change price/stock thresholds (PRICE_THRESHOLD=28000, STOCK_THRESHOLD=15000)
- DO NOT add new configuration options
- DO NOT add new Discord commands
- DO NOT modify bot.py command registration
- DO NOT add separate ping detection/cooldown - role mentions attach directly to messages in the new flow

---

## Verification Strategy (MANDATORY)

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **User wants tests**: TDD
- **Framework**: pytest

### TDD Workflow
Each TODO follows RED-GREEN-REFACTOR:
1. **RED**: Write failing test first
2. **GREEN**: Implement minimum code to pass
3. **REFACTOR**: Clean up while keeping green

---

## Task Flow

```
Task 1 (MarketDatabase tests) 
    ↓
Task 2 (MarketDatabase implementation)
    ↓
Task 3 (monitor.py tests)
    ↓
Task 4 (monitor.py integration)
    ↓
Task 5 (powerplay.py tests)
    ↓
Task 6 (powerplay.py integration)
    ↓
Task 7 (messaging.py tests)
    ↓
Task 8 (messaging.py integration)
    ↓
Task 9 (cleanup old cooldowns)
    ↓
Task 10 (integration test & verification)
```

## Parallelization

| Group | Tasks | Reason |
|-------|-------|--------|
| None | All sequential | Each task depends on previous |

| Task | Depends On | Reason |
|------|------------|--------|
| 2 | 1 | Tests written first (TDD) |
| 3 | 2 | Needs MarketDatabase implemented |
| 4 | 3 | Tests written first (TDD) |
| 5 | 4 | Monitor must work before powerplay |
| 6 | 5 | Tests written first (TDD) |
| 7 | 6 | All writers done before consumer |
| 8 | 7 | Tests written first (TDD) |
| 9 | 8 | Messaging working before cleanup |
| 10 | 9 | All implementation done |

---

## TODOs

### - [x] 1. Write MarketDatabase Tests (TDD - RED phase)

**What to do**:
- Create `tests/test_market_database.py`
- Write tests for:
  - `write_market_entry()` - upsert system/station/metal data
  - `write_powerplay_entry()` - upsert powerplay status
  - `read_all_entries()` - iterate all entries
  - `check_cooldown(station, metal, recipient_type, recipient_id)` - returns True if can send
  - `mark_sent(station, metal, recipient_type, recipient_id)` - updates cooldown timestamp
  - `prune_stale(current_systems)` - removes entries not in set + all cooldowns expired
  - Atomic write behavior (no corruption on crash)
  - Thread-safety (concurrent access)

**Must NOT do**:
- Implement MarketDatabase class yet (TDD - tests first)
- Import from non-existent module (use placeholder)

**Parallelizable**: NO (first task)

**References**:

**Pattern References**:
- `tests/test_messaging.py` - Test structure pattern with pytest fixtures and monkeypatch
- `tests/test_monitor_metals.py:47-74` - How to test with fake data and control flow
- `gold_detector/services.py:392-458` - CooldownService tests pattern (should_send, mark_sent)

**API/Type References**:
- `gold_detector/services.py:31-47` - JsonStore class interface to emulate
- `gold_detector/services.py:429-447` - `should_send()` / `mark_sent()` signature pattern

**Test References**:
- `tests/test_message_filters.py` - pytest fixture patterns used in this project

**Acceptance Criteria**:
- [ ] Test file created: `tests/test_market_database.py`
- [ ] Tests cover: write_market_entry, write_powerplay_entry, read_all_entries, check_cooldown, mark_sent, prune_stale
- [ ] `pytest tests/test_market_database.py` → FAIL (module not found, expected at this stage)

**Commit**: YES
- Message: `test(market-db): add failing tests for MarketDatabase class`
- Files: `tests/test_market_database.py`
- Pre-commit: `pytest tests/test_market_database.py` (expected to fail)

---

### - [x] 2. Implement MarketDatabase Class (TDD - GREEN phase)

**What to do**:
- Create `gold_detector/market_database.py`
- Implement `MarketDatabase` class with:
  ```python
  class MarketDatabase:
      def __init__(self, path: Path):
          self._path = path
          self._lock = threading.Lock()
      
      def write_market_entry(self, system_name: str, system_address: str, 
                              station_name: str, station_type: str, url: str,
                              metal: str, stock: int) -> None
      
      def write_powerplay_entry(self, system_name: str, system_address: str,
                                 power: str, status: str, progress: int) -> None
      
      def read_all_entries(self) -> Dict[str, Any]
      
      def check_cooldown(self, system_name: str, station_name: str, metal: str,
                         recipient_type: str, recipient_id: str,
                         cooldown_seconds: float) -> bool
      
      def mark_sent(self, system_name: str, station_name: str, metal: str,
                    recipient_type: str, recipient_id: str) -> None
      
      def prune_stale(self, current_systems: Set[str]) -> None
      
      def begin_scan(self) -> None  # Mark scan started
      def end_scan(self, scanned_systems: Set[str]) -> None  # Finalize + prune
  ```
- Use JsonStore atomic write pattern (temp file + rename)
- Use threading.Lock for thread-safety
- Schema:
  ```json
  {
    "SystemName": {
      "system_address": "...",
      "powerplay": {
        "power": "...",
        "status": "...",
        "progress": 0
      },
      "stations": {
        "StationName": {
          "station_type": "...",
          "url": "...",
          "metals": {
            "Gold": {
              "stock": 25000,
              "cooldowns": {
                "guild": { "123": 1704067200.0 },
                "user": { "456": 1704067200.0 }
              }
            }
          }
        }
      }
    }
  }
  ```

**Must NOT do**:
- Add new dependencies
- Change existing services.py
- Implement Discord integration yet

**Parallelizable**: NO (depends on 1)

**References**:

**Pattern References**:
- `gold_detector/services.py:31-47` - JsonStore atomic write pattern (temp file + rename)
- `gold_detector/services.py:392-458` - CooldownService thread-safety pattern (Lock usage)
- `gold_detector/services.py:429-447` - Cooldown check logic (timestamp comparison)

**API/Type References**:
- `gold_detector/monitor.py:24-31` - HiddenMarketEntry fields to capture

**Acceptance Criteria**:
- [ ] File created: `gold_detector/market_database.py`
- [ ] `pytest tests/test_market_database.py` → PASS (all tests green)
- [ ] `pytest tests/` → PASS (no regression)

**Commit**: YES
- Message: `feat(market-db): implement MarketDatabase class with atomic writes`
- Files: `gold_detector/market_database.py`
- Pre-commit: `pytest tests/`

---

### - [x] 3. Write monitor.py Integration Tests (TDD - RED phase)

**What to do**:
- Update `tests/test_monitor_metals.py` with new tests:
  - Test that `monitor_metals()` writes entries to MarketDatabase instead of emitting
  - Test that cooldown checking happens via MarketDatabase
  - Test that stale entries are pruned after scan
- Keep existing tests passing (backward compatibility during transition)

**Must NOT do**:
- Modify monitor.py implementation yet
- Break existing test_monitor_metals.py tests

**Parallelizable**: NO (depends on 2)

**References**:

**Pattern References**:
- `tests/test_monitor_metals.py:47-74` - Existing test structure with monkeypatch
- `tests/test_monitor_metals.py:16-34` - HTML_TEMPLATE fake response pattern

**API/Type References**:
- `gold_detector/market_database.py` - MarketDatabase interface (from Task 2)
- `gold_detector/monitor.py:87-236` - Current monitor_metals signature

**Acceptance Criteria**:
- [ ] Tests added to `tests/test_monitor_metals.py`
- [ ] Tests cover: DB write on detection, cooldown check via DB, stale pruning
- [ ] `pytest tests/test_monitor_metals.py` → Some tests FAIL (new tests for unimplemented feature)

**Commit**: YES
- Message: `test(monitor): add failing tests for MarketDatabase integration`
- Files: `tests/test_monitor_metals.py`
- Pre-commit: N/A (expected failures)

---

### - [x] 4. Integrate MarketDatabase into monitor.py (TDD - GREEN phase)

**What to do**:
- Modify `gold_detector/monitor.py`:
  - Add `market_db: MarketDatabase` parameter to `monitor_metals()` (optional, with default)
  - Replace `last_ping` dict with `market_db.check_cooldown()` / `market_db.mark_sent()`
  - Add `market_db.write_market_entry()` calls when market detected
  - Add `market_db.begin_scan()` at loop start, `market_db.end_scan()` at loop end
  - Keep `send_to_discord()` calls for now (will be removed in Task 8)
- Update `gold.py` to pass MarketDatabase instance

**Must NOT do**:
- Remove `send_to_discord()` calls yet (messaging integration is Task 8)
- Change detection thresholds
- Modify HiddenMarketEntry dataclass

**Parallelizable**: NO (depends on 3)

**References**:

**Pattern References**:
- `gold_detector/monitor.py:87-115` - Current loop structure and last_ping usage
- `gold_detector/monitor.py:136-170` - Where market entries are detected and assembled

**API/Type References**:
- `gold_detector/market_database.py` - MarketDatabase interface
- `gold_detector/monitor.py:24-31` - HiddenMarketEntry fields to write

**Documentation References**:
- This plan's "Schema" section in Task 2 - Expected JSON structure

**Acceptance Criteria**:
- [ ] `gold_detector/monitor.py` modified to use MarketDatabase
- [ ] `gold.py` passes MarketDatabase instance
- [ ] `pytest tests/test_monitor_metals.py` → PASS (all tests green)
- [ ] `pytest tests/` → PASS (no regression)

**Commit**: YES
- Message: `feat(monitor): integrate MarketDatabase for market data persistence`
- Files: `gold_detector/monitor.py`, `gold.py`
- Pre-commit: `pytest tests/`

---

### - [x] 5. Write powerplay.py Integration Tests (TDD - RED phase)

**What to do**:
- Update `tests/test_powerplay.py` with new tests:
  - Test that `get_powerplay_status()` writes powerplay entries to MarketDatabase
  - Test that powerplay messages check cooldowns via MarketDatabase
  - Test powerplay status fields (power, status, progress) are captured

**Must NOT do**:
- Modify powerplay.py implementation yet
- Break existing test_powerplay.py tests

**Parallelizable**: NO (depends on 4)

**References**:

**Pattern References**:
- `tests/test_powerplay.py` - Existing test structure
- `gold_detector/powerplay.py:65-156` - Current get_powerplay_status flow

**API/Type References**:
- `gold_detector/market_database.py` - MarketDatabase.write_powerplay_entry()
- `gold_detector/powerplay.py:40-55` - _parse_powerplay_fields() return structure

**Acceptance Criteria**:
- [ ] Tests added to `tests/test_powerplay.py`
- [ ] Tests cover: powerplay write to DB, cooldown check
- [ ] `pytest tests/test_powerplay.py` → Some tests FAIL (new tests)

**Commit**: YES
- Message: `test(powerplay): add failing tests for MarketDatabase integration`
- Files: `tests/test_powerplay.py`
- Pre-commit: N/A (expected failures)

---

### - [x] 6. Integrate MarketDatabase into powerplay.py (TDD - GREEN phase)

**What to do**:
- Modify `gold_detector/powerplay.py`:
  - Add `market_db: MarketDatabase` parameter to `get_powerplay_status()`
  - Add `market_db.write_powerplay_entry()` calls for each system
  - Keep `send_to_discord()` calls for now (will be removed in Task 8)
- Update caller in `monitor.py` to pass MarketDatabase instance

**Must NOT do**:
- Remove `send_to_discord()` calls yet
- Change powerplay alert logic (Fortified vs Stronghold handling)
- Modify assemble_commodity_links behavior

**Parallelizable**: NO (depends on 5)

**References**:

**Pattern References**:
- `gold_detector/powerplay.py:107-145` - Where powerplay alerts are sent
- `gold_detector/powerplay.py:40-55` - _parse_powerplay_fields() structure

**API/Type References**:
- `gold_detector/market_database.py` - MarketDatabase.write_powerplay_entry()

**Acceptance Criteria**:
- [ ] `gold_detector/powerplay.py` modified to use MarketDatabase
- [ ] `gold_detector/monitor.py` passes MarketDatabase to get_powerplay_status
- [ ] `pytest tests/test_powerplay.py` → PASS
- [ ] `pytest tests/` → PASS

**Commit**: YES
- Message: `feat(powerplay): integrate MarketDatabase for powerplay persistence`
- Files: `gold_detector/powerplay.py`, `gold_detector/monitor.py`
- Pre-commit: `pytest tests/`

---

### - [x] 7. Write messaging.py Integration Tests (TDD - RED phase)

**What to do**:
- Update `tests/test_messaging.py` with new tests:
  - Test `DiscordMessenger` reads from MarketDatabase
  - Test message building by iterating DB entries
  - Test cooldown checking via `market_db.check_cooldown()`
  - Test cooldown marking via `market_db.mark_sent()`
  - Test preference filtering still applied per recipient
  - Test powerplay messages read from DB
  - Test role mentions are included in guild messages (when pings enabled)

**Must NOT do**:
- Modify messaging.py implementation yet
- Break existing test_messaging.py tests

**Parallelizable**: NO (depends on 6)

**References**:

**Pattern References**:
- `tests/test_messaging.py` - Existing test structure and mocking patterns
- `gold_detector/messaging.py:84-107` - Current _dispatcher_loop flow
- `gold_detector/messaging.py:196-216` - Current cooldown checking in send

**API/Type References**:
- `gold_detector/market_database.py` - MarketDatabase.read_all_entries(), check_cooldown(), mark_sent()
- `gold_detector/alert_helpers.py:63-84` - assemble_hidden_market_messages signature

**Acceptance Criteria**:
- [ ] Tests added to `tests/test_messaging.py`
- [ ] Tests cover: DB iteration, cooldown check/mark, preference filtering, powerplay
- [ ] `pytest tests/test_messaging.py` → Some tests FAIL

**Commit**: YES
- Message: `test(messaging): add failing tests for database-driven message dispatch`
- Files: `tests/test_messaging.py`
- Pre-commit: N/A (expected failures)

---

### - [x] 8. Integrate MarketDatabase into messaging.py (TDD - GREEN phase)

**What to do**:
- Modify `gold_detector/messaging.py`:
  - Add `market_db: MarketDatabase` to DiscordMessenger constructor
  - Create new method `dispatch_from_database()`:
    - Read all entries from `market_db.read_all_entries()`
    - For each system/station/metal entry:
      - Build message using `assemble_hidden_market_messages()` format
      - For each guild: check cooldown → filter preferences → send with role mention → mark sent
      - For each DM subscriber: check cooldown → filter preferences → send → mark sent
    - For each powerplay entry:
      - Build message using existing powerplay format
      - Apply same cooldown/filter/send/mark pattern (with role mention for guilds)
  - Remove queue-based dispatch (no longer needed)
  - Remove separate `_ping_loop()` - role mentions built directly into message send
- Modify `gold_detector/monitor.py`:
  - Remove `send_to_discord()` calls (DB is now the interface)
  - Call `messenger.dispatch_from_database()` after scan completes
- Modify `gold_detector/powerplay.py`:
  - Remove `send_to_discord()` calls

**Must NOT do**:
- Change message format (use existing helpers)
- Change preference filtering logic (use existing filters)
- Change existing DiscordMessenger public API (except adding new method)

**Parallelizable**: NO (depends on 7)

**References**:

**Pattern References**:
- `gold_detector/messaging.py:84-107` - Current dispatch pattern to refactor
- `gold_detector/messaging.py:109-145` - _send_to_guild pattern to reuse
- `gold_detector/messaging.py:147-175` - _dm_subscribers_broadcast pattern to reuse

**API/Type References**:
- `gold_detector/market_database.py` - Full MarketDatabase interface
- `gold_detector/alert_helpers.py:63-84` - assemble_hidden_market_messages()
- `gold_detector/message_filters.py:15-80` - filter_message_for_preferences()

**Acceptance Criteria**:
- [ ] `gold_detector/messaging.py` reads from MarketDatabase
- [ ] `gold_detector/monitor.py` no longer calls send_to_discord() directly
- [ ] `gold_detector/powerplay.py` no longer calls send_to_discord() directly
- [ ] `pytest tests/test_messaging.py` → PASS
- [ ] `pytest tests/` → PASS

**Commit**: YES
- Message: `feat(messaging): implement database-driven message dispatch`
- Files: `gold_detector/messaging.py`, `gold_detector/monitor.py`, `gold_detector/powerplay.py`
- Pre-commit: `pytest tests/`

---

### - [x] 9. Remove Old Cooldown Infrastructure

**What to do**:
- Delete files:
  - `server_cooldowns.json` (if exists)
  - `user_cooldowns.json` (if exists)
- Modify `gold_detector/services.py`:
  - Remove `CooldownService` class (lines 392-458)
  - Remove cooldown paths from `default_paths()` (lines 466-467)
- Update any imports that referenced CooldownService
- Clean up any dead code related to old cooldown mechanism

**Must NOT do**:
- Remove GuildPreferencesService (still needed for preferences)
- Remove SubscriberService (still needed for DM subscribers)
- Remove OptOutService (still needed for guild opt-out)
- Remove JsonStore class (used by MarketDatabase)

**Parallelizable**: NO (depends on 8)

**References**:

**Pattern References**:
- `gold_detector/services.py:392-458` - CooldownService to remove
- `gold_detector/services.py:461-468` - default_paths() to modify

**API/Type References**:
- `gold_detector/messaging.py` - Verify no CooldownService imports remain

**Acceptance Criteria**:
- [ ] `CooldownService` class removed from services.py
- [ ] Cooldown file paths removed from default_paths()
- [ ] No imports reference CooldownService
- [ ] `pytest tests/` → PASS (no regression)
- [ ] `server_cooldowns.json`, `user_cooldowns.json` paths no longer in code

**Commit**: YES
- Message: `refactor(services): remove deprecated CooldownService and old cooldown files`
- Files: `gold_detector/services.py`
- Pre-commit: `pytest tests/`

---

### - [x] 10. Integration Test & Final Verification

**What to do**:
- Run full test suite: `pytest tests/ -v`
- Manual verification (if possible):
  - Start bot in debug mode
  - Verify market_database.json is created on scan
  - Verify entries contain system/station/metal/stock
  - Verify cooldowns are written after message send
  - Verify stale entries are pruned
- Review all changes for:
  - No debug code left behind
  - No commented-out code
  - Consistent coding style
  - Type hints where appropriate

**Must NOT do**:
- Skip any verification steps
- Leave TODO comments in code
- Leave print/debug statements

**Parallelizable**: NO (final task)

**References**:

**Documentation References**:
- This plan - All acceptance criteria

**Acceptance Criteria**:
- [ ] `pytest tests/ -v` → ALL PASS
- [ ] `mypy gold_detector/` → No new errors (existing errors acceptable)
- [ ] `ruff check gold_detector/` → No new errors
- [ ] No debug/print statements left
- [ ] No TODO comments in new code

**Commit**: YES
- Message: `chore: final cleanup and verification for database refactor`
- Files: Any cleanup needed
- Pre-commit: `pytest tests/ && mypy gold_detector/ && ruff check gold_detector/`

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | `test(market-db): add failing tests for MarketDatabase class` | tests/test_market_database.py | N/A (expected fail) |
| 2 | `feat(market-db): implement MarketDatabase class with atomic writes` | gold_detector/market_database.py | pytest tests/ |
| 3 | `test(monitor): add failing tests for MarketDatabase integration` | tests/test_monitor_metals.py | N/A (expected fail) |
| 4 | `feat(monitor): integrate MarketDatabase for market data persistence` | gold_detector/monitor.py, gold.py | pytest tests/ |
| 5 | `test(powerplay): add failing tests for MarketDatabase integration` | tests/test_powerplay.py | N/A (expected fail) |
| 6 | `feat(powerplay): integrate MarketDatabase for powerplay persistence` | gold_detector/powerplay.py, gold_detector/monitor.py | pytest tests/ |
| 7 | `test(messaging): add failing tests for database-driven message dispatch` | tests/test_messaging.py | N/A (expected fail) |
| 8 | `feat(messaging): implement database-driven message dispatch` | gold_detector/messaging.py, gold_detector/monitor.py, gold_detector/powerplay.py | pytest tests/ |
| 9 | `refactor(services): remove deprecated CooldownService and old cooldown files` | gold_detector/services.py | pytest tests/ |
| 10 | `chore: final cleanup and verification for database refactor` | Any cleanup | Full suite |

---

## Success Criteria

### Verification Commands
```bash
pytest tests/ -v  # Expected: ALL PASS
mypy gold_detector/  # Expected: No new errors
ruff check gold_detector/  # Expected: Clean
```

### Final Checklist
- [ ] All "Must Have" present:
  - [ ] Atomic JSON writes
  - [ ] Thread-safe concurrent access
  - [ ] Per station-metal-guild/user cooldown granularity
  - [ ] Preserve message format
  - [ ] Preserve preference filtering
  - [ ] TDD approach used
- [ ] All "Must NOT Have" absent:
  - [ ] No message format changes
  - [ ] No preference logic changes
  - [ ] No threshold changes
  - [ ] No new config options
  - [ ] No new commands
- [ ] All tests pass
- [ ] Old cooldown infrastructure removed
