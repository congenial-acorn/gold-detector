from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final
from urllib.parse import urlsplit

from .git_repository import (
    GIT_TIMEOUT_SECONDS,
    BackupGitRepository,
    GitBackupError,
    GitRepositoryConfig,
)

STATE_FILES_LOCK: Final = threading.RLock()

__all__ = (
    "STATE_FILES_LOCK",
    "GitBackupConfig",
    "GitBackupError",
    "GitBackupService",
)


@dataclass(frozen=True, slots=True)
class GitBackupConfig:
    remote_url: str
    checkout_path: Path
    source_paths: tuple[Path, ...]
    interval_seconds: float

    def __post_init__(self) -> None:
        parsed_remote = urlsplit(self.remote_url)
        has_http_credentials = parsed_remote.scheme in {"http", "https"} and (
            parsed_remote.username is not None or parsed_remote.password is not None
        )
        checkout = self.checkout_path.resolve()
        contains_source = any(
            source.resolve().is_relative_to(checkout) for source in self.source_paths
        )
        names = [source.name for source in self.source_paths]
        if (
            not self.remote_url
            or self.interval_seconds <= 0
            or has_http_credentials
            or contains_source
            or len(names) != len(set(names))
        ):
            raise GitBackupError(operation="configuration")


@final
class GitBackupService:
    """Own the mutable lifecycle of the periodic Git backup thread."""

    def __init__(self, config: GitBackupConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._stop_event = threading.Event()
        self._repository = BackupGitRepository(
            GitRepositoryConfig(
                remote_url=config.remote_url,
                checkout_path=config.checkout_path,
                allowed_names=frozenset(path.name for path in config.source_paths),
            ),
            self._stop_event.is_set,
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="git-state-backup",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("Git state backup runner started")

    def stop(self, timeout_seconds: float = GIT_TIMEOUT_SECONDS + 5) -> bool:
        self._stop_event.set()
        if self._thread is None:
            return True
        self._thread.join(timeout=timeout_seconds)
        return not self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.backup_once()
            except GitBackupError as exc:
                if not self._stop_event.is_set():
                    self._logger.error("Git state backup failed: %s", exc)

            _ = self._stop_event.wait(self._config.interval_seconds)

    def backup_once(self) -> None:
        self._repository.prepare()
        self.snapshot_files()
        if self._repository.commit_and_push():
            self._logger.info("Git state backup pushed successfully")

    def snapshot_files(self) -> None:
        try:
            with STATE_FILES_LOCK:
                snapshots: list[tuple[Path, str | None]] = []
                for source in self._config.source_paths:
                    destination = self._config.checkout_path / source.name
                    if not source.exists():
                        if destination.exists():
                            raise GitBackupError(operation="missing source")
                        snapshots.append((source, None))
                        continue
                    content = source.read_text(encoding="utf-8")
                    json.loads(content)
                    snapshots.append((source, content))

                for source, snapshot_content in snapshots:
                    if snapshot_content is None:
                        continue
                    destination = self._config.checkout_path / source.name
                    temporary = destination.with_suffix(destination.suffix + ".tmp")
                    _ = temporary.write_text(snapshot_content, encoding="utf-8")
                    _ = temporary.replace(destination)
        except (json.JSONDecodeError, OSError) as exc:
            raise GitBackupError(operation="snapshot") from exc
