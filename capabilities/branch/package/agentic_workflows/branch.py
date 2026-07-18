"""Native typed operations owned by the branch capability."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Literal, TypeVar

from branch_tools.service import (
    branch_commit_status,
    cleanup_branch_commits,
    commit_branch_snapshot,
    create_branch_worktree,
    drop_branch_worktree,
    publish_branch_worktree,
    snapshot_branch,
)
from agentic_tools import PythonTool, Record, Value


RecordT = TypeVar("RecordT", bound=Record)


def _record(record_type: type[RecordT], data: dict[str, Any]) -> RecordT:
    names = {item.name for item in fields(record_type)}
    return record_type(**{name: value for name, value in data.items() if name in names})


class Snapshot(Record):
    snapshot_id: str
    snapshot_dir: str
    status_path: str
    branch: str
    base_commit: str
    paths: list[str]
    name_status_path: str
    name_status: list[str]


class BranchSnapshotTool(PythonTool[Snapshot]):
    paths: list[str] = Value("Explicit code paths; no globs, directories, or dot")
    commit_message: str = Value("Focused commit message")
    checks: list[str] = Value(
        "Focused, non-redundant check commands",
        guidance=(
            "Checks run in a fresh temporary worktree. Use `uv run --no-project python ...` "
            "for standard-library-only Python checks; use ordinary `uv run` only when project "
            "dependencies are required. Do not precede an executed script with a redundant "
            "`py_compile` check."
        ),
        default_factory=list,
    )
    project_dir: str = "."
    work_branch: str | None = None
    check_timeout_seconds: int | None = None

    def execute(self) -> Snapshot:
        result = snapshot_branch(
            {
                "paths": self.paths,
                "commit_message": self.commit_message,
                "checks": self.checks,
                "project_dir": self.project_dir,
                "work_branch": self.work_branch,
                "check_timeout_seconds": self.check_timeout_seconds,
            }
        )
        return _record(Snapshot, result)


class BranchCommitResult(Record):
    state: Literal["queued", "committed"]
    snapshot_id: str | None = None
    commit: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    worktree: str | None = None
    check_log: str | None = None
    checks: list[dict[str, object]] = Value("Completed check results", default_factory=list)
    diff_stat: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    status_path: str | None = None
    background_log: str | None = None


class BranchCommitTool(PythonTool[BranchCommitResult]):
    snapshot_dir: str
    background: bool = True

    def execute(self) -> BranchCommitResult:
        return _record(
            BranchCommitResult,
            commit_branch_snapshot(
                self.snapshot_dir,
                background=self.background,
            ),
        )


class BranchCommitStatusResult(Record):
    state: str
    snapshot_id: str | None = None
    snapshot_dir: str | None = None
    status_path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    paths: list[str] = Value("Snapshotted paths", default_factory=list)
    name_status_path: str | None = None
    name_status: list[str] = Value("Snapshotted name-status lines", default_factory=list)
    pid: int | None = None
    pid_alive: bool | None = None
    background_log: str | None = None
    started_at: str | None = None
    worktree: str | None = None
    check_log: str | None = None
    check_count: int | None = None
    current_check: str | None = None
    current_check_index: int | None = None
    current_check_started_at: str | None = None
    checks: list[dict[str, object]] = Value("Completed check results", default_factory=list)
    last_check: str | None = None
    last_check_returncode: int | None = None
    commit: str | None = None
    diff_stat: str | None = None
    finished_at: str | None = None
    error: str | None = None
    failed_at: str | None = None


class BranchCommitStatusTool(PythonTool[BranchCommitStatusResult]):
    snapshot_dir: str = Value("Snapshot directory or status.yaml path")

    def execute(self) -> BranchCommitStatusResult:
        return _record(
            BranchCommitStatusResult,
            branch_commit_status(self.snapshot_dir),
        )


class BranchCommitCleanupResult(Record):
    dry_run: bool
    runtime_root: str
    older_than_days: int
    selected_states: list[str]
    planned: list[dict[str, object]]
    removed: list[dict[str, object]]
    skipped: list[dict[str, object]]
    planned_count: int
    removed_count: int
    skipped_count: int


class BranchCommitCleanupTool(PythonTool[BranchCommitCleanupResult]):
    dry_run: bool = True
    older_than_days: int = 7
    states: list[str] = Value(
        "Snapshot states eligible for cleanup",
        default_factory=lambda: ["committed", "failed", "snapshotted"],
    )
    project_dir: str | None = None
    snapshot_dir: str | None = None
    snapshot_dirs: list[str] = Value("Explicit snapshot directories", default_factory=list)
    include_active: bool = False

    def execute(self) -> BranchCommitCleanupResult:
        request: dict[str, object] = {
            "dry_run": self.dry_run,
            "older_than_days": self.older_than_days,
            "states": self.states,
            "include_active": self.include_active,
        }
        if self.project_dir is not None:
            request["project_dir"] = self.project_dir
        if self.snapshot_dir is not None:
            request["snapshot_dir"] = self.snapshot_dir
        if self.snapshot_dirs:
            request["snapshot_dirs"] = self.snapshot_dirs
        return _record(
            BranchCommitCleanupResult,
            cleanup_branch_commits(request),
        )


class BranchWorktreeCreateResult(Record):
    source_worktree: str
    worktree: str
    branch: str
    base_commit: str


class BranchWorktreeCreateTool(PythonTool[BranchWorktreeCreateResult]):
    worktree: str
    source_worktree: str = "."

    def execute(self) -> BranchWorktreeCreateResult:
        return _record(
            BranchWorktreeCreateResult,
            create_branch_worktree(
                source_worktree=self.source_worktree,
                worktree=self.worktree,
            ),
        )


class BranchWorktreePublishResult(Record):
    branch: str
    commit: str
    changed: bool
    paths: list[str]


class BranchWorktreePublishTool(PythonTool[BranchWorktreePublishResult]):
    worktree: str
    branch: str
    base_commit: str
    message: str
    source_worktree: str = "."
    checks: list[str] = Value("Checks run before publication", default_factory=list)
    check_log: str | None = None
    push: bool = False

    def execute(self) -> BranchWorktreePublishResult:
        return _record(
            BranchWorktreePublishResult,
            publish_branch_worktree(
                source_worktree=self.source_worktree,
                worktree=self.worktree,
                branch=self.branch,
                base_commit=self.base_commit,
                message=self.message,
                checks=self.checks,
                check_log=self.check_log,
                push=self.push,
            ),
        )


class BranchWorktreeDropResult(Record):
    removed: bool
    worktree: str


class BranchWorktreeDropTool(PythonTool[BranchWorktreeDropResult]):
    worktree: str
    source_worktree: str = "."

    def execute(self) -> BranchWorktreeDropResult:
        return _record(
            BranchWorktreeDropResult,
            drop_branch_worktree(
                source_worktree=self.source_worktree,
                worktree=self.worktree,
            ),
        )
