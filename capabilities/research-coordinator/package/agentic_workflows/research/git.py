"""Git inspection, snapshot, and commit operation contracts."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import ArgvTool, CommandResult, Value, WorkflowRecord, YAMLArgvTool


class Snapshot(WorkflowRecord):
    """Structured response from branch-snapshot."""

    snapshot_id: str
    snapshot_dir: str
    status_path: str
    branch: str
    base_commit: str
    paths: list[str]
    name_status_path: str
    name_status: list[str]


class GitRecentLogTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("git", "log", "--oneline")
    count: int = 20

    def argv(self) -> list[str]:
        return [*self.argv_template, f"-{self.count}"]


class GitStatusShortTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("git", "status", "--short")


class BranchSnapshotTool(YAMLArgvTool[Snapshot]):
    argv_template: ClassVar[tuple[str, ...]] = ("branch-snapshot",)
    paths: list[str] = Value("Explicit code paths; no globs, directories, or dot")
    commit_message: str = Value("Focused commit message")
    checks: list[str] = Value("Focused check commands")
    project_dir: str = "."
    work_branch: str | None = None


class BranchCommitResult(WorkflowRecord):
    state: Literal["queued", "committed"]
    commit: str | None = None


class BranchCommitTool(YAMLArgvTool[BranchCommitResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("branch-commit",)
    snapshot_dir: str
    background: bool = True
