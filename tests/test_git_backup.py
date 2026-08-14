from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path

import pytest

from gold_detector.config import PROJECT_ROOT, Settings
from gold_detector.git_backup import (
    STATE_FILES_LOCK,
    GitBackupConfig,
    GitBackupService,
)
from gold_detector.services import SubscriberService


def _run_git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_json(path: Path, content: str) -> None:
    _ = path.write_text(content, encoding="utf-8")


def test_backup_once_pushes_only_configured_state_files(tmp_path: Path) -> None:
    # Given
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    guild_prefs = source_dir / "guild_prefs.json"
    guild_optout = source_dir / "guild_optout.json"
    dm_subscribers = source_dir / "dm_subscribers.json"
    _write_json(guild_prefs, json.dumps({"guilds": {"123": "configured"}}))
    _write_json(guild_optout, json.dumps([456]))
    _write_json(dm_subscribers, json.dumps([789]))
    _write_json(
        source_dir / "market_database.json", json.dumps({"Sol": "excluded"})
    )

    remote = tmp_path / "remote.git"
    remote.mkdir()
    _ = _run_git(remote, "init", "--bare", "--initial-branch=main")
    checkout = tmp_path / "backup-checkout"
    service = GitBackupService(
        GitBackupConfig(
            remote_url=str(remote),
            checkout_path=checkout,
            source_paths=(guild_prefs, guild_optout, dm_subscribers),
            interval_seconds=3600,
        ),
        logging.getLogger("test.git_backup"),
    )

    # When
    service.backup_once()

    # Then
    restored = tmp_path / "restored"
    _ = _run_git(tmp_path, "clone", str(remote), str(restored))
    assert json.loads((restored / "guild_prefs.json").read_text()) == {
        "guilds": {"123": "configured"}
    }
    assert json.loads((restored / "guild_optout.json").read_text()) == [456]
    assert json.loads((restored / "dm_subscribers.json").read_text()) == [789]
    assert not (restored / "market_database.json").exists()
    assert _run_git(restored, "rev-list", "--count", "HEAD") == "1"


def test_snapshot_waits_for_state_file_write_lock(tmp_path: Path) -> None:
    # Given
    source = tmp_path / "guild_prefs.json"
    _write_json(source, json.dumps({"guilds": {}}))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    service = GitBackupService(
        GitBackupConfig(
            remote_url="unused",
            checkout_path=checkout,
            source_paths=(source,),
            interval_seconds=3600,
        ),
        logging.getLogger("test.git_backup"),
    )
    started = threading.Event()

    def snapshot() -> None:
        started.set()
        service.snapshot_files()

    # When
    with STATE_FILES_LOCK:
        thread = threading.Thread(target=snapshot)
        thread.start()
        assert started.wait(timeout=1)
        thread.join(timeout=0.05)
        blocked_while_write_lock_is_held = thread.is_alive()

    thread.join(timeout=1)

    # Then
    assert blocked_while_write_lock_is_held
    assert not thread.is_alive()
    assert json.loads((checkout / source.name).read_text()) == {"guilds": {}}


def test_state_file_write_waits_for_backup_lock(tmp_path: Path) -> None:
    # Given
    subscribers = SubscriberService(tmp_path / "dm_subscribers.json")
    started = threading.Event()

    def subscribe() -> None:
        started.set()
        subscribers.add(123)

    # When
    with STATE_FILES_LOCK:
        thread = threading.Thread(target=subscribe)
        thread.start()
        assert started.wait(timeout=1)
        thread.join(timeout=0.05)
        blocked_while_backup_lock_is_held = thread.is_alive()

    thread.join(timeout=1)

    # Then
    assert blocked_while_backup_lock_is_held
    assert not thread.is_alive()
    assert json.loads((tmp_path / "dm_subscribers.json").read_text()) == [123]


def test_settings_reads_git_backup_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("BACKUP_GIT_REMOTE", "git@github.com:owner/backups.git")
    monkeypatch.setenv("BACKUP_CHECKOUT_PATH", "relative-backup-checkout")
    monkeypatch.setenv("BACKUP_INTERVAL_SECONDS", "7200")

    # When
    settings = Settings.from_env()

    # Then
    assert settings.backup_git_remote == "git@github.com:owner/backups.git"
    assert settings.backup_checkout_path == (
        PROJECT_ROOT / "relative-backup-checkout"
    ).resolve()
    assert settings.backup_interval_seconds == 7200
