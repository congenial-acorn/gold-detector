from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path

import pytest

from gold_detector.git_backup import GitBackupConfig, GitBackupError, GitBackupService
from gold_detector.git_repository import BackupGitRepository, GitRepositoryConfig


def _git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_remote(path: Path) -> None:
    path.mkdir()
    _ = _git(path, "init", "--bare", "--initial-branch=main")


def _service(remote: Path, checkout: Path, source: Path) -> GitBackupService:
    return GitBackupService(
        GitBackupConfig(
            remote_url=str(remote),
            checkout_path=checkout,
            source_paths=(source,),
            interval_seconds=3600,
        ),
        logging.getLogger("test.git_backup_boundaries"),
    )


def test_distinct_push_url_is_rejected(tmp_path: Path) -> None:
    # Given
    configured_remote = tmp_path / "configured.git"
    redirected_remote = tmp_path / "redirected.git"
    _create_remote(configured_remote)
    _create_remote(redirected_remote)
    source = tmp_path / "dm_subscribers.json"
    _ = source.write_text("[1]", encoding="utf-8")
    checkout = tmp_path / "checkout"
    service = _service(configured_remote, checkout, source)
    service.backup_once()
    _ = _git(
        checkout,
        "remote",
        "set-url",
        "--push",
        "origin",
        str(redirected_remote),
    )

    # When / Then
    with pytest.raises(GitBackupError):
        service.backup_once()


def test_staged_unexpected_file_in_unborn_checkout_is_rejected(tmp_path: Path) -> None:
    # Given
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    checkout = tmp_path / "checkout"
    _ = _git(tmp_path, "clone", str(remote), str(checkout))
    _ = (checkout / "unexpected-secret.json").write_text(
        '{"secret": true}', encoding="utf-8"
    )
    _ = _git(checkout, "add", "unexpected-secret.json")
    source = tmp_path / "guild_prefs.json"
    _ = source.write_text('{"guilds": {}}', encoding="utf-8")

    # When / Then
    with pytest.raises(GitBackupError):
        _service(remote, checkout, source).backup_once()


def test_failed_push_snapshot_is_retained_when_source_disappears(
    tmp_path: Path,
) -> None:
    # Given
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    source = tmp_path / "dm_subscribers.json"
    _ = source.write_text("[1]", encoding="utf-8")
    checkout = tmp_path / "checkout"
    service = _service(remote, checkout, source)
    service.backup_once()

    _ = source.write_text("[1, 2]", encoding="utf-8")
    reject_hook = remote / "hooks" / "pre-receive"
    _ = reject_hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    reject_hook.chmod(0o755)
    with pytest.raises(GitBackupError):
        service.backup_once()
    reject_hook.unlink()
    source.unlink()

    # When
    with pytest.raises(GitBackupError):
        service.backup_once()

    # Then
    assert json.loads((checkout / source.name).read_text()) == [1, 2]


def test_cancelled_repository_refuses_next_git_command(tmp_path: Path) -> None:
    # Given
    cancelled = threading.Event()
    repository = BackupGitRepository(
        GitRepositoryConfig(
            remote_url=str(tmp_path / "remote.git"),
            checkout_path=tmp_path / "checkout",
            allowed_names=frozenset({"guild_prefs.json"}),
        ),
        cancelled.is_set,
    )
    cancelled.set()

    # When / Then
    with pytest.raises(GitBackupError):
        repository.prepare()


def test_empty_sources_on_empty_remote_do_not_fail_staging(tmp_path: Path) -> None:
    # Given
    remote = tmp_path / "remote.git"
    _create_remote(remote)
    source = tmp_path / "guild_prefs.json"
    checkout = tmp_path / "checkout"

    # When
    _service(remote, checkout, source).backup_once()

    # Then
    assert checkout.is_dir()
    assert _git(checkout, "status", "--porcelain") == ""
    assert _git(remote, "for-each-ref", "--format=%(refname)") == ""
