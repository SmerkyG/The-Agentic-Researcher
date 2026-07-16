"""Private executable implementation for finalization start."""

from __future__ import annotations

from agentic_workflows.contract import ExecutableWorkflowImplementation
from agentic_workflows.research.finalization import FinalizationTicket
from agentic_workflows.research.finalization_capture import FinalizationCaptureTool
from agentic_workflows.research.finalization_start import FinalizationStart
from agentic_workflows.research.git import BranchCommitResult, BranchCommitTool, BranchSnapshotTool, Snapshot


class FinalizationStartWorkflow(
    FinalizationStart,
    ExecutableWorkflowImplementation[FinalizationStart],
):
    """Snapshot and commit explicit code paths, then freeze report assets."""

    def workflow(self) -> FinalizationTicket:
        if self.code_paths:
            if not self.commit_message:
                raise ValueError("commit_message is required when code_paths is nonempty")
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
        elif self.commit_message is not None or self.checks:
            raise ValueError("commit_message and checks require nonempty code_paths")

        return FinalizationCaptureTool(
            report_assets=self.report_assets,
            project_dir=self.project_dir,
            work_state_dir=self.work_state_dir,
        ).run()
