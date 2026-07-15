"""Generic lifecycle for one temporary linked Git worktree."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from branch_git_common import (
    current_branch,
    current_commit,
    git,
    git_text,
    require_git_commit_identity,
    run_checks,
)
from command_common import CommandError


def remove_temporary_worktree(source_worktree: Path, worktree: Path) -> None:
    source_worktree = source_worktree.expanduser().resolve()
    worktree = worktree.expanduser().resolve()
    registered = {
        Path(line.removeprefix("worktree ")).resolve()
        for line in git_text(source_worktree, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    }
    if worktree not in registered:
        if worktree.exists():
            raise CommandError(f"refusing to remove unregistered worktree path: {worktree}")
        return
    git(source_worktree, "worktree", "remove", "--force", str(worktree), check=False)
    if worktree.exists():
        shutil.rmtree(worktree)
    git(source_worktree, "worktree", "prune", check=False)


def create_temporary_worktree(source_worktree: Path, worktree: Path) -> dict[str, Any]:
    source_worktree = source_worktree.expanduser().resolve()
    worktree = worktree.expanduser().resolve()
    branch = current_branch(source_worktree)
    base_commit = current_commit(source_worktree)
    if worktree.exists():
        raise CommandError(f"temporary worktree path already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(source_worktree, "worktree", "add", "--detach", str(worktree), base_commit)
    return {
        "source_worktree": str(source_worktree),
        "worktree": str(worktree),
        "branch": branch,
        "base_commit": base_commit,
    }


def changed_paths(worktree: Path) -> list[str]:
    git(worktree, "add", "-A")
    return [line for line in git_text(worktree, "diff", "--cached", "--name-only").splitlines() if line]


def path_matches_commit(worktree: Path, commit: str, relative: str) -> bool:
    path = worktree / relative
    blob = git(worktree, "rev-parse", f"{commit}:{relative}", check=False)
    if not path.exists():
        return blob.returncode != 0
    if not path.is_file() or blob.returncode != 0:
        return False
    return git_text(worktree, "hash-object", "--", relative) == blob.stdout.strip()


def copy_path(source: Path, target: Path, relative: str) -> None:
    source_path = source / relative
    target_path = target / relative
    if source_path.is_file():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
    elif target_path.exists():
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()


def publish_temporary_worktree(
    source_worktree: Path,
    worktree: Path,
    branch: str,
    base_commit: str,
    message: str,
    *,
    checks: list[str] | None = None,
    check_log: Path | None = None,
    push: bool = False,
) -> dict[str, Any]:
    source_worktree = source_worktree.expanduser().resolve()
    worktree = worktree.expanduser().resolve()
    message = message.strip()
    if not message:
        raise CommandError("temporary worktree publish requires a commit message")
    if not branch or not base_commit:
        raise CommandError("temporary worktree publish requires branch and base_commit")
    if current_branch(source_worktree) != branch:
        raise CommandError(f"source worktree is no longer on captured branch: {branch}")
    if git_text(source_worktree, "rev-parse", f"refs/heads/{branch}") != base_commit:
        raise CommandError(f"target branch moved while temporary worktree was active: {branch}")
    if current_commit(worktree) != base_commit:
        raise CommandError("temporary worktree HEAD moved; publish expects one tool-owned commit")

    paths = changed_paths(worktree)
    if not paths:
        return {"branch": branch, "commit": base_commit, "changed": False, "paths": []}
    refresh_paths = [path for path in paths if path_matches_commit(source_worktree, base_commit, path)]
    if checks:
        if check_log is None:
            raise CommandError("check_log is required when checks are configured")
        run_checks(worktree, checks, check_log, snapshot_dir=worktree)

    require_git_commit_identity(source_worktree)
    git(worktree, "commit", "-m", message)
    commit = git_text(worktree, "rev-parse", "HEAD")
    git(source_worktree, "update-ref", f"refs/heads/{branch}", commit, base_commit)
    for relative in refresh_paths:
        copy_path(worktree, source_worktree, relative)
    git(source_worktree, "reset", "-q", "HEAD", "--", *paths, check=False)
    if push and git(source_worktree, "remote", "get-url", "origin", check=False).returncode == 0:
        git(source_worktree, "push", "origin", f"{commit}:refs/heads/{branch}")
    return {"branch": branch, "commit": commit, "changed": True, "paths": paths}
