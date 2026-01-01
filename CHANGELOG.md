## [1.5.2] - 2026-1-1

Happy New Year! 🎉

### Fixed
Removed debug powerplay message to reduce spam and unneeded pings.

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
  
