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


class GitStatusPathsTool(ArgvTool[CommandResult]):
    """Inspect whether any explicitly selected paths differ from HEAD."""

    argv_template: ClassVar[tuple[str, ...]] = (
        "git", "status", "--porcelain=v1", "--untracked-files=all",
    )
    paths: list[str] = Value("Explicit code paths to inspect")
    project_dir: str = "."

    def argv(self) -> list[str]:
        return [
            "git",
            "-C",
            self.project_dir,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *self.paths,
        ]


class BranchSnapshotTool(YAMLArgvTool[Snapshot]):
    argv_template: ClassVar[tuple[str, ...]] = ("branch-snapshot",)
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
    )
    project_dir: str = "."
    work_branch: str | None = None


class BranchCommitResult(WorkflowRecord):
    state: Literal["queued", "committed"]
    commit: str | None = None


class BranchCommitTool(YAMLArgvTool[BranchCommitResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("branch-commit",)
    snapshot_dir: str
    background: bool = True
