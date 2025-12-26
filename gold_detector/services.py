from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Set, Tuple

from .config import PROJECT_ROOT, sanitize_channel_name, sanitize_role_name
from .utils import now

PREFERENCE_OPTIONS: Dict[str, Tuple[str, ...]] = {
    "station_type": ("Starport", "Outpost", "Surface Port"),
    "commodity": ("Gold", "Palladium"),
    "powerplay": (
        "Aisling Duval",
        "Archon Delaine",
        "Arissa Lavigny-Duval",
        "Denton Patreus",
        "Edmund Mahon",
        "Felicia Winters",
        "Jerome Archer",
        "Li Yong-Rui",
        "Nakato Kaine",
        "Pranav Antal",
        "Yuri Grom",
        "Zemina Torval",
    ),
}


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, default):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def save(self, data) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(self.path)


class GuildPreferencesService:
    def __init__(
        self,
        path: Path,
        *,
        default_channel: str,
        default_role: str,
        channel_override: str,
        role_override: str,
    ):
        self.store = JsonStore(path)
        self.default_channel = default_channel
        self.default_role = default_role
        self.channel_override = sanitize_channel_name(channel_override)
        self.role_override = sanitize_role_name(role_override)
        self._lock = threading.Lock()
        self._prefs, self._user_prefs = self._load()

    def _load(
        self,
    ) -> Tuple[Dict[int, Dict[str, object]], Dict[int, Dict[str, Dict[str, List[str]]]]]:
        raw = self.store.load({})

        if isinstance(raw, dict) and ("guilds" in raw or "users" in raw):
            guild_block = raw.get("guilds") or {}
            user_block = raw.get("users") or {}
        else:
            # Backward compatibility: old format was a flat map of guild IDs.
            guild_block = raw
            user_block = {}

        parsed_guilds: Dict[int, Dict[str, object]] = {}
        parsed_users: Dict[int, Dict[str, Dict[str, List[str]]]] = {}
        try:
            for gid_str, vals in (guild_block or {}).items():
                gid = int(gid_str)
                parsed_guilds[gid] = {
                    "channel_id": vals.get("channel_id"),
                    "channel_name": sanitize_channel_name(vals.get("channel_name")),
                    "role_id": vals.get("role_id"),
                    "role_name": sanitize_role_name(vals.get("role_name")),
                    "pings_enabled": bool(vals.get("pings_enabled", True)),
                    "preferences": self._normalize_preferences(vals.get("preferences")),
                }
            for uid_str, vals in (user_block or {}).items():
                uid = int(uid_str)
                parsed_users[uid] = self._normalize_preferences(vals)
        except Exception:
            return {}, {}
        return parsed_guilds, parsed_users

    def _normalize_preferences(self, raw) -> Dict[str, List[str]]:
        if not isinstance(raw, dict):
            return {}
        normalized: Dict[str, List[str]] = {}
        for key, allowed in PREFERENCE_OPTIONS.items():
            vals = self._normalize_preference_list(raw.get(key), allowed)
            if vals:
                normalized[key] = vals
        return normalized

    @staticmethod
    def _normalize_preference_list(
        raw_values, allowed: Sequence[str]
    ) -> List[str]:
        if raw_values is None:
            return []
        if isinstance(raw_values, str):
            items = [raw_values]
        elif isinstance(raw_values, Sequence):
            items = list(raw_values)
        else:
            return []

        allowed_map = {opt.lower(): opt for opt in allowed}
        deduped: List[str] = []
        for item in items:
            if not isinstance(item, str):
                continue
            key = item.strip().lower()
            if key in allowed_map:
                canonical = allowed_map[key]
                if canonical not in deduped:
                    deduped.append(canonical)
        return deduped

    def _persist_locked(self) -> None:
        guild_serial = {}
        for gid, vals in self._prefs.items():
            entry = {
                "channel_id": vals.get("channel_id"),
                "channel_name": vals.get("channel_name"),
                "role_id": vals.get("role_id"),
                "role_name": vals.get("role_name"),
                "pings_enabled": vals.get("pings_enabled", True),
            }
            prefs = vals.get("preferences") or {}
            if prefs:
                entry["preferences"] = {
                    key: sorted(map(str, vals))
                    for key, vals in prefs.items()
                    if vals
                }
            guild_serial[str(gid)] = entry

        user_serial = {
            str(uid): {key: sorted(map(str, vals)) for key, vals in prefs.items()}
            for uid, prefs in self._user_prefs.items()
            if prefs
        }

        payload = {"guilds": guild_serial, "users": user_serial}
        self.store.save(payload)

    def set_channel(self, guild_id: int, channel_id: int, channel_name: str) -> None:
        with self._lock:
            prefs = self._prefs.get(guild_id, {})
            prefs["channel_id"] = int(channel_id)
            prefs["channel_name"] = sanitize_channel_name(channel_name)
            self._prefs[guild_id] = prefs
            self._persist_locked()

    def clear_channel(self, guild_id: int) -> None:
        with self._lock:
            prefs = self._prefs.get(guild_id, {})
            prefs.pop("channel_id", None)
            prefs.pop("channel_name", None)
            self._prefs[guild_id] = prefs
            self._persist_locked()

    def set_role(self, guild_id: int, role_id: int, role_name: str) -> None:
        with self._lock:
            prefs = self._prefs.get(guild_id, {})
            prefs["role_id"] = int(role_id)
            prefs["role_name"] = sanitize_role_name(role_name)
            self._prefs[guild_id] = prefs
            self._persist_locked()

    def clear_role(self, guild_id: int) -> None:
        with self._lock:
            prefs = self._prefs.get(guild_id, {})
            prefs.pop("role_id", None)
            prefs.pop("role_name", None)
            self._prefs[guild_id] = prefs
            self._persist_locked()

    def set_pings_enabled(self, guild_id: int, enabled: bool) -> None:
        with self._lock:
            prefs = self._prefs.get(guild_id, {})
            prefs["pings_enabled"] = bool(enabled)
            self._prefs[guild_id] = prefs
            self._persist_locked()

    def set_preferences(
        self,
        scope: Literal["guild", "user"],
        scope_id: int,
        category: str,
        selections: Sequence[str],
    ) -> List[str]:
        allowed = PREFERENCE_OPTIONS.get(category)
        if not allowed:
            raise ValueError(f"Unknown preference category: {category}")

        normalized = self._normalize_preference_list(selections, allowed)
        with self._lock:
            if scope == "guild":
                prefs = self._prefs.get(scope_id, {})
                pref_block = prefs.get("preferences", {})
                if normalized:
                    pref_block[category] = normalized
                else:
                    pref_block.pop(category, None)
                prefs["preferences"] = pref_block
                self._prefs[scope_id] = prefs
            else:
                pref_block = self._user_prefs.get(scope_id, {})
                if normalized:
                    pref_block[category] = normalized
                else:
                    pref_block.pop(category, None)
                if pref_block:
                    self._user_prefs[scope_id] = pref_block
                else:
                    self._user_prefs.pop(scope_id, None)
            self._persist_locked()
        return normalized

    def get_preferences(
        self, scope: Literal["guild", "user"], scope_id: int
    ) -> Dict[str, List[str]]:
        if scope == "guild":
            prefs = self._prefs.get(scope_id) or {}
            return dict(prefs.get("preferences") or {})
        return dict(self._user_prefs.get(scope_id) or {})

    def remove_preferences(
        self,
        scope: Literal["guild", "user"],
        scope_id: int,
        category: str,
        removals: Sequence[str],
    ) -> List[str]:
        allowed = PREFERENCE_OPTIONS.get(category)
        if not allowed:
            raise ValueError(f"Unknown preference category: {category}")

        normalized_remove = set(self._normalize_preference_list(removals, allowed))
        with self._lock:
            if scope == "guild":
                prefs = self._prefs.get(scope_id, {})
                pref_block = prefs.get("preferences", {})
                current = pref_block.get(category, [])
                remaining = [v for v in current if v not in normalized_remove]
                if remaining:
                    pref_block[category] = remaining
                else:
                    pref_block.pop(category, None)
                prefs["preferences"] = pref_block
                self._prefs[scope_id] = prefs
            else:
                pref_block = self._user_prefs.get(scope_id, {})
                current = pref_block.get(category, [])
                remaining = [v for v in current if v not in normalized_remove]
                if remaining:
                    pref_block[category] = remaining
                    self._user_prefs[scope_id] = pref_block
                else:
                    pref_block.pop(category, None)
                    if pref_block:
                        self._user_prefs[scope_id] = pref_block
                    else:
                        self._user_prefs.pop(scope_id, None)
            self._persist_locked()
        return remaining

    def effective_channel_name(self, guild_id: int) -> str:
        prefs = self._prefs.get(guild_id) or {}
        raw = prefs.get("channel_name") or self.channel_override or self.default_channel
        return sanitize_channel_name(str(raw))

    def effective_channel_id(self, guild_id: int) -> Optional[int]:
        prefs = self._prefs.get(guild_id) or {}
        cid = prefs.get("channel_id")
        if isinstance(cid, (int, str)) and str(cid).isdigit():
            return int(cid)
        return None

    def effective_role_name(self, guild_id: int) -> str:
        prefs = self._prefs.get(guild_id) or {}
        raw = prefs.get("role_name") or self.role_override or self.default_role
        return sanitize_role_name(str(raw))

    def effective_role_id(self, guild_id: int) -> Optional[int]:
        prefs = self._prefs.get(guild_id) or {}
        rid = prefs.get("role_id")
        if isinstance(rid, (int, str)) and str(rid).isdigit():
            return int(rid)
        return None

    def pings_enabled(self, guild_id: int) -> bool:
        prefs = self._prefs.get(guild_id) or {}
        enabled = prefs.get("pings_enabled")
        if enabled is None:
            return True
        return bool(enabled)

    def source_labels(self, guild_id: int) -> Tuple[str, str]:
        prefs = self._prefs.get(guild_id) or {}
        channel_src = (
            "custom"
            if prefs.get("channel_id") or prefs.get("channel_name")
            else "default"
        )
        role_src = (
            "custom" if prefs.get("role_id") or prefs.get("role_name") else "default"
        )
        return channel_src, role_src


class SubscriberService:
    def __init__(self, path: Path):
        self.store = JsonStore(path)
        self._lock = threading.Lock()
        self._subs: Set[int] = self._load()

    def _load(self) -> Set[int]:
        try:
            data = self.store.load([])
            return {int(v) for v in data}
        except Exception:
            return set()

    def _persist_locked(self) -> None:
        self.store.save(sorted(self._subs))

    def add(self, user_id: int) -> None:
        with self._lock:
            self._subs.add(int(user_id))
            self._persist_locked()

    def discard(self, user_id: int) -> None:
        with self._lock:
            self._subs.discard(int(user_id))
            self._persist_locked()

    def all(self) -> Set[int]:
        with self._lock:
            return set(self._subs)


class OptOutService:
    def __init__(self, path: Path):
        self.store = JsonStore(path)
        self._lock = threading.Lock()
        self._opt_out: Set[int] = self._load()

    def _load(self) -> Set[int]:
        try:
            data = self.store.load([])
            return {int(v) for v in data}
        except Exception:
            return set()

    def _persist_locked(self) -> None:
        self.store.save(sorted(self._opt_out))

    def add(self, guild_id: int) -> None:
        with self._lock:
            self._opt_out.add(int(guild_id))
            self._persist_locked()

    def discard(self, guild_id: int) -> None:
        with self._lock:
            self._opt_out.discard(int(guild_id))
            self._persist_locked()

    def is_opted_out(self, guild_id: int) -> bool:
        with self._lock:
            return int(guild_id) in self._opt_out


class CooldownService:
    def __init__(self, path: Path, *, ttl_seconds: int):
        self.store = JsonStore(path)
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._data: Dict[int, Dict[int, float]] = self._load()
        self._prune_locked()

    def _load(self) -> Dict[int, Dict[int, float]]:
        try:
            raw = self.store.load({})
            return {
                int(g): {int(mid): float(ts) for mid, ts in inner.items()}
                for g, inner in raw.items()
            }
        except Exception:
            return {}

    def _prune_locked(self) -> None:
        cutoff = now() - self.ttl_seconds
        dead_guilds = []
        for gid, inner in self._data.items():
            stale = [mid for mid, ts in inner.items() if ts < cutoff]
            for mid in stale:
                del inner[mid]
            if not inner:
                dead_guilds.append(gid)
        for gid in dead_guilds:
            del self._data[gid]

    def _persist_locked(self) -> None:
        serial = {
            str(g): {str(mid): ts for mid, ts in inner.items()}
            for g, inner in self._data.items()
        }
        self.store.save(serial)

    def should_send(
        self,
        scope_id: int,
        message_id: int,
        ts: float,
        *,
        update_on_allow: bool = True,
    ) -> Tuple[bool, Optional[float], Optional[float]]:
        with self._lock:
            bucket = self._data.setdefault(scope_id, {})
            prev = bucket.get(message_id)
            if prev is None or ts - prev >= self.ttl_seconds:
                if update_on_allow:
                    bucket[message_id] = ts
                    self._persist_locked()
                return True, prev, None

            remaining = self.ttl_seconds - (ts - prev)
            return False, prev, remaining

    def mark_sent(self, scope_id: int, message_id: int, ts: float) -> None:
        with self._lock:
            bucket = self._data.setdefault(scope_id, {})
            bucket[message_id] = ts
            self._persist_locked()

    def snapshot(self) -> None:
        with self._lock:
            self._prune_locked()
            self._persist_locked()


def default_paths() -> dict[str, Path]:
    return {
        "guild_prefs": PROJECT_ROOT / "guild_prefs.json",
        "subs": PROJECT_ROOT / "dm_subscribers.json",
        "guild_optout": PROJECT_ROOT / "guild_optout.json",
        "server_cooldowns": PROJECT_ROOT / "server_cooldowns.json",
        "user_cooldowns": PROJECT_ROOT / "user_cooldowns.json",
    }
