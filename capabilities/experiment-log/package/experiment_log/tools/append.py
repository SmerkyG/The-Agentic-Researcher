"""Append operation for the Experiment Log."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_tools import PythonTool, Record, Value
from experiment_log.tools._state import common, models, project_path


class ExperimentCode(Record):
    branch: str | None = Value("Code branch, or null when inferred", default=None)
    commit: str | None = Value("Code commit, or null when unavailable", default=None)


class ExperimentMetric(Record):
    name: str = Value("Metric name")
    value: str = Value("Metric value with units or direction when useful")


class ExperimentLogAppendResult(Record):
    experiment_id: str


class ExperimentLogAppendTool(PythonTool[ExperimentLogAppendResult]):
    """Append one completed experiment to the durable ledger."""

    guidance: ClassVar[str] = """
Record completed positive, negative, and failed experiments. Let the tool
manage work-state locking, pull, commit, push, retry, and success tagging. Do
not edit experiment-log state manually and never force-push.
"""

    title: str = Value("Experiment title")
    short_description: str = Value("Short slug-like description")
    code: ExperimentCode = Value("Code identity for the experiment")
    description: str = Value("What was tested and why")
    command: str = Value("Exact command or command group")
    status: Literal["completed", "failed", "invalid"] = Value("Outcome status")
    success: bool = Value("True only for a completed successful result")
    key_result: str = Value("One-line outcome")
    metrics: list[ExperimentMetric] = Value("Measured results", default_factory=list)
    artifacts: list[str] = Value("Artifact paths or URLs", default_factory=list)
    work_branch: str | None = Value("Explicit work branch, or current branch", default=None)
    notes: str | None = Value("Concise interpretation and caveats", default=None)
    project_dir: str = Value("Project directory", default=".")

    def execute(self) -> ExperimentLogAppendResult:
        experiment_id = common.log_experiment(
            models.ExperimentLogAppendRequest(
                title=self.title,
                short_description=self.short_description,
                code=models.ExperimentCode(
                    branch=self.code.branch,
                    commit=self.code.commit,
                ),
                description=self.description,
                command=self.command,
                status=self.status,
                success=self.success,
                key_result=self.key_result,
                metrics=[
                    models.ExperimentMetric(name=metric.name, value=metric.value)
                    for metric in self.metrics
                ],
                artifacts=list(self.artifacts),
                work_branch=self.work_branch,
                notes=self.notes,
            ),
            project_path(self.project_dir),
            self.work_branch,
        )
        return ExperimentLogAppendResult(experiment_id=experiment_id)
