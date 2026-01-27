# Draft: JSON Database for gold.py

## Original Request
Update gold.py to write to a JSON "database" with hierarchical structure:
- System name → powerplay status + stations
- Powerplay status → server/user cooldowns
- Stations → metals → stock + cooldowns

gold.py reports data, Discord messaging merges cooldowns.
Messages built by reading preferences and iterating through database.

## Current Architecture Understanding
- `monitor_metals()` collects: system, station, metal, stock, price via Inara scraping
- `get_powerplay_status()` collects: power, role, status, progress
- Cooldowns currently tracked:
  - In-memory: `last_ping` dict in monitor.py (per station-metal)
  - JSON files: `server_cooldowns.json`, `user_cooldowns.json` (per message hash)
- Discord messaging: reads preferences, filters messages, applies cooldowns

## Requirements (confirmed)
- Cooldowns in DB = existing Discord cooldowns (per-guild, per-user)
- Data flow = Write-then-read: gold.py writes raw data, Discord bot reads DB and sends
- Stale handling = Remove system if no longer present AND cooldown is expired
- Merge = Upsert raw data, preserve existing cooldowns during merge
- Message trigger = Every scan cycle, iterate entire DB, send non-cooled-down entries
- DB format = Single file (market_database.json)
- Cooldown consolidation = FULL: replace both monitor.py last_ping AND server/user cooldowns
- Message format = Keep current format, change how it's built
- Cooldown scope = Per station-metal-guild/user (most granular)

## Technical Decisions
- Major architecture shift: decouple data collection from message emission
- Database becomes the single source of truth for market state AND cooldowns
- gold.py: scan → write raw market data (system, powerplay, stations, metals, stock)
- Discord bot: read DB → filter by preferences → send if cooldown expired → update cooldown
- Prune logic: remove entry if (not in latest scan) AND (cooldown expired)
- Remove existing: server_cooldowns.json, user_cooldowns.json, last_ping dict

## Proposed DB Schema
```json
{
  "SystemName": {
    "system_address": "...",
    "powerplay": {
      "power": "Jerome Archer",
      "status": "Fortified",
      "progress": 85
    },
    "stations": {
      "StationName": {
        "station_type": "Starport",
        "url": "https://...",
        "metals": {
          "Gold": {
            "stock": 25000,
            "cooldowns": {
              "guilds": { "guild_id": timestamp },
              "users": { "user_id": timestamp }
            }
          }
        }
      }
    }
  }
}
```

## Test Strategy
- TDD approach: write failing tests first, then implement
- Existing test patterns in tests/ directory with pytest

## Detection Cooldown
- Removing in-memory `last_ping` is acceptable
- gold.py writes ALL markets meeting thresholds to DB each scan
- Delivery cooldowns (per station-metal-guild/user) prevent duplicate messages

## Metis Review Findings (addressed)
- Cooldown semantics: NEW behavior (station-metal key, stock changes don't matter)
- Powerplay: INCLUDED in refactor (store powerplay alerts in DB with cooldowns)
- Thread safety: Use JsonStore atomic write pattern
- Partial scan failure: Only prune stations successfully verified as absent
- Empty scan results: Don't prune anything (safety)
- File corruption: Follow existing JsonStore pattern (returns default on error)
- First run: Create empty structure, send all qualifying alerts

## Scope Boundaries
- INCLUDE: Database service, gold.py write logic, Discord read/iterate logic, cooldown consolidation, prune logic, tests, **powerplay messages**
- EXCLUDE: Message format changes, new commands, UI changes

## Scope Boundaries
- INCLUDE: [pending]
- EXCLUDE: [pending]
