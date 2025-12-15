from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from .config import PROJECT_ROOT, sanitize_channel_name, sanitize_role_name
from .utils import now


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
        self._prefs: Dict[int, Dict[str, object]] = self._load()

    def _load(self) -> Dict[int, Dict[str, object]]:
        raw = self.store.load({})
        parsed: Dict[int, Dict[str, object]] = {}
        try:
            for gid_str, vals in raw.items():
                gid = int(gid_str)
                parsed[gid] = {
                    "channel_id": vals.get("channel_id"),
                    "channel_name": sanitize_channel_name(vals.get("channel_name")),
                    "role_id": vals.get("role_id"),
                    "role_name": sanitize_role_name(vals.get("role_name")),
                }
        except Exception:
            return {}
        return parsed

    def _persist_locked(self) -> None:
        serial = {
            str(gid): {
                "channel_id": vals.get("channel_id"),
                "channel_name": vals.get("channel_name"),
                "role_id": vals.get("role_id"),
                "role_name": vals.get("role_name"),
            }
            for gid, vals in self._prefs.items()
        }
        self.store.save(serial)

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

    def source_labels(self, guild_id: int) -> Tuple[str, str]:
        prefs = self._prefs.get(guild_id) or {}
        channel_src = "custom" if prefs.get("channel_id") or prefs.get("channel_name") else "default"
        role_src = "custom" if prefs.get("role_id") or prefs.get("role_name") else "default"
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
