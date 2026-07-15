"""Summary operation for the independent experiment-log command."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import ArgvTool, CommandResult


class ExperimentLogSummaryTool(ArgvTool[CommandResult]):
    """Read the active work-branch experiment summary."""

    argv_template: ClassVar[tuple[str, ...]] = ("experiment-log", "summary")
