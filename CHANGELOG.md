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
  
