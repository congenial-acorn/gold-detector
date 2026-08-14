from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, final

GIT_TIMEOUT_SECONDS: Final = 120
BACKUP_BRANCH: Final = "main"


class GitBackupError(Exception):
    def __init__(self, operation: str) -> None:
        super().__init__(f"Git backup failed during {operation}")


@dataclass(frozen=True, slots=True)
class GitRepositoryConfig:
    remote_url: str
    checkout_path: Path
    allowed_names: frozenset[str]


@final
class BackupGitRepository:
    def __init__(
        self, config: GitRepositoryConfig, cancellation_requested: Callable[[], bool]
    ) -> None:
        self._config = config
        self._cancellation_requested = cancellation_requested

    def prepare(self) -> None:
        try:
            self._ensure_checkout()
            self._verify_checkout()
            self._verify_index()
            self._verify_reachable_history()
            self._git("fetch", "fetch", "origin")
            self._synchronize()
            self._verify_index()
            self._verify_reachable_history()
        except OSError as exc:
            raise GitBackupError(operation="checkout setup") from exc

    def commit_and_push(self) -> bool:
        names = sorted(
            name
            for name in self._config.allowed_names
            if (self._config.checkout_path / name).exists()
        )
        if names:
            self._git("stage", "add", "--all", "--", *names)
        self._verify_index()
        if self._has_staged_changes():
            timestamp = datetime.now(UTC).isoformat(timespec="seconds")
            self._git(
                "commit",
                "-c",
                "user.name=Gold Detector Backup",
                "-c",
                "user.email=backup@gold-detector.invalid",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-m",
                f"Backup {timestamp}",
            )

        if not self._ref_exists("HEAD"):
            return False
        self._verify_reachable_history()
        self._verify_push_urls()
        self._git(
            "push",
            "push",
            "--set-upstream",
            "origin",
            f"HEAD:{BACKUP_BRANCH}",
        )
        return True

    def _ensure_checkout(self) -> None:
        checkout = self._config.checkout_path
        if (checkout / ".git").is_dir():
            return
        if checkout.exists():
            try:
                _ = next(checkout.iterdir())
            except StopIteration:
                checkout.rmdir()
            else:
                raise GitBackupError(operation="checkout setup")

        checkout.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".git-backup-clone-", dir=checkout.parent
        ) as temporary_directory:
            clone_target = Path(temporary_directory) / "checkout"
            _ = self._command(
                "clone",
                checkout.parent,
                "git",
                "clone",
                self._config.remote_url,
                str(clone_target),
            )
            _ = clone_target.replace(checkout)

    def _verify_checkout(self) -> None:
        worktree = self._command(
            "checkout verification",
            self._config.checkout_path,
            "git",
            "rev-parse",
            "--is-inside-work-tree",
            check=False,
        )
        if worktree.returncode != 0 or worktree.stdout.strip() != "true":
            raise GitBackupError(operation="checkout verification")

        origin = self._command(
            "origin verification",
            self._config.checkout_path,
            "git",
            "remote",
            "get-url",
            "origin",
        ).stdout.strip()
        if origin != self._config.remote_url:
            raise GitBackupError(operation="origin verification")
        self._verify_push_urls()

    def _verify_push_urls(self) -> None:
        result = self._command(
            "push URL verification",
            self._config.checkout_path,
            "git",
            "remote",
            "get-url",
            "--push",
            "--all",
            "origin",
        )
        if result.stdout.splitlines() != [self._config.remote_url]:
            raise GitBackupError(operation="push URL verification")

    def _verify_index(self) -> None:
        result = self._command(
            "index verification",
            self._config.checkout_path,
            "git",
            "ls-files",
            "--cached",
        )
        indexed_names = frozenset(result.stdout.splitlines())
        if not indexed_names.issubset(self._config.allowed_names):
            raise GitBackupError(operation="index verification")

    def _verify_reachable_history(self) -> None:
        if not self._ref_exists("HEAD"):
            return
        revisions = self._command(
            "history verification",
            self._config.checkout_path,
            "git",
            "rev-list",
            "HEAD",
        ).stdout.splitlines()
        for revision in revisions:
            tree = self._command(
                "history verification",
                self._config.checkout_path,
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                revision,
            )
            tracked_names = frozenset(tree.stdout.splitlines())
            if not tracked_names.issubset(self._config.allowed_names):
                raise GitBackupError(operation="history verification")

    def _synchronize(self) -> None:
        remote_ref = f"refs/remotes/origin/{BACKUP_BRANCH}"
        if not self._ref_exists(remote_ref):
            return
        remote_branch = f"origin/{BACKUP_BRANCH}"
        if not self._ref_exists("HEAD") or self._is_ancestor("HEAD", remote_branch):
            self._git("synchronize", "reset", "--hard", remote_branch)
            return
        if not self._is_ancestor(remote_branch, "HEAD"):
            raise GitBackupError(operation="history reconciliation")

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = self._command(
            "history reconciliation",
            self._config.checkout_path,
            "git",
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise GitBackupError(operation="history reconciliation")
        return result.returncode == 0

    def _ref_exists(self, reference: str) -> bool:
        result = self._command(
            "reference detection",
            self._config.checkout_path,
            "git",
            "rev-parse",
            "--verify",
            reference,
            check=False,
        )
        return result.returncode == 0

    def _has_staged_changes(self) -> bool:
        result = self._command(
            "change detection",
            self._config.checkout_path,
            "git",
            "diff",
            "--cached",
            "--quiet",
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise GitBackupError(operation="change detection")
        return result.returncode == 1

    def _git(self, operation: str, *arguments: str) -> None:
        _ = self._command(
            operation,
            self._config.checkout_path,
            "git",
            *arguments,
        )

    def _command(
        self,
        operation: str,
        working_directory: Path,
        *command: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if self._cancellation_requested():
            raise GitBackupError(operation="shutdown")
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            return subprocess.run(
                command,
                cwd=working_directory,
                check=check,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitBackupError(operation=operation) from exc
