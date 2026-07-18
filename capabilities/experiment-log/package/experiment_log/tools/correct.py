"""Append-only correction operation for the Experiment Log."""

from __future__ import annotations

from agentic_tools import PythonTool, Record, Value
from experiment_log.tools._state import common, models, project_path


class ExperimentLogCorrectResult(Record):
    correction_id: str


class ExperimentLogCorrectTool(PythonTool[ExperimentLogCorrectResult]):
    """Append a correction without rewriting an existing experiment."""

    experiment_id: str = Value("Qualified experiment ID to correct")
    summary: str = Value("One-line correction summary")
    correction: str = Value("Corrected interpretation or value")
    work_branch: str | None = Value("Explicit work branch, or current branch", default=None)
    project_dir: str = Value("Project directory", default=".")

    def execute(self) -> ExperimentLogCorrectResult:
        correction_id = common.log_correction(
            models.ExperimentLogCorrectRequest(
                experiment_id=self.experiment_id,
                summary=self.summary,
                correction=self.correction,
            ),
            project_path(self.project_dir),
            self.work_branch,
        )
        return ExperimentLogCorrectResult(correction_id=correction_id)
