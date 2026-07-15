"""Correction operation for the independent experiment-log command."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import Value, WorkflowRecord, YAMLArgvTool


class ExperimentLogCorrectResult(WorkflowRecord):
    correction_id: str


class ExperimentLogCorrectTool(YAMLArgvTool[ExperimentLogCorrectResult]):
    """Append a correction without rewriting an existing experiment."""

    argv_template: ClassVar[tuple[str, ...]] = ("experiment-log", "correct")

    experiment_id: str = Value("Qualified experiment ID to correct")
    summary: str = Value("One-line correction summary")
    correction: str = Value("Corrected interpretation or value")
