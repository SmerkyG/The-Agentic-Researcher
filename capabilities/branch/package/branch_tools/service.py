"""In-process entry points for branch snapshot and worktree operations."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


CAPABILITY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = CAPABILITY_ROOT.parents[1]
LIB_ROOT = CAPABILITY_ROOT / "lib"
COMMAND_ROOT = REPO_ROOT / "scripts" / "lib" / "commands"
for path in (LIB_ROOT, COMMAND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from branch_git_common import (  # noqa: E402
    cleanup_commit_artifacts,
    commit_snapshot_foreground,
    create_snapshot,
    show_status,
    start_background_commit,
)
from temporary_worktree import (  # noqa: E402
    create_temporary_worktree,
    publish_temporary_worktree,
    remove_temporary_worktree,
)


def snapshot_branch(request: dict[str, Any]) -> dict[str, Any]:
    return create_snapshot(request)


def commit_branch_snapshot(
    snapshot_dir: str | Path,
    *,
    background: bool = True,
) -> dict[str, Any]:
    snapshot = Path(snapshot_dir).expanduser().resolve()
    if not background:
        return commit_snapshot_foreground(snapshot)
    worker = CAPABILITY_ROOT / "bin" / "branch-commit"
    return start_background_commit(
        snapshot,
        [str(worker), "--worker", "--snapshot-dir", str(snapshot)],
    )


def commit_snapshot_worker(snapshot_dir: str | Path) -> dict[str, Any]:
    return commit_snapshot_foreground(Path(snapshot_dir).expanduser().resolve())


def branch_commit_status(snapshot_dir: str | Path) -> dict[str, Any]:
    path = Path(snapshot_dir).expanduser().resolve()
    if path.name == "status.yaml":
        path = path.parent
    return show_status(path)


def cleanup_branch_commits(request: dict[str, Any]) -> dict[str, Any]:
    return cleanup_commit_artifacts(request)


def create_branch_worktree(
    *,
    source_worktree: str | Path,
    worktree: str | Path,
) -> dict[str, Any]:
    return create_temporary_worktree(Path(source_worktree), Path(worktree))


def publish_branch_worktree(
    *,
    source_worktree: str | Path,
    worktree: str | Path,
    branch: str,
    base_commit: str,
    message: str,
    checks: list[str] | None = None,
    check_log: str | Path | None = None,
    push: bool = False,
) -> dict[str, Any]:
    return publish_temporary_worktree(
        Path(source_worktree),
        Path(worktree),
        branch,
        base_commit,
        message,
        checks=checks,
        check_log=Path(check_log) if check_log is not None else None,
        push=push,
    )


def drop_branch_worktree(
    *,
    source_worktree: str | Path,
    worktree: str | Path,
) -> dict[str, Any]:
    target = Path(worktree).expanduser().resolve()
    remove_temporary_worktree(
        Path(source_worktree).expanduser().resolve(),
        target,
    )
    return {"removed": True, "worktree": str(target)}
