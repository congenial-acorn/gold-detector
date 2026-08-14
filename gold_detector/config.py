from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from dotenv import find_dotenv, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment() -> None:
    """Load environment variables from the working tree."""
    _ = load_dotenv(find_dotenv())
    if not os.getenv("DISCORD_TOKEN"):
        _ = load_dotenv(PROJECT_ROOT / ".env")


def configure_logging(log_level: str) -> logging.Logger:
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.StreamHandler(sys.stdout)],
        )
    root.setLevel(level)
    return logging.getLogger("bot")


def sanitize_channel_name(raw: str | None) -> str:
    return (raw or "").strip().lstrip("#")


def sanitize_role_name(raw: str | None) -> str:
    return (raw or "").strip().lstrip("@")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    default_alert_channel: str
    default_role_name: str
    alert_channel_override: str
    role_name_override: str
    bot_verbose: bool
    debug_mode: bool
    debug_server_id: int | None
    debug_mode_dms: bool
    debug_user_id: int | None
    queue_max_size: int
    help_url: str
    monitor_interval_seconds: float
    http_cooldown_seconds: float
    log_level: str
    backup_git_remote: str = ""
    backup_checkout_path: Path = PROJECT_ROOT / ".backup-repo"
    backup_interval_seconds: float = 3600.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_environment()

        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise SystemExit("Missing DISCORD_TOKEN in environment or .env")

        default_channel = "market-watch"
        default_role = "Market Alert"

        alert_override = sanitize_channel_name(os.getenv("ALERT_CHANNEL_NAME", ""))
        role_override = sanitize_role_name(os.getenv("ROLE_NAME", ""))

        try:
            monitor_interval = float(os.getenv("GOLD_MONITOR_INTERVAL_SECONDS", "1800"))
        except ValueError:
            monitor_interval = 1800.0

        try:
            http_cooldown = float(os.getenv("GOLD_HTTP_COOLDOWN", "1.0"))
        except ValueError:
            http_cooldown = 1.0

        try:
            backup_interval = float(os.getenv("BACKUP_INTERVAL_SECONDS", "3600"))
        except ValueError:
            backup_interval = 3600.0
        if backup_interval <= 0:
            backup_interval = 3600.0

        configured_backup_path = Path(
            os.getenv("BACKUP_CHECKOUT_PATH", str(PROJECT_ROOT / ".backup-repo"))
        ).expanduser()
        backup_checkout_path = (
            configured_backup_path
            if configured_backup_path.is_absolute()
            else PROJECT_ROOT / configured_backup_path
        ).resolve()

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        return cls(
            token=token,
            default_alert_channel=default_channel,
            default_role_name=default_role,
            alert_channel_override=alert_override,
            role_name_override=role_override,
            bot_verbose=os.getenv("BOT_VERBOSE", "1") == "1",
            debug_mode=_bool_env("DEBUG_MODE", False),
            debug_server_id=_int_env("DEBUG_SERVER_ID"),
            debug_mode_dms=_bool_env("DEBUG_MODE_DMS", False),
            debug_user_id=_int_env("DEBUG_USER_ID"),
            queue_max_size=int(os.getenv("DISCORD_QUEUE_MAX_SIZE", "100")),
            help_url=os.getenv(
                "HELP_URL",
                "https://github.com/congenial-acorn/gold-detector/tree/main?tab=readme-ov-file#commands",
            ),
            monitor_interval_seconds=monitor_interval,
            http_cooldown_seconds=http_cooldown,
            log_level=log_level,
            backup_git_remote=os.getenv("BACKUP_GIT_REMOTE", "").strip(),
            backup_checkout_path=backup_checkout_path,
            backup_interval_seconds=backup_interval,
        )
