"""Append operation for the independent experiment-log command."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import Value, WorkflowRecord, YAMLArgvTool


class ExperimentCode(WorkflowRecord):
    branch: str | None = Value("Code branch, or None when inferred", default=None)
    commit: str | None = Value("Code commit, or None when filled after commit", default=None)


class ExperimentMetric(WorkflowRecord):
    name: str = Value("Metric name")
    value: str = Value("Metric value with units or direction when useful")


class ExperimentLogAppendResult(WorkflowRecord):
    experiment_id: str


class ExperimentLogAppendTool(YAMLArgvTool[ExperimentLogAppendResult]):
    """Append one completed experiment to the durable ledger."""

    argv_template: ClassVar[tuple[str, ...]] = ("experiment-log", "append")
    guidance: ClassVar[str] = """
Record completed positive, negative, and failed experiments. Let the helper
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
