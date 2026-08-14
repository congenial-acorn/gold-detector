from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from gold_detector.git_backup import (
    GitBackupConfig,
    GitBackupError,
    GitBackupService,
)


def _git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(cwd: Path, message: str) -> None:
    _ = _git(cwd, "add", "--all")
    _ = _git(
        cwd,
        "-c",
        "user.name=Backup Test",
        "-c",
        "user.email=backup-test@example.invalid",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "-m",
        message,
    )


def _create_remote(path: Path) -> None:
    path.mkdir()
    _ = _git(path, "init", "--bare", "--initial-branch=main")


def _service(remote: Path, checkout: Path, sources: tuple[Path, ...]) -> GitBackupService:
    return GitBackupService(
        GitBackupConfig(
            remote_url=str(remote),
            checkout_path=checkout,
            source_paths=sources,
            interval_seconds=3600,
        ),
        logging.getLogger("test.git_backup_safety"),
    )


def test_missing_source_does_not_delete_latest_remote_backup(tmp_path: Path) -> None:
    # Given
    source = tmp_path / "guild_prefs.json"
    _ = source.write_text(json.dumps({"guilds": {"1": {}}}), encoding="utf-8")
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    service = _service(remote, tmp_path / "checkout", (source,))
    service.backup_once()
    source.unlink()

    # When
    with pytest.raises(GitBackupError):
        service.backup_once()

    # Then
    restored = tmp_path / "restored"
    _ = _git(tmp_path, "clone", str(remote), str(restored))
    assert json.loads((restored / source.name).read_text()) == {"guilds": {"1": {}}}
    assert _git(restored, "rev-list", "--count", "HEAD") == "1"


def test_checkout_with_different_origin_is_rejected(tmp_path: Path) -> None:
    # Given
    first_remote = tmp_path / "first.git"
    second_remote = tmp_path / "second.git"
    _create_remote(first_remote)
    _create_remote(second_remote)
    source = tmp_path / "dm_subscribers.json"
    _ = source.write_text("[]", encoding="utf-8")
    checkout = tmp_path / "checkout"
    _service(first_remote, checkout, (source,)).backup_once()

    # When / Then
    with pytest.raises(GitBackupError):
        _service(second_remote, checkout, (source,)).backup_once()


def test_unexpected_tracked_file_prevents_push(tmp_path: Path) -> None:
    # Given
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    source = tmp_path / "guild_optout.json"
    _ = source.write_text("[]", encoding="utf-8")
    checkout = tmp_path / "checkout"
    service = _service(remote, checkout, (source,))
    service.backup_once()
    _ = (checkout / "unexpected.txt").write_text("not backup state", encoding="utf-8")
    _commit(checkout, "Add unexpected file")

    # When / Then
    with pytest.raises(GitBackupError):
        service.backup_once()


def test_empty_checkout_directory_recovers_by_cloning(tmp_path: Path) -> None:
    # Given
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    source = tmp_path / "dm_subscribers.json"
    _ = source.write_text("[123]", encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    service = _service(remote, checkout, (source,))

    # When
    service.backup_once()

    # Then
    assert json.loads((checkout / source.name).read_text()) == [123]


def test_remote_advancement_is_reconciled_before_backup(tmp_path: Path) -> None:
    # Given
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    source = tmp_path / "dm_subscribers.json"
    _ = source.write_text("[1]", encoding="utf-8")
    checkout = tmp_path / "checkout"
    service = _service(remote, checkout, (source,))
    service.backup_once()

    other = tmp_path / "other"
    _ = _git(tmp_path, "clone", str(remote), str(other))
    _ = (other / source.name).write_text("[1, 2]", encoding="utf-8")
    _commit(other, "Remote backup update")
    _ = _git(other, "push", "origin", "main")
    _ = source.write_text("[1, 3]", encoding="utf-8")

    # When
    service.backup_once()

    # Then
    restored = tmp_path / "restored"
    _ = _git(tmp_path, "clone", str(remote), str(restored))
    assert json.loads((restored / source.name).read_text()) == [1, 3]


def test_https_remote_with_embedded_credentials_is_rejected(tmp_path: Path) -> None:
    # Given / When / Then
    with pytest.raises(GitBackupError):
        _ = GitBackupConfig(
            remote_url="https://user:token@github.com/owner/backups.git",
            checkout_path=tmp_path / "checkout",
            source_paths=(tmp_path / "guild_prefs.json",),
            interval_seconds=3600,
        )
