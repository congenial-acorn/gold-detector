from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .services import PREFERENCE_OPTIONS

_POWERPLAY_NAMES = tuple(name.lower() for name in PREFERENCE_OPTIONS.get("powerplay", ()))
_COMMODITY_PATTERN = re.compile(r"([A-Za-z][A-Za-z ]*?)\s+stock:\s*\d+", re.IGNORECASE)
_STATION_TYPE_PATTERN = re.compile(r"\(([^)]+)\)")


def _extract_station_type(text: str) -> str | None:
    match = _STATION_TYPE_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    base = raw.split("(", 1)[0].strip()
    return base or raw


def _filter_commodity_segments(text: str, allowed: set[str]) -> str | None:
    if text is None:
        return None

    segments = [seg.strip() for seg in text.split(";") if seg.strip()]
    if not segments:
        return "" if not allowed else None

    if not allowed:
        return "; ".join(segments)

    kept = []
    for seg in segments:
        match = _COMMODITY_PATTERN.search(seg)
        if match:
            commodity = match.group(1).strip().lower()
            if commodity in allowed:
                kept.append(seg)
        else:
            kept.append(seg)

    if not kept:
        return None
    return "; ".join(kept)


def _filter_alert_message(
    content: str, station_type_prefs: Sequence[str], commodity_prefs: Sequence[str]
) -> str | None:
    station_allowed = {p.lower() for p in station_type_prefs or []}
    commodity_allowed = {c.lower() for c in commodity_prefs or []}

    lines = content.splitlines()
    if not lines:
        return content

    header, *body = lines
    filtered_lines = []
    for line in body:
        stripped = line.strip()
        if not stripped:
            continue

        station_type = _extract_station_type(stripped)
        if station_allowed and station_type:
            lowered = station_type.lower()
            matches = any(
                lowered == opt
                or lowered.startswith(f"{opt} ")
                or lowered.startswith(f"{opt}(")
                for opt in station_allowed
            )
            if not matches:
                continue

        if station_allowed and station_type is None:
            continue

        prefix = stripped
        remainder = None
        if " - " in stripped:
            prefix, remainder = stripped.split(" - ", 1)

        if remainder is not None:
            filtered_remainder = _filter_commodity_segments(
                remainder, commodity_allowed
            )
            if commodity_allowed and filtered_remainder is None:
                continue
            if filtered_remainder not in (None, ""):
                stripped = f"{prefix} - {filtered_remainder}"
            else:
                stripped = prefix

        filtered_lines.append(stripped)

    if not filtered_lines:
        return None

    return "\n".join([header] + filtered_lines)


def _filter_powerplay_message(content: str, powerplay_prefs: Sequence[str]) -> str | None:
    allowed = {p.lower() for p in powerplay_prefs or []}
    if not allowed:
        return content

    lowered = content.lower()
    return content if any(name in lowered for name in allowed) else None


def _is_powerplay_message(content: str) -> bool:
    lowered = content.lower()
    if "powerplay" in lowered or "merit" in lowered:
        return True
    return any(name in lowered for name in _POWERPLAY_NAMES)


def filter_message_for_preferences(
    content: str, preferences: Mapping[str, Sequence[str]] | None
) -> str | None:
    """
    Apply per-recipient filters to a message. Returns the filtered content, or None if
    the message should be suppressed for this recipient.
    """
    if not preferences:
        return content

    if _is_powerplay_message(content):
        return _filter_powerplay_message(content, preferences.get("powerplay", ()))

    return _filter_alert_message(
        content,
        preferences.get("station_type", ()),
        preferences.get("commodity", ()),
    )


def filter_entries_for_preferences(
    entries: list[dict[str, Any]],
    preferences: dict[str, list[str]] | None,
) -> list[dict[str, Any]]:
    """Filter entries by recipient preferences at data level."""
    if not preferences:
        return entries

    station_type_prefs = {p.lower() for p in preferences.get("station_type", [])}
    commodity_prefs = {c.lower() for c in preferences.get("commodity", [])}
    powerplay_prefs = {p.lower() for p in preferences.get("powerplay", [])}

    has_market_prefs = station_type_prefs or commodity_prefs
    has_powerplay_prefs = bool(powerplay_prefs)

    filtered = []
    for entry in entries:
        # Skip if no preferences are set
        if not any([station_type_prefs, commodity_prefs, powerplay_prefs]):
            filtered.append(entry)
            continue

        # Powerplay entry
        if entry.get("is_powerplay"):
            # If market prefs exist, skip powerplay entries
            if has_market_prefs:
                continue
            if has_powerplay_prefs:
                power = entry.get("power", "").lower()
                if not any(name in power for name in powerplay_prefs):
                    continue
            filtered.append(entry)
            continue

        # Market entry
        passes_filters = True

        # Station type filter
        if station_type_prefs and "station_type" in entry:
            station_type = entry["station_type"].lower()
            matches_station = any(
                station_type == opt
                or station_type.startswith(f"{opt} ")
                or station_type.startswith(f"{opt}(")
                or f" {opt} " in f" {station_type} "
                for opt in station_type_prefs
            )
            if not matches_station:
                passes_filters = False

        # Commodity filter
        if commodity_prefs and passes_filters and "metals" in entry:
            metals = entry.get("metals", [])
            has_commodity = any(
                metal[0].lower() in commodity_prefs for metal in metals
            )
            if not has_commodity:
                passes_filters = False

        # Apply commodity filter if set, even if station_type not set
        if commodity_prefs and "station_type" not in entry and "metals" in entry:
            metals = entry.get("metals", [])
            has_commodity = any(
                metal[0].lower() in commodity_prefs for metal in metals
            )
            if not has_commodity:
                passes_filters = False

        if passes_filters:
            filtered.append(entry)

    return filtered
