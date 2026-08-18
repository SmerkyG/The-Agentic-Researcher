"""Public request contract for freezing one completed research result."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.branch import (
    BranchCommitResult,
    BranchCommitTool,
    BranchSnapshotTool,
    Snapshot,
)
from agentic_workflows.contract import CommandResult, ExecutableWorkflow, Value
from agentic_workflows.research.git import GitStatusPathsTool
from research_finalization.records import FinalizationTicket
from research_finalization.tools.capture import FinalizationCaptureTool


class FinalizationStart(ExecutableWorkflow[FinalizationTicket]):
    """Snapshot and commit explicit code paths, then freeze report assets."""

    guidance: ClassVar[str] = (
        "Use explicit code paths, a focused commit message, immutable-snapshot checks, "
        "and branch-records-relative report asset paths. Paths that already match HEAD are a "
        "valid replay no-op. The operation is inert until Python calls run()."
    )

    code_paths: list[str] = Value(
        "Explicit code paths to snapshot and commit; empty when the result changed no code",
        default_factory=list,
    )
    commit_message: str | None = Value(
        "Focused commit message required when code_paths is nonempty; null otherwise",
        default=None,
    )
    checks: list[str] = Value(
        "Focused, non-redundant commands run against the immutable code snapshot; "
        "empty when code_paths is empty",
        guidance=(
            "For Python checks that use only the standard library, use `uv run --no-project "
            "python ...` so the temporary worktree does not provision every project dependency. "
            "Use ordinary `uv run` only when the check imports project dependencies. "
            "Do not add a separate `py_compile` check when another check executes the same script."
        ),
        default_factory=list,
    )
    report_assets: list[str] = Value(
        "Explicit report-asset paths relative to the branch records directory",
        default_factory=list,
    )
    project_dir: str = "."
    branch_records_dir: str | None = None

    def workflow(self) -> FinalizationTicket:
        if self.code_paths:
            status: CommandResult = GitStatusPathsTool(
                paths=self.code_paths,
                project_dir=self.project_dir,
            ).run()
            if status.returncode != 0:
                raise RuntimeError(
                    "could not inspect finalization code paths: "
                    + (status.stderr or status.stdout).strip()
                )
            if status.stdout.strip():
                if not self.commit_message:
                    raise ValueError("commit_message is required when selected code paths changed")
                snapshot: Snapshot = BranchSnapshotTool(
                    paths=self.code_paths,
                    commit_message=self.commit_message,
                    checks=self.checks,
                    project_dir=self.project_dir,
                ).run()
                commit: BranchCommitResult = BranchCommitTool(
                    snapshot_dir=snapshot.snapshot_dir,
                    background=False,
                ).run()
                if commit.state != "committed" or commit.commit is None:
                    raise RuntimeError("code snapshot was not committed")
        return FinalizationCaptureTool(
            report_assets=self.report_assets,
            project_dir=self.project_dir,
            branch_records_dir=self.branch_records_dir,
        ).run()
