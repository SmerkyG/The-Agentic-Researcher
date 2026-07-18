"""Summary read operation for the Experiment Log."""

from __future__ import annotations

from agentic_tools import PythonTool, Record, Value
from experiment_log.tools._state import common, project_path


class ExperimentLogSummaryResult(Record):
    work_branch: str
    exists: bool
    content: str
    error: str | None = None


class ExperimentLogSummaryTool(PythonTool[ExperimentLogSummaryResult]):
    """Read the active work-branch experiment summary."""

    project_dir: str = Value("Project directory", default=".")
    work_branch: str | None = Value("Explicit work branch, or current branch", default=None)

    def execute(self) -> ExperimentLogSummaryResult:
        branch = common.work_branch(self.work_branch)
        try:
            content = common.read_summary(project_path(self.project_dir), branch)
        except common.ExperimentLogError as error:
            if not str(error).startswith("experiment summary does not exist on "):
                raise
            return ExperimentLogSummaryResult(
                work_branch=branch,
                exists=False,
                content="",
                error=str(error),
            )
        return ExperimentLogSummaryResult(
            work_branch=branch,
            exists=True,
            content=content,
        )
