## [1.6.1] - 2026-01-29

### Added
- **Commodity URLs in powerplay alerts**: Powerplay messages now include masked Inara commodity links for Gold and Palladium, allowing easy access to station market pages.
- **Masked commodity links generation**: When a monitored system is Fortified or Stronghold, the bot now generates and stores masked commodity links to bypass Inara's link blocking.
- **Diagnostic logging for powerplay operations**: Added detailed logging to powerplay write operations for easier troubleshooting of database issues.

### Fixed
- **Critical: Fixed database being empty after every scan** - Monitor was overwriting the entire database on each scan instead of preserving existing powerplay entries. Now properly merges new data with existing state.
- **Critical: Fixed powerplay cooldown tracking** - Cooldowns were not persisting across updates, causing duplicate powerplay alerts. Added `check_powerplay_cooldown()` and `mark_powerplay_sent()` methods to MarketDatabase to properly track and preserve cooldowns.
- **Critical: Fixed powerplay systems being pruned immediately** - Powerplay systems were written to database but then removed because they weren't in `scanned_systems` (which only contains systems from station page scans). Now merges powerplay systems with scanned_systems before pruning.
- **Fixed Future handling in message dispatch** - `loop_done_from_thread` now properly awaits `Future.result()` with timeout, preventing potential blocking issues.
- **Strip unicode variation selectors from system names** - System names now have unicode variation selectors (U+FE00-U+FE0F) stripped to prevent duplicate entries with slight name variations.

### Changed
- **Comprehensive test coverage expansion**:
  - Added tests for commodity links functionality in powerplay alerts
  - Added batch testing for powerplay operations
  - Added helper tests for database operations
  - Total of 539 lines of new tests added
- **Improved test organization** - Removed orphaned test code and refactored test assertions for better maintainability.
- **Enhanced logging throughout message dispatch flow** - Added INFO and DEBUG level logs for filtering diagnostics and dispatch troubleshooting.

### Technical Details
- Powerplay entries now include `commodity_urls` field with masked links for Gold and Palladium
- Database write operations preserve cooldown state across updates
- Powerplay systems are tracked independently and merged with scanned systems to prevent data loss
- All database operations maintain atomic write guarantees

---

## [1.6.0] - 2026-01-28

### Added
- **Implemented MarketDatabase class** with atomic writes for persistent storage of market data, powerplay entries, and cooldown tracking. The database now serves as the single source of truth, replacing multiple JSON files.

### Changed
- **Major architectural refactor to database-driven message dispatch**:
  - Messages now flow: scan → write to DB → dispatch from DB → send
  - Cooldown checking and marking handled directly by MarketDatabase
  - Removed `send_to_discord()` calls from monitor.py and powerplay.py
  - Implemented per-recipient dispatch behavior with data-level filtering
  - All filtering logic now inline in messaging, removing message_filters.py module
- **Removed legacy cooldown infrastructure**:
  - Deprecated CooldownService class removed (~70 lines)
  - Removed server_cooldowns.json and user_cooldowns.json files
  - Removed snapshot_cooldowns() method
  - Cooldown tracking fully integrated into MarketDatabase
- **Cleaned up vestigial code**:
  - Removed unused send_to_discord() function
  - Removed unused imports and variables throughout codebase
  - Fixed type hints consistency
  - Removed commented-out code in powerplay.py
- **Improved test coverage**:
  - Added comprehensive tests for MarketDatabase class
  - Updated tests for database-driven message dispatch
  - Refactored test assertions for inline filtering logic
  - All 53 tests passing with no new mypy or ruff errors

### Technical Details
- MarketDatabase provides atomic write operations to prevent data corruption
- Per-recipient dispatch allows granular control over which entries each user/server receives
- Inline filtering logic replaces the deprecated message_filters.py module
- Database-driven architecture enables better crash recovery and state persistence

### Performance Impact
- Reduced duplicate cooldown tracking by centralizing in database
- Eliminated JSON file I/O for cooldown state during normal operation
- Atomic database writes prevent partial state updates

---

## [1.5.2] - 2026-1-1

Happy New Year! 🎉

### Added
- Added `/diagnose` command to check if channel permissions are set properly.

### Fixed
- Removed debug powerplay message to reduce spam and unneeded pings.
- Fixed bot permissions. See top of README for details.

## [1.5.1] - 2025-12-28

### Fixed
- Fixed various bugs and errors to prevent possible crashes.
- Fixed typos in messages.

## [1.5.0] - 2025-12-25
### Added
- New `/set_preferences` slash command group lets users and servers filter alerts by station type, commodity (Gold/Palladium), and preferred Powerplay leaders; filters apply to both server posts and DMs.
- Powerplay awareness: when a monitored system is Fortified or Stronghold, the bot posts merit guidance with masked Inara commodity links and skips unoccupied systems.
- Hardened HTTP client now rate-limits all outbound requests, handles 429 backoff, and surfaces IP block errors for easier debugging.

### Changed
- Reduced Discord spam by aggregating hidden-market alerts per system (single system heading with multiple stations/metals) instead of repeating "Hidden market detected" for each station.
- Ping cycle is now tied to the scan cycle so servers only get pings when they actually received alerts in that pass.

## [1.4.1] - 2025-12-18
### Fixed
- Ensured some slash commands (`/alerts_on`, `/alerts_off`, `/help`, `/ping`) are available in both guilds and DMs by explicitly allowing user installs and DM/private-channel contexts, while keeping guild-only commands gated to servers.
- `/alerts_on` now tells users when the confirmation DM could not be delivered so they can check Message Requests or server DM privacy settings.
- `/show_alert_settings` is now only visible in servers as intended. 


## [1.4.0]
### Added
- Added `/server_ping_off` and `/server_ping_on` commands so servers can suppress @role pings without disabling alert messages entirely.

## [1.3.1]
### Fixed
- Fixed issue where servers would recieve pings despite not recieving any alerts.

## [1.3.0] - 2025-12-14
### Added
- Modularized bot into services (`config`, `services`, `messaging`, `gold_runner`, command modules) for cleaner composition and future testing.
- Added centralized JSON-backed state stores with locks for guild prefs, opt-outs, subscribers, and cooldowns.

### Changed
- `bot.py` is now a thin wiring layer that builds settings/logging, registers commands, and starts background tasks.
- Dispatcher/ping/DM logic now lives in `DiscordMessenger` with explicit queues and cooldown snapshotting.

### Fixed
- Server-only slash commands are now gated to guild installs (`allowed_installs(guilds=True, users=False)`) so they do not appear for user installs in other servers.

## [1.2.6] - 2025-12-10
### Added
- **Added Palladium monitoring.** The bot now monitors both Gold and Palladium markets.

## [1.2.5] - 2025-12-08
### Fixed
- **Prevented tight restart loop when gold.py exits.** `bot.py` now treats an unexpected return from `gold.main()` as a failure that follows the existing backoff instead of instant restarts.

## [1.2.4] - 2025-11-18
### Fixed
- **Critical: Fixed unsafe guild member lookup causing permission check failures.** The bot now properly validates `client.user` and uses `guild.me` directly instead of potentially failing back to incorrect permissions. Added detailed permission logging for debugging.
- **Critical: Fixed race condition in ping tracking system.** Added thread-safe locking (`_sent_guilds_lock`) to protect the `_sent_since_last_loop_by_guild` set from concurrent access between the dispatcher loop and gold.py's thread, preventing lost or duplicate pings.
- **Critical: Fixed DM cooldown being applied before message delivery.** Cooldowns are now only updated after successful message sends, preventing situations where users miss messages due to failed sends being counted against their cooldown.
- **Critical: Fixed cooldown state loss on bot crashes.** Implemented atomic file writes with temp files and immediate persistence after each cooldown update, reducing potential data loss from 60 seconds to <1 second. Prevents duplicate messages being sent to servers/users after bot restarts.
- **Fixed DM error handling and subscriber cleanup.** Added specific exception handling for `discord.NotFound`, `discord.Forbidden`, and `discord.HTTPException`. Users with deleted accounts or blocked DMs are now properly unsubscribed, while temporary errors (rate limits) no longer cause unsubscriptions.
- **Fixed race conditions in ping loop.** Added comprehensive exception handling for `discord.Forbidden`, `discord.HTTPException`, and unexpected errors in `_ping_loop()`, with detailed logging for all failure paths.
- **Fixed unbounded queue growth risk.** Added configurable size limits to message and ping queues (default: 100, configurable via `DISCORD_QUEUE_MAX_SIZE` env var) with backpressure handling. Messages are now dropped with warnings during API outages rather than causing memory exhaustion.
- **Fixed slash command error handler suppressing errors.** Improved error handling to properly log all errors, send user-friendly messages, and only apply special handling for cooldown errors. Users now receive clear error messages instead of generic Discord timeouts.

### Changed
- Enhanced logging throughout bot.py with detailed error messages and context for easier debugging.
- Queue emitters now handle backpressure gracefully when Discord API is unavailable.
- Cooldown persistence now uses atomic file operations (write to temp file + rename) for safer crash recovery.
- Background cooldown snapshot loop converted to "belt-and-suspenders" safety net since cooldowns are now persisted immediately.

### Technical Details
- Added `_sent_guilds_lock` (threading.Lock) for thread-safe ping tracking.
- Added `_persist_server_cooldowns()` and `_persist_user_cooldowns()` helper functions.
- Refactored `_dm_subscribers_broadcast()` to handle cooldowns and errors correctly.
- Removed deprecated `_dm_should_send_and_update()` function.
- Improved `_resolve_sendable_channel()` with proper null checks and detailed permission logging.

## [1.2.3] - 2025-11-10
### Added
- Comprehensive structured logging with timestamps, log levels, and proper formatting.
- Added `LOG_LEVEL` environment variable to control logging verbosity (DEBUG, INFO, WARNING, ERROR).
- Automatic detection and logging of Inara IP blocks with clear error messages and contact information.
- Discord connection event logging (disconnects, reconnections, errors, guild joins/removals).
- Detailed HTTP request/response logging at DEBUG level.
- Scan cycle metrics showing stations checked and alerts sent per cycle.

### Changed
- Replaced basic print statements with Python's logging module throughout bot.py and gold.py.
- Enhanced error messages with stack traces for easier debugging.
- Improved crash handling with error categorization (IP blocks, rate limits, network errors).
- Track consecutive failure count and warn when errors accumulate.
- Better handling of multi-line log messages to prevent log confusion.

### Fix
- Fixed logging configuration order to properly load LOG_LEVEL from .env file.
- Improved error logging with exception details for all HTTP operations.

## [1.2.2] - 2025-10-25
### Changed
- Restored the monitoring loop's default 30-minute sleep and allow overriding it with the `GOLD_MONITOR_INTERVAL_SECONDS` environment variable. (#5)

### Fix
- Skip Inara stations that are missing header links or pricing data to avoid crashes when parsing HTML. (#4)
- Reuse the cached cooldown timedelta inside the monitor loop so duplicate alerts are not emitted prematurely. (#6)
- Reset the Discord background startup flag if initialization fails, ensuring background tasks can restart cleanly. (#8)

## [1.2.1] - 2025-10-18
### Fix
- Fixed issue causing role pings to be sent even when no messages were received from the bot.

## [1.2.0] - 2025-10-12
### Added
- Added new slash commands to set a custom alert channel and role.
- If these are not set it will still default to #market-watch and @Market Alert.
- Added `/help`.

## [1.1.1] - 2025-10-11
### Fix
- Reduced number of pings per message group.

## [1.1.0] - 2025-10-11
### Added
- Added user installation. The Discord bot can now send direct messages (DMs) to users.
- Implemented new slash commands for easier interaction.
- Implemented a way for the developer to send occasional updates to users. This will be used to notify users about changes to the bot.

### Changed
- Improved request handling to avoid HTTP 429 (rate-limit) errors.
- Improved crash handling.
  
